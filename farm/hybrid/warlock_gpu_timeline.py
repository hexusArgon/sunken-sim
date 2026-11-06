# -*- coding: utf-8 -*-
"""Batched next-event timeline for Warlock (demonology / destruction / affliction).

Faithful port of sunken_sim.warlock._simulate onto batched torch.
Rows = builds x policies; generate_* returns best-policy events per build.
Demons in fixed slots; per-target DoTs + dither; f64 clocks on CPU.
Event: (when, name, weight, kind) = KIND_HERO_MAG/PHYS/EXEC/FLAT.
"""
from __future__ import annotations

MAX_STEPS = 400000
MAX_PENDING = 256
MAX_DEMONS = 64
MAX_T = 8
MAX_EVENTS = 8192

A_FEL, A_WRATH, A_HAUNT, A_CB, A_SIPHON, A_TAP = 0, 1, 2, 3, 4, 5
N_ABIL = 6
COSTS = (40.0, 40.0, 35.0, 40.0, 20.0, 0.0)  # fel wrath haunt cb siphon tap
FIXED_CD = (12.0, 6.0, 7.0, 12.0, 3.0, 4.0)
P_SIPHON, P_ROF = 0, 1
K_IMP, K_FEL = 0, 1

N_AUTO, N_SIPHON, N_ROF, N_HAUNT, N_HAUNT_RE = 0, 1, 2, 3, 4
N_AGONY, N_IMMOLATE, N_INCIN, N_FIREBOLT = 5, 6, 7, 8
N_IMP, N_FELGUARD, N_WRATHGUARD, N_DEMON_RAGE = 9, 10, 11, 12
N_CB, N_BACKDRAFT, N_BACK_IMP, N_BACK_FEL = 13, 14, 15, 16
N_BACK_WG, N_HAVOC, N_MALEFIC, N_FIRE = 17, 18, 19, 20
N_SULF, N_SULF_ECHO = 21, 22

NAMES = {
    N_AUTO: "Автоатака", N_SIPHON: "Siphon Life", N_ROF: "Rain of Fire",
    N_HAUNT: "Haunt", N_HAUNT_RE: "Haunt (повтор)", N_AGONY: "Agony",
    N_IMMOLATE: "Immolate", N_INCIN: "Incinerate",
    N_FIREBOLT: "Firebolt (Ashen Mantle)", N_IMP: "Imp",
    N_FELGUARD: "Felguard", N_WRATHGUARD: "Wrathguard",
    N_DEMON_RAGE: "Demon Rage (cleave)", N_CB: "Chaos Bolt",
    N_BACKDRAFT: "Backdraft", N_BACK_IMP: "Backdraft (Imp)",
    N_BACK_FEL: "Backdraft (Felguard)", N_BACK_WG: "Backdraft (Wrathguard)",
    N_HAVOC: "Havoc", N_MALEFIC: "Malefic Hood",
    N_FIRE: "Всплеск огня", N_SULF: "Sulfuras", N_SULF_ECHO: "Sulfuras (удар)",
}
KIND_HERO_MAG, KIND_HERO_PHYS, KIND_EXEC, KIND_FLAT = 0.0, 1.0, 2.0, 3.0


class _Overflow(Exception):
    pass


def _policies_for(spec: str, targets: int):
    from sunken_sim import warlock as mod
    for policy in mod.POLICIES:
        if spec != "affliction" and not policy[2]:
            continue
        if targets == 1 and policy[0] == "spread":
            continue
        yield policy


def generate_warlock_timelines(torch, device, builds, spec: str, targets: int, policies=None):
    if spec not in ("demonology", "destruction", "affliction"):
        raise ValueError(f"warlock GPU timeline specs demo/destro/affli, got {spec}")
    if not builds:
        return []
    dev_type = getattr(device, "type", str(device))
    if dev_type in ("privateuseone", "dml") or "privateuseone" in str(device):
        device = torch.device("cpu")
    if policies is not None:
        if len(policies) != len(builds):
            raise ValueError("policies must align with builds")
        try:
            return _warlock_batch(torch, device, torch.float64, list(builds), list(policies), spec, int(targets))
        except _Overflow:
            return _cpu_one(builds, policies, spec, targets)
    policy_list = list(_policies_for(spec, int(targets)))
    exp_builds, exp_pols, owners = [], [], []
    for i, b in enumerate(builds):
        for p in policy_list:
            exp_builds.append(b); exp_pols.append(p); owners.append(i)
    try:
        rows = _warlock_batch(torch, device, torch.float64, exp_builds, exp_pols, spec, int(targets))
    except _Overflow:
        return _cpu_best(builds, spec, targets)
    from sunken_sim import warlock as mod
    best = [None] * len(builds)
    best_tot = [-1.0] * len(builds)
    for owner, (events, stats) in zip(owners, rows):
        total = sum(mod.score_events(events, stats).values())
        if total > best_tot[owner]:
            best_tot[owner] = total
            best[owner] = (events, stats)
    out = []
    for i, b in enumerate(builds):
        out.append(best[i] if best[i] is not None else ([], mod.stats_of(b)))
    return out


def _cpu_one(builds, policies, spec, targets):
    from sunken_sim import warlock as mod
    out = []
    for build, policy in zip(builds, policies):
        stats = mod.stats_of(build)
        key = mod._timeline_key(build, stats, spec, targets, policy)
        cached = mod._TIMELINE.get(key)
        if cached is None:
            mod._simulate(build, targets, spec, policy)
            cached = mod._TIMELINE[key]
        out.append((list(cached[0]), stats))
    return out


def _cpu_best(builds, spec, targets):
    from sunken_sim import warlock as mod
    out = []
    for build in builds:
        stats = mod.stats_of(build)
        best_events, best_tot = None, -1.0
        for policy in _policies_for(spec, targets):
            key = mod._timeline_key(build, stats, spec, targets, policy)
            cached = mod._TIMELINE.get(key)
            if cached is None:
                mod._simulate(build, targets, spec, policy)
                cached = mod._TIMELINE[key]
            events = list(cached[0])
            total = sum(mod.score_events(events, stats).values())
            if total > best_tot:
                best_tot = total
                best_events = events
        out.append((best_events or [], stats))
    return out


def _armor_taken_t(torch, armor, factor):
    pos = armor > 0; neg = armor < 0
    out = torch.ones_like(armor)
    out = torch.where(pos, 1.0 - (armor * factor) / (1.0 + factor * armor), out)
    out = torch.where(neg, 2.0 - (1.0 - factor) ** (-armor), out)
    return out


def _push(torch, bufs, mask, when, weight, name_id, kind, pot=None):
    if not bool(mask.any()):
        return
    B = int(mask.shape[0])
    pot_t = pot if pot is not None else torch.zeros_like(weight)
    active = mask & (bufs["length"] < MAX_EVENTS) & ((weight != 0) | (pot_t != 0))
    if not bool(active.any()):
        return
    rows = torch.arange(B, device=weight.device)
    idx = bufs["length"].clone()
    bufs["when"][rows[active], idx[active]] = when[active]
    bufs["weight"][rows[active], idx[active]] = weight[active]
    bufs["pot"][rows[active], idx[active]] = pot_t[active]
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
        "pot": torch.zeros((B, MAX_EVENTS), dtype=dtype, device=device),
        "length": torch.zeros(B, dtype=torch.int64, device=device),
    }


def _finalize(bufs, stats_list):
    out = []
    lengths = bufs["length"].detach().cpu().tolist()
    whens = bufs["when"].detach().cpu()
    names = bufs["name"].detach().cpu()
    weights = bufs["weight"].detach().cpu()
    kinds = bufs["kind"].detach().cpu()
    pots = bufs["pot"].detach().cpu()
    for i, stats in enumerate(stats_list):
        n = int(lengths[i])
        events = [(float(whens[i, j]), NAMES[int(names[i, j])], float(weights[i, j]), float(kinds[i, j]), float(pots[i, j]))
                  for j in range(n)]
        out.append((events, stats))
    return out


def _warlock_batch(torch, device, dtype, builds, policies, spec, T):
    from sunken_sim import warlock as mod
    from sunken_sim.shadow import (
        CAST_BACKSWING, CAST_POINT, DUMMY_ARMOR, FIGHT, ARMOR_FACTOR,
        CHAOS_UNARMORED, LEVEL,
        attack_mana_gain, cast_mana_back, sulfuras_echo_chance, _wears,
    )

    B = len(builds)
    fight = float(FIGHT)
    cast_point = float(CAST_POINT)
    cast_time = float(CAST_POINT + CAST_BACKSWING)
    RANK = float(mod.RANK)
    WHITE = float(mod.WHITE_BASE)
    SWING0 = float(mod.SWING)
    BIG = 1e18
    Tt = min(int(T), MAX_T)
    zeros = torch.zeros(B, dtype=dtype, device=device)
    ones = torch.ones(B, dtype=dtype, device=device)
    rix = torch.arange(B, device=device)
    demo = spec == "demonology"
    destro = spec == "destruction"
    affli = spec == "affliction"
    factor = float(ARMOR_FACTOR)
    chaos_u = float(CHAOS_UNARMORED)
    lvl = float(LEVEL)

    stats_list, rows = [], []
    for build, policy in zip(builds, policies):
        haunt_mode, tap_mode, use_siphon_p = policy
        stats = mod.stats_of(build)
        stats_list.append(stats)
        has = lambda c, b=build: mod._has(b, c)
        luck_mult = 1.0 + stats["luck"]
        use_siphon = bool(use_siphon_p and affli)
        has_cb = bool(destro)
        order = [1, 1, 1, int(has_cb), int(use_siphon), int(tap_mode != "off")]  # fel wrath haunt cb siphon tap
        rows.append({
            "mana_max": stats["mana_max"], "mana_regen": stats["mana_regen"],
            "hp_max": stats["hp"], "dmp": stats.get("damage_mana_pct") or 0.0,
            "stun": stats["cast_stun_lock"], "haste": stats["haste"],
            "intel": float(int(stats["int"])), "mastery": float(int(stats["mastery"])),
            "damage": stats["damage"], "potency": stats["potency"],
            "crit": stats["crit"], "rating": stats["rating"],
            "attack_speed": stats["attack_speed"], "armor_pen": stats["armor_pen"],
            "auto_pct": 1.0 if stats["auto_pct"] == 1.0 else stats["auto_pct"],
            "attack_potency": stats["attack_potency"], "pet_damage": stats["pet_damage"],
            "summon_crit": stats["summon_crit"], "summon_rating": stats["summon_rating"],
            "luck_mult": luck_mult, "cd_temp": stats["cd_temp"], "flat_cdr": stats["flat_cdr"],
            "amg": attack_mana_gain(stats), "sulf_echo": sulfuras_echo_chance(stats["luck"]),
            "backs": [cast_mana_back(c, stats) for c in COSTS],
            "sulfuras": 1.0 if _wears(build, "I0BR") else 0.0,
            "fire_orb": 1.0 if stats["fire_orb"] else 0.0,
            "galactic": 1.0 if stats["galactic"] else 0.0,
            "skull": 1.0 if stats["skull"] else 0.0,
            "ashen": 1.0 if stats["ashen"] else 0.0,
            "hood": 1.0 if stats["hood"] else 0.0,
            "guldan": 1.0 if stats["guldan"] else 0.0,
            "sargeras": 1.0 if stats["sargeras"] else 0.0,
            "spell_crit": 1.0 if stats["spell_crit"] else 0.0,
            "spell_mult": stats["spell_mult"],
            "haunt_flat": stats["haunt_flat"],
            "wrathguard": 1.0 if has(mod.TALENT_WRATHGUARD) else 0.0,
            "drain_soul": 1.0 if has(mod.TALENT_DRAIN_SOUL) else 0.0,
            "chaotic": 1.0 if has(mod.TALENT_CHAOTIC_ENERGIES) else 0.0,
            "incinerate": 1.0 if has(mod.TALENT_INCINERATE) else 0.0,
            "soul_leech": 1.0 if has(mod.TALENT_SOUL_LEECH) else 0.0,
            "malefic_grasp": 1.0 if has(mod.TALENT_MALEFIC_GRASP) else 0.0,
            "havoc_t": 1.0 if has(mod.TALENT_HAVOC) else 0.0,
            "demonic_fury": 1.0 if has(mod.TALENT_DEMONIC_FURY) else 0.0,
            "consumption": 1.0 if has(mod.TALENT_CONSUMPTION) else 0.0,
            "acceleration": 1.0 if has(mod.TALENT_ACCELERATION) else 0.0,
            "implosion": 1.0 if has(mod.TALENT_IMPLOSION) else 0.0,
            "rain": 1.0 if has(mod.TALENT_RAIN_OF_FIRE) else 0.0,
            "grimoire": 1.0 if has(mod.TALENT_GRIMOIRE) else 0.0,
            "cremation": 1.0 if has(mod.TALENT_CREMATION) else 0.0,
            "demon_rage": 1.0 if has(mod.TALENT_DEMON_RAGE) else 0.0,
            "withered_t": 1.0 if has(mod.TALENT_WITHERED_SOUL) else 0.0,
            "demonic_emp": 1.0 if has(mod.TALENT_DEMONIC_EMPOWERMENT) else 0.0,
            "all_mastery": 1.0 if has(mod.TALENT_ALL_MASTERY) else 0.0,
            "has_cb": 1.0 if has_cb else 0.0,
            "has_agony": 1.0 if (not destro) else 0.0,
            "has_backdraft": 1.0 if (not affli) else 0.0,
            "use_siphon": 1.0 if use_siphon else 0.0,
            "tap_code": float({"off": 0, "mana": 1, "always": 2}[tap_mode]),
            "haunt_code": 0.0 if haunt_mode == "focus" else 1.0,
            "order": order,
        })

    def V(k):
        return torch.tensor([r[k] for r in rows], dtype=dtype, device=device)

    def F(k):
        return V(k) > 0.5

    mana_max, mana_regen, hp_max = V("mana_max"), V("mana_regen"), V("hp_max")
    dmp, stun, haste = V("dmp"), V("stun"), V("haste")
    intel, mastery, damage = V("intel"), V("mastery"), V("damage")
    potency0, crit0, rating0 = V("potency"), V("crit"), V("rating")
    attack_speed0, armor_pen = V("attack_speed"), V("armor_pen")
    auto_pct, attack_potency = V("auto_pct"), V("attack_potency")
    pet_damage = V("pet_damage")
    summon_crit, summon_rating = V("summon_crit"), V("summon_rating")
    luck_mult, cd_temp, flat_cdr = V("luck_mult"), V("cd_temp"), V("flat_cdr")
    amg, sulf_echo, haunt_flat = V("amg"), V("sulf_echo"), V("haunt_flat")
    backs = torch.tensor([r["backs"] for r in rows], dtype=dtype, device=device)
    costs_t = torch.tensor(COSTS, dtype=dtype, device=device)
    order_en = torch.tensor([r["order"] for r in rows], dtype=dtype, device=device)
    tap_code, haunt_code = V("tap_code"), V("haunt_code")
    spell_mult = V("spell_mult")

    wrathguard, drain_soul = F("wrathguard"), F("drain_soul")
    chaotic, incinerate = F("chaotic"), F("incinerate")
    soul_leech, malefic_grasp = F("soul_leech"), F("malefic_grasp")
    havoc_t, demonic_fury = F("havoc_t"), F("demonic_fury")
    consumption, acceleration = F("consumption"), F("acceleration")
    implosion, rain = F("implosion"), F("rain")
    grimoire, cremation = F("grimoire"), F("cremation")
    demon_rage_t, withered_t = F("demon_rage"), F("withered_t")
    demonic_emp, all_mastery = F("demonic_emp"), F("all_mastery")
    has_cb, has_agony = F("has_cb"), F("has_agony")
    has_backdraft, use_siphon = F("has_backdraft"), F("use_siphon")
    is_demo = torch.full((B,), demo, device=device)
    is_destro = torch.full((B,), destro, device=device)
    is_affli = torch.full((B,), affli, device=device)
    fire_orb, galactic, sulfuras_on = F("fire_orb"), F("galactic"), F("sulfuras")
    skull, ashen, hood = F("skull"), F("ashen"), F("hood")
    guldan, sargeras = F("guldan"), F("sargeras")
    spell_crit_f = F("spell_crit")

    mana = mana_max.clone()
    mana_time = zeros.clone()
    hp = hp_max.clone()
    busy = zeros.clone()
    next_attack = zeros.clone()
    ready = torch.zeros((B, N_ABIL), dtype=dtype, device=device)
    haunt_until = torch.full((B, Tt), -1.0, dtype=dtype, device=device)
    agony_until = torch.full((B, Tt), -1.0, dtype=dtype, device=device)
    immolate_until = torch.full((B, Tt), -1.0, dtype=dtype, device=device)
    withered = torch.zeros((B, Tt), dtype=dtype, device=device)
    wrath_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    drain_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    cb_buff_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    siphon_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    siphon_target = torch.zeros(B, dtype=torch.int64, device=device)
    casts = torch.zeros(B, dtype=torch.int64, device=device)
    sulf_armed = torch.zeros(B, dtype=torch.bool, device=device)

    d_agony = torch.zeros((B, Tt), dtype=dtype, device=device)
    d_drain = zeros.clone(); d_imp = zeros.clone()
    d_revel = zeros.clone(); d_haunt_apply = zeros.clone()

    haunt_timer = ones.clone()
    agony_timer = torch.where(has_agony, ones.clone(), torch.full((B,), fight * 10, dtype=dtype, device=device))
    immolate_timer = torch.full((B,), 1.5, dtype=dtype, device=device)

    p_time = torch.full((B, MAX_PENDING), BIG, dtype=dtype, device=device)
    p_order = torch.zeros((B, MAX_PENDING), dtype=torch.int64, device=device)
    p_kind = torch.zeros((B, MAX_PENDING), dtype=torch.int64, device=device)
    order_c = torch.zeros(B, dtype=torch.int64, device=device)

    dem_alive = torch.zeros((B, MAX_DEMONS), dtype=torch.bool, device=device)
    dem_kind = torch.zeros((B, MAX_DEMONS), dtype=torch.int64, device=device)
    dem_next = torch.full((B, MAX_DEMONS), BIG, dtype=dtype, device=device)
    dem_end = torch.full((B, MAX_DEMONS), -BIG, dtype=dtype, device=device)
    dem_raw = torch.zeros((B, MAX_DEMONS), dtype=dtype, device=device)
    dem_wrath = torch.full((B, MAX_DEMONS), -1.0, dtype=dtype, device=device)
    dem_revel = torch.zeros((B, MAX_DEMONS), dtype=torch.bool, device=device)
    dem_bolt = torch.full((B, MAX_DEMONS), BIG, dtype=dtype, device=device)
    dem_count = torch.zeros(B, dtype=torch.int64, device=device)  # append-only like CPU list

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

    def heal_hp(mask, amount):
        nonlocal hp
        hp = torch.where(mask, torch.minimum(hp_max, hp + full(amount)), hp)

    def note_dmp(mask, count):
        gain(mask & (dmp > 0), dmp * mana_max * full(count))

    def cd(base, flat=0.0):
        return torch.clamp((full(base) * cd_temp - flat_cdr - full(flat)) / (1.0 + haste), min=0.5)

    def wrath_on(now):
        return full(now) < wrath_until

    def dcs(now):
        value = WHITE + 0.75 * intel + damage
        return torch.where(wrath_on(now), value * (1.0 + float(mod.WRATH_DCS)), value)

    def live_count(now):
        return (dem_alive & (dem_end > full(now).view(B, 1))).sum(dim=1).to(dtype)

    def taken(index, now, hero=True):
        armor = full(float(DUMMY_ARMOR)) - withered[:, index]
        armor = armor - torch.where(haunt_until[:, index] > full(now), full(mod.HAUNT_ARMOR), zeros)
        if hero:
            armor = armor - armor_pen
        return _armor_taken_t(torch, armor, factor)

    def agony_flat(index, now):
        return torch.where(is_affli & (agony_until[:, index] > full(now)), full(5.0) + 0.07 * intel, zeros)

    def hero_crit(now):
        c = crit0 + torch.where(is_destro | all_mastery, full(5.0) + 0.5 * mastery, zeros)
        return c + torch.where(demonic_emp, full(3.0) * live_count(now), zeros)

    def cf(ch, mult):
        ch = torch.clamp(full(ch), 0.0, 100.0) / 100.0
        return 1.0 + ch * (full(mult) - 1.0)

    def push_pend(mask, when, kind):
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
        p_time[rix[mask], slot[mask]] = BIG
        return now, kind

    def haunt_rate(now):
        rate = ones.clone()
        rate = rate + torch.where(is_affli | all_mastery, full(0.05) + 0.005 * mastery, zeros)
        rate = rate + torch.where(acceleration, full(0.12) + 0.12 * dcs(now) / 100.0, zeros)
        return rate

    def agony_rate(now):
        rate = ones.clone()
        return rate + torch.where(acceleration, full(0.12) + 0.12 * dcs(now) / 100.0, zeros)

    def immolate_rate(now):
        rate = ones.clone()
        return rate + torch.where(is_affli | all_mastery, full(0.05) + 0.005 * mastery, zeros)

    def haunt_tick_raw(now):
        raw = full(10.0 * RANK) + 0.15 * intel
        return raw + torch.where(drain_soul, 0.10 * dcs(now), zeros)

    def immolate_raw(now):
        return full(5.0 * RANK) + 0.10 * dcs(now)


    MAX_E = 8
    exec_thr = torch.full((B, MAX_E), -1.0, dtype=dtype, device=device)
    exec_bon = torch.zeros((B, MAX_E), dtype=dtype, device=device)
    magic_add = torch.tensor([stats_list[i]["magic_add"] for i in range(B)], dtype=dtype, device=device)
    phys_add = torch.tensor([stats_list[i]["phys_add"] for i in range(B)], dtype=dtype, device=device)
    sulfuron = torch.tensor([1.0 if stats_list[i]["sulfuron"] else 0.0 for i in range(B)], dtype=dtype, device=device) > 0.5
    spellbinder = torch.tensor([1.0 if stats_list[i]["spellbinder"] else 0.0 for i in range(B)], dtype=dtype, device=device) > 0.5
    glass = torch.tensor([1.0 if stats_list[i]["glass"] else 0.0 for i in range(B)], dtype=dtype, device=device) > 0.5
    for i, st in enumerate(stats_list):
        for j, (thr, bon) in enumerate(st["executes"][:MAX_E]):
            exec_thr[i, j] = thr
            exec_bon[i, j] = bon

    def exec_f(now):
        hp = torch.clamp(1.0 - full(now) / fight, min=0.0)
        fac = ones.clone()
        for j in range(MAX_E):
            active = exec_thr[:, j] >= 0
            hit = active & (hp <= exec_thr[:, j])
            fac = torch.where(hit, fac * (1.0 + exec_bon[:, j]), fac)
        return fac

    def typed_bonus(magical, now):
        bonus = ones + (magic_add if magical else phys_add)
        th = torch.clamp(1.0 - full(now) / fight, min=0.0)
        bonus = bonus + torch.where(sulfuron, full(0.13) + 0.25 * th, zeros)
        if magical:
            bonus = bonus + torch.where(spellbinder, full(0.05) + 0.005 * mastery, zeros)
        return torch.where(glass, bonus * 1.15, bonus)

    def hero_hit(mask, name, raw, now, indices, magical=True, attack=False, weight=1.0, pot_scale=1.0, chaos=False):
        """One aggregated event across indices. Returns (dealt_base, dealt_pot, crit_share)."""
        if not bool(mask.any()) or not indices:
            return zeros, zeros, zeros
        now = full(now); raw = full(raw); weight = full(weight); pot_scale = full(pot_scale)
        is_atk = ones if attack is True else zeros
        ch = hero_crit(now)
        share = torch.where((is_atk > 0.5) | spell_crit_f, torch.clamp(ch, 0.0, 100.0) / 100.0, zeros)
        pre_total = zeros.clone()
        pre_pot_total = zeros.clone()
        first_pre = zeros.clone()
        first_pot = zeros.clone()
        for i, index in enumerate(indices):
            base = raw + agony_flat(index, now)
            scale = pot_scale
            if chaos:
                base = base * chaos_u
                scale = scale * chaos_u
            rating = rating0 + torch.where(cremation, full(0.15), zeros)
            rating = rating + torch.where(incinerate & (immolate_until[:, index] > now), full(0.30), zeros)
            crit_m = torch.where(is_atk > 0.5, cf(ch, 2.0 + rating),
                                 torch.where(spell_crit_f, cf(ch, spell_mult + rating), ones))
            take = taken(index, now, True)
            pre = base * crit_m * take
            pre_pot = scale * crit_m * take
            pre_total = pre_total + pre
            pre_pot_total = pre_pot_total + pre_pot
            if i == 0:
                first_pre = pre
                first_pot = pre_pot
        kind = KIND_HERO_MAG if magical else KIND_HERO_PHYS
        _push(torch, bufs, mask, now, pre_total * weight, name, kind, pot=pre_pot_total * weight)
        note_dmp(mask, full(float(len(indices))) * weight)
        tf = typed_bonus(magical, now) * exec_f(now)
        return first_pre * tf, first_pot * tf, share

    def summon_hit(mask, name, raw, now, indices, magical=True, attack=True, weight=1.0, increase=0.0, chaos=False):
        if not bool(mask.any()) or not indices:
            return zeros, zeros, zeros
        now = full(now); raw = full(raw); weight = full(weight); increase = full(increase)
        ch = summon_crit + torch.where(demonic_emp, full(10.0) + 0.25 * crit0, zeros)
        share = torch.where(torch.tensor(bool(attack), device=device), torch.clamp(ch, 0.0, 100.0) / 100.0, zeros) if not isinstance(attack, torch.Tensor) else torch.where(attack, torch.clamp(ch, 0.0, 100.0) / 100.0, zeros)
        if attack is False:
            share = zeros
        elif attack is True:
            share = torch.clamp(ch, 0.0, 100.0) / 100.0
        pre_total = zeros.clone()
        pre_pot_total = zeros.clone()
        first_pre = zeros.clone()
        first_pot = zeros.clone()
        pet = 1.0 + pet_damage + increase
        for i, index in enumerate(indices):
            base = (raw + agony_flat(index, now)) * pet
            pot_part = pet
            if chaos:
                base = base * chaos_u
                pot_part = pot_part * chaos_u
            if attack:
                cm = cf(ch, 2.0 + summon_rating)
                base = base * cm
                pot_part = pot_part * cm
            take = taken(index, now, False)
            pre = base * take
            pre_pot = pot_part * take
            pre_total = pre_total + pre
            pre_pot_total = pre_pot_total + pre_pot
            if i == 0:
                first_pre = pre
                first_pot = pre_pot
        _push(torch, bufs, mask, now, pre_total * weight, name, KIND_EXEC, pot=pre_pot_total * weight)
        ex = exec_f(now)
        return first_pre * ex, first_pot * ex, share

    def malefic(mask, now, t):
        w = chance(0.33 * luck_mult)
        hero_hit(mask & hood & (w > 0), N_MALEFIC, full(30.0) + 0.30 * intel, now, [t], magical=True, attack=False, weight=w)

    def agony_apply(mask, now, t):
        nonlocal agony_until
        m = mask & has_agony
        agony_until[:, t] = torch.where(m, now + float(mod.AGONY_DUR), agony_until[:, t])
        malefic(m, now, t)

    def agony_chance(mask, now, t, ch):
        nonlocal d_agony
        fire, d_agony[:, t] = dither(d_agony[:, t], mask & has_agony, ch)
        agony_apply(fire, now, t)

    def haunt_apply(mask, now, t):
        nonlocal haunt_until, withered
        now = full(now)
        refresh = mask & (haunt_until[:, t] > now)
        if bool(refresh.any()):
            raw = haunt_tick_raw(now) * 10.0 * haunt_rate(now)
            hero_hit(refresh, N_HAUNT_RE, raw, now, [t], magical=True, attack=False)
            agony_apply(refresh, now, t)
        haunt_until[:, t] = torch.where(mask, now + float(mod.HAUNT_DUR), haunt_until[:, t])
        withered[:, t] = torch.where(mask & withered_t, torch.minimum(full(8.0), withered[:, t] + 1.0), withered[:, t])
        malefic(mask, now, t)

    def _alloc_demon(mask, kind, now, life, raw_v):
        """Append-only slot alloc — matches CPU demons.append order for revel pool[0]."""
        nonlocal dem_alive, dem_count
        if not bool(mask.any()):
            return
        if bool((mask & (dem_count >= MAX_DEMONS)).any()):
            raise _Overflow("demons")
        slot = dem_count
        r = rix[mask]; s = slot[mask]
        dem_alive[r, s] = True
        dem_kind[r, s] = int(kind) if not isinstance(kind, torch.Tensor) else kind[mask]
        dem_next[r, s] = full(now)[mask]
        dem_end[r, s] = (full(now) + life if isinstance(life, torch.Tensor) else full(now) + full(life))[mask]
        dem_raw[r, s] = (raw_v if isinstance(raw_v, torch.Tensor) else full(raw_v))[mask]
        dem_wrath[r, s] = -1.0
        dem_revel[r, s] = False
        dem_bolt[r, s] = (full(now) + float(mod.FIREBOLT_PERIOD))[mask]
        dem_count = dem_count + mask.to(torch.int64)

    def spawn_demon(mask, kind, now, life, raw_v):
        life_t = life if isinstance(life, torch.Tensor) else full(life)
        raw_t = raw_v if isinstance(raw_v, torch.Tensor) else full(raw_v)
        _alloc_demon(mask, kind, now, life_t, raw_t)

    def spawn_imp(mask, now):
        life = float(mod.IMP_LIFE) + torch.where(skull, full(1.2), zeros)
        raw_v = full(6.0 * RANK) + torch.floor(0.10 * dcs(now)) + 1.0
        _alloc_demon(mask, K_IMP, now, life, raw_v)

    def spawn_felguard(mask, now):
        life = float(mod.FELGUARD_LIFE) * torch.where(skull, full(1.2), ones)
        _alloc_demon(mask, K_FEL, now, life, zeros)

    def imp_chance(mask, now, base, weight=1.0):
        nonlocal d_imp
        m = mask & implosion
        if not bool(m.any()):
            return
        now = full(now); weight = full(weight)
        imps = (dem_alive & (dem_end > now.view(B, 1)) & (dem_kind == K_IMP)).sum(dim=1).to(dtype)
        ch = full(base) * (0.75 ** imps) * luck_mult * weight
        fire, d_imp = dither(d_imp, m, ch)
        spawn_imp(fire, now)

    def backdraft(mask, now, weight, hero_source, by_name_id):
        nonlocal ready
        m = mask & (full(weight) > 0)
        if not bool(m.any()):
            return
        now = full(now); weight = full(weight)
        raw = full(20.0) + 0.40 * dcs(now)
        raw = torch.where(sargeras, raw * 1.25, raw)
        others = list(range(1, Tt))
        if hero_source:
            hero_hit(m, N_BACKDRAFT, raw, now, [0], magical=False, attack=False, weight=weight)
            if others:
                hero_hit(m, N_BACKDRAFT, raw / 2.0, now, others, magical=False, attack=False, weight=weight)
            # CB cdr
            left = ready[:, A_CB] - now
            ready[:, A_CB] = torch.where(m & has_cb & (ready[:, A_CB] > now), now + torch.clamp(left - 0.75 * weight, min=0.0), ready[:, A_CB])
        else:
            hero_hit  # noqa — use summon
            summon_hit(m, by_name_id, raw, now, [0], magical=False, attack=False, weight=weight)
            if others:
                summon_hit(m, by_name_id, raw / 2.0, now, others, magical=False, attack=False, weight=weight)
        imp_chance(m, now, 0.50, weight)

    def backdraft_on_attack(mask, now, crit_share, hero_source, by_name_id):
        m = mask & has_backdraft
        if not bool(m.any()):
            return
        now = full(now); crit_share = full(crit_share)
        base = crit_share * 30.0 + (1.0 - crit_share) * 12.0
        ch = (base + 0.08 * dcs(now)) / 100.0
        if not hero_source:
            ch = ch * 0.5
        ch = torch.where(cremation, ch * 1.2, ch)
        ch = ch * luck_mult
        backdraft(m, now, chance(ch), hero_source, by_name_id)

    def havoc(mask, now, dealt, dealt_pot=None):
        pot = dealt_pot if dealt_pot is not None else torch.zeros_like(dealt)
        m = mask & havoc_t & ((dealt != 0) | (pot != 0))
        if not bool(m.any()):
            return
        now = full(now)
        haunted = (haunt_until > now.view(B, 1)).sum(dim=1).to(dtype)
        amt = 0.12 * dealt * haunted
        amt_pot = 0.12 * pot * haunted
        _push(torch, bufs, m & (haunted > 0), now, amt, N_HAVOC, KIND_FLAT, pot=amt_pot)

    def demon_speed(slot, now):
        speed = torch.where(is_demo | all_mastery, full(0.08) + 0.006 * mastery, zeros)
        speed = speed + torch.where(full(now) < dem_wrath[:, slot], full(float(mod.WRATH_AS)) + torch.where(demonic_fury, full(0.20), zeros), zeros)
        return torch.clamp(speed, -0.8, 4.0)

    def interval(now):
        swing = SWING0 * torch.where(galactic, full(1.20), ones)
        speed = attack_speed0.clone()
        speed = speed + torch.where(wrath_on(now), full(float(mod.WRATH_AS)) + torch.where(demonic_fury, full(0.20), zeros), zeros)
        return swing / (1.0 + torch.clamp(speed, -0.8, 4.0))

    def spellcast(mask, now):
        nonlocal casts
        casts = casts + mask.to(torch.int64)
        spawn_felguard(mask & grimoire & (casts % 8 == 0), now)

    # init haunt/agony/immolate timers with rates at 0
    haunt_timer = ones / haunt_rate(zeros)
    agony_timer = torch.where(has_agony, ones / agony_rate(zeros), torch.full((B,), fight * 10, dtype=dtype, device=device))
    immolate_timer = full(1.5) / immolate_rate(zeros)

    steps = 0
    while bool(alive.any()):
        steps += 1
        if steps > MAX_STEPS:
            raise _Overflow("steps")

        # prune demons
        dem_alive = dem_alive & (dem_end > zeros.view(B, 1))  # keep until end; clock check below

        attack_at = torch.maximum(torch.maximum(next_attack, busy), torch.maximum(zeros, siphon_until))
        # cast choice
        ready_at = torch.maximum(ready, torch.maximum(busy, siphon_until).view(B, 1).expand(B, N_ABIL))
        # tap gates
        tap_value = full(25.0 + 25.0 * lvl)
        guess_mana = torch.minimum(mana_max, mana + mana_regen * torch.clamp(ready_at[:, A_TAP] - mana_time, min=0.0))
        tap_ok = (order_en[:, A_TAP] > 0.5) & (hp - tap_value >= 0.30 * hp_max)
        tap_ok = tap_ok & ~((tap_code > 0.5) & (tap_code < 1.5) & (guess_mana > mana_max - 0.40 * tap_value))
        # wrath due
        wrath_due = wrath_until - 1.0
        # also min over demons — approximate with wrath_due only (CPU also checks demon wrath)
        dem_wrath_due = torch.where(dem_alive & (dem_next < dem_end), torch.maximum(dem_next - 0.5, dem_wrath - 1.0), full(fight * 10).view(B, 1).expand(B, MAX_DEMONS))
        dem_wrath_min = dem_wrath_due.min(dim=1).values
        wrath_due = torch.minimum(wrath_due, dem_wrath_min)
        ready_at[:, A_WRATH] = torch.maximum(ready_at[:, A_WRATH], wrath_due)
        # siphon near end skip
        siphon_ok = (order_en[:, A_SIPHON] > 0.5) & (ready_at[:, A_SIPHON] < fight - 0.5)
        enabled = order_en > 0.5
        enabled[:, A_TAP] = tap_ok
        enabled[:, A_SIPHON] = siphon_ok
        enabled[:, A_CB] = order_en[:, A_CB] > 0.5
        cast_cand = torch.where(enabled, ready_at, full(fight * 10).view(B, 1).expand(B, N_ABIL))
        cast_at, choice = cast_cand.min(dim=1)

        pending_at = peek_pend()
        dem_cand = torch.where(dem_alive & (dem_next < dem_end), dem_next, full(fight * 10).view(B, 1).expand(B, MAX_DEMONS))
        demon_at = dem_cand.min(dim=1).values
        bolt_cand = torch.where(dem_alive & ashen.view(B, 1) & (dem_bolt < dem_end), dem_bolt, full(fight * 10).view(B, 1).expand(B, MAX_DEMONS))
        bolt_at = bolt_cand.min(dim=1).values
        timers = torch.minimum(torch.minimum(haunt_timer, agony_timer), immolate_timer)
        moment = torch.min(torch.min(attack_at, cast_at), torch.min(pending_at, torch.min(demon_at, torch.min(bolt_at, timers))))
        alive = alive & (moment < fight)
        if not bool(alive.any()):
            break

        # prune by clock
        dem_alive = dem_alive & (dem_end > moment.view(B, 1) - 1e-9)

        is_pend = alive & (moment == pending_at)
        is_haunt_t = alive & ~is_pend & (moment == haunt_timer)
        is_agony_t = alive & ~is_pend & ~is_haunt_t & (moment == agony_timer)
        is_imm_t = alive & ~is_pend & ~is_haunt_t & ~is_agony_t & (moment == immolate_timer)
        is_bolt = alive & ~is_pend & ~is_haunt_t & ~is_agony_t & ~is_imm_t & (moment == bolt_at) & (bolt_at < attack_at) & (bolt_at < cast_at)
        is_demon = alive & ~is_pend & ~is_haunt_t & ~is_agony_t & ~is_imm_t & ~is_bolt & (moment == demon_at) & (demon_at < attack_at) & (demon_at < cast_at)
        is_cast = alive & ~is_pend & ~is_haunt_t & ~is_agony_t & ~is_imm_t & ~is_bolt & ~is_demon & (cast_at <= attack_at) & (moment == cast_at)
        is_auto = alive & ~is_pend & ~is_haunt_t & ~is_agony_t & ~is_imm_t & ~is_bolt & ~is_demon & ~is_cast

        # PENDING
        if bool(is_pend.any()):
            _n, pk = pop_pend(is_pend)
            # siphon
            m = is_pend & (pk == P_SIPHON)
            if bool(m.any()):
                raw = (full(10.0) + 5.0 * lvl + 0.65 * intel) / 4.0
                # siphon_target always 0 in CPU after cast
                hero_hit(m, N_SIPHON, raw, moment, [0], magical=True, attack=False)
                heal_hp(m, (full(18.0) + 0.08 * hp_max) / 4.0)
                agony_chance(m, moment, 0, 0.05 * luck_mult)
                fire, d_haunt_apply = dither(d_haunt_apply, m & soul_leech, 0.04 * luck_mult)
                haunt_apply(fire, moment, 0)
                imp_chance(m, moment, 0.20)
            # rain of fire
            m = is_pend & (pk == P_ROF)
            if bool(m.any()):
                raw = full(5.0) + 0.20 * dcs(moment)
                hero_hit(m, N_ROF, raw, moment, list(range(Tt)), magical=True, attack=False)
                for t in range(Tt):
                    immolate_until[:, t] = torch.where(m, torch.maximum(immolate_until[:, t], moment + float(mod.IMMOLATE_DUR)), immolate_until[:, t])
                if bool((m & has_backdraft).any()):
                    ch = chance((full(5.0) + 0.20 * crit0) / 100.0 * luck_mult)
                    # CPU: for each target, backdraft(moment, chance, True) — weight = _chance once per target stacked?
                    # for _t in range(targets): backdraft(moment, chance, True, ...)
                    # so weight applied targets times via separate calls each with same chance weight
                    for _t in range(Tt):
                        backdraft(m & has_backdraft, moment, ch, True, N_BACKDRAFT)

        # HAUNT TICK
        if bool(is_haunt_t.any()):
            raw = haunt_tick_raw(moment)
            for t in range(Tt):
                active = is_haunt_t & (haunt_until[:, t] > moment)
                ticks = torch.where(malefic_grasp & (moment < siphon_until) & (siphon_target == int(t)), full(2.0), ones)
                # weight=ticks — but ticks is per-row; hero_hit weight tensor ok
                # CPU uses weight=ticks on hero_hit
                # Our hero_hit takes scalar-ish weight tensor
                hero_hit(active, N_HAUNT, raw, moment, [t], magical=True, attack=False, weight=ticks)
                agony_chance(active, moment, t, 0.20 * luck_mult * ticks)
                # CPU only rolls while drain is down: moment >= drain_until
                fire, d_drain = dither(d_drain, active & drain_soul & (moment >= drain_until), 0.12 * luck_mult * ticks)
                drain_until = torch.where(fire, moment + float(mod.DRAIN_SOUL_DUR), drain_until)
            haunt_timer = torch.where(is_haunt_t, moment + ones / haunt_rate(moment), haunt_timer)

        # AGONY TICK
        if bool(is_agony_t.any()):
            raw = full(5.0) + 0.10 * intel
            for t in range(Tt):
                active = is_agony_t & (agony_until[:, t] > moment)
                hero_hit(active, N_AGONY, raw, moment, [t], magical=True, attack=False)
                fire, d_revel = dither(d_revel, active & is_demo, 0.20 * luck_mult)
                # mark first live non-revel demon, else first live
                if bool(fire.any()):
                    for slot in range(MAX_DEMONS):
                        live = dem_alive[:, slot] & (dem_end[:, slot] > moment)
                        take = fire & live & ~dem_revel[:, slot]
                        # only first slot wins per row — use a consumed flag
                        # simpler: set revel on first matching slot among fire rows that don't already have one set this tick
                        pass
                    # vectorized: pick min slot among live
                    live_slots = torch.where(dem_alive & (dem_end > moment.view(B, 1)), torch.arange(MAX_DEMONS, device=device).view(1, MAX_DEMONS).expand(B, MAX_DEMONS), torch.full((B, MAX_DEMONS), MAX_DEMONS, device=device))
                    # prefer non-revel
                    pref = torch.where(dem_alive & (dem_end > moment.view(B, 1)) & ~dem_revel, torch.arange(MAX_DEMONS, device=device).view(1, MAX_DEMONS).expand(B, MAX_DEMONS), torch.full((B, MAX_DEMONS), MAX_DEMONS, device=device))
                    slot_pref = pref.min(dim=1).values
                    slot_any = live_slots.min(dim=1).values
                    use = torch.where(slot_pref < MAX_DEMONS, slot_pref, slot_any)
                    for slot in range(MAX_DEMONS):
                        dem_revel[:, slot] = dem_revel[:, slot] | (fire & (use == slot) & (use < MAX_DEMONS))
            agony_timer = torch.where(is_agony_t, moment + ones / agony_rate(moment), agony_timer)

        # IMMOLATE TICK
        if bool(is_imm_t.any()):
            raw = immolate_raw(moment)
            for t in range(Tt):
                active = is_imm_t & (immolate_until[:, t] > moment)
                w = ones + chance(crit0 / 100.0 * luck_mult)
                w = w + torch.where(malefic_grasp & (agony_until[:, t] > moment), chance(0.20 * luck_mult), zeros)
                hero_hit(active, N_IMMOLATE, raw, moment, [t], magical=True, attack=False, weight=w)
            immolate_timer = torch.where(is_imm_t, moment + full(1.5) / immolate_rate(moment), immolate_timer)

        # ASHEN BOLT — one demon per row (CPU: min by bolt)
        if bool(is_bolt.any()):
            due_b = torch.where(
                dem_alive & ashen.view(B, 1) & (dem_bolt == moment.view(B, 1)) & (dem_bolt < dem_end),
                torch.arange(MAX_DEMONS, device=device).view(1, MAX_DEMONS).expand(B, MAX_DEMONS),
                torch.full((B, MAX_DEMONS), MAX_DEMONS, device=device),
            )
            pick_b = due_b.min(dim=1).values
            for slot in range(MAX_DEMONS):
                active = is_bolt & (pick_b == slot) & (pick_b < MAX_DEMONS)
                if not bool(active.any()):
                    continue
                summon_hit(active, N_FIREBOLT, full(10.0) + 0.10 * intel, moment, [0], magical=True, attack=False)
                dem_bolt[:, slot] = torch.where(active, moment + float(mod.FIREBOLT_PERIOD), dem_bolt[:, slot])

        # DEMON SWING — one demon per row per step (CPU: min by next, append order)
        if bool(is_demon.any()):
            due = torch.where(
                dem_alive & (dem_next == moment.view(B, 1)) & (dem_next < dem_end),
                torch.arange(MAX_DEMONS, device=device).view(1, MAX_DEMONS).expand(B, MAX_DEMONS),
                torch.full((B, MAX_DEMONS), MAX_DEMONS, device=device),
            )
            pick = due.min(dim=1).values
            for slot in range(MAX_DEMONS):
                active = is_demon & (pick == slot) & (pick < MAX_DEMONS)
                if not bool(active.any()):
                    continue
                increase = torch.where(dem_revel[:, slot], full(float(mod.REVEL_BONUS)), zeros)
                dem_revel[:, slot] = dem_revel[:, slot] & ~active  # clear on attack
                # imp
                m = active & (dem_kind[:, slot] == K_IMP)
                if bool(m.any()):
                    dealt, dealt_pot, share = summon_hit(m, N_IMP, dem_raw[:, slot], moment, [0], magical=True, attack=True, increase=increase)
                    havoc(m, moment, dealt, dealt_pot)
                    swing = full(float(mod.IMP_SWING))
                    backdraft_on_attack(m, moment, share, False, N_BACK_IMP)
                    dem_next[:, slot] = torch.where(m, moment + swing / (1.0 + demon_speed(slot, moment)), dem_next[:, slot])
                # fel / wrathguard
                m = active & (dem_kind[:, slot] == K_FEL)
                if bool(m.any()):
                    raw = full(7.0) + torch.floor(full(8.0 * RANK) + 0.20 * dcs(moment) + 0.02 * hp_max) + 1.0
                    nm = torch.where(wrathguard, full(float(N_WRATHGUARD)), full(float(N_FELGUARD))).to(torch.int64)
                    # summon_hit with per-row name: push twice
                    dealt_f, pot_f, share_f = summon_hit(m & ~wrathguard, N_FELGUARD, raw, moment, [0], magical=False, attack=True, increase=increase, chaos=False)
                    dealt_w, pot_w, share_w = summon_hit(m & wrathguard, N_WRATHGUARD, raw, moment, [0], magical=False, attack=True, increase=increase, chaos=True)
                    dealt = torch.where(wrathguard, dealt_w, dealt_f)
                    dealt_pot = torch.where(wrathguard, pot_w, pot_f)
                    share = torch.where(wrathguard, share_w, share_f)
                    havoc(m & wrathguard, moment, dealt, dealt_pot)
                    # demon rage cleave FLAT
                    extra = float(max(1, Tt - 1))
                    cleave = 0.15 * dealt * extra
                    cleave_pot = 0.15 * dealt_pot * extra
                    _push(torch, bufs, m & demon_rage_t, moment, cleave, N_DEMON_RAGE, KIND_FLAT, pot=cleave_pot)
                    swing = full(float(mod.FELGUARD_SWING)) * torch.where(consumption, full(1.20), ones)
                    backdraft_on_attack(m & ~wrathguard, moment, share, False, N_BACK_FEL)
                    backdraft_on_attack(m & wrathguard, moment, share, False, N_BACK_WG)
                    dem_next[:, slot] = torch.where(m, moment + swing / (1.0 + demon_speed(slot, moment)), dem_next[:, slot])
                agony_chance(active, moment, 0, 0.05 * luck_mult)

        # CAST
        if bool(is_cast.any()):
            cost_v = costs_t[choice]
            back_v = backs[rix, choice]
            recover(is_cast, moment)
            can = is_cast & (mana >= cost_v)
            fail = is_cast & ~can
            for k in range(N_ABIL):
                ready[:, k] = torch.where(fail & (choice == k), moment + 0.25, ready[:, k])
            if bool(can.any()):
                mana = torch.where(can, mana - cost_v, mana)
                gain(can, back_v)
                hit_at = moment + cast_point
                sulf_armed = sulf_armed | (can & sulfuras_on & ~sulf_armed)
                busy = torch.where(can, moment + cast_time + stun, busy)
                spellcast(can, hit_at)

                # FELGUARD
                m = can & (choice == A_FEL)
                if bool(m.any()):
                    for t in range(Tt):
                        immolate_until[:, t] = torch.where(m, hit_at + float(mod.IMMOLATE_DUR), immolate_until[:, t])
                        raw_inc = immolate_raw(hit_at) * 8.0 * immolate_rate(hit_at)
                        hero_hit(m & incinerate, N_INCIN, raw_inc, hit_at, [t], magical=True, attack=False)
                        malefic(m, hit_at, t)
                    # rain of fire waves
                    if bool((m & rain).any()):
                        speed = 0.5 * attack_speed0
                        waves = torch.floor(full(5.0) * (1.0 + speed) + 0.5).to(torch.int64)
                        gap = ones / (1.0 + speed)
                        max_w = int(waves.max().item()) if bool(waves.numel()) else 0
                        max_w = min(max_w, 32)
                        for i in range(max_w):
                            push_pend(m & rain & (waves > i), hit_at + (i + 1) * gap, P_ROF)
                    spawn_felguard(m, hit_at)
                    spawn_felguard(m & is_demo, hit_at)  # demo summons 2
                    ready[:, A_FEL] = torch.where(m, moment + cd(FIXED_CD[A_FEL]), ready[:, A_FEL])

                # HAUNT
                m = can & (choice == A_HAUNT)
                if bool(m.any()):
                    # focus -> 0; spread -> first fresh else min until
                    # For batch: focus all to 0; spread pick per row
                    haunt_apply(m & (haunt_code < 0.5), hit_at, 0)
                    # spread
                    ms = m & (haunt_code > 0.5)
                    if bool(ms.any()):
                        # pick target: first with haunt_until <= hit_at else argmin
                        fresh = haunt_until <= hit_at.view(B, 1)
                        # first fresh index
                        idx_fresh = torch.where(fresh, torch.arange(Tt, device=device).view(1, Tt).expand(B, Tt), torch.full((B, Tt), Tt, device=device)).min(dim=1).values
                        idx_min = haunt_until.argmin(dim=1)
                        tgt = torch.where(idx_fresh < Tt, idx_fresh, idx_min)
                        for t in range(Tt):
                            haunt_apply(ms & (tgt == t), hit_at, t)
                    ready[:, A_HAUNT] = torch.where(m, moment + cd(FIXED_CD[A_HAUNT], haunt_flat), ready[:, A_HAUNT])

                # WRATH
                m = can & (choice == A_WRATH)
                if bool(m.any()):
                    wrath_until = torch.where(m, hit_at + float(mod.WRATH_DUR), wrath_until)
                    dem_wrath = torch.where((dem_alive & (dem_end > hit_at.view(B, 1))) & m.view(B, 1), hit_at.view(B, 1) + float(mod.WRATH_DUR), dem_wrath)
                    ready[:, A_WRATH] = torch.where(m, moment + cd(FIXED_CD[A_WRATH]), ready[:, A_WRATH])

                # CB
                m = can & (choice == A_CB)
                if bool(m.any()):
                    cb_buff_until = torch.where(m, hit_at + float(mod.CB_DUR), cb_buff_until)
                    ready[:, A_CB] = torch.where(m, moment + cd(FIXED_CD[A_CB]), ready[:, A_CB])

                # TAP
                m = can & (choice == A_TAP)
                if bool(m.any()):
                    hp = torch.where(m, hp - tap_value, hp)
                    gain(m, 0.40 * tap_value)
                    # guldan CDR
                    if bool((m & guldan).any()):
                        for k in range(N_ABIL):
                            if k == A_TAP:
                                continue
                            left = ready[:, k]
                            cut = 0.08 * cd(FIXED_CD[k])  # approx full_cd
                            ready[:, k] = torch.where(m & guldan & (left > hit_at), torch.maximum(hit_at, left - cut), ready[:, k])
                    ready[:, A_TAP] = torch.where(m, moment + cd(FIXED_CD[A_TAP]), ready[:, A_TAP])

                # SIPHON
                m = can & (choice == A_SIPHON)
                if bool(m.any()):
                    rate = immolate_rate(hit_at)
                    period = full(0.25) / rate
                    stop = hit_at + float(mod.SIPHON_CHANNEL)
                    for other in range(N_ABIL):
                        if other in (A_SIPHON, A_TAP):
                            continue
                        when = ready[:, other]
                        if other == A_WRATH:
                            when = torch.maximum(when, wrath_until - 1.0)
                        stop = torch.where(m & (order_en[:, other] > 0.5) & (when > hit_at), torch.minimum(stop, when), stop)
                    siphon_target = torch.where(m, torch.zeros_like(siphon_target), siphon_target)
                    siphon_until = torch.where(m, torch.maximum(hit_at + period, stop), siphon_until)
                    n = torch.floor((siphon_until - hit_at) / period + 1e-9).to(torch.int64)
                    max_n = int(n.max().item()) if bool(n.numel()) else 0
                    max_n = min(max_n, 64)
                    for i in range(max_n):
                        push_pend(m & (n > i), hit_at + (i + 1) * period, P_SIPHON)
                    busy = torch.where(m, torch.maximum(busy, siphon_until), busy)
                    ready[:, A_SIPHON] = torch.where(m, moment + cd(FIXED_CD[A_SIPHON]), ready[:, A_SIPHON])

                next_attack = torch.where(can, torch.maximum(next_attack, busy), next_attack)

        # AUTO
        if bool(is_auto.any()):
            now = torch.where(is_auto, attack_at, moment)
            recover(is_auto, now)
            white = WHITE + 0.75 * intel
            white = torch.where(wrath_on(now), white * (1.0 + float(mod.WRATH_DCS)), white)
            power = white + damage
            power = power + torch.where(drain_soul & (now < drain_until), full(5.0 + 5.0 * lvl), zeros)
            if bool((is_auto & (auto_pct != 1.0)).any()):
                raise _Overflow("auto_pct")
            dealt, dealt_pot, share = hero_hit(is_auto, N_AUTO, power, now, [0], magical=True, attack=True, pot_scale=attack_potency)
            havoc(is_auto, now, dealt, dealt_pot)
            agony_chance(is_auto, now, 0, 0.05 * luck_mult)
            backdraft_on_attack(is_auto, now, share, True, N_BACKDRAFT)
            # chaos bolt proc
            m = is_auto & has_cb & (now < cb_buff_until)
            if bool(m.any()):
                cb_buff_until = torch.where(m, full(-1.0), cb_buff_until)
                raw = (full(75.0) + 1.5 * dcs(now)) * (1.0 + 0.01 * crit0)
                raw = torch.where(chaotic, raw * 1.255, raw)
                cb_dealt, cb_dealt_pot, cb_share = hero_hit(m, N_CB, raw, now, [0], magical=False, attack=True, chaos=True)
                havoc(m, now, cb_dealt, cb_dealt_pot)
                backdraft_on_attack(m, now, cb_share, True, N_BACKDRAFT)
            gain(is_auto, amg)
            if bool(fire_orb.any()):
                splash = (full(20.0) + 0.35 * intel) * float(Tt) * taken(0, now, True)
                _push(torch, bufs, is_auto & fire_orb, now, splash, N_FIRE, KIND_EXEC)
                note_dmp(is_auto & fire_orb, float(Tt))
            if bool(sulfuras_on.any()):
                m = is_auto & sulfuras_on
                splash_fire = m & sulf_armed
                taken0 = taken(0, now, True)
                splash_w = intel * taken0 * float(Tt) * cf(hero_crit(now), 2.0 + rating0)
                _push(torch, bufs, splash_fire, now, splash_w, N_SULF, KIND_HERO_MAG)
                note_dmp(splash_fire, float(Tt))
                sulf_armed = torch.where(splash_fire, torch.zeros_like(sulf_armed), sulf_armed)
                _push(torch, bufs, m, now, power * taken0 * sulf_echo, N_SULF_ECHO, KIND_EXEC)
            next_attack = torch.where(is_auto, now + interval(now), next_attack)

    return _finalize(bufs, stats_list)
