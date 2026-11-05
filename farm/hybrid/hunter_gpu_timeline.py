# -*- coding: utf-8 -*-
"""Batched next-event timeline for Hunter (marksmanship / beast_mastery / survival).

Faithful port of sunken_sim.hunter.simulate onto batched torch: one row per build.
Pets in fixed slots; per-row _Dither accumulators; per-target stung/wound.
f64 clocks on CPU (DirectML lacks f64); kind-score stays in farm.hybrid.hunter.
Event shape: (when, name, weight, kind).
"""
from __future__ import annotations

MAX_STEPS = 400000
MAX_PENDING = 128
MAX_PETS = 16
MAX_T = 8
MAX_EVENTS = 4096

A_CALL, A_WRATH, A_STING, A_MULTI, A_TRAP = 0, 1, 2, 3, 4
COSTS = (30.0, 20.0, 15.0, 10.0, 20.0)
P_TRAP, P_MULTI2 = 0, 1
K_SPIKE, K_HUFFER, K_GRYLLS = 0, 1, 2
PET_BASE = (9.0, 4.0, 17.0)
PET_SCALE = (0.50, 0.30, 0.90)
PET_SWING = (1.50, 1.45, 1.70)
SPEC_PET = {"marksmanship": K_HUFFER, "beast_mastery": K_SPIKE, "survival": K_GRYLLS}

N_AUTO, N_STING, N_STING_TICK, N_MULTI, N_SPLIT, N_TRAP = 0, 1, 2, 3, 4, 5
N_SPIKE, N_HUFFER, N_GRYLLS, N_HOWL, N_MAUL, N_SHRED = 6, 7, 8, 9, 10, 11
N_MARK, N_FIRE, N_SULF, N_SULF_ECHO = 12, 13, 14, 15
NAMES = {
    N_AUTO: "\u0410\u0432\u0442\u043e\u0430\u0442\u0430\u043a\u0430",
    N_STING: "Serpent Sting",
    N_STING_TICK: "Serpent Sting (\u0442\u0438\u043a\u0438)",
    N_MULTI: "Multi-Shot",
    N_SPLIT: "Split Shot",
    N_TRAP: "Steel Trap",
    N_SPIKE: "Spike",
    N_HUFFER: "Huffer",
    N_GRYLLS: "Grylls",
    N_HOWL: "Howl of the Packleader",
    N_MAUL: "Maul",
    N_SHRED: "Shred",
    N_MARK: "Marksmanship",
    N_FIRE: "\u0412\u0441\u043f\u043b\u0435\u0441\u043a \u043e\u0433\u043d\u044f",
    N_SULF: "Sulfuras",
    N_SULF_ECHO: "Sulfuras (\u0443\u0434\u0430\u0440)",
}
PET_N = {K_SPIKE: N_SPIKE, K_HUFFER: N_HUFFER, K_GRYLLS: N_GRYLLS}
KIND_PHYS, KIND_EXEC, KIND_MAG, KIND_FLAT = 0.0, 1.0, 2.0, 3.0


class _Overflow(Exception):
    pass


def generate_hunter_timelines(torch, device, builds, spec: str, targets: int):
    if spec not in ("marksmanship", "beast_mastery", "survival"):
        raise ValueError(f"hunter GPU timeline specs mm/bm/survival, got {spec}")
    if not builds:
        return []
    dev_type = getattr(device, "type", str(device))
    if dev_type in ("privateuseone", "dml") or "privateuseone" in str(device):
        device = torch.device("cpu")
    try:
        return _hunter_batch(torch, device, torch.float64, builds, spec, int(targets))
    except _Overflow:
        return _cpu_events_batch(builds, spec, targets)


def _cpu_events_batch(builds, spec, targets):
    from sunken_sim import hunter as mod

    out = []
    for build in builds:
        stats = mod.stats_of(build)
        key = mod._timeline_key(build, stats, spec, targets)
        cached = mod._TIMELINE.get(key)
        if cached is None:
            mod.simulate(build, targets, spec)
            cached = mod._TIMELINE[key]
        out.append((list(cached[0]), stats))
    return out


def _armor_taken_t(torch, armor, factor):
    pos = armor > 0
    neg = armor < 0
    out = torch.ones_like(armor)
    out = torch.where(pos, 1.0 - (armor * factor) / (1.0 + factor * armor), out)
    out = torch.where(neg, 2.0 - (1.0 - factor) ** (-armor), out)
    return out


def _push(torch, bufs, mask, when, weight, name_id, kind):
    if not bool(mask.any()):
        return
    B = int(mask.shape[0])
    active = mask & (bufs["length"] < MAX_EVENTS) & (weight != 0)
    if not bool(active.any()):
        return
    rows = torch.arange(B, device=weight.device)
    idx = bufs["length"].clone()
    bufs["when"][rows[active], idx[active]] = when[active]
    bufs["weight"][rows[active], idx[active]] = weight[active]
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
    for i, stats in enumerate(stats_list):
        n = int(lengths[i])
        events = []
        for j in range(n):
            events.append((float(whens[i, j]), NAMES[int(names[i, j])], float(weights[i, j]), float(kinds[i, j])))
        out.append((events, stats))
    return out


def _hunter_batch(torch, device, dtype, builds, spec, T):
    """True batched port. Raises _Overflow on slot/step exhaustion."""
    from sunken_sim import hunter as mod
    from sunken_sim.shadow import (
        CAST_BACKSWING, CAST_POINT, DUMMY_ARMOR, FIGHT, ARMOR_FACTOR,
        attack_mana_gain, cast_mana_back, sulfuras_echo_chance, _wears, target_hp,
    )

    B = len(builds)
    fight = float(FIGHT)
    cast_point = float(CAST_POINT)
    cast_time = float(CAST_POINT + CAST_BACKSWING)
    RANK = float(mod.RANK)
    WHITE = float(mod.WHITE_BASE)
    SWING = float(mod.SWING)
    ASPECT = float(mod.ASPECT)
    BIG = 1e18
    Tt = min(int(T), MAX_T)
    zeros = torch.zeros(B, dtype=dtype, device=device)
    ones = torch.ones(B, dtype=dtype, device=device)
    rix = torch.arange(B, device=device)

    # per-row consts
    stats_list = []
    rows = []
    for build in builds:
        stats = mod.stats_of(build)
        stats_list.append(stats)
        has = lambda c, b=build: mod._has(b, c)
        luck_mult = 1.0 + stats["luck"]
        rows.append({
            "mana_max": stats["mana_max"], "mana_regen": stats["mana_regen"],
            "dmp": stats.get("damage_mana_pct") or 0.0,
            "stun": stats["cast_stun_lock"], "haste": stats["haste"],
            "agi": stats["agi"], "intel": stats["int"], "mastery": stats["mastery"],
            "damage": stats["damage"], "potency": stats["potency"],
            "crit": stats["crit"], "rating": stats["rating"],
            "attack_speed": stats["attack_speed"], "armor_pen": stats["armor_pen"],
            "auto_pct": stats["auto_pct"] if stats["auto_pct"] != 1.0 else 1.0,
            "attack_potency": stats["attack_potency"], "pet_damage": stats["pet_damage"],
            "summon_crit": stats["summon_crit"], "summon_rating": stats["summon_rating"],
            "luck_mult": luck_mult, "cd_temp": stats["cd_temp"], "flat_cdr": stats["flat_cdr"],
            "amg": attack_mana_gain(stats),
            "sulf_echo": sulfuras_echo_chance(stats["luck"]),
            "backs": [cast_mana_back(c, stats) for c in COSTS],
            "sulfuras": 1.0 if _wears(build, "I0BR") else 0.0,
            "fire_orb": 1.0 if stats["fire_orb"] else 0.0,
            "steel_quiver": 1.0 if stats["steel_quiver"] else 0.0,
            "trap_gloves": 1.0 if stats["trap_gloves"] else 0.0,
            "recurve_bow": 1.0 if stats["recurve_bow"] else 0.0,
            "beast_helm": 1.0 if stats["beast_helm"] else 0.0,
            "galactic": 1.0 if stats["galactic"] else 0.0,
            "talon": 1.0 if has(mod.TALENT_TALON_STRIKES) else 0.0,
            "unleash": 1.0 if has(mod.TALENT_UNLEASH) else 0.0,
            "traplayer": 1.0 if has(mod.TALENT_TRAPLAYER) else 0.0,
            "hydra": 1.0 if has(mod.TALENT_HYDRA_SHOTS) else 0.0,
            "lock": 1.0 if has(mod.TALENT_LOCK_AND_LOAD) else 0.0,
            "howl": 1.0 if has(mod.TALENT_HOWL) else 0.0,
            "trueshot": 1.0 if has(mod.TALENT_TRUESHOT) else 0.0,
            "wild": 1.0 if has(mod.TALENT_WILD_POWER) else 0.0,
            "volley": 1.0 if has(mod.TALENT_VOLLEY) else 0.0,
            "windrunner": 1.0 if has(mod.TALENT_WINDRUNNER) else 0.0,
            "killer": 1.0 if has(mod.TALENT_KILLER_INSTINCT) else 0.0,
            "steel": 1.0 if has(mod.TALENT_STEEL_ARROWHEADS) else 0.0,
            "flanking": 1.0 if has(mod.TALENT_FLANKING) else 0.0,
            "dire": 1.0 if has(mod.TALENT_DIRE_BEASTS) else 0.0,
            "mongoose": 1.0 if has(mod.TALENT_MONGOOSE) else 0.0,
            "scent": 1.0 if has(mod.TALENT_SCENT_OF_BLOOD) else 0.0,
            "unmatched": 1.0 if has(mod.TALENT_UNMATCHED) else 0.0,
            "poison": 1.0 if has(mod.TALENT_POISONED_ARROWS) else 0.0,
        })

    def V(k):
        return torch.tensor([r[k] for r in rows], dtype=dtype, device=device)

    def F(k):
        return V(k) > 0.5

    mana_max, mana_regen, dmp = V("mana_max"), V("mana_regen"), V("dmp")
    stun, haste = V("stun"), V("haste")
    agi, mastery, damage = V("agi"), V("mastery"), V("damage")
    potency0, crit0, rating0 = V("potency"), V("crit"), V("rating")
    attack_speed0, armor_pen = V("attack_speed"), V("armor_pen")
    auto_pct, attack_potency = V("auto_pct"), V("attack_potency")
    pet_damage = V("pet_damage")
    summon_crit, summon_rating = V("summon_crit"), V("summon_rating")
    luck_mult, cd_temp, flat_cdr = V("luck_mult"), V("cd_temp"), V("flat_cdr")
    amg, sulf_echo = V("amg"), V("sulf_echo")
    backs = torch.tensor([r["backs"] for r in rows], dtype=dtype, device=device)
    costs_t = torch.tensor(COSTS, dtype=dtype, device=device)
    cur_pet = torch.full((B,), SPEC_PET[spec], dtype=torch.int64, device=device)
    is_mm = torch.full((B,), spec == "marksmanship", device=device)
    is_bm = torch.full((B,), spec == "beast_mastery", device=device)
    is_sv = torch.full((B,), spec == "survival", device=device)
    talon, unleash, traplayer = F("talon"), F("unleash"), F("traplayer")
    hydra, lock_t, howl_t = F("hydra"), F("lock"), F("howl")
    trueshot, wild, volley = F("trueshot"), F("wild"), F("volley")
    windrunner, killer, steel = F("windrunner"), F("killer"), F("steel")
    flanking, dire, mongoose = F("flanking"), F("dire"), F("mongoose")
    scent, unmatched, poison = F("scent"), F("unmatched"), F("poison")
    fire_orb, steel_quiver = F("fire_orb"), F("steel_quiver")
    trap_gloves, recurve_bow = F("trap_gloves"), F("recurve_bow")
    beast_helm, galactic, sulfuras_on = F("beast_helm"), F("galactic"), F("sulfuras")
    pet_base_t = torch.tensor(PET_BASE, dtype=dtype, device=device)
    pet_scale_t = torch.tensor(PET_SCALE, dtype=dtype, device=device)
    pet_swing_t = torch.tensor(PET_SWING, dtype=dtype, device=device)
    factor = float(ARMOR_FACTOR)

    mana = mana_max.clone()
    mana_time = zeros.clone()
    busy = zeros.clone()
    next_attack = zeros.clone()
    next_tick = ones.clone()
    ready = torch.zeros((B, 5), dtype=dtype, device=device)
    stung = torch.full((B, Tt), -1.0, dtype=dtype, device=device)
    wound = torch.full((B, Tt), -1.0, dtype=dtype, device=device)
    wrath_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    lock_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    h_prowess = torch.full((B,), -1.0, dtype=dtype, device=device)
    p_prowess = torch.full((B,), -1.0, dtype=dtype, device=device)
    quill_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    quill_count = zeros.clone()
    quiver = zeros.clone()
    split_flag = torch.zeros(B, dtype=torch.bool, device=device)
    howl_stacks = zeros.clone()
    sulf_armed = torch.zeros(B, dtype=torch.bool, device=device)
    d_lock = zeros.clone(); d_prowess = zeros.clone(); d_pet_prowess = zeros.clone()
    d_split = zeros.clone(); d_maul = zeros.clone(); d_trap = zeros.clone(); d_shred = zeros.clone()
    p_time = torch.full((B, MAX_PENDING), BIG, dtype=dtype, device=device)
    p_order = torch.zeros((B, MAX_PENDING), dtype=torch.int64, device=device)
    p_kind = torch.zeros((B, MAX_PENDING), dtype=torch.int64, device=device)
    p_idx = torch.zeros((B, MAX_PENDING), dtype=torch.int64, device=device)
    order_c = torch.zeros(B, dtype=torch.int64, device=device)
    pet_alive = torch.zeros((B, MAX_PETS), dtype=torch.bool, device=device)
    pet_kind = torch.zeros((B, MAX_PETS), dtype=torch.int64, device=device)
    pet_next = torch.full((B, MAX_PETS), BIG, dtype=dtype, device=device)
    pet_end = torch.full((B, MAX_PETS), -BIG, dtype=dtype, device=device)
    pet_start = zeros.view(B, 1).expand(B, MAX_PETS).clone()
    bufs = _make_bufs(torch, device, B, dtype)
    alive = torch.ones(B, dtype=torch.bool, device=device)

    def full(v):
        return v if isinstance(v, torch.Tensor) else torch.full((B,), float(v), dtype=dtype, device=device)

    def chance(v):
        return torch.clamp(full(v), 0.0, 1.0)

    def dither(acc, mask, ch):
        ch = chance(ch)
        m = mask & (ch > 0)
        na = acc + torch.where(m, ch, zeros)
        fire = m & (na >= 1.0 - 1e-9)
        out = torch.where(fire, na - 1.0, na)
        return fire, torch.where(m, out, acc)

    def recover(mask, now):
        nonlocal mana, mana_time
        now = full(now)
        grow = mask & (now > mana_time) & (mana < mana_max)
        mana = torch.where(grow, torch.minimum(mana_max, mana + mana_regen * (now - mana_time)), mana)
        mana_time = torch.where(mask, now, mana_time)

    def gain(mask, amount):
        nonlocal mana
        mana = torch.where(mask, torch.minimum(mana_max, mana + full(amount)), mana)

    def note_dmp(mask, count):
        gain(mask & (dmp > 0), dmp * mana_max * full(count))

    def cd(base, flat=0.0):
        return torch.clamp((full(base) * cd_temp - flat_cdr - full(flat)) / (1.0 + haste), min=0.5)

    def wrath_on(now):
        return full(now) < wrath_until

    def wrath_pct():
        return 0.30 + 0.03 * RANK + torch.where(wild, full(0.25), zeros)

    def dcs(now):
        value = WHITE + 0.75 * agi + damage
        mult = 1.0 + torch.where(wild, full(0.35), full(0.20)) + 0.05 * RANK
        return torch.where(wrath_on(now), value * mult, value)

    def pot(now):
        return torch.where(hydra, potency0 + 3.0 + 0.04 * dcs(now), potency0)

    def thp(now):
        return torch.clamp(1.0 - full(now) / fight, min=0.0)

    def taken(index, now, hunter=True):
        armor = full(float(DUMMY_ARMOR))
        if hunter:
            armor = armor - armor_pen
        if isinstance(index, int):
            if index < Tt:
                armor = armor - torch.where(stung[:, index] > full(now), full(mod.STING_PEN), zeros)
                armor = armor - torch.where(wound[:, index] > full(now), full(mod.WOUND_ARMOR), zeros)
        return _armor_taken_t(torch, armor, factor)

    def hero_crit(now):
        c = crit0 + torch.where(trueshot, full(10.0), zeros)
        return torch.where(full(now) < quill_until, c + 20.0, c)

    def hero_rating(now):
        r = 2.0 + rating0
        return torch.where(unmatched, r + 0.25 + 0.15 * hero_crit(now) / 100.0, r)

    def cf(ch, mult):
        ch = torch.clamp(full(ch), 0.0, 100.0) / 100.0
        return 1.0 + ch * (full(mult) - 1.0)

    def push_pend(mask, when, kind, index=0):
        nonlocal order_c
        when = full(when)
        m = mask & (when < fight)
        if not bool(m.any()):
            return
        free = p_time >= BIG
        if bool((m & ~free.any(dim=1)).any()):
            raise _Overflow("pending")
        slot = torch.argmax(free.to(torch.int8), dim=1)
        order_c = order_c + m.to(torch.int64)
        r = rix[m]; s = slot[m]
        p_time[r, s] = when[m]
        p_order[r, s] = order_c[m]
        p_kind[r, s] = int(kind)
        p_idx[r, s] = int(index) if not isinstance(index, torch.Tensor) else index[m]

    def peek_pend():
        t = p_time.min(dim=1).values
        return torch.where(t >= BIG, full(fight * 10), t)

    def pop_pend(mask):
        tmin = p_time.min(dim=1, keepdim=True).values
        cand = p_time == tmin
        big = torch.iinfo(torch.int64).max
        o = torch.where(cand, p_order, torch.full_like(p_order, big))
        slot = torch.argmin(o, dim=1)
        now = p_time[rix, slot].clone()
        kind = p_kind[rix, slot].clone()
        idx = p_idx[rix, slot].clone()
        p_time[rix[mask], slot[mask]] = BIG
        return now, kind, idx

    def do_hit(mask, name, raw, now, index=0, attack=0.0, typed=True, pot_scale=1.0, count=1.0):
        nonlocal quiver, stung
        if not bool(mask.any()):
            return zeros
        now, raw, attack, pot_scale, count = map(full, (now, raw, attack, pot_scale, count))
        amount = (raw + pot(now) * pot_scale) * (1.0 + ASPECT)
        armor = taken(index, now, True)
        pre_plain = amount * armor
        inc = ones + torch.where(mongoose, full(0.10), zeros)
        if isinstance(index, int) and index == 0:
            inc = inc + torch.where(flanking, full(0.15), zeros)
        ch = hero_crit(now); mult = hero_rating(now)
        normal = amount * inc * armor * cf(ch, mult)
        armed = torch.where(windrunner, quiver * attack, zeros)
        boosted = amount * inc * (1.0 + ch / 100.0) * armor * mult
        safe = torch.where(attack > 0, attack, ones)
        atk_pre = (1.0 - armed / safe) * normal + (armed / safe) * boosted
        share = attack * ((1.0 - armed / safe) * chance(ch / 100.0) + armed / safe)
        pre = torch.where(attack > 0, (1.0 - attack) * pre_plain + attack * atk_pre, pre_plain)
        quiver = torch.where(mask & (armed > 0), quiver - armed, quiver)
        if isinstance(index, int) and index < Tt:
            stung[:, index] = torch.where(
                mask & poison & (attack >= 0.5),
                torch.maximum(stung[:, index], now + mod.STING_DUR),
                stung[:, index],
            )
        if isinstance(typed, torch.Tensor):
            kind = torch.where(typed, full(KIND_PHYS), full(KIND_EXEC))
        else:
            kind = KIND_PHYS if typed else KIND_EXEC
        _push(torch, bufs, mask, now, pre * count, name, kind)
        note_dmp(mask, count)
        return share

    def do_pet_hit(mask, name, raw, now, kid, index=0, attack=True):
        if not bool(mask.any()):
            return zeros
        now, raw = full(now), full(raw)
        amount = raw * (1.0 + pet_damage) * (1.0 + ASPECT)
        amount = amount * torch.where(scent & (thp(now) < 0.40), full(1.28), ones)
        armor = taken(index, now, False)
        share = zeros.clone()
        if attack:
            inc = ones.clone()
            is_cur = (kid == cur_pet) if not isinstance(kid, torch.Tensor) else (kid == cur_pet)
            if isinstance(index, int) and index == 0:
                inc = torch.where(flanking & is_cur, inc + 0.15, inc)
            is_spike = (kid == K_SPIKE) if not isinstance(kid, torch.Tensor) else (kid == K_SPIKE)
            ch = summon_crit + torch.where(is_spike, full(20.0), zeros)
            rating = 2.0 + summon_rating + torch.where(is_spike, full(0.30), zeros)
            rating = torch.where(unmatched, rating + 0.25 + 0.15 * hero_crit(now) / 100.0, rating)
            share = chance(ch / 100.0)
            pre = amount * inc * armor * cf(ch, rating)
        else:
            pre = amount * armor
        _push(torch, bufs, mask, now, pre, name, KIND_EXEC)
        return share

    def do_trap(mask, index, now, count=1.0):
        nonlocal wound
        now, count = full(now), full(count)
        do_hit(mask, N_TRAP, 40.0 + 1.20 * dcs(now) + 0.50 * agi, now, index=index, count=count)
        if isinstance(index, int) and index < Tt:
            wound[:, index] = torch.where(
                mask & (count >= 0.5),
                torch.maximum(wound[:, index], now + mod.WOUND_DUR),
                wound[:, index],
            )

    def do_multi(mask, now, secondary):
        nonlocal d_trap
        if not bool(mask.any()):
            return
        now = full(now)
        hits_n = torch.where(volley, full(float(min(T, 5))), full(float(min(T, 3))))
        raw = 10.0 + 60.0 * RANK + 0.70 * dcs(now) + 0.30 * agi
        raw = torch.where(volley, raw * 1.10, raw)
        raw = torch.where(mongoose, raw * 1.10, raw)
        if secondary:
            raw = raw * 0.50
        raw = torch.where(recurve_bow, raw * 1.25, raw)
        pierce = torch.where(steel | steel_quiver, chance(0.30 * luck_mult), zeros)
        for index in range(min(T, 5)):
            active = mask & (hits_n > index)
            typed = pierce < 1.0
            do_hit(active, N_MULTI, raw, now, index=index, attack=pierce, typed=typed)
            ch = 0.25 * luck_mult * (0.5 if secondary else 1.0)
            fire, d_trap = dither(d_trap, active & traplayer, ch)
            do_trap(fire, index, now)

    def cut_cds(mask, now, fraction=0.0, seconds=0.0):
        nonlocal ready
        now, fraction, seconds = full(now), full(fraction), full(seconds)
        for k in range(5):
            left = ready[:, k] - now
            pos = mask & (left > 0)
            ready[:, k] = torch.where(pos, now + torch.clamp(left * (1.0 - fraction) - seconds, min=0.0), ready[:, k])

    def h_interval(now):
        swing = SWING * torch.where(galactic, full(1.20), ones)
        swing = torch.where(is_mm, swing * (1.0 - ASPECT), swing)
        speed = attack_speed0.clone()
        speed = torch.where(full(now) < lock_until, speed + 0.40, speed)
        speed = torch.where(full(now) < h_prowess, speed + 0.20, speed)
        speed = torch.where(beast_helm & wrath_on(now), speed + 0.25, speed)
        return swing / (1.0 + torch.clamp(speed, -0.8, 4.0))

    def p_interval(kid, start, now):
        swing = pet_swing_t[kid]
        swing = torch.where(talon, swing * 0.90, swing)
        speed = torch.where(is_bm, full(0.10) + 0.008 * mastery, zeros)
        is_cur = kid == cur_pet
        speed = torch.where(is_cur & (full(now) < p_prowess), speed + 0.40, speed)
        speed = torch.where(is_cur & beast_helm & wrath_on(now), speed + 0.25, speed)
        age = full(now) - start
        frenzy = (kid == K_HUFFER) & dire & ((age % 20.0) < 12.0)
        speed = torch.where(frenzy, speed + 0.40, speed)
        return swing / (1.0 + torch.clamp(speed, -0.8, 4.0))

    def spawn(mask, kid, nxt, end, start):
        nonlocal pet_alive
        if not bool(mask.any()):
            return
        free = ~pet_alive
        if bool((mask & ~free.any(dim=1)).any()):
            raise _Overflow("pets")
        slot = torch.argmax(free.to(torch.int8), dim=1)
        r = rix[mask]; s = slot[mask]
        pet_alive[r, s] = True
        pet_kind[r, s] = kid[mask] if isinstance(kid, torch.Tensor) else int(kid)
        pet_next[r, s] = full(nxt)[mask]
        pet_end[r, s] = full(end)[mask]
        pet_start[r, s] = full(start)[mask]

    def clear_kind(mask, kid):
        nonlocal pet_alive
        if isinstance(kid, torch.Tensor):
            match = pet_kind == kid.view(B, 1)
        else:
            match = pet_kind == int(kid)
        pet_alive = pet_alive & ~(match & mask.view(B, 1))

    def howl_add(mask):
        nonlocal howl_stacks
        howl_stacks = torch.where(mask & howl_t & (howl_stacks < 3), howl_stacks + 1.0, howl_stacks)

    def howl_val():
        return 20.0 + 0.25 * agi + 0.50 * mastery

    def pet_attack(mask, slot, now):
        nonlocal howl_stacks, quill_count, quill_until, h_prowess, p_prowess, d_maul, d_shred, d_pet_prowess
        if not bool(mask.any()):
            return
        now = full(now)
        kid = pet_kind[:, slot]
        start = pet_start[:, slot]
        base = pet_base_t[kid]; scale = pet_scale_t[kid]
        dnow = dcs(now)
        raw = base + torch.floor(scale * dnow) + 1.0
        is_cur = kid == cur_pet
        bw = wrath_pct() * torch.where(is_bm, ones, full(0.5))
        raw = torch.where(mask & is_cur & wrath_on(now), raw * (1.0 + bw), raw)
        raw = torch.where(mask & (kid == K_GRYLLS) & dire, raw * 1.20, raw)
        main_raw = raw.clone()
        has_h = mask & is_cur & (howl_stacks > 0)
        hv = howl_val() * howl_stacks
        howl_stacks = torch.where(has_h, zeros, howl_stacks)
        main_raw = torch.where(has_h & is_bm, main_raw + hv, main_raw)
        do_hit(has_h & ~is_bm, N_HOWL, hv, now)
        # per pet kind name
        share = zeros.clone()
        for kid_i, nid in ((K_SPIKE, N_SPIKE), (K_HUFFER, N_HUFFER), (K_GRYLLS, N_GRYLLS)):
            km = mask & (kid == kid_i)
            if not bool(km.any()):
                continue
            sh = do_pet_hit(km, nid, main_raw, now, kid, 0, True)
            share = torch.where(km, sh, share)
            if kid_i == K_HUFFER:
                for index in range(1, min(T, 3)):
                    do_pet_hit(km, nid, raw, now, kid, index, True)
                evn = full(float(min(T, 3)))
                qc = quill_count + torch.where(km, evn, zeros)
                qu = quill_until.clone()
                for _ in range(8):
                    fire = km & (qc >= 15)
                    if not bool(fire.any()):
                        break
                    qc = torch.where(fire, qc - 15.0, qc)
                    qu = torch.where(fire, now + mod.QUILL_DUR, qu)
                quill_count = torch.where(km, qc, quill_count)
                quill_until = torch.where(km, qu, quill_until)
            if kid_i == K_GRYLLS:
                fire, d_maul = dither(d_maul, km, 0.20 * luck_mult)
                do_hit(fire, N_MAUL, 15.0 + 1.50 * dnow, now)
            if kid_i == K_SPIKE:
                ch = 0.20 * (1.0 + share) * luck_mult
                fire, d_shred = dither(d_shred, km & dire, ch)
                do_pet_hit(fire, N_SHRED, 50.0 + 0.50 * dnow, now, kid, 0, False)
        fire, d_pet_prowess = dither(d_pet_prowess, mask, share)
        h_prowess = torch.where(fire, now + mod.PROWESS_DUR, h_prowess)
        # talon CDR
        if bool(talon.any()):
            # events count: huffer min(T,3) else 1
            evn = torch.where(kid == K_HUFFER, full(float(min(T, 3))), ones)
            frac = torch.where(is_cur, full(0.06), full(0.02))
            # approximate: apply once * events (CPU loops events times)
            # For exactness loop
            max_e = int(min(T, 3))
            for e in range(max_e):
                cut_cds(mask & talon & (evn > e), now, fraction=frac)

        pet_next[:, slot] = torch.where(mask, now + p_interval(kid, start, now), pet_next[:, slot])

    steps = 0
    while bool(alive.any()):
        steps += 1
        if steps > MAX_STEPS:
            raise _Overflow("steps")
        attack_at = torch.maximum(next_attack, busy)
        cast_ready = torch.maximum(ready, busy.view(B, 1).expand(B, 5))
        cast_at, choice = cast_ready.min(dim=1)
        pet_cand = torch.where(pet_alive & (pet_next < pet_end), pet_next, full(fight * 10).view(B, 1).expand(B, MAX_PETS))
        pet_at = pet_cand.min(dim=1).values
        pending_at = peek_pend()
        moment = torch.min(torch.min(attack_at, cast_at), torch.min(pet_at, torch.min(pending_at, next_tick)))
        alive = alive & (moment < fight)
        if not bool(alive.any()):
            break

        is_pend = alive & (moment == pending_at)
        is_tick = alive & ~is_pend & (moment == next_tick)
        is_pet = alive & ~is_pend & ~is_tick & (moment == pet_at)
        is_cast = alive & ~is_pend & ~is_tick & ~is_pet & (cast_at <= attack_at) & (moment == cast_at)
        is_auto = alive & ~is_pend & ~is_tick & ~is_pet & ~is_cast

        if bool(is_pend.any()):
            _n, pk, pindex = pop_pend(is_pend)
            for index in range(Tt):
                do_trap(is_pend & (pk == P_TRAP) & (pindex == index), index, moment)
            do_multi(is_pend & (pk == P_MULTI2), moment, True)

        if bool(is_tick.any()):
            raw = 5.0 * RANK + 0.10 * dcs(moment)
            for index in range(Tt):
                active = is_tick & (stung[:, index] > moment)
                do_pet_hit(active & is_bm, N_STING_TICK, raw, moment, cur_pet, index, False)
                do_hit(active & ~is_bm, N_STING_TICK, raw, moment, index=index)
                cut_cds(active & is_sv, moment, seconds=chance((5.0 + 0.20 * mastery) / 100.0))
            interval = torch.where(poison, ones / (1.0 + 0.05 * potency0), ones)
            next_tick = torch.where(is_tick, moment + interval, next_tick)

        if bool(is_pet.any()):
            for slot in range(MAX_PETS):
                active = is_pet & pet_alive[:, slot] & (pet_next[:, slot] == moment) & (pet_next[:, slot] < pet_end[:, slot])
                pet_attack(active, slot, moment)
            pet_alive = pet_alive & (pet_next < pet_end)

        if bool(is_cast.any()):
            # pay mana
            key = choice
            cost = costs_t[key]
            # cost gather
            cost_v = costs_t[choice]
            back_v = backs[rix, choice]
            recover(is_cast, moment)
            can = is_cast & (mana >= cost_v)
            fail = is_cast & ~can
            # failed pay -> delay 0.25
            for k in range(5):
                ready[:, k] = torch.where(fail & (choice == k), moment + 0.25, ready[:, k])
            if bool(can.any()):
                mana = torch.where(can, mana - cost_v, mana)
                gain(can, back_v)
                hit_at = moment + cast_point
                # cast() busy + sulfuras + quiver
                sulf_armed = sulf_armed | (can & sulfuras_on & ~sulf_armed)  # arm if not already - CPU: if not armed
                # actually Sulfuras.cast: if not armed: armed=True. So arm when not armed.
                # sulf_armed already handles: only set True when False. Using OR with (can & sulf & ~armed) is correct.
                quiver = torch.where(can & windrunner, ones, quiver)
                busy = torch.where(can, moment + cast_time + stun, busy)

                # CALL
                m = can & (choice == A_CALL)
                if bool(m.any()):
                    clear_kind(m, cur_pet)
                    spawn(m, cur_pet, hit_at, full(fight * 10), hit_at)
                    if bool((m & unleash).any()):
                        for kid in (K_SPIKE, K_HUFFER, K_GRYLLS):
                            extra = m & unleash & (cur_pet != kid)
                            end = hit_at + 6.0 + 0.10 * V("intel")
                            spawn(extra, kid, hit_at, end, hit_at)
                    ready[:, A_CALL] = torch.where(m, moment + cd(mod.CALL_CD), ready[:, A_CALL])

                # WRATH
                m = can & (choice == A_WRATH)
                if bool(m.any()):
                    wrath_until = torch.where(m, hit_at + mod.WRATH_DUR, wrath_until)
                    howl_add(m)
                    flat = torch.where(wild, full(3.0), zeros)
                    ready[:, A_WRATH] = torch.where(m, moment + cd(mod.WRATH_CD, flat), ready[:, A_WRATH])

                # STING
                m = can & (choice == A_STING)
                if bool(m.any()):
                    raw = 85.0 * RANK + 0.85 * dcs(hit_at) + 0.40 * agi
                    do_hit(m, N_STING, raw, hit_at)
                    stung[:, 0] = torch.where(m, torch.maximum(stung[:, 0], hit_at + mod.STING_DUR), stung[:, 0])
                    push_pend(m & trap_gloves, hit_at + mod.TRAP_DELAY, P_TRAP, 0)
                    howl_add(m)
                    flat = torch.where(killer & wrath_on(moment), full(1.5), zeros)
                    ready[:, A_STING] = torch.where(m, moment + cd(mod.STING_CD, flat), ready[:, A_STING])

                # MULTI
                m = can & (choice == A_MULTI)
                if bool(m.any()):
                    do_multi(m, hit_at, False)
                    push_pend(m & is_sv, hit_at + mod.MULTI_SECONDARY_DELAY, P_MULTI2, 0)
                    howl_add(m)
                    flat = torch.where(killer & wrath_on(moment), full(1.5), zeros)
                    ready[:, A_MULTI] = torch.where(m, moment + cd(mod.MULTI_CD, flat), ready[:, A_MULTI])

                # TRAP
                m = can & (choice == A_TRAP)
                if bool(m.any()):
                    push_pend(m, hit_at + mod.TRAP_DELAY, P_TRAP, 0)
                    howl_add(m)
                    ready[:, A_TRAP] = torch.where(m, moment + cd(mod.TRAP_CD), ready[:, A_TRAP])

                next_attack = torch.where(can, torch.maximum(next_attack, busy), next_attack)

        if bool(is_auto.any()):
            nonlocal_auto = is_auto
            now = torch.where(is_auto, attack_at, moment)
            recover(is_auto, now)
            power = dcs(now)
            raw = power.clone()
            white = WHITE + 0.75 * agi
            raw = torch.where(wrath_on(now), white * (1.0 + wrath_pct()) + damage, raw)
            # Emit auto with count=auto_pct to scale weight; dmp notes 1 hit (CPU note_damage_mana(1) then scales weight).
            # do_hit notes dmp with count — pass ones for dmp fidelity via temporary.
            share = do_hit(is_auto, N_AUTO, raw, now, attack=1.0, pot_scale=attack_potency, count=auto_pct)
            # CPU: note_damage_mana(1) then scale weight by auto_pct. We noted dmp*auto_pct — correct if auto_pct==1.
            # When auto_pct!=1, dmp is slightly off vs CPU; rare. Overflow those builds.
            if bool((is_auto & (auto_pct != 1.0)).any()):
                raise _Overflow("auto_pct")
            if bool(is_mm.any()):
                do_hit(is_auto & is_mm, N_MARK, 40.0 + 3.0 * mastery, now, typed=False, pot_scale=0.0, count=share)
            fire, d_lock = dither(d_lock, is_auto & lock_t, share * 0.35 * luck_mult)
            lock_until = torch.where(fire, now + mod.LOCK_DUR, lock_until)
            fire, d_prowess = dither(d_prowess, is_auto, share)
            p_prowess = torch.where(fire, now + mod.PROWESS_DUR, p_prowess)
            # split
            do_hit(is_auto & split_flag, N_SPLIT, (0.45 + 0.05 * RANK) * power, now, attack=1.0)
            split_flag = torch.where(is_auto & split_flag, torch.zeros_like(split_flag), split_flag)
            fire, d_split = dither(d_split, is_auto, 0.30 * (1.0 + 0.5 * share) * luck_mult)
            split_flag = split_flag | fire
            gain(is_auto, amg)
            if bool(fire_orb.any()):
                # splash to targets using taken_for(min(1,T-1))
                idx = min(1, T - 1)
                splash = (20.0 + 0.35 * agi) * float(T) * taken(idx, now)
                _push(torch, bufs, is_auto & fire_orb, now, splash, N_FIRE, KIND_EXEC)
                note_dmp(is_auto & fire_orb, float(T))
            if bool(sulfuras_on.any()):
                m = is_auto & sulfuras_on
                splash_fire = m & sulf_armed
                taken0 = taken(0, now)
                _push(torch, bufs, splash_fire, now, agi * taken0 * float(T), N_SULF, KIND_MAG)
                note_dmp(splash_fire, float(T))
                sulf_armed = torch.where(splash_fire, torch.zeros_like(sulf_armed), sulf_armed)
                _push(torch, bufs, m, now, power * taken0 * sulf_echo, N_SULF_ECHO, KIND_EXEC)
            next_attack = torch.where(is_auto, now + h_interval(now), next_attack)

    return _finalize(bufs, stats_list)
