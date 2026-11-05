# -*- coding: utf-8 -*-
"""Batched next-event timeline for Death Knight (frost / blood / unholy).

Faithful port of sunken_sim.death_knight.simulate onto batched torch.
Ledger events: KIND_EXEC (when, name, dealt/execute) and KIND_FLAT (when=0).
f64 clocks on CPU; DirectML kind-score via kindscore.pack.
Sulfuras → CPU overflow for the batch.
Summons (Bloodworms / Army) use append-only slots like warlock demons.
"""
from __future__ import annotations

MAX_STEPS = 400000
MAX_SUMMONS = 64
MAX_T = 8
MAX_EVENTS = 8192

(
    N_AUTO,
    N_DG,
    N_BS,
    N_UF,
    N_FS,
    N_OUTBREAK,
    N_PB,
    N_US,
    N_SINDR,
    N_ARMY,
    N_WORMS,
    N_FIRE,
    N_SULF,
    N_SULF_ECHO,
) = range(14)
NAMES = {
    N_AUTO: "Автоатака",
    N_DG: "Death Grip",
    N_BS: "Blood Strike",
    N_UF: "Unholy Fury",
    N_FS: "Frost Strike",
    N_OUTBREAK: "Outbreak",
    N_PB: "Plaguebearer",
    N_US: "Unholy Strikes",
    N_SINDR: "Breath of Sindragosa",
    N_ARMY: "Army of the Dead",
    N_WORMS: "Bloodworms",
    N_FIRE: "Всплеск огня",
    N_SULF: "Sulfuras",
    N_SULF_ECHO: "Sulfuras (удар)",
}
KIND_EXEC = 2.0
KIND_FLAT = 3.0

K_UF, K_FS, K_BS, K_DG, K_ERW = 0, 1, 2, 3, 4
ORDER = (K_UF, K_FS, K_BS, K_DG)
SUM_WORM, SUM_GHOUL = 0, 1

SPELL_NAME = {K_UF: N_UF, K_FS: N_FS, K_BS: N_BS, K_DG: N_DG}


class _Overflow(Exception):
    pass


def generate_death_knight_timelines(torch, device, builds, spec: str, targets: int):
    if spec not in ("frost", "blood", "unholy"):
        raise ValueError(f"death_knight GPU timeline specs frost/blood/unholy, got {spec}")
    if not builds:
        return []
    dev_type = getattr(device, "type", str(device))
    if dev_type in ("privateuseone", "dml") or "privateuseone" in str(device):
        device = torch.device("cpu")
    try:
        return _dk_batch(torch, device, torch.float64, builds, spec, int(targets))
    except _Overflow:
        return _cpu_fallback(builds, spec, targets)


def _cpu_fallback(builds, spec, targets):
    from sunken_sim import death_knight as mod

    out = []
    for b in builds:
        report = mod.simulate(b, targets, spec)
        out.append((list(report.events), report.stats))
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
    w = weight if isinstance(weight, torch.Tensor) else torch.full(
        (B,), float(weight), dtype=bufs["weight"].dtype, device=bufs["weight"].device
    )
    when_t = when if isinstance(when, torch.Tensor) else torch.full(
        (B,), float(when), dtype=bufs["when"].dtype, device=bufs["when"].device
    )
    active = mask & (bufs["length"] < MAX_EVENTS) & (w != 0)
    if not bool(active.any()):
        return
    rows = torch.arange(B, device=bufs["when"].device)
    idx = bufs["length"].clone()
    bufs["when"][rows[active], idx[active]] = when_t[active]
    bufs["weight"][rows[active], idx[active]] = w[active]
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
        events = [
            (float(whens[i, j]), NAMES[int(names[i, j])], float(weights[i, j]), float(kinds[i, j]))
            for j in range(n)
        ]
        out.append((events, stats))
    return out


def _dk_batch(torch, device, dtype, builds, spec, T):
    from sunken_sim import death_knight as mod
    from sunken_sim.shadow import (
        CAST_BACKSWING,
        CAST_POINT,
        DUMMY_ARMOR,
        FIGHT,
        LEVEL,
        _crit_factor,
        _execute_factor,
        _wears,
        armor_taken,
        attack_mana_gain,
        sulfuras_echo_chance,
        target_hp,
    )

    B = len(builds)
    Tt = min(int(T), MAX_T)
    fight = float(FIGHT)
    cast_point = float(CAST_POINT)
    cast_swing = float(CAST_POINT) + float(CAST_BACKSWING)
    BIG = 1e18
    zeros = torch.zeros(B, dtype=dtype, device=device)
    ones = torch.ones(B, dtype=dtype, device=device)
    rix = torch.arange(B, device=device)
    frost = spec == "frost"
    blood = spec == "blood"
    unholy = spec == "unholy"

    stats_list = []
    meta = []
    for build in builds:
        stats = mod.stats_of(build)
        stats_list.append(stats)
        has = lambda c, b=build: mod._has(b, c)
        if _wears(build, "I0BR"):
            raise _Overflow("sulfuras")
        frost_presence = frost or has(mod.TALENT_DEATH_PRESENCE)
        unholy_presence = unholy or has(mod.TALENT_DEATH_PRESENCE)
        meta.append(
            {
                "str": float(stats["str"]),
                "hp": float(stats["hp"]),
                "potency": float(stats["potency"]),
                "mastery": float(stats["mastery"]),
                "crit": float(stats["crit"]),
                "rating": float(stats["rating"]),
                "haste": float(stats["haste"]),
                "attack_speed": float(stats["attack_speed"]),
                "attack_potency": float(stats["attack_potency"]),
                "armor_pen": float(stats["armor_pen"]),
                "armor": float(stats["armor"]),
                "phys_add": float(stats["phys_add"]),
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
                "spellbinder": float(stats["spellbinder"]),
                "belt": float(stats["belt"]),
                "siphon": float(stats["siphon"]),
                "coldbringer": float(stats["coldbringer"]),
                "maw": float(stats["maw"]),
                "spell_crit": float(stats["spell_crit"]),
                "spell_mult": float(stats["spell_mult"]),
                "amg": float(attack_mana_gain(stats)),
                "bt": float(mod.BLOOD_TAP if has(mod.TALENT_BLOOD_TAP) else 1.0),
                "bone_shield": float(mod.BONE_SHIELD_ARMOR if has(mod.TALENT_MARROWREND) else 0.0),
                "frost_presence": 1.0 if frost_presence else 0.0,
                "unholy_presence": 1.0 if unholy_presence else 0.0,
                "has_erw": 1.0 if not unholy else 0.0,
                "plaguebearer": 1.0 if unholy else 0.0,
                "army": 1.0 if has(mod.TALENT_ARMY) else 0.0,
                "virulent": 1.0 if has(mod.TALENT_VIRULENT) else 0.0,
                "sindragosa": 1.0 if has(mod.TALENT_SINDRAGOSA) else 0.0,
                "marrowrend": 1.0 if has(mod.TALENT_MARROWREND) else 0.0,
                "obliterate": 1.0 if has(mod.TALENT_OBLITERATE) else 0.0,
                "lich_king": 1.0 if has(mod.TALENT_LICH_KING) else 0.0,
                "unholy_strikes": 1.0 if has(mod.TALENT_UNHOLY_STRIKES) else 0.0,
                "bloodworms": 1.0 if has(mod.TALENT_BLOODWORMS) else 0.0,
                "decomposition": 1.0 if has(mod.TALENT_DECOMPOSITION) else 0.0,
                "pestilence": 1.0 if has(mod.TALENT_PESTILENCE) else 0.0,
                "razorice": 1.0 if has(mod.TALENT_RAZORICE) else 0.0,
                "grim_reaper": 1.0 if has(mod.TALENT_GRIM_REAPER) else 0.0,
                "bloodforged": 1.0 if has(mod.TALENT_BLOODFORGED) else 0.0,
            }
        )

    def F(name):
        return torch.tensor([m[name] for m in meta], dtype=dtype, device=device)

    def Bool(name):
        return F(name) > 0.5

    strength = F("str")
    hp0 = F("hp")
    pot0 = F("potency")
    mastery = F("mastery")
    crit0 = F("crit")
    rating = F("rating")
    haste = F("haste")
    attack_speed = F("attack_speed")
    attack_potency = F("attack_potency")
    armor_pen = F("armor_pen")
    armor0 = F("armor")
    phys_add = F("phys_add")
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
    spellbinder = Bool("spellbinder")
    belt = Bool("belt")
    siphon = Bool("siphon")
    coldbringer = Bool("coldbringer")
    maw = Bool("maw")
    spell_crit_on = Bool("spell_crit")
    spell_mult = F("spell_mult")
    amg = F("amg")
    bt = F("bt")
    bone_shield = F("bone_shield")
    frost_presence = Bool("frost_presence")
    unholy_presence = Bool("unholy_presence")
    has_erw = Bool("has_erw")
    plaguebearer = Bool("plaguebearer")
    army_t = Bool("army")
    virulent_on = Bool("virulent")
    sindragosa = Bool("sindragosa")
    marrowrend = Bool("marrowrend")
    obliterate = Bool("obliterate")
    lich_king = Bool("lich_king")
    unholy_strikes_t = Bool("unholy_strikes")
    bloodworms_t = Bool("bloodworms")
    decomposition = Bool("decomposition")
    pestilence = Bool("pestilence")
    razorice = Bool("razorice")
    grim_reaper = Bool("grim_reaper")
    bloodforged = Bool("bloodforged")

    attack_crit = torch.tensor(
        [_crit_factor(float(crit0[i]), 2.0 + float(rating[i])) for i in range(B)],
        dtype=dtype,
        device=device,
    )
    spell_crit = torch.tensor(
        [
            (
                _crit_factor(float(crit0[i]), float(spell_mult[i]) + float(rating[i]))
                if float(meta[i]["spell_crit"]) > 0.5
                else 1.0
            )
            for i in range(B)
        ],
        dtype=dtype,
        device=device,
    )

    drain = torch.full((B,), 1.5 + 2.0 * float(LEVEL), dtype=dtype, device=device)
    virulent = torch.where(virulent_on, (0.12 + 0.005 * pot0) * luck_mult, zeros)
    tick_rate = ones + ((0.10 + 0.005 * mastery) if unholy else 0.0) + torch.where(belt, ones * 0.25, zeros)
    first_tick = ones * (1.0 - (0.10 + 0.005 * mastery))

    fs_flat = torch.where(lich_king, ones, zeros) + torch.where(coldbringer, ones * 2.0, zeros)

    bufs = _make_bufs(torch, device, B, dtype)

    def full(v):
        return v if isinstance(v, torch.Tensor) else torch.full((B,), float(v), dtype=dtype, device=device)

    def execute_t(now):
        now = full(now)
        outs = []
        for i in range(B):
            outs.append(_execute_factor(stats_list[i], float(now[i].item())))
        return torch.tensor(outs, dtype=dtype, device=device)

    def target_hp_t(now):
        now = full(now)
        return torch.clamp(ones - now / fight, min=0.0)

    def add_exec(mask, name_id, dealt, when, scale=None):
        when = full(when)
        dealt = full(dealt)
        if scale is not None:
            dealt = dealt * full(scale)
        ex = execute_t(when)
        weight = torch.where(ex != 0, dealt / ex, zeros)
        _push(torch, bufs, mask & (dealt != 0), when, weight, name_id, KIND_EXEC)

    def note_damage_mana(mask, count):
        nonlocal mana
        count = full(count)
        mana = torch.where(
            mask & (dmp > 0), torch.minimum(mana_max, mana + dmp * mana_max * count), mana
        )

    def recover(mask, now):
        nonlocal mana, mana_time
        now = full(now)
        dt = now - mana_time
        do = mask & (dt > 0)
        net = mana_regen - drain
        value = mana + net * dt
        floor = drain / 4.0
        low = do & (net < 0) & (value < floor)
        value = torch.where(low, torch.minimum(mana, floor), value)
        value = torch.clamp(value, min=0.0)
        value = torch.minimum(value, mana_max)
        mana = torch.where(do, value, mana)
        mana_time = torch.where(mask, now, mana_time)

    def dcs():
        return full(mod.WHITE_BASE) + 0.75 * strength + damage

    def max_life():
        return hp0 + hp_bonus

    def potency_now(mask, now):
        """Mutates mana via recover when unholy_presence."""
        value = pot0.clone()
        need = mask & unholy_presence & (mana_max > 0)
        if bool(need.any()):
            recover(need, now)
            value = value + torch.where(
                need, (mana / mana_max) * (3.0 + 0.4 * float(LEVEL)), zeros
            )
        return value

    def typed(mask, magical, now):
        now = full(now)
        mag = bool(magical)
        bonus = ones + (magic_add if mag else phys_add)
        bonus = bonus + torch.where(sulfuron, full(0.13) + 0.25 * target_hp_t(now), zeros)
        if mag:
            bonus = bonus + torch.where(spellbinder, full(0.05) + 0.005 * mastery, zeros)
            need = mask & frost_presence
            if bool(need.any()):
                recover(need, now)
                bonus = bonus + torch.where(need, 0.01 * (mana / 40.0), zeros)
            bonus = bonus + torch.where(
                bloodforged, full(0.05) + 0.01 * (armor0 + bone_shield), zeros
            )
        return torch.where(glass, bonus * 1.15, bonus)

    def increase(t, now):
        now = full(now)
        bonus = ones.clone()
        is_frozen = (t == 0) & (frozen >= now)
        bonus = bonus + torch.where(is_frozen, full(0.15), zeros)
        bonus = bonus + torch.where(~is_frozen & (chill[:, t] >= now), full(0.08), zeros)
        if bool(grim_reaper.any()):
            count = (
                (plague[:, t] >= now).to(dtype)
                + (outbreak[:, t] >= now).to(dtype)
                + is_frozen.to(dtype)
                + (chill[:, t] >= now).to(dtype)
            )
            if t == 0:
                count = count + (marrow >= now).to(dtype)
            bonus = bonus + torch.where(grim_reaper, full(0.06) * count, zeros)
        return bonus

    def taken(t, now):
        now = full(now)
        armor = full(float(DUMMY_ARMOR)) - armor_pen
        if t == 0:
            armor = torch.where(marrow >= now, armor - mod.MARROW_ARMOR, armor)
        # use python armor_taken for fidelity
        outs = []
        for i in range(B):
            outs.append(armor_taken(float(armor[i].item())))
        return torch.tensor(outs, dtype=dtype, device=device)

    def plague_flat(t, now):
        now = full(now)
        active = plague[:, t] >= now
        value = full(2.0 + mod.RANK) + torch.where(
            decomposition, full(3.0) + 0.08 * dcs(), zeros
        )
        return torch.where(active, value, zeros)

    def cooldown(base, flat=None):
        # Python-exact per row so ready/busy inequalities match CPU float
        outs = []
        for i in range(B):
            f = 0.0 if flat is None else float(flat[i].item() if isinstance(flat, torch.Tensor) else flat)
            outs.append(max(0.5, (float(base) * float(cd_temp[i]) - float(flat_cdr[i]) - f) / (1.0 + float(haste[i]))))
        return torch.tensor(outs, dtype=dtype, device=device)

    # state
    mana = mana_max.clone()
    mana_time = zeros.clone()
    hp_bonus = zeros.clone()
    outbreak = torch.full((B, Tt), -1.0, dtype=dtype, device=device)
    plague = torch.full((B, Tt), -1.0, dtype=dtype, device=device)
    chill = torch.full((B, Tt), -1.0, dtype=dtype, device=device)
    frozen = full(-1.0)
    marrow = full(-1.0)
    pb_acc = torch.zeros((B, Tt), dtype=dtype, device=device)
    decomp_acc = torch.zeros((B, Tt), dtype=dtype, device=device)
    worm_acc = zeros.clone()
    ghoul_acc = zeros.clone()
    razor_acc = zeros.clone()
    army_count = torch.zeros(B, dtype=torch.int64, device=device)
    last_cast = torch.full((B,), -1, dtype=torch.int64, device=device)
    rested = torch.zeros(B, dtype=torch.bool, device=device)

    ready_uf = zeros.clone()
    ready_fs = zeros.clone()
    ready_bs = zeros.clone()
    ready_dg = zeros.clone()
    ready_erw = torch.where(has_erw, zeros, full(fight + 1.0))

    next_attack = zeros.clone()
    busy = zeros.clone()
    next_tick = first_tick.clone()

    # Python float mirrors for cast scheduling (preserve CPU ready/busy inequalities)
    def _py_cd(i, base, flat=0.0):
        return max(0.5, (float(base) * float(cd_temp[i]) - float(flat_cdr[i]) - float(flat)) / (1.0 + float(haste[i])))

    py_busy = [0.0] * B
    py_natk = [0.0] * B
    py_ruf = [0.0] * B
    py_rfs = [0.0] * B
    py_rbs = [0.0] * B
    py_rdg = [0.0] * B
    py_rerw = [0.0 if bool(has_erw[i]) else fight + 1.0 for i in range(B)]
    py_last = [-1] * B
    py_rested = [False] * B
    py_ntick = [float(first_tick[i]) for i in range(B)]
    cast_len = float(CAST_POINT) + float(CAST_BACKSWING)

    dem_alive = torch.zeros((B, MAX_SUMMONS), dtype=torch.bool, device=device)
    dem_kind = torch.zeros((B, MAX_SUMMONS), dtype=torch.int64, device=device)
    dem_next = torch.full((B, MAX_SUMMONS), BIG, dtype=dtype, device=device)
    dem_end = torch.full((B, MAX_SUMMONS), -BIG, dtype=dtype, device=device)
    dem_raw = torch.zeros((B, MAX_SUMMONS), dtype=dtype, device=device)
    dem_count = torch.zeros(B, dtype=torch.int64, device=device)

    alive = torch.ones(B, dtype=torch.bool, device=device)

    def dither(acc, mask, ch):
        ch = torch.clamp(full(ch), 0.0, 1.0)
        m = mask & (ch > 0)
        na = acc + torch.where(m, ch, zeros)
        fire = m & (na >= 1.0 - 1e-9)
        out = torch.where(fire, na - 1.0, na)
        return fire, torch.where(m, out, acc)

    def apply_outbreak(mask, t, now):
        nonlocal outbreak
        now = full(now)
        do = mask & plaguebearer & (outbreak[:, t] >= now)
        if bool(do.any()):
            raw = full(20.0) + 0.015 * max_life() * bt
            amount = raw * increase(t, now) * taken(t, now) * execute_t(now)
            add_exec(do, N_PB, amount, now)
        outbreak[:, t] = torch.where(mask, now + mod.OUTBREAK_TIME, outbreak[:, t])

    def after_hit(mask, t, now):
        nonlocal pb_acc, outbreak
        now = full(now)
        if not bool((mask & plaguebearer).any()):
            return
        chance = full(0.05) * torch.where(pestilence, full(1.25), ones) * luck_mult
        chance = torch.where(outbreak[:, t] < now, chance * 0.5, chance)
        fire, pb_acc[:, t] = dither(pb_acc[:, t], mask & plaguebearer, chance)
        if bool(fire.any()):
            apply_outbreak(fire, t, now)

    def deal(mask, name_id, raw, t, now, magical=True, pot_scale=1.0, scale=None):
        now = full(now)
        raw = full(raw)
        pot_scale = full(pot_scale)
        pot = potency_now(mask, now)
        amount = raw + pot * pot_scale + plague_flat(t, now)
        amount = amount * typed(mask, magical, now) * increase(t, now)
        amount = amount * (spell_crit if magical else attack_crit)
        amount = amount * taken(t, now) * execute_t(now)
        add_exec(mask, name_id, amount, now, scale=scale)
        note_damage_mana(mask, 1.0)
        after_hit(mask, t, now)
        return amount

    def summon_hit(mask, name_id, raw, t, now):
        now = full(now)
        raw = full(raw)
        amount = (raw + plague_flat(t, now)) * increase(t, now) * taken(t, now) * execute_t(now)
        add_exec(mask, name_id, amount, now)
        after_hit(mask, t, now)
        return amount

    def do_unholy_strikes(mask, now):
        m = mask & unholy_strikes_t
        if not bool(m.any()):
            return
        for _ in range(2):
            deal(m, N_US, full(15.0) + 0.40 * strength, 0, now)

    def spawn_summon(mask, kind, end, nxt, raw):
        nonlocal dem_alive, dem_kind, dem_next, dem_end, dem_raw, dem_count
        if not bool(mask.any()):
            return
        if bool((mask & (dem_count >= MAX_SUMMONS)).any()):
            raise _Overflow("summons")
        slot = dem_count
        r = rix[mask]
        s = slot[mask]
        dem_alive[r, s] = True
        dem_kind[r, s] = int(kind)
        dem_end[r, s] = end[mask] if isinstance(end, torch.Tensor) else full(end)[mask]
        dem_next[r, s] = nxt[mask] if isinstance(nxt, torch.Tensor) else full(nxt)[mask]
        dem_raw[r, s] = raw[mask] if isinstance(raw, torch.Tensor) else full(raw)[mask]
        dem_count = dem_count + mask.to(torch.int64)

    def cast_spell(mask, key, now):
        nonlocal frozen, marrow, hp_bonus, last_cast, rested, army_count, mana
        nonlocal ready_uf, ready_fs, ready_bs, ready_dg, worm_acc, ghoul_acc, razor_acc
        now = full(now)
        hit = now + cast_point
        life = max_life()
        if key == K_DG:
            raw = full(20.0) + 10.0 * float(LEVEL) + 0.10 * life * bt
            raw = raw + torch.where(obliterate, 0.75 * dcs(), zeros)
            deal(mask, N_DG, raw, 0, hit)
            recover(mask, hit)
            mana = torch.where(mask, torch.minimum(mana_max, mana + 0.05 * mana_max), mana)
            do_unholy_strikes(mask, hit)
        elif key == K_BS:
            raw = full(70.0 * mod.RANK - 10.0) + 0.10 * life * bt
            raw = raw + torch.where(obliterate, 0.75 * dcs(), zeros)
            healing = full(70.0 * mod.RANK - 10.0 - 40.0) + 0.10 * life * bt
            healing = torch.where(siphon, healing * 2.0, healing)
            raw = raw + torch.where(maw, 0.35 * healing, zeros)
            deal(mask, N_BS, raw, 0, hit)
            plague[:, 0] = torch.where(mask & ~maw, hit + mod.BLOOD_PLAGUE_TIME, plague[:, 0])
            marrow = torch.where(mask & marrowrend, hit + mod.MARROW_TIME, marrow)
            hp_bonus = torch.where(mask & ~rested, hp_bonus + 1.0, hp_bonus)
        elif key == K_UF:
            raw = full(50.0) + 0.05 * life * bt
            raw = raw + torch.where(obliterate, 0.50 * dcs(), zeros)
            for t in range(Tt):
                # only first `T` targets matter; Tt may be >T but we use T from caller via Tt=min(T,MAX_T)
                if t >= T:
                    break
                deal(mask, N_UF, raw, t, hit)
                apply_outbreak(mask, t, hit)
        elif key == K_FS:
            raw = full(70.0) + 0.05 * life * bt + 0.15 * mana_max
            raw = torch.where(lich_king, raw * 1.20, raw)
            raw = raw + torch.where(obliterate, 1.00 * dcs(), zeros)
            if frost:
                raw = raw * (1.05 + 0.005 * mastery) + 0.10 * mana_max
            deal(mask, N_FS, raw, 0, hit)
            frozen = torch.where(mask, hit + mod.FREEZE_TIME, frozen)
            do_unholy_strikes(mask, hit)
            if bool((mask & sindragosa).any()):
                wyrm = full(20.0) + 0.05 * mana_max + 0.05 * life * bt
                m2 = mask & sindragosa
                for t in range(Tt):
                    if t >= T:
                        break
                    if t == 0:
                        deal(m2 & (frozen >= hit), N_SINDR, wyrm * 1.5, t, hit)
                        deal(m2 & ~(frozen >= hit), N_SINDR, wyrm, t, hit)
                        chill[:, t] = torch.where(
                            m2 & ~(frozen >= hit),
                            torch.maximum(chill[:, t], hit + mod.CHILL_TIME),
                            chill[:, t],
                        )
                    else:
                        deal(m2, N_SINDR, wyrm, t, hit)
                        chill[:, t] = torch.where(
                            m2, torch.maximum(chill[:, t], hit + mod.CHILL_TIME), chill[:, t]
                        )
        elif key == K_ERW:
            # reset last_cast CD to now
            for k, ready in (
                (K_UF, "ready_uf"),
                (K_FS, "ready_fs"),
                (K_BS, "ready_bs"),
                (K_DG, "ready_dg"),
            ):
                pass
            is_uf = mask & (last_cast == K_UF)
            is_fs = mask & (last_cast == K_FS)
            is_bs = mask & (last_cast == K_BS)
            is_dg = mask & (last_cast == K_DG)
            ready_uf = torch.where(is_uf, now, ready_uf)
            ready_fs = torch.where(is_fs, now, ready_fs)
            ready_bs = torch.where(is_bs, now, ready_bs)
            ready_dg = torch.where(is_dg, now, ready_dg)
            rested = torch.where(mask, last_cast == K_BS, rested)

        if key != K_ERW:
            rested = torch.where(mask, False, rested)
            last_cast = torch.where(mask, key, last_cast)

        # summons on spellcast
        if bool((mask & bloodworms_t).any()):
            m = mask & bloodworms_t
            raw_w = full(5.0) + (0.12 * dcs() + 0.005 * life * bt).to(torch.int64).to(dtype)
            spawn_summon(m, SUM_WORM, hit + mod.WORM_TIME, hit, raw_w)
        if key != K_ERW and bool((mask & army_t).any()):
            m = mask & army_t
            army_count = army_count + m.to(torch.int64)
            spawn = m & (army_count >= 3)
            army_count = torch.where(spawn, torch.zeros_like(army_count), army_count)
            if bool(spawn.any()):
                raw_g = full(10.0) + (0.35 * dcs()).to(torch.int64).to(dtype)
                spawn_summon(spawn, SUM_GHOUL, hit + mod.GHOUL_TIME, hit, raw_g)

    # main loop
    steps = 0
    while bool(alive.any()):
        steps += 1
        if steps > MAX_STEPS:
            raise _Overflow("steps")

        # prune expired for summon_at calc (CPU filters each loop)
        dem_alive = dem_alive & (dem_next < dem_end)

        # Sync torch clocks from python scheduling state
        busy = torch.tensor(py_busy, dtype=dtype, device=device)
        ready_uf = torch.tensor(py_ruf, dtype=dtype, device=device)
        ready_fs = torch.tensor(py_rfs, dtype=dtype, device=device)
        ready_bs = torch.tensor(py_rbs, dtype=dtype, device=device)
        ready_dg = torch.tensor(py_rdg, dtype=dtype, device=device)
        ready_erw = torch.tensor(py_rerw, dtype=dtype, device=device)
        next_attack = torch.tensor(py_natk, dtype=dtype, device=device)
        next_tick = torch.tensor(py_ntick, dtype=dtype, device=device)
        last_cast = torch.tensor(py_last, dtype=torch.int64, device=device)
        rested = torch.tensor(py_rested, dtype=torch.bool, device=device)

        spell_at_l = []
        erw_at_l = []
        py_moment = [fight + 1.0] * B
        for i in range(B):
            if not bool(alive[i]):
                spell_at_l.append(fight + 1)
                erw_at_l.append(fight + 1)
                continue
            bsv = py_busy[i]
            rmin = min(py_ruf[i], py_rfs[i], py_rbs[i], py_rdg[i])
            sat = max(bsv, rmin)
            spell_at_l.append(sat)
            erw_at_i = fight + 1
            if bool(has_erw[i]) and py_last[i] >= 0 and py_rerw[i] < fight:
                last_r = (py_ruf, py_rfs, py_rbs, py_rdg)[py_last[i]][i]
                erw_cand = max(bsv, py_rerw[i])
                if last_r - erw_cand > 2.0:
                    erw_at_i = erw_cand
            erw_at_l.append(erw_at_i)
            # python min of clocks (summon/tick via tensors below; fill after)
            py_moment[i] = min(py_natk[i], sat, erw_at_i, py_ntick[i])
        spell_at = torch.tensor(spell_at_l, dtype=dtype, device=device)
        erw_at = torch.tensor(erw_at_l, dtype=dtype, device=device)

        dem_cand = torch.where(dem_alive, dem_next, full(fight * 10).view(B, 1).expand(B, MAX_SUMMONS))
        summon_at = dem_cand.min(dim=1).values
        summon_at = torch.where(summon_at < fight * 5, summon_at, full(fight))

        for i in range(B):
            if bool(alive[i]):
                py_moment[i] = min(py_moment[i], float(summon_at[i].item()))
        moment = torch.tensor(py_moment, dtype=dtype, device=device)
        done = alive & (moment >= fight)
        alive = alive & ~done
        if not bool(alive.any()):
            break

        acted = torch.zeros(B, dtype=torch.bool, device=device)

        # 1) tick
        is_tick = alive & ~acted & (moment == next_tick)
        if bool(is_tick.any()):
            for t in range(Tt):
                if t >= T:
                    break
                m = is_tick & (outbreak[:, t] >= moment)
                if bool(m.any()):
                    raw = full(5.0 * mod.RANK) + 0.008 * max_life() * bt
                    scale = ones + virulent
                    deal(m, N_OUTBREAK, raw, t, moment, scale=scale)
                    fire, decomp_acc[:, t] = dither(
                        decomp_acc[:, t], m & decomposition, 0.20 * luck_mult
                    )
                    plague[:, t] = torch.where(
                        fire, moment + mod.BLOOD_PLAGUE_TIME, plague[:, t]
                    )
            for i in range(B):
                if bool(is_tick[i]):
                    py_ntick[i] = py_moment[i] + 1.25 / float(tick_rate[i])
            next_tick = torch.tensor(py_ntick, dtype=dtype, device=device)
            acted = acted | is_tick

        # 2) summons
        is_sum = alive & ~acted & (moment == summon_at) & (summon_at < fight)
        if bool(is_sum.any()):
            for slot in range(MAX_SUMMONS):
                live = is_sum & dem_alive[:, slot] & (dem_next[:, slot] == moment)
                if not bool(live.any()):
                    continue
                is_g = live & (dem_kind[:, slot] == SUM_GHOUL)
                is_w = live & (dem_kind[:, slot] == SUM_WORM)
                if bool(is_g.any()):
                    summon_hit(is_g, N_ARMY, dem_raw[:, slot], 0, moment)
                    # ghoul dither 10% if not blood
                    if not blood:
                        fire, ghoul_acc = dither(ghoul_acc, is_g, 0.10 * luck_mult)
                        # if outbreak down → apply; elif chill down → chill; else apply
                        need_out = fire & (outbreak[:, 0] < moment)
                        need_chill = fire & ~need_out & (chill[:, 0] < moment)
                        need_out2 = fire & ~need_out & ~need_chill
                        if bool(need_out.any()):
                            apply_outbreak(need_out, 0, moment)
                        chill[:, 0] = torch.where(
                            need_chill, moment + mod.GHOUL_CHILL, chill[:, 0]
                        )
                        if bool(need_out2.any()):
                            apply_outbreak(need_out2, 0, moment)
                    fire_r, razor_acc = dither(razor_acc, is_g & razorice, 0.15 * luck_mult)
                    for i in range(B):
                        if bool(fire_r[i]):
                            py_rfs[i] = max(py_moment[i], py_rfs[i] - 0.30)
                    ready_fs = torch.tensor(py_rfs, dtype=dtype, device=device)
                    dem_next[:, slot] = torch.where(is_g, moment + mod.GHOUL_SWING, dem_next[:, slot])
                if bool(is_w.any()):
                    dealt = summon_hit(is_w, N_WORMS, dem_raw[:, slot], 0, moment)
                    fire_w, worm_acc = dither(worm_acc, is_w, 0.20 * luck_mult)
                    if bool(fire_w.any()):
                        deal(fire_w, N_WORMS, 2.0 * dealt, 0, moment, pot_scale=0.0)
                    fire_r, razor_acc = dither(razor_acc, is_w & razorice, 0.15 * luck_mult)
                    for i in range(B):
                        if bool(fire_r[i]):
                            py_rfs[i] = max(py_moment[i], py_rfs[i] - 0.30)
                    ready_fs = torch.tensor(py_rfs, dtype=dtype, device=device)
                    dem_next[:, slot] = torch.where(is_w, moment + mod.WORM_SWING, dem_next[:, slot])
            acted = acted | is_sum

        # 3) ERW if <= next_attack
        is_erw = alive & ~acted & (moment == erw_at) & (erw_at <= next_attack)
        if bool(is_erw.any()):
            cast_spell(is_erw, K_ERW, moment)
            for i in range(B):
                if not bool(is_erw[i]):
                    continue
                now = py_moment[i]
                # ERW resets last_cast CD
                if py_last[i] >= 0:
                    lst = py_last[i]
                    if lst == K_UF: py_ruf[i] = now
                    elif lst == K_FS: py_rfs[i] = now
                    elif lst == K_BS: py_rbs[i] = now
                    elif lst == K_DG: py_rdg[i] = now
                    py_rested[i] = lst == K_BS
                py_busy[i] = now + cast_point + float(CAST_BACKSWING) + float(cast_stun[i])
                py_rerw[i] = now + _py_cd(i, mod.ERW_CD)
                py_natk[i] = max(py_natk[i], py_busy[i])
            busy = torch.tensor(py_busy, dtype=dtype, device=device)
            ready_uf = torch.tensor(py_ruf, dtype=dtype, device=device)
            ready_fs = torch.tensor(py_rfs, dtype=dtype, device=device)
            ready_bs = torch.tensor(py_rbs, dtype=dtype, device=device)
            ready_dg = torch.tensor(py_rdg, dtype=dtype, device=device)
            ready_erw = torch.tensor(py_rerw, dtype=dtype, device=device)
            next_attack = torch.tensor(py_natk, dtype=dtype, device=device)
            rested = torch.tensor(py_rested, dtype=torch.bool, device=device)
            acted = acted | is_erw

        # 4) spell if <= next_attack
        is_spell = alive & ~acted & (moment == spell_at) & (spell_at <= next_attack)
        if bool(is_spell.any()):
            # Python-exact choice + CD updates (match CPU float inequalities)
            choice = torch.full((B,), -1, dtype=torch.int64, device=device)
            for i in range(B):
                if not bool(is_spell[i]):
                    continue
                bsv = py_busy[i]
                cands = [
                    (max(bsv, py_ruf[i]), 0, K_UF),
                    (max(bsv, py_rfs[i]), 1, K_FS),
                    (max(bsv, py_rbs[i]), 2, K_BS),
                    (max(bsv, py_rdg[i]), 3, K_DG),
                ]
                cands.sort()
                choice[i] = cands[0][2]
            for key, base_cd in (
                (K_UF, mod.UNHOLY_FURY_CD),
                (K_FS, mod.FROST_STRIKE_CD),
                (K_BS, mod.BLOOD_STRIKE_CD),
                (K_DG, mod.DEATH_GRIP_CD),
            ):
                m = is_spell & (choice == key)
                if not bool(m.any()):
                    continue
                cast_spell(m, key, moment)
                for i in range(B):
                    if not bool(m[i]):
                        continue
                    now = py_moment[i]
                    flat = float(fs_flat[i]) if key == K_FS else 0.0
                    cd = _py_cd(i, base_cd, flat)
                    stun = float(cast_stun[i])
                    # match CPU: moment + CAST_POINT + CAST_BACKSWING + stun (associativity)
                    py_busy[i] = now + cast_point + float(CAST_BACKSWING) + stun
                    if key == K_UF:
                        py_ruf[i] = now + cd
                    elif key == K_FS:
                        py_rfs[i] = now + cd
                    elif key == K_BS:
                        py_rbs[i] = now + cd
                    elif key == K_DG:
                        py_rdg[i] = now + cd
                    py_last[i] = key
                    py_rested[i] = False
                    py_natk[i] = max(py_natk[i], py_busy[i])
                # sync tensors from python
                busy = torch.tensor(py_busy, dtype=dtype, device=device)
                ready_uf = torch.tensor(py_ruf, dtype=dtype, device=device)
                ready_fs = torch.tensor(py_rfs, dtype=dtype, device=device)
                ready_bs = torch.tensor(py_rbs, dtype=dtype, device=device)
                ready_dg = torch.tensor(py_rdg, dtype=dtype, device=device)
                next_attack = torch.tensor(py_natk, dtype=dtype, device=device)
                last_cast = torch.tensor(py_last, dtype=torch.int64, device=device)
                rested = torch.tensor(py_rested, dtype=torch.bool, device=device)
            acted = acted | is_spell

        # 5) auto gated by busy
        is_busy_auto = alive & ~acted & (moment == next_attack) & (next_attack < busy)
        if bool(is_busy_auto.any()):
            for i in range(B):
                if bool(is_busy_auto[i]):
                    py_natk[i] = py_busy[i]
            next_attack = torch.tensor(py_natk, dtype=dtype, device=device)
            acted = acted | is_busy_auto

        # 6) auto
        is_auto = alive & ~acted & (moment == next_attack)
        if bool(is_auto.any()):
            recover(is_auto, moment)
            swing = full(mod.SWING) * torch.where(galactic, full(1.20), ones)
            interval = swing / (ones + attack_speed)
            deal(is_auto, N_AUTO, dcs(), 0, moment, magical=False, pot_scale=attack_potency, scale=auto_pct)
            mana = torch.where(is_auto, torch.minimum(mana_max, mana + amg), mana)
            for i in range(B):
                if bool((is_auto & razorice)[i]):
                    py_rfs[i] = max(py_moment[i], py_rfs[i] - 0.30)
            ready_fs = torch.tensor(py_rfs, dtype=dtype, device=device)
            if bool((is_auto & fire_orb).any()):
                m = is_auto & fire_orb
                # splash uses taken(1 % targets); if T==1 use taken(0)
                t_idx = 1 % T if T > 1 else 0
                splash = (
                    (full(20.0) + 0.35 * strength)
                    * float(T)
                    * taken(t_idx, moment)
                    * execute_t(moment)
                )
                add_exec(m, N_FIRE, splash, moment)
                note_damage_mana(m, float(T))
            for i in range(B):
                if bool(is_auto[i]):
                    py_natk[i] = py_moment[i] + float(interval[i])
            next_attack = torch.tensor(py_natk, dtype=dtype, device=device)
            acted = acted | is_auto

        stuck = alive & ~acted
        if bool(stuck.any()):
            for i in range(B):
                if bool(stuck[i]):
                    py_natk[i] += 1e-6
            next_attack = torch.tensor(py_natk, dtype=dtype, device=device)


    return _finalize(bufs, stats_list)
