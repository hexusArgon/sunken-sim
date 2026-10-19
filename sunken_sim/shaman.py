"""Shaman fight for Sunken City, level 6.

Unit O000. Strength 11 + 1.1, agility 14 + 1.4, intellect 25 + 2.5.
White hit is 12 + 1 die, attack cooldown 1.85, attack type magic.
Ability rank is 1. Spec level on A06Z: 1 Restoration, 2 Enhancement, 3 Elemental.
"""

from __future__ import annotations

from sunken_sim.pressure import ATTACK_INTERVAL
from sunken_sim.shadow import (
    CAST_BACKSWING,
    CAST_POINT,
    DUMMY_ARMOR,
    FIGHT,
    LEVEL,
    ORB_MODE,
    Build,
    Report,
    Sulfuras,
    _crit_factor,
    _execute_factor,
    _has,
    _magical_multiplier,
    _wears,
    armor_taken,
    attack_mana_gain,
    cast_mana_back,
    character,
    sulfuras_echo_chance,
)

BASE_STR = int(11 + (LEVEL - 1) * 1.1)
BASE_AGI = int(14 + (LEVEL - 1) * 1.4)
BASE_INT = int(25 + (LEVEL - 1) * 2.5)
WHITE_BASE = 13.0
SWING = 1.85
CAST_TIME = CAST_POINT + CAST_BACKSWING

TALENT_LANDSLIDE = "I0FA"
TALENT_STORM_INFUSION = "I0F4"
TALENT_MOLTEN_BLAST = "I0MA"
TALENT_OVERCHARGE = "I0F1"
TALENT_TIDAL_WAVES = "I0EY"
TALENT_TOTEM_MASTERY = "I0EU"
TALENT_FUSION = "I0OA"
TALENT_BLOODLUST = "I0FB"
TALENT_FLASH = "I0NN"
TALENT_STORMSTRIKE = "I0AG"
TALENT_GUIDANCE = "I0ER"
TALENT_FURY = "I0MB"
TALENT_SPIRIT_CALL = "I0ME"
TALENT_WRATH = "I0EX"
TALENT_ANCESTRAL = "I0EB"
TALENT_STORM_WARD = "I03T"
TALENT_CHAIN_REACTION = "I03U"
TALENT_THUNDERSTORM = "I03V"

TALENTS = {
    TALENT_LANDSLIDE: "Landslide",
    TALENT_STORM_INFUSION: "Storm Infusion",
    TALENT_MOLTEN_BLAST: "Molten Blast",
    TALENT_OVERCHARGE: "Overcharge",
    TALENT_TIDAL_WAVES: "Tidal Waves",
    TALENT_TOTEM_MASTERY: "Totem Mastery",
    TALENT_FUSION: "Elemental Fusion",
    TALENT_BLOODLUST: "Bloodlust",
    TALENT_FLASH: "Flash of Lightning",
    TALENT_STORMSTRIKE: "Stormstrike",
    TALENT_GUIDANCE: "Spiritual Guidance",
    TALENT_FURY: "Elemental Fury",
    TALENT_SPIRIT_CALL: "Spirit Call",
    TALENT_WRATH: "Totemic Wrath",
    TALENT_ANCESTRAL: "Ancestral Touch",
    TALENT_STORM_WARD: "Storm Ward",
    TALENT_CHAIN_REACTION: "Chain Reaction",
    TALENT_THUNDERSTORM: "Thunderstorm",
}

SPECS = ("restoration", "enhancement", "elemental")

EPAULETS = "I0O9"
GHOST_WOLF = "I0S7"
TRIBAL_FURY = "I0O8"
EARTH_HELM = "I0QO"
TEN_STORMS_HELM = "I0S8"
MOLTEN_BELT = "I0O6"
MULGORE = "I0S9"
FIRE_ORB = "I07O"
GALACTIC_FURY = "I0JO"
DIAMOND = "I00D"
PIPE = "I00L"
SULFURAS_CODE = "I0BR"
BOUND_NAME = {
    "chain": "Chain Lightning",
    "shield": "Lightning Shield",
    "spirit": "Feral Spirit",
    "lava": "Lava Burst",
    "totem": "Totemic Call",
}

CHAIN_HITS = 6
LESSER_HITS = 3
SHIELD_CAST = 8
SHIELD_MAX = 12
TOTEM_LIFE = 12.0
SPIRIT_LIFE = 12.0
SPIRIT_SWING = 1.4
MAGMA_GAP = 1.5
INCOMING_GAP = 0.75


def sheet(build: Build) -> dict[str, float]:
    stats = character(build, BASE_STR, BASE_AGI, BASE_INT, WHITE_BASE, bake_timed_buffs=False)
    galactic = 1.20 if _wears(build, GALACTIC_FURY) else 1.0
    stats["attack_base"] = SWING * galactic
    stats["swing"] = stats["attack_base"] / (1.0 + stats["attack_speed"])
    return stats


def buttons(spec: str) -> tuple[str, ...]:
    if spec == "elemental":
        return ("chain", "shield", "lava", "totem")
    return ("chain", "shield", "spirit", "totem")


def _bound_key(bound_spell: str | None) -> str | None:
    if not bound_spell:
        return None
    for key, name in BOUND_NAME.items():
        if bound_spell == key or bound_spell == name:
            return key
    raise ValueError(bound_spell)


def simulate(build: Build, targets: int = 5, spec: str = "restoration", bound_spell: str | None = None) -> Report:
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    if _wears(build, DIAMOND) and bound_spell is None:
        best = None
        for spell in buttons(spec):
            report = simulate(build, targets, spec, BOUND_NAME[spell])
            if best is None or report.dps > best.dps:
                best = report
        return best
    bound_key = _bound_key(bound_spell)
    stats = sheet(build)
    codes = frozenset(item.rawcode for item in build.items) | build.talents | build.glyphs
    taken = armor_taken(DUMMY_ARMOR - stats["armor_pen"])
    elemental = spec == "elemental"
    enhancement = spec == "enhancement"
    overcharge = _has(build, TALENT_OVERCHARGE)
    storm_ward = _has(build, TALENT_STORM_WARD)
    flash = _has(build, TALENT_FLASH)
    fury = _has(build, TALENT_FURY)
    fusion_talent = _has(build, TALENT_FUSION)
    wrath = _has(build, TALENT_WRATH)
    thunder = _has(build, TALENT_THUNDERSTORM)
    spirit_call = _has(build, TALENT_SPIRIT_CALL) and not elemental
    infusion_talent = _has(build, TALENT_STORM_INFUSION)
    bloodlust_on = _has(build, TALENT_BLOODLUST) or _wears(build, TRIBAL_FURY)
    belt = _wears(build, MOLTEN_BELT)
    wolf = _wears(build, GHOST_WOLF)
    cast_charges = SHIELD_CAST + (3 if storm_ward else 0)
    max_charges = SHIELD_MAX + (3 if storm_ward else 0)
    spirit_pack = 3 if wolf else 2
    totem_life = TOTEM_LIFE + (4.0 if _wears(build, MULGORE) else 0.0)
    chain_count = min(targets, CHAIN_HITS)
    lesser_count = min(targets, LESSER_HITS)

    sources = {
        "Автоатака": 0.0,
        "Chain Lightning": 0.0,
        "Lesser Chain Lightning": 0.0,
        "Stormfury": 0.0,
        "Lightning Shield": 0.0,
        "Lava Burst": 0.0,
        "Liquid Magma": 0.0,
        "Feral Spirit": 0.0,
        "Thunderstorm": 0.0,
        "Всплеск огня": 0.0,
    }
    actions: list[tuple[float, str]] = []
    mana = stats["mana_max"]
    mana_time = 0.0
    hero_ready = 0.0
    next_attack = 0.0
    next_chain = 0.0
    next_shield = 0.0
    next_spirit = 0.0
    next_lava = 0.0
    next_totem = 0.0
    chain_until = -1.0
    shield_until = -1.0
    charges = 0.0
    next_incoming = FIGHT
    totem_until = -1.0
    next_bolt = FIGHT
    fusion_until = -1.0
    fusion_seen: set[str] = set()
    bloodlust: list[tuple[float, float, float]] = []
    spirits: list[dict] = []
    pending: list[tuple[float, str]] = []
    attack_count = 0
    sulfuras = Sulfuras() if _wears(build, SULFURAS_CODE) else None
    fire_orb = _wears(build, FIRE_ORB)

    def luck_mult() -> float:
        return 1.0 + stats["luck"]

    def proc(percent: float) -> float:
        return min(1.0, percent / 100.0 * luck_mult())

    def totem_up(now: float) -> bool:
        return now < totem_until

    def mastery_of(now: float) -> float:
        bonus = 6.0 if wrath and totem_up(now) else 0.0
        return stats["mastery"] + bonus

    def crit_of(now: float) -> float:
        bonus = 8.0 if wrath and totem_up(now) else 0.0
        return min(100.0, stats["crit"] + bonus)

    def fusion_up(now: float) -> bool:
        return now < fusion_until

    def blood_factor(now: float) -> float:
        weight = 0.0
        for start, end, chance in bloodlust:
            if start <= now < end:
                weight += chance
        return 1.0 - 0.18 * min(1.0, weight)

    def spirit_as(now: float) -> float:
        alive = sum(1 for spirit in spirits if now < spirit["expire"])
        return min(0.40, 0.10 * alive)

    def attack_interval(now: float) -> float:
        speed = min(4.0, max(-0.8, stats["attack_speed"] + spirit_as(now)))
        return stats["attack_base"] * blood_factor(now) / (1.0 + speed)

    def cooldown(base: float, key: str) -> float:
        temp = stats["cd_temp"] * (0.70 if bound_key == key else 1.0)
        return max(0.5, (base * temp - stats["flat_cdr"]) / (1.0 + stats["haste"]))

    def recover(now: float) -> None:
        nonlocal mana, mana_time
        if now > mana_time and mana < stats["mana_max"]:
            mana = min(stats["mana_max"], mana + stats["mana_regen"] * (now - mana_time))
        mana_time = now

    def pay(cost: float, now: float) -> bool:
        nonlocal mana
        recover(now)
        if mana < cost:
            return False
        mana -= cost
        mana = min(stats["mana_max"], mana + cast_mana_back(cost, stats))
        return True

    def deal(name: str, raw: float, now: float, count: float, attack: bool, magical: bool, from_thunder: bool = False) -> None:
        nonlocal mana
        if count <= 0 or now >= FIGHT:
            return
        mastery = mastery_of(now)
        crit = crit_of(now)
        amount = raw + stats["potency"]
        if magical:
            amount *= _magical_multiplier(codes, now, mastery)
        if attack:
            amount *= _crit_factor(crit, 2.0 + stats["rating"])
        elif stats["spell_crit"]:
            amount *= _crit_factor(crit, stats["spell_mult"] + stats["rating"])
        if fusion_up(now):
            amount *= 1.25
        amount *= taken * _execute_factor(stats, now)
        sources[name] = sources.get(name, 0.0) + amount * count
        if stats.get("damage_mana_pct"):
            mana = min(stats["mana_max"], mana + stats["damage_mana_pct"] * stats["mana_max"] * count)
        if thunder and not from_thunder:
            chance = proc(2.0)
            if chance > 0:
                deal(
                    "Thunderstorm",
                    30.0 + 1.80 * stats["int"],
                    now,
                    count * chance * targets,
                    False,
                    True,
                    True,
                )

    def shield_raw(now: float) -> float:
        raw = 20.0 + 0.30 * stats["int"]
        if elemental:
            raw *= 1.05 + 0.006 * mastery_of(now)
        if storm_ward:
            raw *= 1.10
        return raw

    def chain_raw(now: float) -> float:
        raw = 70.0 + 1.60 * stats["int"]
        if enhancement:
            raw *= 1.08 + 0.005 * mastery_of(now)
        return raw

    def add_flash(now: float, hits: float) -> None:
        nonlocal charges, shield_until
        if not flash or hits <= 0:
            return
        gained = hits * proc(15.0)
        if gained <= 0:
            return
        if now >= shield_until:
            charges = 0.0
            shield_until = now + 20.0
            arm_incoming(now)
        charges = min(max_charges, charges + gained)

    def monster_hit_at(now: float) -> float:
        """First median hit at or after now. Hits are 0.2, 0.4, 0.6, ..."""
        step = ATTACK_INTERVAL
        index = int((now + 1e-9) / step)
        hit = index * step
        if hit + 1e-9 < now:
            hit += step
        return hit

    def arm_incoming(now: float) -> None:
        nonlocal next_incoming
        hit = monster_hit_at(now)
        if next_incoming >= FIGHT or hit < next_incoming:
            next_incoming = hit

    def chain_package(now: float, scale: float, count: int, name: str, weight: float = 1.0) -> None:
        if count <= 0 or weight <= 0:
            return
        raw = chain_raw(now)
        primary = raw * (1.40 if overcharge else 1.0) * scale
        deal(name, primary, now, weight, False, True)
        if count > 1:
            deal(name, raw * scale, now, weight * (count - 1), False, True)
        add_flash(now, weight * count)

    def note_fusion(key: str, now: float) -> None:
        nonlocal fusion_until
        if not fusion_talent or key in fusion_seen:
            return
        fusion_seen.add(key)
        if len(fusion_seen) < 3:
            return
        fusion_seen.clear()
        fusion_until = now + 4.0

    def note_bloodlust(now: float) -> None:
        if not bloodlust_on:
            return
        chance = proc(30.0)
        if chance <= 0:
            return
        duration = 5.0 if spec == "restoration" else 8.0
        bloodlust.append((now, now + duration, chance))

    def summon(now: float, count: int) -> None:
        step = SPIRIT_SWING * blood_factor(now)
        for _ in range(count):
            spirits.append({"expire": now + SPIRIT_LIFE, "next": now + step})

    def cast(name: str, now: float) -> None:
        nonlocal hero_ready, next_attack, next_chain, next_shield, next_spirit, next_lava, next_totem
        costs = {"chain": 20.0, "shield": 25.0, "spirit": 35.0, "lava": 20.0, "totem": 40.0}
        labels = {
            "chain": "Chain Lightning",
            "shield": "Lightning Shield",
            "spirit": "Feral Spirit",
            "lava": "Lava Burst",
            "totem": "Totemic Call",
        }
        if not pay(costs[name], now):
            if name == "chain":
                next_chain = now + 0.25
            elif name == "shield":
                next_shield = now + 0.25
            elif name == "spirit":
                next_spirit = now + 0.25
            elif name == "lava":
                next_lava = now + 0.25
            else:
                next_totem = now + 0.25
            return
        actions.append((now, labels[name]))
        if name == "chain":
            next_chain = now + cooldown(7.0, "chain")
        elif name == "shield":
            base = 13.0 - (3.0 if _wears(build, TEN_STORMS_HELM) else 0.0)
            next_shield = now + cooldown(base, "shield")
        elif name == "spirit":
            next_spirit = now + cooldown(15.0, "spirit")
        elif name == "lava":
            base = 8.0 - (1.2 if fury else 0.0)
            next_lava = now + cooldown(base, "lava")
        else:
            base = 16.0 - (5.0 if _has(build, TALENT_TOTEM_MASTERY) else 0.0)
            next_totem = now + cooldown(base, "totem")
        if sulfuras is not None:
            sulfuras.cast()
        pending.append((now + CAST_POINT, name))
        pending.sort()
        busy = now + CAST_TIME + stats["cast_stun_lock"]
        hero_ready = busy
        next_attack = max(next_attack, busy)

    def resolve(name: str, now: float) -> None:
        nonlocal chain_until, shield_until, charges, next_incoming, totem_until, next_bolt, next_shield, next_lava
        if name == "chain":
            note_fusion("chain", now)
            note_bloodlust(now)
            chain_until = now + 4.0
            if infusion_talent:
                until = now + 3.0
                for spirit in spirits:
                    if now < spirit["expire"]:
                        spirit["infusion"] = until
        elif name == "shield":
            note_fusion("shield", now)
            note_bloodlust(now)
            shield_until = now + 20.0
            charges = float(cast_charges)
            arm_incoming(now)
            if belt:
                next_lava = now
        elif name == "spirit":
            note_fusion("summon", now)
            note_bloodlust(now)
            summon(now, spirit_pack)
        elif name == "lava":
            note_fusion("summon", now)
            note_bloodlust(now)
            spent = charges if now < shield_until else 0.0
            if spent > 0:
                deal("Lightning Shield", shield_raw(now), now, spent, False, True)
                charges = 0.0
                shield_until = -1.0
                if _has(build, TALENT_MOLTEN_BLAST) and spent >= 1.0:
                    next_shield = max(now, next_shield - 4.0)
            raw = 100.0 + 2.50 * stats["int"]
            raw *= 1.0 + 0.008 * mastery_of(now)
            if fury:
                raw *= 1.18
            raw *= 1.0 + 0.08 * spent
            deal("Lava Burst", raw, now, 1.0, False, True)
        elif name == "totem":
            note_fusion("totem", now)
            note_bloodlust(now)
            totem_until = now + totem_life
            next_bolt = (now + MAGMA_GAP) if elemental else FIGHT

    def next_ready(now: float) -> float | None:
        times = [max(next_chain, chain_until)]
        times.append(next_shield)
        times.append(max(next_totem, totem_until))
        if not elemental:
            times.append(next_spirit)
        else:
            times.append(next_lava)
        future = [moment for moment in times if moment > now + 1e-9]
        if not future:
            return None
        return min(future)

    def choose(now: float) -> str | None:
        lava_ready = elemental and next_lava <= now
        shield_ready = next_shield <= now
        need_shield = now >= shield_until or charges < 1.0
        chain_ready = next_chain <= now and now >= chain_until
        spirit_ready = (not elemental) and next_spirit <= now
        totem_ready = next_totem <= now and now >= totem_until
        if elemental and lava_ready and charges >= 1.0 and now < shield_until:
            return "lava"
        if elemental and need_shield and shield_ready:
            return "shield"
        if chain_ready:
            return "chain"
        if (not elemental) and need_shield and shield_ready:
            return "shield"
        if spirit_ready:
            return "spirit"
        if totem_ready:
            return "totem"
        if lava_ready:
            return "lava"
        if shield_ready and need_shield:
            return "shield"
        return None

    def on_attack(now: float) -> None:
        nonlocal next_attack, chain_until, charges, shield_until, attack_count, mana
        recover(now)
        if chain_until >= now:
            chain_until = -1.0
            chain_package(now, 1.0, chain_count, "Chain Lightning")
            if enhancement and totem_up(now):
                chain_package(now, 0.30, lesser_count, "Stormfury")
        chance = 8.0 + 0.15 * stats["agi"]
        if enhancement:
            chance += 10.0
        if _wears(build, EPAULETS):
            chance += 8.0
        if _has(build, TALENT_STORMSTRIKE):
            chance *= 1.20
        lesser_p = proc(chance)
        if lesser_p > 0:
            chain_package(now, 0.50, lesser_count, "Lesser Chain Lightning", lesser_p)
            if enhancement and totem_up(now):
                chain_package(now, 0.30, lesser_count, "Stormfury", lesser_p)
        if now < shield_until and charges > 0:
            spent = min(1.0, charges)
            charges -= spent
            deal("Lightning Shield", shield_raw(now), now, spent, False, True)
            if charges <= 1e-9:
                charges = 0.0
                shield_until = -1.0
        before = sources["Автоатака"]
        deal("Автоатака", stats["ad"], now, 1.0, True, True)
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        mana = min(stats["mana_max"], mana + attack_mana_gain(stats))
        if fire_orb:
            splash = (20.0 + 0.35 * stats["int"]) * targets * taken * _execute_factor(stats, now)
            sources["Всплеск огня"] += splash
        if sulfuras is not None:
            execute = _execute_factor(stats, now)
            if sulfuras.attack():
                splash = (
                    stats["int"]
                    * _magical_multiplier(codes, now, mastery_of(now))
                    * (_crit_factor(crit_of(now), stats["spell_mult"] + stats["rating"]) if stats["spell_crit"] else 1.0)
                    * (1.25 if fusion_up(now) else 1.0)
                    * taken
                    * execute
                    * targets
                )
                sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
            echo = stats["ad"] * taken * execute * sulfuras_echo_chance(stats["luck"])
            sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo
        attack_count += 1
        if spirit_call and attack_count >= 4:
            attack_count = 0
            summon(now, 1)
        next_attack = now + attack_interval(now)

    def on_incoming(now: float) -> None:
        nonlocal charges, shield_until, next_incoming
        if now >= shield_until or charges <= 0:
            next_incoming = FIGHT
            return
        spent = min(1.0, charges)
        charges -= spent
        deal("Lightning Shield", shield_raw(now), now, spent, False, True)
        if charges <= 1e-9:
            charges = 0.0
            shield_until = -1.0
            next_incoming = FIGHT
        else:
            next_incoming = monster_hit_at(now + INCOMING_GAP)

    def on_spirit(spirit: dict, now: float) -> None:
        if now >= spirit["expire"]:
            spirit["next"] = FIGHT
            return
        hit = 8.0 + int(0.25 * stats["ad"])
        crit = 10.0 + (8.0 if wrath and totem_up(now) else 0.0)
        amount = hit * _crit_factor(crit, 2.0)
        if fusion_up(now):
            amount *= 1.25
        amount *= taken * _execute_factor(stats, now)
        sources["Feral Spirit"] += amount
        if thunder:
            chance = proc(2.0)
            if chance > 0:
                deal("Thunderstorm", 30.0 + 1.80 * stats["int"], now, chance * targets, False, True, True)
        infused = 1.5 if now < spirit.get("infusion", -1.0) else 1.0
        crit_p = min(100.0, crit) / 100.0
        base_p = 0.15 * infused * luck_mult()
        lesser_p = (1.0 - crit_p) * min(1.0, base_p) + crit_p * min(1.0, base_p * 1.5)
        if lesser_p > 0:
            chain_package(now, 0.50, lesser_count, "Lesser Chain Lightning", lesser_p)
        spirit["next"] = now + SPIRIT_SWING * blood_factor(now)

    def on_bolt(now: float) -> None:
        nonlocal next_bolt, next_lava, next_shield
        if now >= totem_until:
            next_bolt = FIGHT
            return
        raw = 20.0 + 0.50 * stats["int"] + mastery_of(now)
        deal("Liquid Magma", raw, now, 1.0, False, True)
        cut = 0.50 * proc(50.0)
        if cut > 0:
            lava_left = next_lava - now
            shield_left = next_shield - now
            if lava_left > shield_left and lava_left > 0:
                next_lava = max(now, next_lava - cut)
            elif shield_left > 0:
                next_shield = max(now, next_shield - cut)
            elif lava_left > 0:
                next_lava = max(now, next_lava - cut)
        next_bolt = now + MAGMA_GAP

    guard = 0
    while guard < 200000:
        guard += 1
        spirits = [spirit for spirit in spirits if spirit["next"] < spirit["expire"] and spirit["next"] < FIGHT]
        next_spirit_swing = min((spirit["next"] for spirit in spirits), default=FIGHT)
        if next_bolt >= totem_until:
            next_bolt = FIGHT
        if next_incoming >= shield_until:
            next_incoming = FIGHT
        next_effect = pending[0][0] if pending else FIGHT
        moment = min(next_attack, next_spirit_swing, next_bolt, next_incoming, next_effect)
        if pending and next_effect <= moment and next_effect < FIGHT:
            _, effect_name = pending.pop(0)
            resolve(effect_name, next_effect)
            continue
        if hero_ready <= moment and hero_ready < FIGHT:
            spell = choose(hero_ready)
            if spell:
                cast(spell, hero_ready)
                continue
            wake = next_ready(hero_ready)
            if wake is not None and wake <= moment:
                hero_ready = wake
                continue
        if moment >= FIGHT:
            break
        if moment == next_attack:
            on_attack(moment)
            continue
        if moment == next_incoming:
            on_incoming(moment)
            continue
        if moment == next_bolt:
            on_bolt(moment)
            continue
        for spirit in spirits:
            if spirit["next"] == moment:
                on_spirit(spirit, moment)
        continue

    recover(FIGHT)
    total = sum(sources.values())
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    mode = next((name for code, name in ORB_MODE.items() if _wears(build, code)), None)
    return Report(
        build,
        total / FIGHT,
        total,
        sources,
        actions,
        stats,
        targets,
        orb_mode=mode,
        bound_spell=BOUND_NAME.get(bound_key or "", None),
        mana_left=mana_left,
    )


def best_points(build: Build, targets: int, spec: str) -> tuple[float, tuple[int, int, int, int]]:
    from sunken_sim.search import POINT_SPLITS

    best_dps = -1.0
    best = (0, 5, 0, 0)
    for crit, potency, luck, mastery in POINT_SPLITS:
        trial = Build(build.talents, build.glyphs, build.items, potency, mastery, crit, luck)
        report = simulate(trial, targets, spec)
        if report.dps > best_dps:
            best_dps = report.dps
            best = (crit, potency, luck, mastery)
    return best_dps, best
