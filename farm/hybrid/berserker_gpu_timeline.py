# -*- coding: utf-8 -*-
"""Batched next-event timeline for Berserker (headhunter / poison / fury).

Faithful port of sunken_sim.berserker.simulate onto batched torch.
Ledger events: KIND_EXEC (when, name, raw_weight, kind, pot_coeff).
Scoring applies (raw_weight + potency * pot_coeff) * execute; crit/luck stay baked.
f64 clocks on CPU; DirectML kind-score via kindscore.pack.
Sulfuras → CPU overflow for the batch.
"""
from __future__ import annotations

MAX_STEPS = 400000
MAX_PENDING = 64
MAX_T = 8
MAX_EVENTS = 8192

N_AUTO, N_SACK, N_SKULL, N_VA, N_SURGE, N_SNAKE, N_AXE, N_FIRE = range(8)
N_SULF, N_SULF_ECHO = 8, 9
NAMES = {
    N_AUTO: "Автоатака",
    N_SACK: "Toxic Sack",
    N_SKULL: "Skull Split",
    N_VA: "Venomous Axes",
    N_SURGE: "Surge of Toxins",
    N_SNAKE: "Way of the Snake",
    N_AXE: "Axe Mastery",
    N_FIRE: "Всплеск огня",
    N_SULF: "Sulfuras",
    N_SULF_ECHO: "Sulfuras (удар)",
}
KIND_EXEC = 2.0
KIND_FLAT = 3.0

P_SACK = 0  # pending toxic sack land


class _Overflow(Exception):
    pass


def generate_berserker_timelines(torch, device, builds, spec: str, targets: int):
    if spec not in ("headhunter", "poison", "fury"):
        raise ValueError(f"berserker GPU timeline specs headhunter/poison/fury, got {spec}")
    if not builds:
        return []
    dev_type = getattr(device, "type", str(device))
    if dev_type in ("privateuseone", "dml") or "privateuseone" in str(device):
        device = torch.device("cpu")
    try:
        return _berserker_batch(torch, device, torch.float64, builds, spec, int(targets))
    except _Overflow:
        return _cpu_fallback(builds, spec, targets)


def _cpu_fallback(builds, spec, targets):
    from sunken_sim import berserker as mod

    out = []
    for b in builds:
        report = mod.simulate(b, targets, spec)
        out.append((list(report.events), report.stats))
    return out


def _push(torch, bufs, mask, when, weight, name_id, kind, pot_coeff=0.0):
    if not bool(mask.any()):
        return
    B = int(mask.shape[0])
    w = weight if isinstance(weight, torch.Tensor) else torch.full((B,), float(weight), dtype=bufs["weight"].dtype, device=weight.device if isinstance(weight, torch.Tensor) else bufs["weight"].device)
    when_t = when if isinstance(when, torch.Tensor) else torch.full((B,), float(when), dtype=bufs["when"].dtype, device=bufs["when"].device)
    pc = pot_coeff if isinstance(pot_coeff, torch.Tensor) else torch.full_like(w, float(pot_coeff))
    nonzero = (w != 0) | (pc != 0)
    if bool((mask & nonzero & (bufs["length"] >= MAX_EVENTS)).any()):
        raise _Overflow("events")
    active = mask & nonzero
    if not bool(active.any()):
        return
    rows = torch.arange(B, device=bufs["when"].device)
    idx = bufs["length"].clone()
    bufs["when"][rows[active], idx[active]] = when_t[active]
    bufs["weight"][rows[active], idx[active]] = w[active]
    bufs["pot_coeff"][rows[active], idx[active]] = pc[active]
    if isinstance(name_id, torch.Tensor):
        bufs["name"][rows[active], idx[active]] = name_id[active]
    else:
        bufs["name"][rows[active], idx[active]] = int(name_id)
    if isinstance(kind, torch.Tensor):
        bufs["kind"][rows[active], idx[active]] = kind[active]
    else:
        bufs["kind"][rows[active], idx[active]] = float(kind)
    bufs["length"] = bufs["length"] + active.to(torch.int64)


def _make_bufs(torch, device, B, dtype):
    return {
        "when": torch.zeros((B, MAX_EVENTS), dtype=dtype, device=device),
        "name": torch.zeros((B, MAX_EVENTS), dtype=torch.int64, device=device),
        "weight": torch.zeros((B, MAX_EVENTS), dtype=dtype, device=device),
        "pot_coeff": torch.zeros((B, MAX_EVENTS), dtype=dtype, device=device),
        "kind": torch.zeros((B, MAX_EVENTS), dtype=dtype, device=device),
        "length": torch.zeros(B, dtype=torch.int64, device=device),
    }


def _finalize(bufs, stats_list):
    out = []
    lengths = bufs["length"].detach().cpu().tolist()
    whens = bufs["when"].detach().cpu()
    names = bufs["name"].detach().cpu()
    weights = bufs["weight"].detach().cpu()
    kinds = bufs["kind"].detach().cpu()
    coeffs = bufs["pot_coeff"].detach().cpu()
    for i, stats in enumerate(stats_list):
        n = int(lengths[i])
        events = [
            (float(whens[i, j]), NAMES[int(names[i, j])], float(weights[i, j]), float(kinds[i, j]), float(coeffs[i, j]))
            for j in range(n)
        ]
        out.append((events, stats))
    return out


def _berserker_batch(torch, device, dtype, builds, spec, T):
    from sunken_sim import berserker as mod
    from sunken_sim.pressure import hero_hp_ratio
    from sunken_sim.shadow import (
        CAST_BACKSWING,
        CAST_POINT,
        DUMMY_ARMOR,
        FIGHT,
        LEVEL,
        MEDIAN_MONSTER_HP,
        _crit_factor,
        _execute_factor,
        _wears,
        armor_taken,
        attack_mana_gain,
        cast_mana_back,
        sulfuras_echo_chance,
        target_hp,
    )

    B = len(builds)
    if T < 1 or T > MAX_T:
        raise _Overflow("targets")
    Tt = int(T)
    fight = float(FIGHT)
    cast_point = float(CAST_POINT)
    cast_time = float(CAST_POINT + CAST_BACKSWING)
    BIG = 1e18
    zeros = torch.zeros(B, dtype=dtype, device=device)
    ones = torch.ones(B, dtype=dtype, device=device)
    rix = torch.arange(B, device=device)

    fury = spec == "fury"
    poison = spec == "poison"
    headhunter = spec == "headhunter"
    fury_mult = 0.85 if fury else 1.0

    stats_list = []
    meta = []
    for build in builds:
        stats = mod.stats_of(build)
        stats_list.append(stats)
        has = lambda c, b=build: mod._has(b, c)
        wears = lambda c, b=build: _wears(b, c)
        if wears(mod.__dict__.get("SULFURAS", "I0BR")) or wears("I0BR"):
            # rare — overflow whole batch to keep Sulfuras RNG parity
            raise _Overflow("sulfuras")
        meta.append(
            {
                "agi": float(stats["agi"]),
                "hp": float(stats["hp"]),
                "potency": float(stats["potency"]),
                "mastery": float(stats["mastery"]),
                "crit": float(stats["crit"]),
                "rating": float(stats["rating"]),
                "haste": float(stats["haste"]),
                "attack_speed": float(stats["attack_speed"]),
                "attack_potency": float(stats["attack_potency"]),
                "armor_pen": float(stats["armor_pen"]),
                "phys_add": float(stats["phys_add"]),
                "hemotoxin_add": float(stats.get("hemotoxin_add") or 0.0),
                "magic_add": float(stats["magic_add"]),
                "damage": float(stats["damage"]),
                "luck": float(stats["luck"]),
                "mana_max": float(stats["mana_max"]),
                "mana_regen": float(stats["mana_regen"]),
                "cast_stun_lock": float(stats["cast_stun_lock"]),
                "auto_pct": float(stats["auto_pct"]),
                "damage_mana_pct": float(stats.get("damage_mana_pct") or 0.0),
                "cd_temp": float(stats["cd_temp"]),
                "flat_cdr": float(stats["flat_cdr"]),
                "sulfuron": float(stats["sulfuron"]),
                "glass": float(stats["glass"]),
                "galactic": float(stats["galactic"]),
                "fire_orb": float(stats["fire_orb"]),
                "blood_fanatic": float(stats["blood_fanatic"]),
                "venombite": float(stats["venombite"]),
                "amg": float(attack_mana_gain(stats)),
                "axe": 1.0 if has(mod.TALENT_AXE_MASTERY) else 0.0,
                "dambala": 1.0 if has(mod.TALENT_MIGHT_OF_DAMBALA) else 0.0,
                "berserk": 1.0 if has(mod.TALENT_BERSERK) else 0.0,
                "executor": 1.0 if has(mod.TALENT_EXECUTOR) else 0.0,
                "deadly": 1.0 if has(mod.TALENT_DEADLY_POISON) else 0.0,
                "poison_bomb": 1.0 if has(mod.TALENT_POISON_BOMB) else 0.0,
                "boneslicer": 1.0 if has(mod.TALENT_BONESLICER) else 0.0,
                "blood_craze": 1.0 if has(mod.TALENT_BLOOD_CRAZE) else 0.0,
                "leeching": 1.0 if has(mod.TALENT_LEECHING_POISON) else 0.0,
                "blades": 1.0 if (has(mod.TALENT_POISONED_BLADES) or stats["venombite"] > 0) else 0.0,
                "blood_hunter": 1.0 if has(mod.TALENT_BLOOD_HUNTER) else 0.0,
                "snake": 1.0 if has(mod.TALENT_WAY_OF_THE_SNAKE) else 0.0,
                "wound": 1.0 if has(mod.TALENT_WOUND_POISON) else 0.0,
                "hemotoxin": 1.0 if has(mod.TALENT_HEMOTOXIN) else 0.0,
            }
        )

    def F(name):
        return torch.tensor([m[name] for m in meta], dtype=dtype, device=device)

    def Bool(name):
        return F(name) > 0.5

    agi = F("agi")
    hp = F("hp")
    potency = F("potency")
    mastery = F("mastery")
    crit0 = F("crit")
    rating = F("rating")
    haste = F("haste")
    attack_speed0 = F("attack_speed")
    attack_potency = F("attack_potency")
    armor_pen = F("armor_pen")
    phys_add = F("phys_add")
    hemotoxin_add = F("hemotoxin_add")
    magic_add = F("magic_add")
    damage = F("damage")
    luck = F("luck")
    luck_mult = ones + luck
    mana_max = F("mana_max")
    mana_regen = F("mana_regen")
    cast_stun = F("cast_stun_lock")
    auto_pct = F("auto_pct")
    dmp = F("damage_mana_pct")
    cd_temp = F("cd_temp")
    flat_cdr = F("flat_cdr")
    sulfuron = Bool("sulfuron")
    glass = Bool("glass")
    galactic = Bool("galactic")
    fire_orb = Bool("fire_orb")
    blood_fanatic = Bool("blood_fanatic")
    axe_t = Bool("axe")
    dambala = Bool("dambala")
    berserk_t = Bool("berserk")
    executor = Bool("executor")
    deadly = Bool("deadly")
    poison_bomb = Bool("poison_bomb")
    boneslicer = Bool("boneslicer")
    blood_craze = Bool("blood_craze")
    leeching = Bool("leeching")
    blades = Bool("blades")
    blood_hunter = Bool("blood_hunter")
    snake = Bool("snake")
    wound = Bool("wound")
    hemotoxin = Bool("hemotoxin")
    amg = F("amg")

    # precompute cast_mana_back for fixed costs
    sack_back = torch.tensor([cast_mana_back(mod.SACK_MANA, s) for s in stats_list], dtype=dtype, device=device)
    skull_back = torch.tensor([cast_mana_back(mod.SKULL_MANA, s) for s in stats_list], dtype=dtype, device=device)

    def full(v):
        return v if isinstance(v, torch.Tensor) else torch.full((B,), float(v), dtype=dtype, device=device)

    def cf(chance, mult):
        ch = torch.clamp(full(chance), 0.0, 100.0)
        return ones + (ch / 100.0) * (full(mult) - ones)

    def target_hp_t(now):
        now = full(now)
        return torch.clamp(ones - now / fight, min=0.0)

    def execute_t(now):
        # per-row _execute_factor — use python for fidelity on execute curve
        now = full(now)
        outs = []
        for i in range(B):
            outs.append(_execute_factor(stats_list[i], float(now[i].item())))
        return torch.tensor(outs, dtype=dtype, device=device)

    def hero_ratio_t(now):
        now = full(now)
        outs = []
        for i in range(B):
            outs.append(hero_hp_ratio(float(now[i].item()), float(hp[i].item()), 0.0))
        return torch.tensor(outs, dtype=dtype, device=device)

    def berserk_speed(now):
        now = full(now)
        # phase stacks — vectorized
        active = berserk_t & (now >= mod.PRESSURE_STEP)
        phase = torch.remainder(now - mod.PRESSURE_STEP, mod.BERSERK_DUR + mod.PRESSURE_STEP)
        in_win = active & (phase < mod.BERSERK_DUR)
        stacks = torch.floor(phase / mod.PRESSURE_STEP + 1e-9)
        per = 0.02 if fury else 0.03
        return torch.where(in_win, full(0.12) + per * stacks, zeros)

    def taken_for(index, now):
        now = full(now)
        armor = full(float(DUMMY_ARMOR)) - armor_pen
        va = now < va_until[:, index]
        armor = torch.where(wound & va, armor - 3.0, armor)
        # armor_taken is nonlinear — per-row
        outs = []
        for i in range(B):
            outs.append(armor_taken(float(armor[i].item())))
        return torch.tensor(outs, dtype=dtype, device=device)

    def generic(now):
        now = full(now)
        bonus = ones + torch.where(sulfuron, full(0.13) + 0.25 * target_hp_t(now), zeros)
        return torch.where(glass, bonus * 1.15, bonus)

    def physical(now):
        now = full(now)
        bonus = ones + phys_add + hemotoxin_add
        bonus = bonus + torch.where(sulfuron, full(0.13) + 0.25 * target_hp_t(now), zeros)
        return torch.where(glass, bonus * 1.15, bonus)

    def add_exec(mask, name_id, dealt, when):
        """dealt already includes execute; store weight=dealt/execute."""
        when = full(when)
        dealt = full(dealt)
        ex = execute_t(when)
        weight = torch.where(ex != 0, dealt / ex, zeros)
        _push(torch, bufs, mask & (dealt != 0), when, weight, name_id, KIND_EXEC)

    def finish(mask, name_id, raw, index, when, count=1.0, pot_coeff=0.0):
        when = full(when)
        scale = taken_for(index, when) * fury_mult * full(count)
        weight, coeff = full(raw) * scale, full(pot_coeff) * scale
        _push(torch, bufs, mask, when, weight, name_id, KIND_EXEC, coeff)
        return (weight + potency * coeff) * execute_t(when)

    def chance(v):
        return torch.clamp(full(v), 0.0, 1.0)

    def surge_proc(mask, index, when, ch):
        nonlocal surge_p, surge_at
        when = full(when)
        ch = full(ch)
        expired = when - surge_at[:, index] > mod.SURGE_DUR
        surge_p[:, index] = torch.where(mask & expired, zeros, surge_p[:, index])
        new_p = ones - (ones - surge_p[:, index]) * (ones - chance(ch))
        surge_p[:, index] = torch.where(mask, new_p, surge_p[:, index])
        surge_at[:, index] = torch.where(mask, when, surge_at[:, index])

    def poison_spec_proc(mask, index, when, events=1.0):
        if not poison:
            return
        events = full(events)
        ch = ones - (ones - chance(0.03 * luck_mult)) ** events
        surge_proc(mask & (events > 0), index, when, ch)

    def surge_consume(mask, index, when):
        nonlocal surge_p
        when = full(when)
        expired = when - surge_at[:, index] > mod.SURGE_DUR
        surge_p[:, index] = torch.where(mask & expired, zeros, surge_p[:, index])
        active = mask & (surge_p[:, index] > 0)
        if not bool(active.any()):
            return
        raw = full(15.0 * LEVEL) + 2.5 * agi
        finish(active, N_SURGE, raw * generic(when), index, when, surge_p[:, index], generic(when))
        surge_p[:, index] = torch.where(active, zeros, surge_p[:, index])

    def attack_hit(mask, name_id, raw, when, pot_scale, index=0, count=1.0):
        when = full(when)
        raw = full(raw)
        pot_scale = full(pot_scale)
        amount = raw
        increase = ones.clone()
        if headhunter:
            increase = increase + 0.12
        increase = increase + torch.where(executor & (target_hp_t(when) <= 0.40), full(0.35), zeros)
        amount = amount * increase
        chance_c = crit0.clone()
        chance_c = chance_c + torch.where(
            boneslicer, full(10.0) + 0.5 * (full(100.0) * (ones - hero_ratio_t(when))), zeros
        )
        mult = full(2.0) + rating
        if headhunter:
            mult = mult + 0.10 + 0.008 * mastery
        crit_factor = cf(chance_c, mult)
        expected = amount * crit_factor
        coeff = pot_scale * increase * crit_factor
        expected = expected + torch.where(
            blood_hunter,
            torch.clamp(chance_c, 0.0, 100.0) / 100.0 * (full(15.0) + 0.05 * hp) * mult,
            zeros,
        )
        return finish(mask, name_id, expected * physical(when), index, when, count, coeff * physical(when))

    def dcs(now):
        value = full(mod.WHITE_BASE) + 0.75 * agi + damage + full(float(mod.TROPHIES))
        value = value + torch.where(blood_craze, full(mod.BLOOD_CRAZE_DCS), zeros)
        return value

    def va_tick(mask, index, now):
        nonlocal dambala_acc, va_until
        now = full(now)
        calls = ones.clone()
        for code_on in (deadly, wound, leeching):
            calls = calls + torch.where(code_on, chance(0.30 * luck_mult), zeros)
        scale = torch.where(dambala, full(0.25), full(0.15))
        raw = full(10.0 * mod.RANK) + scale * dcs(now)
        coeff = cf(crit0 * luck_mult, full(1.5) + rating)
        coeff = coeff * torch.where(deadly, ones + 0.005 * 100.0 * (ones - target_hp_t(now)), ones)
        raw = raw * coeff
        ticks = ones.clone()
        if poison:
            ticks = ticks + chance((full(5.0) + 0.5 * mastery) / 100.0)
        typed = torch.where(hemotoxin, physical(now), generic(now))
        finish(mask, N_VA, raw * typed, index, now, calls * ticks, coeff * typed)
        if not poison:
            ch = ones - (ones - chance(0.02 * luck_mult)) ** calls
            surge_proc(mask, index, now, ch)
        else:
            poison_spec_proc(mask, index, now, calls * ticks)
        if bool((mask & dambala).any()):
            add = chance(0.20 * luck_mult) * calls * ticks
            dambala_acc[:, index] = torch.where(mask & dambala, dambala_acc[:, index] + add, dambala_acc[:, index])
            # while >= 1: refresh VA (expected: floor adds)
            whole = torch.floor(dambala_acc[:, index])
            do = mask & dambala & (whole >= 1)
            dambala_acc[:, index] = torch.where(do, dambala_acc[:, index] - whole, dambala_acc[:, index])
            va_until[:, index] = torch.where(do, torch.maximum(va_until[:, index], now + mod.VA_DUR), va_until[:, index])

    def recover(mask, now):
        nonlocal mana, mana_time
        now = full(now)
        grow = mask & (now > mana_time) & (mana < mana_max)
        mana = torch.where(grow, torch.minimum(mana_max, mana + mana_regen * (now - mana_time)), mana)
        mana_time = torch.where(mask, now, mana_time)

    def note_damage_mana(mask, count):
        nonlocal mana
        count = full(count)
        mana = torch.where(mask & (dmp > 0), torch.minimum(mana_max, mana + dmp * mana_max * count), mana)

    def cooldown(base):
        return torch.clamp((full(base) * cd_temp - flat_cdr) / (ones + haste), min=0.5)

    def attack_interval(now):
        swing = full(mod.SWING) * torch.where(galactic, full(1.20), ones)
        speed = attack_speed0 + berserk_speed(now)
        speed = speed + torch.where(blood_fanatic, 0.01 * 100.0 * (ones - hero_ratio_t(now)), zeros)
        speed = torch.clamp(speed, -0.8, 4.0)
        return swing / (ones + speed)

    def axe_hit(mask, now, count):
        attack_hit(mask, N_AXE, full(20.0) + 1.25 * dcs(now), now,
                   attack_potency, count=count)

    # state
    mana = mana_max.clone()
    mana_time = zeros.clone()
    next_attack = zeros.clone()
    next_sack = zeros.clone()
    next_skull = zeros.clone()
    next_tick = full(1.0)
    next_pressure = full(mod.PRESSURE_STEP)
    busy = zeros.clone()
    va_until = torch.full((B, Tt), -1.0, dtype=dtype, device=device)
    dambala_acc = torch.zeros((B, Tt), dtype=dtype, device=device)
    surge_p = torch.zeros((B, Tt), dtype=dtype, device=device)
    surge_at = torch.full((B, Tt), -1.0, dtype=dtype, device=device)

    # pending sack lands
    p_time = torch.full((B, MAX_PENDING), BIG, dtype=dtype, device=device)
    p_order = torch.zeros((B, MAX_PENDING), dtype=torch.int64, device=device)
    order_c = torch.zeros(B, dtype=torch.int64, device=device)

    def peek_land():
        return p_time.min(dim=1).values

    def push_land(mask, when):
        nonlocal order_c
        if not bool(mask.any()):
            return
        when = full(when)
        free = p_time >= BIG
        if bool((mask & ~free.any(dim=1)).any()):
            raise _Overflow("pending_sack")
        slot = torch.argmax(free.to(torch.int8), dim=1)
        r = rix[mask]
        s = slot[mask]
        p_time[r, s] = when[mask]
        p_order[r, s] = order_c[mask]
        order_c = order_c + mask.to(torch.int64)

    def pop_land(mask):
        scored = p_time * 1e6 + p_order.to(dtype)
        scored = torch.where(p_time < BIG, scored, torch.full_like(scored, BIG * 1e7))
        slot = scored.argmin(dim=1)
        p_time[rix[mask], slot[mask]] = BIG

    bufs = _make_bufs(torch, device, B, dtype)
    alive = torch.ones(B, dtype=torch.bool, device=device)

    steps = 0
    while bool(alive.any()):
        steps += 1
        if steps > MAX_STEPS:
            raise _Overflow("steps")

        land = peek_land()
        moment = next_attack.clone()
        for tmr in (next_sack, next_skull, next_tick, next_pressure, land):
            moment = torch.minimum(moment, tmr)

        done = alive & (moment >= fight)
        alive = alive & ~done
        if not bool(alive.any()):
            break

        acted = torch.zeros(B, dtype=torch.bool, device=device)

        # LAND toxic sack
        is_land = alive & (moment == land) & (land < BIG)
        if bool(is_land.any()):
            pop_land(is_land)
            raw = full(80.0 * mod.RANK - 20.0) + 2.2 * agi
            for index in range(min(Tt, T)):
                va = moment < va_until[:, index]
                coeff = torch.where(poison_bomb, torch.where(va, full(1.6), full(1.3)), ones)
                finish(is_land, N_SACK, raw * coeff * physical(moment), index, moment,
                       pot_coeff=coeff * physical(moment))
                poison_spec_proc(is_land, index, moment)
                va_until[:, index] = torch.where(
                    is_land, torch.maximum(va_until[:, index], moment + mod.VA_DUR), va_until[:, index]
                )
            note_damage_mana(is_land, float(T))
            acted = acted | is_land

        # VA tick
        is_tick = alive & ~acted & (moment == next_tick)
        if bool(is_tick.any()):
            for index in range(min(Tt, T)):
                on = is_tick & (moment - 1e-9 < va_until[:, index])
                if bool(on.any()):
                    va_tick(on, index, moment)
            next_tick = torch.where(is_tick, next_tick + 1.0, next_tick)
            acted = acted | is_tick

        # Pressure / Axe Mastery
        is_press = alive & ~acted & (moment == next_pressure)
        if bool(is_press.any()):
            do = is_press & axe_t
            if bool(do.any()):
                axe_hit(do, moment, chance(0.05 * luck_mult))
            next_pressure = torch.where(is_press, next_pressure + mod.PRESSURE_STEP, next_pressure)
            acted = acted | is_press

        # Busy gate: defer hero actions
        is_busy = alive & ~acted & (moment < busy)
        if bool(is_busy.any()):
            next_attack = torch.where(is_busy & (moment == next_attack), busy, next_attack)
            next_sack = torch.where(is_busy & (moment == next_sack), busy, next_sack)
            next_skull = torch.where(is_busy & (moment == next_skull), busy, next_skull)
            acted = acted | is_busy

        # Toxic Sack cast
        is_sack = alive & ~acted & (moment == next_sack)
        if bool(is_sack.any()):
            recover(is_sack, moment)
            ok = is_sack & (mana >= mod.SACK_MANA)
            fail = is_sack & ~ok
            next_sack = torch.where(fail, moment + 0.25, next_sack)
            if bool(ok.any()):
                mana = torch.where(ok, mana - mod.SACK_MANA, mana)
                mana = torch.where(ok, torch.minimum(mana_max, mana + sack_back), mana)
                push_land(ok, moment + cast_point + mod.SACK_DELAY)
                busy_n = moment + cast_time + cast_stun
                busy = torch.where(ok, busy_n, busy)
                next_sack = torch.where(ok, moment + cooldown(mod.SACK_CD), next_sack)
                next_attack = torch.where(ok, torch.maximum(next_attack, busy_n), next_attack)
            acted = acted | is_sack

        # Skull Split cast
        is_skull = alive & ~acted & (moment == next_skull)
        if bool(is_skull.any()):
            recover(is_skull, moment)
            ok = is_skull & (mana >= mod.SKULL_MANA)
            fail = is_skull & ~ok
            next_skull = torch.where(fail, moment + 0.25, next_skull)
            if bool(ok.any()):
                mana = torch.where(ok, mana - mod.SKULL_MANA, mana)
                mana = torch.where(ok, torch.minimum(mana_max, mana + skull_back), mana)
                hit = moment + cast_point
                raw = full(150.0 * mod.RANK) + 2.0 * dcs(hit) + full(0.05 * MEDIAN_MONSTER_HP)
                coeff = torch.where(executor & (target_hp_t(hit) <= 0.40), full(1.35), ones)
                finish(ok, N_SKULL, raw * coeff * physical(hit), 0, hit, pot_coeff=coeff * physical(hit))
                poison_spec_proc(ok, 0, hit)
                note_damage_mana(ok, 1.0)
                busy_n = moment + cast_time + cast_stun
                busy = torch.where(ok, busy_n, busy)
                next_skull = torch.where(ok, moment + cooldown(mod.SKULL_CD), next_skull)
                next_attack = torch.where(ok, torch.maximum(next_attack, busy_n), next_attack)
            acted = acted | is_skull

        # Auto attack
        is_auto = alive & ~acted & (moment == next_attack)
        if bool(is_auto.any()):
            recover(is_auto, moment)
            power = dcs(moment)
            had_va = moment < va_until[:, 0]
            surge_consume(is_auto, 0, moment)
            # Scale both raw and coefficient; no potency-baked FLAT adjustment.
            attack_hit(is_auto, N_AUTO, power, moment, attack_potency, count=auto_pct)
            poison_spec_proc(is_auto, 0, moment)
            mana = torch.where(is_auto, torch.minimum(mana_max, mana + amg), mana)
            note_damage_mana(is_auto, 1.0)
            va_until[:, 0] = torch.where(is_auto, torch.maximum(va_until[:, 0], moment + mod.VA_DUR), va_until[:, 0])
            blades_tick = is_auto & blades & had_va
            if bool(blades_tick.any()):
                va_tick(blades_tick, 0, moment)
            if bool((is_auto & snake).any()):
                ch = chance(0.20 * luck_mult)
                raw = full(2.0) * (full(10.0 * mod.RANK) + 0.5 * agi)
                for index in range(min(Tt, T)):
                    finish(is_auto & snake, N_SNAKE, raw * generic(moment), index, moment, ch, generic(moment))
                    # consume surge portion
                    active_s = is_auto & snake & (surge_p[:, index] > 0) & (moment - surge_at[:, index] <= mod.SURGE_DUR)
                    consumed = surge_p[:, index] * ch
                    surge_value = (full(15.0 * LEVEL) + 2.5 * agi) * generic(moment)
                    finish(active_s, N_SURGE, surge_value, index, moment, consumed, generic(moment))
                    surge_p[:, index] = torch.where(active_s, surge_p[:, index] - consumed, surge_p[:, index])
                note_damage_mana(is_auto & snake, float(T) * ch)
            if bool((is_auto & axe_t).any()):
                rolls = ones + torch.where(blood_craze, chance(0.30 * luck_mult), zeros)
                axe_hit(is_auto & axe_t, moment, rolls * chance(0.10 * luck_mult))
            if bool((is_auto & fire_orb).any()):
                splash = (full(20.0) + 0.35 * agi) * float(T) * taken_for(0, moment) * execute_t(moment) * fury_mult
                add_exec(is_auto & fire_orb, N_FIRE, splash, moment)
                note_damage_mana(is_auto & fire_orb, float(T))
            next_attack = torch.where(is_auto, moment + attack_interval(moment), next_attack)
            acted = acted | is_auto

        # Safety: if nothing acted but alive, bump something
        stuck = alive & ~acted
        if bool(stuck.any()):
            # should not happen; advance smallest timer past moment
            raise _Overflow("stuck")

    return _finalize(bufs, stats_list)

