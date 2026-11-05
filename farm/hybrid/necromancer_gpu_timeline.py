# -*- coding: utf-8 -*-
"""Batched next-event timeline for Necromancer.

Inlined CPU-exact _simulate + best-of POLICIES. Sulfuras → overflow.
torch/device kept for API parity with other GPU timelines.
"""
from __future__ import annotations



from sunken_sim.shadow import (
    CAST_BACKSWING,
    CAST_POINT,
    DUMMY_ARMOR,
    FIGHT,
    LEVEL,
    Sulfuras,
    _crit_factor,
    _execute_factor,
    _wears,
    armor_taken,
    attack_mana_gain,
    cast_mana_back,
    sulfuras_echo_chance,
    target_hp,
)
from sunken_sim.ledger import Ledger, attach
from sunken_sim import necromancer as mod

SPECS = mod.SPECS
POLICIES = mod.POLICIES
stats_of = mod.stats_of
_has = mod._has
_cooldown = mod._cooldown
RANK = getattr(mod, "RANK", 1)
if hasattr(mod, "_chance"):
    _chance = mod._chance
if hasattr(mod, "_Dither"):
    _Dither = mod._Dither

_g = globals()
for _n in dir(mod):
    if _n[:1] == "_":
        continue
    if _n.isupper() or _n.startswith("TALENT_") or _n.startswith("GLYPH_"):
        _g[_n] = getattr(mod, _n)


class _Overflow(Exception):
    pass


def generate_necromancer_timelines(torch, device, builds, spec: str, targets: int):
    if spec not in ('bone', 'blood', 'essence'):
        raise ValueError(f"necromancer GPU timeline unexpected spec {spec}")
    if not builds:
        return []
    _ = (torch, device)
    try:
        for b in builds:
            if _wears(b, "I0BR"):
                raise _Overflow("sulfuras")
        return [_best_fight(b, int(targets), spec) for b in builds]
    except _Overflow:
        out = []
        for b in builds:
            report = mod.simulate(b, int(targets), spec)
            out.append((list(report.events), report.stats))
        return out


def _best_fight(build, targets, spec):
    best = None
    for policy in POLICIES:
        events, stats, total = _fight_one(build, targets, spec, policy)
        if best is None or total > best[0] + 1e-9:
            best = (total, events, stats)
    return best[1], best[2]



def _fight_one(build, targets: int, spec: str, policy):
    use_trans, use_raise = policy
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    bone, blood, essence = spec == "bone", spec == "blood", spec == "essence"
    use_raise = use_raise and not essence
    intel = int(stats["int"])
    mastery = int(stats["mastery"])
    hp_max = stats["hp"]
    mana_max = stats["mana_max"]
    hero_taken = armor_taken(DUMMY_ARMOR - stats["armor_pen"])
    summon_taken = armor_taken(DUMMY_ARMOR)
    pen_taken = armor_taken(DUMMY_ARMOR - 8.0)  # A042: 8 armor penetration

    sources: dict[str, float] = Ledger({"Автоатака": 0.0})
    actions: list[tuple[float, str]] = []
    mana = mana_max
    mana_time = 0.0
    hp = hp_max
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    last_gs = 0.0  # GrimScythe_PassiveDamage (global, starts at 0)
    swift_until = -1.0
    globe_until = -1.0
    teeth_lvl = 1  # A0AS level
    rd_ticks = 0
    guard_ce = False
    archer_roll = _Dither()
    skeletons: list[dict] = []
    tombs: list[float] = []  # expiry times
    pending: list[tuple[float, int, str, float]] = []  # (time, seq, kind, arg)
    seq = 0

    def push(when: float, kind: str, arg: float = 0.0) -> None:
        nonlocal seq
        seq += 1
        pending.append((when, seq, kind, arg))

    def recover(now: float) -> None:
        nonlocal mana, mana_time
        if now > mana_time and mana < mana_max:
            mana = min(mana_max, mana + stats["mana_regen"] * (now - mana_time))
        mana_time = now

    def gain_mana(amount: float) -> None:
        nonlocal mana
        mana = min(mana_max, mana + amount)

    def pay(cost: float, now: float, refund: bool = True) -> bool:
        nonlocal mana
        recover(now)
        if mana < cost:
            return False
        mana -= cost
        if refund:
            gain_mana(cast_mana_back(cost, stats))
        return True

    def note_damage_mana(count: float) -> None:
        if stats["damage_mana_pct"]:
            gain_mana(stats["damage_mana_pct"] * mana_max * count)

    def lose_hp(amount: float) -> None:
        nonlocal hp
        hp = max(1.0, hp - amount)

    def heal(amount: float) -> None:
        nonlocal hp
        hp = min(hp_max, hp + amount)

    def typed(magical: bool, now: float) -> float:
        bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if magical and stats["spellbinder"]:
            bonus += 0.05 + 0.005 * stats["mastery"]
        if stats["glass"]:
            bonus *= 1.15
        return bonus

    def sacrifice(magical: bool, count: float) -> float:
        """Blood Sacrifice I057: +0.5% max HP per instance (x1.25 magical) while HP > 25%."""
        if not has(TALENT_BLOOD_SACRIFICE) or hp <= 0.25 * hp_max:
            return 0.0
        lose_hp(0.005 * hp_max * count)
        return 0.005 * hp_max * (1.25 if magical else 1.0)

    def ce_proc(count: float, now: float) -> None:
        """Corpse Explosion passive: 1.5% (3% Blood) x luck per owner damage instance."""
        if guard_ce or count <= 0:
            return
        chance = _chance((3.0 if blood else 1.5) / 100.0 * luck_mult)
        explode(now, None, chance * count)

    def explosion_raw() -> float:
        value = 20.0 * RANK + 0.35 * intel + 0.01 * hp_max
        if blood:
            value *= 1.10 + 0.005 * mastery
        return value

    def explode(now: float, dealer: str | None, weight: float, name: str = "Corpse Explosion (пассив)") -> None:
        """One Corpse Explosion passive (AoE 350, magical) by the Necromancer or a summon."""
        nonlocal guard_ce
        if weight <= 0:
            return
        was = guard_ce
        guard_ce = True  # CorpseExp_Running: no chain procs
        if dealer is None:
            hero_hit(name, explosion_raw(), now, magical=True, attack=False, count=targets * weight)
        else:
            summon_hit(name, explosion_raw(), now, magical=True, attack=False, count=targets * weight)
        guard_ce = was

    def hero_hit(name: str, raw: float, now: float, *, magical: bool, attack: bool, count: float = 1.0,
                 potency_scale: float = 1.0) -> float:
        """Damage dealt by the Necromancer. Returns dealt per instance."""
        amount = raw + stats["potency"] * potency_scale
        amount += sacrifice(magical, count)
        amount *= typed(magical, now)
        if has(TALENT_BLOOD_REAPER):
            amount *= 0.88
        if attack:
            amount *= _crit_factor(stats["crit"], 2.0 + stats["rating"])
        elif stats["spell_crit"]:
            amount *= _crit_factor(stats["crit"], stats["spell_mult"] + stats["rating"])
        dealt = amount * hero_taken * _execute_factor(stats, now)
        sources.add_exec(name, dealt * count, now, _execute_factor(stats, now))
        note_damage_mana(count)
        ce_proc(count, now)
        return dealt

    def summon_hit(name: str, raw: float, now: float, *, magical: bool, attack: bool, count: float = 1.0,
                   crit_bonus: float = 0.0, pen_share: float = 0.0, depth: int = 0) -> float:
        """Damage dealt by a summon / tombstone: potency, Blood Sacrifice, Pet Damage, summon crit."""
        amount = raw + stats["potency"] + sacrifice(magical, count)
        amount *= 1.0 + stats["pet_damage"]
        if attack:
            amount *= _crit_factor(stats["summon_crit"] + crit_bonus, 2.0 + stats["summon_rating"])
        taken = pen_share * pen_taken + (1.0 - pen_share) * summon_taken
        dealt = amount * taken * _execute_factor(stats, now)
        sources.add_exec(name, dealt * count, now, _execute_factor(stats, now))
        ce_proc(count, now)
        if has(TALENT_SERRATION) and depth < 3:
            chance = _chance(0.05 * luck_mult) * count
            summon_hit("Serration", 15.0 * RANK + 0.75 * dcs(), now, magical=False, attack=False,
                       count=chance, depth=depth + 1)
        return dealt

    def gs_passive(count: float, now: float) -> None:
        """Grim Scythe passive on Necromancer attack damage (magical, per target)."""
        nonlocal last_gs, mana
        raw = 10.0 + 10.0 * RANK + 0.55 * intel
        recover(now)
        if has(TALENT_REAPER_OF_SOULS) and mana > 0.20 * mana_max:
            raw += 0.02 * mana_max
            mana = max(0.0, mana - 0.002 * mana_max * count)
        if essence:
            raw *= 1.10 + 0.01 * mastery
        if has(TALENT_EXECUTORS_SWING):
            raw *= 1.10
        last_gs = raw
        hero_hit("Grim Scythe (пассив)", raw, now, magical=True, attack=False, count=count)

    def dcs() -> float:
        return WHITE_BASE + 0.75 * intel + stats["damage"]

    def skeleton_raw() -> float:
        return 6.0 + int(4.0 * RANK + 0.20 * dcs())  # 5 + 1d1, + R2I(4 x Tomb lvl + 0.20 x DCS)

    def spawn(kind: str, now: float) -> None:
        life = SKELETON_LIFE + (3.0 if has(TALENT_HOUR_OF_THE_DEAD) else 0.0)
        pen = _chance((5.0 + mastery) / 100.0) if bone else 0.0
        skeletons.append({"kind": kind, "next": now, "end": now + life, "group": kind != "mage",
                          "pen": pen, "spectral": -1.0})
        if has(TALENT_SKELETAL_ARCHER) and archer_roll.roll(0.25 * luck_mult):
            skeletons.append({"kind": "archer", "next": now, "end": now + life, "group": True,
                              "pen": pen, "spectral": -1.0})

    def haste_now() -> float:
        return stats["haste"]

    def interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        speed = stats["attack_speed"] + 0.08 * (teeth_lvl - 1)
        if now < swift_until:
            speed += SWIFT_AS
        if has(TALENT_SANGUINE_FURY) and now < globe_until:
            speed += SANGUINE_AS
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    def tomb_first(count: int) -> float:
        return (1.80 - 0.20 * RANK) / (1.0 + (0.35 if count > 1 else 0.0))

    def tomb_period(count: int) -> float:
        rate = 1.0 + (0.5 if count > 1 else 0.0)
        if has(TALENT_CALL_OF_THE_GRAVE):
            rate += 0.35 + 0.05 * stats["potency"]
        return 1.5 / rate

    fixed_cd = {"gs": GS_CD, "ce": CE_CD, "tomb": TOMB_CD, "trans": TRANS_CD, "teeth": TEETH_CD}
    cost = {"gs": GS_MANA, "ce": CE_MANA, "tomb": TOMB_MANA, "trans": TRANS_MANA, "teeth": TEETH_MANA}
    names = {"gs": "Grim Scythe", "ce": "Corpse Explosion", "tomb": "Tombstone",
             "trans": "Transfusion", "teeth": "Teeth"}
    order = ["tomb", "ce", "gs"] + (["teeth"] if essence else []) + (["trans"] if use_trans else [])
    nxt = {key: 0.0 for key in order}
    full_cd = {key: 0.0 for key in order}
    tomb_timer = FIGHT * 10
    if use_raise:
        push(1.0 / (1.0 + haste_now()), "rd")

    next_attack = 0.0
    busy = 0.0
    loops = 0
    clock = 0.0
    while True:
        loops += 1
        if loops > 400000:
            break
        attack_at = max(next_attack, busy, clock)
        cast_at = FIGHT * 10
        choice = None
        for key in order:
            ready = max(nxt[key], busy, clock)
            if ready < cast_at - 1e-9:
                cast_at, choice = ready, key
        pending_at = min((p[0] for p in pending), default=FIGHT * 10)
        skeletons[:] = [s for s in skeletons if s["end"] > clock - 1e-9]
        live = [s for s in skeletons if s["next"] < s["end"]]
        summon_at = min((s["next"] for s in live), default=FIGHT * 10)
        moment = min(attack_at, cast_at, pending_at, summon_at, tomb_timer)
        if moment >= FIGHT:
            break
        clock = moment
        if moment == pending_at:
            event = min(pending)
            pending.remove(event)
            _, _, kind, arg = event
            if kind == "rd":
                recover(moment)
                if mana >= 2.0 + 1.5 * RANK and pay(2.0 + 1.5 * RANK, moment, refund=False):
                    rd_ticks += 1
                need = 4 if bone else 6
                while rd_ticks >= need:
                    rd_ticks -= need
                    spawn("warrior", moment)
                push(moment + 1.0 / (1.0 + haste_now()), "rd")
            elif kind == "gs":
                raw = 60.0 * RANK - 20.0 + 1.5 * intel + 0.04 * hp_max
                if has(TALENT_EXECUTORS_SWING):
                    raw *= 1.20
                hero_hit("Grim Scythe", raw, moment, magical=True, attack=False, count=targets)
                if stats["scythe_passive"]:
                    gs_passive(targets * _chance(0.50 * luck_mult), moment)
                if has(TALENT_BLOODY_SCYTHE):
                    explode(moment, None, _chance(0.60 * luck_mult), "Bloody Scythe (взрыв)")
                if has(TALENT_SWIFT_HARVEST):
                    swift_until = moment + SWIFT_DUR
                for s in skeletons:
                    if s["group"]:
                        s["spectral"] = moment + SPECTRAL_DUR
            elif kind == "ce":
                explode(moment, None, 1.0, "Corpse Explosion")
            continue
        if moment == tomb_timer:
            alive = [t for t in tombs if t > moment]
            tombs[:] = alive
            if not alive:
                tomb_timer = FIGHT * 10
                continue
            raw = 8.0 * RANK + 0.01 * hp_max + 0.01 * mana_max
            if bone:
                summon_hit("Tombstone (аура)", raw, moment, magical=False, attack=False, count=targets)
            else:
                hero_hit("Tombstone (аура)", raw, moment, magical=False, attack=False, count=targets)
            tomb_timer = moment + tomb_period(len(alive))
            continue
        if moment == summon_at and summon_at < attack_at and summon_at < cast_at:
            s = min(live, key=lambda u: u["next"])
            kind = s["kind"]
            raw = skeleton_raw()
            if moment < s["spectral"]:
                raw += 0.15 * last_gs
            magical = kind == "mage"
            label = {"warrior": "Скелеты (Raise Dead/Tombstone)", "archer": "Skeletal Archer",
                     "assassin": "Assassin (Lord)", "executor": "Executor (Lord)", "mage": "Mage (Lord)"}[kind]
            dealt = summon_hit(label, raw, moment, magical=magical, attack=True,
                               crit_bonus=50.0 if kind == "assassin" else 0.0, pen_share=s["pen"])
            if kind == "executor":
                hero_hit("Executor (эхо)", 0.75 * dealt, moment, magical=True, attack=True)
                gs_passive(1.0, moment)
            if kind == "mage" and "ce" in nxt and nxt["ce"] > moment:
                nxt["ce"] = max(moment, nxt["ce"] - 0.5)
            s["next"] = moment + SWINGS[kind]
            continue
        if cast_at <= attack_at and choice is not None and moment == cast_at:
            key = choice
            if not pay(cost[key], moment):
                nxt[key] = moment + 0.25
                continue
            hit_at = moment + CAST_POINT
            actions.append((moment, names[key]))
            busy = moment + cast_time + stats["cast_stun_lock"]
            if sulfuras is not None:
                sulfuras.cast()
            haste = haste_now()
            if has(TALENT_DARK_BARGAIN):
                haste += 0.05 + 0.01 * ((100.0 - 100.0 * hp / hp_max) / 2.0)
            if key == "gs":
                push(hit_at + GS_DELAY, "gs")
            elif key == "ce":
                lose_hp(0.08 * hp)
                ticks = 3 + (1 if blood else 0) + int(stats["ce_tick"])
                for i in range(ticks):
                    push(hit_at + (i + 1) * 1.2 / ticks, "ce")
                if has(TALENT_BLOOD_BOMB):
                    group = sorted((s for s in skeletons if s["group"]), key=lambda u: u["end"])
                    for s in group[:3]:
                        skeletons.remove(s)
                        explode(hit_at, UNIT[s["kind"]], 1.0, "Blood Bomb (взрыв скелета)")
            elif key == "tomb":
                tombs.append(hit_at + (13.0 if has(TALENT_GRAVEDIGGER) else 10.0))
                tombs[:] = [t for t in tombs if t > hit_at]
                tomb_timer = hit_at + tomb_first(len(tombs))
                count = (3 if has(TALENT_GRAVEDIGGER) else 2) + int(stats["tomb_extra"])
                for _ in range(count):
                    spawn("warrior", hit_at)
                if has(TALENT_LORD_OF_THE_DEAD):
                    spawn({"bone": "assassin", "blood": "mage", "essence": "executor"}[spec], hit_at)
            elif key == "teeth":
                lose_hp(0.08 * hp)
                raw = 20.0 + 0.80 * intel + 0.05 * hp_max
                hero_hit("Teeth", raw, hit_at, magical=False, attack=True, count=targets)
                gs_passive(float(targets), hit_at)
                heal(0.04 * hp_max * targets)
                teeth_lvl = min(7, teeth_lvl + targets)
            elif key == "trans":
                globes = 1 + int(stats["globe_extra"])
                for _ in range(globes):
                    heal(0.15 * hp_max)
                    globe_until = hit_at + GLOBE_DUR
                    if has(TALENT_ESSENCE_FROM_BLOOD):
                        gain_mana(0.05 * mana_max)
                        for other in order:
                            if nxt[other] > hit_at:
                                nxt[other] = max(hit_at, nxt[other] - 0.06 * full_cd[other])
                    if has(TALENT_LIFE_FROM_DEATH) and use_raise:
                        rd_ticks += 2
            cd = _cooldown(fixed_cd[key], haste, stats, stats["ce_flat"] if key == "ce" else 0.0)
            full_cd[key] = cd
            nxt[key] = max(nxt[key], moment + cd) if key != "trans" else moment + cd
            next_attack = max(next_attack, busy)
            continue

        # Necromancer auto-attack (magic attack type).
        moment = attack_at
        recover(moment)
        power = dcs()
        before = sources["Автоатака"]
        hero_hit("Автоатака", power, moment, magical=True, attack=True, potency_scale=stats["attack_potency"])
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        gs_passive(1.0, moment)
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * stats["int"]) * targets * hero_taken * _execute_factor(stats, moment)
            sources.add_exec("Всплеск огня", splash, moment, _execute_factor(stats, moment))
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = stats["int"] * typed(True, moment) * hero_taken * execute * targets
                splash *= _crit_factor(stats["crit"], 2.0 + stats["rating"])
                sources.add_exec("Sulfuras", splash, moment, execute)
                note_damage_mana(targets)
            echo = power * hero_taken * execute * sulfuras_echo_chance(stats["luck"])
            sources.add_exec("Sulfuras (удар)", echo, moment, execute)
        next_attack = moment + interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if mana_max <= 0 else 100.0 * mana / mana_max
    return list(sources.events), stats, total

