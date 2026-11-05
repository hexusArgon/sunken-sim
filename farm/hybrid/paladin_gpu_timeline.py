# -*- coding: utf-8 -*-
"""GPU next-event timeline for Paladin (retribution / protection / holy).

Batched port of sunken_sim.paladin._fight_events. Hammer orbits use fixed-capacity
slots (MAX_HAMMERS). Clocks run float64 on CPU when DirectML lacks f64; kind-score
stays on DirectML. CPU _fight_events remains the parity oracle.
"""

from __future__ import annotations

from farm.hybrid.timeline_gpu import (
    SPEC_ECHO,
    SPEC_FLAT,
    SPEC_NONE,
    SPEC_SPLASH,
    cooldown_torch,
    make_event_buffers,
    pick_priority_clock,
)

# Priority = column order (matches CPU if-ladder after hammer hits / expire).
C_HHIT = 0
C_EXPIRE = 1
C_ATTACK = 2
C_CS = 3
C_HAMMER = 4
C_HOJ = 5
N_CLOCKS = 6

MAX_EVENTS = 512
MAX_STEPS = 200000
MAX_HAMMERS = 24  # divine hammer 12s + toll; 8 overflowed (~4 casts x2) mid-fight
MAX_ORBIT = 8


def _stat_vec(torch, device, dtype, stats_list, key, default=0.0):
    return torch.tensor([float(s.get(key, default)) for s in stats_list], dtype=dtype, device=device)


def _flag_vec(torch, device, dtype, builds, pred):
    return torch.tensor([1.0 if pred(b) else 0.0 for b in builds], dtype=dtype, device=device)


def buffers_to_paladin_events(bufs) -> list[list[tuple]]:
    """(when, name, raw, magical, count, pot_scale, mastery_now, auto_scale)."""
    when = bufs.when.detach().cpu().numpy()
    raw = bufs.raw.detach().cpu().numpy()
    magical = bufs.magical.detach().cpu().numpy()
    count = bufs.count.detach().cpu().numpy()
    pot = bufs.pot_scale.detach().cpu().numpy()
    mastery = bufs.mastery.detach().cpu().numpy()
    auto_pct = bufs.auto_pct.detach().cpu().numpy()  # auto_scale flag
    special = bufs.special.detach().cpu().numpy()
    length = bufs.length.detach().cpu().numpy()
    name_of = {
        SPEC_NONE: "",
        SPEC_SPLASH: "Всплеск огня",
        SPEC_ECHO: "Sulfuras (удар)",
        SPEC_FLAT: "Sulfuras",
    }
    out = []
    for b in range(when.shape[0]):
        n = int(length[b])
        evs = []
        for i in range(n):
            sp = int(special[b, i])
            name = name_of.get(sp, "")
            evs.append(
                (
                    float(when[b, i]),
                    name,
                    float(raw[b, i]),
                    bool(magical[b, i] >= 0.5),
                    int(round(float(count[b, i]))),
                    float(pot[b, i]),
                    float(mastery[b, i]),
                    bool(auto_pct[b, i] >= 0.5),
                )
            )
        out.append(evs)
    return out


def generate_paladin_timelines(torch, device, builds, spec: str, targets: int):
    """Return list[(events, stats, knowledge)] aligned with builds."""
    from sunken_sim import paladin as mod
    from sunken_sim.shadow import (
        CAST_BACKSWING,
        CAST_POINT,
        FIGHT,
        sulfuras_echo_chance,
    )

    if spec not in mod.SPECS:
        raise ValueError(spec)
    B = len(builds)
    if B == 0:
        return []

    dtype = torch.float64
    dev_type = getattr(device, "type", str(device))
    if dev_type in ("privateuseone", "dml") or "privateuseone" in str(device):
        device = torch.device("cpu")

    stats_list = [mod.stats_of(b) for b in builds]
    knowledge_list = [
        (
            1.0 + 0.003 * s["int"]
            if spec == "retribution" and mod._has(b, mod.TALENT_DIVINE_KNOWLEDGE)
            else 1.0
        )
        for b, s in zip(builds, stats_list)
    ]

    haste0 = _stat_vec(torch, device, dtype, stats_list, "haste")
    cd_temp = _stat_vec(torch, device, dtype, stats_list, "cd_temp", 1.0)
    flat_cdr = _stat_vec(torch, device, dtype, stats_list, "flat_cdr")
    mana_max = _stat_vec(torch, device, dtype, stats_list, "mana_max")
    mana_regen = _stat_vec(torch, device, dtype, stats_list, "mana_regen")
    cast_refund = _stat_vec(torch, device, dtype, stats_list, "cast_refund")
    cast_refund_flat = _stat_vec(torch, device, dtype, stats_list, "cast_refund_flat")
    cast_refund_mastery = _stat_vec(torch, device, dtype, stats_list, "cast_refund_mastery")
    cast_stun_lock = _stat_vec(torch, device, dtype, stats_list, "cast_stun_lock")
    damage_mana_pct = _stat_vec(torch, device, dtype, stats_list, "damage_mana_pct")
    str_ = _stat_vec(torch, device, dtype, stats_list, "str")
    int_ = _stat_vec(torch, device, dtype, stats_list, "int")
    damage = _stat_vec(torch, device, dtype, stats_list, "damage")
    mastery0 = _stat_vec(torch, device, dtype, stats_list, "mastery")
    attack_speed = _stat_vec(torch, device, dtype, stats_list, "attack_speed")
    attack_potency = _stat_vec(torch, device, dtype, stats_list, "attack_potency")
    luck = _stat_vec(torch, device, dtype, stats_list, "luck")
    stun_hit = _stat_vec(torch, device, dtype, stats_list, "stun_hit_damage")

    galactic = torch.tensor([1.0 if s["galactic"] else 0.0 for s in stats_list], dtype=dtype, device=device)
    judgement = torch.tensor([1.0 if s["judgement"] else 0.0 for s in stats_list], dtype=dtype, device=device)
    fire_orb = torch.tensor([1.0 if s["fire_orb"] else 0.0 for s in stats_list], dtype=dtype, device=device)
    bell = torch.tensor([1.0 if s["bell"] else 0.0 for s in stats_list], dtype=dtype, device=device)

    has_storm = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_DIVINE_STORM))
    has_divine_hammer = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_DIVINE_HAMMER))
    has_toll_talent = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_DIVINE_TOLL))
    has_zeal = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_ZEAL))
    has_hm = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_HAMMER_MASTERY))
    has_hoj = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_HAMMER_OF_JUSTICE))
    has_crusade = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_CRUSADE))
    has_sulfuras = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I0BR"))

    toll = torch.where(
        (has_toll_talent > 0.5) | (bell > 0.5),
        0.25 * (1.0 + luck),
        torch.zeros(B, dtype=dtype, device=device),
    )
    hammer_duration = torch.where(has_divine_hammer > 0.5, torch.full((B,), 12.0, dtype=dtype, device=device), torch.full((B,), 9.0, dtype=dtype, device=device))
    # pulse 150 if divine hammer else 100 — pick orbit row per build
    orbit_key = has_divine_hammer  # 1 -> (12,150), 0 -> (9,100)
    orbit_a = list(mod._ORBIT[(9.0, 100.0)])
    orbit_b = list(mod._ORBIT[(12.0, 150.0)])
    while len(orbit_a) < MAX_ORBIT:
        orbit_a.append(1e9)
    while len(orbit_b) < MAX_ORBIT:
        orbit_b.append(1e9)
    orbit_a = orbit_a[:MAX_ORBIT]
    orbit_b = orbit_b[:MAX_ORBIT]
    orbit_tbl = torch.tensor(
        [orbit_b if float(orbit_key[i]) > 0.5 else orbit_a for i in range(B)],
        dtype=dtype,
        device=device,
    )  # [B, MAX_ORBIT]
    orbit_len = torch.tensor(
        [len(mod._ORBIT[(12.0, 150.0)]) if float(orbit_key[i]) > 0.5 else len(mod._ORBIT[(9.0, 100.0)]) for i in range(B)],
        dtype=torch.int64,
        device=device,
    )

    is_ret = spec == "retribution"
    rank = float(mod.RANK)
    fight = float(FIGHT)
    cast_time = float(CAST_POINT + CAST_BACKSWING)
    targets_f = float(targets)
    white = float(mod.WHITE_BASE)

    # hammer slots
    h_active = torch.zeros((B, MAX_HAMMERS), dtype=torch.bool, device=device)
    h_start = torch.zeros((B, MAX_HAMMERS), dtype=dtype, device=device)
    h_end = torch.zeros((B, MAX_HAMMERS), dtype=dtype, device=device)
    h_next = torch.full((B, MAX_HAMMERS), fight, dtype=dtype, device=device)
    h_weight = torch.zeros((B, MAX_HAMMERS), dtype=dtype, device=device)
    h_index = torch.zeros((B, MAX_HAMMERS), dtype=torch.int64, device=device)

    clocks = torch.zeros((B, N_CLOCKS), dtype=dtype, device=device)
    clocks[:, C_HHIT] = fight
    clocks[:, C_EXPIRE] = fight
    clocks[:, C_HOJ] = torch.where(has_hoj > 0.5, torch.zeros(B, dtype=dtype, device=device), torch.full((B,), fight, dtype=dtype, device=device))

    busy = torch.zeros(B, dtype=dtype, device=device)
    mana = mana_max.clone()
    mana_time = torch.zeros(B, dtype=dtype, device=device)
    haste = haste0.clone()
    mastery_bonus = torch.zeros(B, dtype=dtype, device=device)
    zeal_charges = torch.zeros(B, dtype=torch.int64, device=device)
    zeal_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    cs_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    fury_attacks = torch.zeros(B, dtype=torch.int64, device=device)
    crusade = torch.zeros(B, dtype=torch.int64, device=device)
    sulf_armed = torch.zeros(B, dtype=dtype, device=device)
    alive = torch.ones(B, dtype=torch.bool, device=device)

    bufs = make_event_buffers(torch, device, B, MAX_EVENTS, dtype=dtype)

    def cur_mastery():
        return mastery0 + mastery_bonus

    def recover(now, mask):
        nonlocal mana, mana_time
        dt = torch.clamp(now - mana_time, min=0.0)
        room = torch.clamp(mana_max - mana, min=0.0)
        gain = torch.minimum(room, mana_regen * dt)
        mana = torch.where(mask, mana + gain, mana)
        mana_time = torch.where(mask, torch.maximum(mana_time, now), mana_time)

    def mana_back(cost):
        return cost * cast_refund + cast_refund_flat + cast_refund_mastery * cur_mastery()

    def try_pay(cost, now, mask):
        nonlocal mana
        recover(now, mask)
        can = mask & (mana >= cost)
        paid = mana - cost + mana_back(torch.full_like(mana, float(cost)))
        mana = torch.where(can, torch.minimum(mana_max, paid), mana)
        return can

    def note_dmg_mana(count, mask):
        nonlocal mana
        if float(damage_mana_pct.max()) <= 0:
            return
        add = damage_mana_pct * mana_max * float(count)
        mana = torch.where(mask, torch.minimum(mana_max, mana + add), mana)

    def do_cast(now, mask):
        nonlocal busy, sulf_armed, zeal_charges, zeal_until
        sulf_armed = torch.where(
            mask & (has_sulfuras > 0.5) & (sulf_armed < 0.5),
            torch.ones_like(sulf_armed),
            sulf_armed,
        )
        busy = torch.where(mask, now + cast_time + cast_stun_lock, busy)
        # zeal on any cast
        zeal_on = mask & (has_zeal > 0.5)
        zeal_charges = torch.where(zeal_on, torch.full_like(zeal_charges, 2), zeal_charges)
        zeal_until = torch.where(zeal_on, now + 4.0, zeal_until)

    def hammer_count(now):
        # sum weight where start <= now < end
        active = h_active & (h_start <= now.unsqueeze(1)) & (now.unsqueeze(1) < h_end)
        return (h_weight * active.to(dtype)).sum(dim=1)

    def refresh_hammer_clocks():
        # next hit among active with next < end
        valid = h_active & (h_next < h_end)
        nxt = torch.where(valid, h_next, torch.full_like(h_next, fight))
        clocks[:, C_HHIT] = nxt.min(dim=1).values
        endv = torch.where(h_active, h_end, torch.full_like(h_end, fight))
        clocks[:, C_EXPIRE] = endv.min(dim=1).values
        # if no hammers, both stay fight
        any_h = h_active.any(dim=1)
        clocks[:, C_HHIT] = torch.where(any_h, clocks[:, C_HHIT], torch.full((B,), fight, dtype=dtype, device=device))
        clocks[:, C_EXPIRE] = torch.where(any_h, clocks[:, C_EXPIRE], torch.full((B,), fight, dtype=dtype, device=device))

    def spawn(now, weight, mask):
        nonlocal h_active, h_start, h_end, h_next, h_weight, h_index
        want = mask & (weight > 0)
        if not bool(want.any()):
            return
        # first free slot per row
        free = ~h_active
        # pick lowest index free
        prio = torch.arange(MAX_HAMMERS, device=device, dtype=dtype).view(1, MAX_HAMMERS).expand(B, -1)
        prio = torch.where(free, prio, torch.full_like(prio, float(MAX_HAMMERS + 1)))
        slot = prio.argmin(dim=1)
        has_free = free.any(dim=1) & want
        rows = torch.arange(B, device=device)
        # first orbit hit offset
        first = orbit_tbl[rows, 0]
        # write
        for i in range(B):
            if not bool(has_free[i]):
                continue
            s = int(slot[i])
            h_active[i, s] = True
            h_start[i, s] = now[i]
            h_end[i, s] = now[i] + hammer_duration[i]
            h_next[i, s] = now[i] + first[i]
            h_weight[i, s] = weight[i] if isinstance(weight, torch.Tensor) else float(weight)
            h_index[i, s] = 0
        refresh_hammer_clocks()

    def push(mask, when, raw, *, magical=0.0, count=1.0, pot_scale=1.0, auto_scale=0.0, special=SPEC_NONE):
        bufs.push_mask(
            torch,
            mask,
            when,
            raw,
            magical=magical,
            count=count,
            pot_scale=pot_scale,
            auto=0.0,
            mastery=cur_mastery(),
            enraged=0.0,
            auto_pct=auto_scale,
            special=special,
        )

    def attack_mana_gain_vec():
        from sunken_sim.shadow import attack_mana_gain as _amg
        # use stats dicts on CPU for exact parity
        return torch.tensor([_amg(s) for s in stats_list], dtype=dtype, device=device)

    amg = attack_mana_gain_vec()

    refresh_hammer_clocks()
    steps = 0
    while bool(alive.any()) and steps < MAX_STEPS:
        steps += 1
        refresh_hammer_clocks()
        moment, which, active = pick_priority_clock(clocks, busy, fight)
        alive = active
        if not bool(alive.any()):
            break

        # Rows that already took hammer-hit / expire this step must not also cast.
        handled = torch.zeros(B, dtype=torch.bool, device=device)

        # --- hammer hits (priority over busy) ---
        m_hit = alive & (which == C_HHIT)
        if bool(m_hit.any()):
            recover(moment, m_hit)
            due = h_active & (h_next <= moment.unsqueeze(1) + 1e-9) & (moment.unsqueeze(1) < h_end)
            due = due & m_hit.unsqueeze(1)
            if bool(due.any()):
                for s in range(MAX_HAMMERS):
                    slot_due = due[:, s]
                    if not bool(slot_due.any()):
                        continue
                    w = h_weight[:, s]
                    raw = (5.0 + 10.0 * rank + 0.45 * str_) * w
                    push(slot_due, moment, raw, magical=1.0, count=targets_f)
                    note_dmg_mana(targets, slot_due)
                    h_index[:, s] = torch.where(slot_due, h_index[:, s] + 1, h_index[:, s])
                    idx = h_index[:, s].clamp(max=MAX_ORBIT - 1)
                    rows = torch.arange(B, device=device)
                    next_off = orbit_tbl[rows, idx]
                    still = h_index[:, s] < orbit_len
                    new_next = torch.where(
                        still,
                        h_start[:, s] + next_off,
                        h_end[:, s],
                    )
                    h_next[:, s] = torch.where(slot_due, new_next, h_next[:, s])
                    if float(has_hm.max()) > 0:
                        add = 2.0 * w * targets_f
                        mastery_bonus = torch.where(
                            slot_due & (has_hm > 0.5),
                            torch.minimum(torch.full_like(mastery_bonus, 30.0), mastery_bonus + add),
                            mastery_bonus,
                        )
                    if float(has_hoj.max()) > 0:
                        cut = 0.10 * w * targets_f
                        clocks[:, C_HOJ] = torch.where(
                            slot_due & (has_hoj > 0.5),
                            torch.maximum(moment, clocks[:, C_HOJ] - cut),
                            clocks[:, C_HOJ],
                        )
                h_active = torch.where(
                    m_hit.unsqueeze(1),
                    h_active & (h_end > moment.unsqueeze(1) + 1e-9),
                    h_active,
                )
            handled = handled | m_hit

        # --- expire ---
        m_exp = alive & (which == C_EXPIRE) & ~handled
        if bool(m_exp.any()):
            h_active = torch.where(
                m_exp.unsqueeze(1),
                h_active & (h_end > moment.unsqueeze(1) + 1e-9),
                h_active,
            )
            handled = handled | m_exp

        # --- busy defer (only unhandled rows) ---
        in_busy = alive & ~handled & (moment < busy)
        if bool(in_busy.any()):
            for col in (C_ATTACK, C_CS, C_HAMMER, C_HOJ):
                hit = in_busy & (which == col)
                if bool(hit.any()):
                    clocks[:, col] = torch.where(hit, busy, clocks[:, col])
            alive_actions = alive & ~handled & ~in_busy
        else:
            alive_actions = alive & ~handled

        if not bool(alive_actions.any()):
            continue

        # --- auto attack ---
        m_at = alive_actions & (which == C_ATTACK)
        if bool(m_at.any()):
            recover(moment, m_at)
            hc = hammer_count(moment)
            swing = float(mod.SWING) * torch.where(galactic > 0.5, torch.full_like(galactic, 1.20), torch.ones_like(galactic))
            if is_ret:
                swing = swing * torch.clamp(1.0 - 0.03 * hc, min=0.2)
            speed = attack_speed.clone()
            zeal_hit = (zeal_charges > 0) & (moment <= zeal_until) & m_at
            speed = torch.where(zeal_hit, torch.clamp(speed + 0.80, max=4.0), speed)
            zeal_charges = torch.where(zeal_hit, zeal_charges - 1, zeal_charges)
            interval = swing / (1.0 + speed)

            # Crusader Strike consume
            cs_hit = m_at & (cs_until >= moment)
            if bool(cs_hit.any()):
                raw = 90.0 * rank + 30.0 + 2.75 * str_
                if is_ret:
                    raw = raw * (1.10 + 0.01 * cur_mastery())
                raw = raw * torch.where(judgement > 0.5, 1.0 + 0.05 * hc, torch.ones_like(raw))
                push(cs_hit, moment, raw, magical=1.0, count=1.0)
                note_dmg_mana(1, cs_hit)
                cs_until = torch.where(cs_hit, torch.full_like(cs_until, -1.0), cs_until)
                # Divine Storm
                storm_m = cs_hit & (has_storm > 0.5)
                if bool(storm_m.any()):
                    storm = 20.0 + str_ + int_ + cur_mastery()
                    if not is_ret:
                        storm = storm * 0.5
                    push(storm_m, moment, storm, magical=1.0, count=targets_f)
                    note_dmg_mana(targets, storm_m)

            # white
            white_raw = white + 0.75 * str_ + damage
            push(m_at, moment, white_raw, magical=0.0, count=1.0, pot_scale=attack_potency, auto_scale=1.0)
            mana = torch.where(m_at, torch.minimum(mana_max, mana + amg), mana)
            note_dmg_mana(1, m_at)
            fury_attacks = torch.where(m_at, fury_attacks + 1, fury_attacks)
            # Righteous Fury if no HoJ
            rf = m_at & (has_hoj < 0.5) & (fury_attacks >= 3)
            if bool(rf.any()):
                fury_attacks = torch.where(rf, torch.zeros_like(fury_attacks), fury_attacks)
                push(rf, moment, 5.0 + 25.0 * rank + 2.0 * str_, magical=1.0, count=1.0)
                note_dmg_mana(1, rf)
            # fire orb
            fo = m_at & (fire_orb > 0.5)
            if bool(fo.any()):
                push(fo, moment, 20.0 + 0.35 * str_, magical=0.0, count=targets_f, pot_scale=0.0, special=SPEC_SPLASH)
                note_dmg_mana(targets, fo)
            # sulfuras
            sul = m_at & (has_sulfuras > 0.5)
            if bool(sul.any()):
                fire = sul & (sulf_armed > 0.5)
                if bool(fire.any()):
                    push(fire, moment, str_, magical=1.0, count=targets_f, pot_scale=0.0, special=SPEC_FLAT)
                    note_dmg_mana(targets, fire)
                    sulf_armed = torch.where(fire, torch.zeros_like(sulf_armed), sulf_armed)
                echo_ch = torch.tensor(
                    [sulfuras_echo_chance(float(luck[i])) for i in range(B)],
                    dtype=dtype,
                    device=device,
                )
                push(sul, moment, white_raw * echo_ch, magical=0.0, count=1.0, pot_scale=0.0, special=SPEC_ECHO)
            # crusade
            cr = m_at & (has_crusade > 0.5) & (crusade < 20)
            if bool(cr.any()):
                crusade = torch.where(cr, torch.minimum(torch.full_like(crusade, 20), crusade + 2), crusade)
                haste = torch.where(cr, haste0 + crusade.to(dtype) / 100.0, haste)

            clocks[:, C_ATTACK] = torch.where(m_at, moment + interval, clocks[:, C_ATTACK])

        # --- Crusader Strike cast ---
        m_cs = alive_actions & (which == C_CS)
        if bool(m_cs.any()):
            ok = try_pay(float(mod.CS_MANA), moment, m_cs)
            fail = m_cs & ~ok
            clocks[:, C_CS] = torch.where(fail, moment + 0.25, clocks[:, C_CS])
            if bool(ok.any()):
                cs_until = torch.where(ok, moment + float(mod.CS_BUFF), cs_until)
                do_cast(moment, ok)
                cd = cooldown_torch(float(mod.CS_COOLDOWN), haste, cd_temp, flat_cdr)
                clocks[:, C_CS] = torch.where(ok, moment + cd, clocks[:, C_CS])
                clocks[:, C_ATTACK] = torch.where(ok, torch.maximum(clocks[:, C_ATTACK], busy), clocks[:, C_ATTACK])

        # --- Blessed Hammer cast ---
        m_hm = alive_actions & (which == C_HAMMER)
        if bool(m_hm.any()):
            ok = try_pay(float(mod.HAMMER_MANA), moment, m_hm)
            fail = m_hm & ~ok
            clocks[:, C_HAMMER] = torch.where(fail, moment + 0.25, clocks[:, C_HAMMER])
            if bool(ok.any()):
                spawn_at = moment + float(CAST_POINT)
                ones = torch.ones(B, dtype=dtype, device=device)
                spawn(spawn_at, ones, ok)
                toll_m = ok & (toll > 0)
                if bool(toll_m.any()):
                    spawn(spawn_at + 0.5, toll, toll_m)
                do_cast(moment, ok)
                cd = cooldown_torch(float(mod.HAMMER_COOLDOWN), haste, cd_temp, flat_cdr)
                clocks[:, C_HAMMER] = torch.where(ok, moment + cd, clocks[:, C_HAMMER])
                clocks[:, C_ATTACK] = torch.where(ok, torch.maximum(clocks[:, C_ATTACK], busy), clocks[:, C_ATTACK])

        # --- Hammer of Justice ---
        m_hoj = alive_actions & (which == C_HOJ) & (has_hoj > 0.5)
        if bool(m_hoj.any()):
            ok = try_pay(float(mod.HOJ_MANA), moment, m_hoj)
            fail = m_hoj & ~ok
            clocks[:, C_HOJ] = torch.where(fail, moment + 0.25, clocks[:, C_HOJ])
            if bool(ok.any()):
                raw = (60.0 + 1.75 * str_) * (1.0 + 0.01 * int_)
                push(ok, moment, raw, magical=1.0, count=1.0)
                stun_m = ok & (stun_hit > 0)
                if bool(stun_m.any()):
                    push(stun_m, moment, stun_hit, magical=0.0, count=1.0, pot_scale=0.0)
                do_cast(moment, ok)
                cd = cooldown_torch(float(mod.HOJ_COOLDOWN), haste, cd_temp, flat_cdr)
                clocks[:, C_HOJ] = torch.where(ok, moment + cd, clocks[:, C_HOJ])
                clocks[:, C_ATTACK] = torch.where(ok, torch.maximum(clocks[:, C_ATTACK], busy), clocks[:, C_ATTACK])

    events_list = buffers_to_paladin_events(bufs)
    return list(zip(events_list, stats_list, knowledge_list))
