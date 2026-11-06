# -*- coding: utf-8 -*-
"""GPU next-event timeline for Warrior (protection / arms / fury).

Faithful port of sunken_sim.warrior.simulate's discrete-event loop onto a
batched DirectML/torch state machine (one row per build). Emits the same
event tuples the existing farm.hybrid.warrior kind-score path consumes.

CPU simulate() remains the parity oracle (rel/abs <= 1e-4).
"""

from __future__ import annotations

from farm.hybrid.timeline_gpu import (
    SPEC_ECHO,
    SPEC_NONE,
    SPEC_SPLASH,
    buffers_to_warrior_events,
    cooldown_torch,
    make_event_buffers,
    pick_priority_clock,
)

# Clock columns (priority order = index).
C_SHOUT = 0
C_WW = 1
C_BT = 2
C_DEMO = 3
C_ATTACK = 4
N_CLOCKS = 5

MAX_EVENTS = 512
MAX_STEPS = 200000


def _stat_vec(torch, device, dtype, builds, stats_list, key, default=0.0):
    vals = [float(s.get(key, default)) for s in stats_list]
    return torch.tensor(vals, dtype=dtype, device=device)


def _flag_vec(torch, device, dtype, builds, pred) -> "torch.Tensor":
    return torch.tensor([1.0 if pred(b) else 0.0 for b in builds], dtype=dtype, device=device)


def generate_warrior_timelines(torch, device, builds, spec: str, targets: int):
    """Run GPU timeline for a batch of warrior builds.

    Returns list[(events, stats, taken, taken_auto)] aligned with builds.
    """
    from sunken_sim import warrior as mod
    from sunken_sim.shadow import (
        CAST_BACKSWING,
        CAST_POINT,
        DUMMY_ARMOR,
        FIGHT,
        armor_taken,
        cast_mana_back,
        sulfuras_echo_chance,
    )

    if spec not in mod.SPECS:
        raise ValueError(spec)
    B = len(builds)
    if B == 0:
        return []

    # float64 clocks match the CPU oracle's ULP-sensitive priority ties.
    # DirectML (privateuseone) has no reliable f64 path — run the state machine
    # on CPU float64; kind-score still runs on the caller's DirectML device.
    dtype = torch.float64
    dev_type = getattr(device, "type", str(device))
    if dev_type in ("privateuseone", "dml") or "privateuseone" in str(device):
        device = torch.device("cpu")

    stats_list = [mod.stats_of(b) for b in builds]
    taken_list = []
    taken_auto_list = []
    for build, stats in zip(builds, stats_list):
        sunder_extra = 0.0
        if mod._has(build, mod.TALENT_SUNDER):
            if spec in ("fury", "arms"):
                sunder_extra = 2.0
        armor_pen = stats["armor_pen"] + (sunder_extra if spec == "arms" else 0.0)
        taken_list.append(armor_taken(DUMMY_ARMOR - armor_pen))
        taken_auto_list.append(
            armor_taken(DUMMY_ARMOR - armor_pen - (sunder_extra if spec == "fury" else 0.0))
        )

    # --- upload stats ---
    haste = _stat_vec(torch, device, dtype, builds, stats_list, "haste")
    cd_temp = _stat_vec(torch, device, dtype, builds, stats_list, "cd_temp", 1.0)
    flat_cdr = _stat_vec(torch, device, dtype, builds, stats_list, "flat_cdr")
    mana_max = _stat_vec(torch, device, dtype, builds, stats_list, "mana_max")
    mana_regen = _stat_vec(torch, device, dtype, builds, stats_list, "mana_regen")
    cast_refund = _stat_vec(torch, device, dtype, builds, stats_list, "cast_refund")
    cast_refund_flat = _stat_vec(torch, device, dtype, builds, stats_list, "cast_refund_flat")
    cast_refund_mastery = _stat_vec(torch, device, dtype, builds, stats_list, "cast_refund_mastery")
    cast_stun_lock = _stat_vec(torch, device, dtype, builds, stats_list, "cast_stun_lock")
    damage_mana_pct = _stat_vec(torch, device, dtype, builds, stats_list, "damage_mana_pct")
    str_ = _stat_vec(torch, device, dtype, builds, stats_list, "str")
    damage = _stat_vec(torch, device, dtype, builds, stats_list, "damage")
    mastery = _stat_vec(torch, device, dtype, builds, stats_list, "mastery")
    attack_speed = _stat_vec(torch, device, dtype, builds, stats_list, "attack_speed")
    attack_potency = _stat_vec(torch, device, dtype, builds, stats_list, "attack_potency")
    auto_pct = _stat_vec(torch, device, dtype, builds, stats_list, "auto_pct", 1.0)
    hp = _stat_vec(torch, device, dtype, builds, stats_list, "hp")
    luck = _stat_vec(torch, device, dtype, builds, stats_list, "luck")
    potency = _stat_vec(torch, device, dtype, builds, stats_list, "potency")  # unused in event raw

    has_warcry = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_WARCRY))
    has_double = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_DOUBLE_TIME))
    has_pain = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_PAIN_TRAIN))
    has_shock = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_SHOCKWAVE))
    has_blade = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_BLADESTORM))
    has_sulfuras = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I0BR"))
    ww_item = torch.tensor(
        [1.0 if s["ww_item"] else 0.0 for s in stats_list], dtype=dtype, device=device
    )
    bt_item = torch.tensor(
        [1.0 if s["bt_item"] else 0.0 for s in stats_list], dtype=dtype, device=device
    )
    galactic = torch.tensor(
        [1.0 if s["galactic"] else 0.0 for s in stats_list], dtype=dtype, device=device
    )
    titans = torch.tensor(
        [1.0 if s["titans_grip"] else 0.0 for s in stats_list], dtype=dtype, device=device
    )
    fire_orb = torch.tensor(
        [1.0 if s["fire_orb"] else 0.0 for s in stats_list], dtype=dtype, device=device
    )
    weapons_master = torch.tensor(
        [1.0 if s["weapons_master"] else 0.0 for s in stats_list], dtype=dtype, device=device
    )

    is_arms = spec == "arms"
    is_fury = spec == "fury"
    is_prot = spec == "protection"
    rank = float(mod.RANK)
    fight = float(FIGHT)
    cast_time = float(CAST_POINT + CAST_BACKSWING)
    targets_f = float(targets)

    shout_cd_base = float(mod.SHOUT_CD) - (2.0 if is_prot else 0.0)
    demo_cd_base = float(mod.DEMO_CD) - (2.0 if is_prot else 0.0)
    mastery_mult = torch.where(weapons_master > 0.5, torch.full_like(weapons_master, 1.40), torch.ones_like(weapons_master))

    def arms_mastery_mult():
        if not is_arms:
            return torch.ones(B, device=device)
        return 1.0 + (0.10 + 0.006 * mastery) * mastery_mult

    # clocks: shout, ww, bt, demo, attack
    clocks = torch.zeros((B, N_CLOCKS), dtype=dtype, device=device)
    if not is_arms:
        clocks[:, C_DEMO] = fight  # disabled
    busy = torch.zeros(B, dtype=dtype, device=device)
    mana = mana_max.clone()
    mana_time = torch.zeros(B, dtype=dtype, device=device)
    shout_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    enrage_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    bt_extra = torch.zeros(B, dtype=dtype, device=device)
    ww_on_cd_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    enrage_attacks = torch.zeros(B, dtype=torch.int64, device=device)
    sulf_armed = torch.zeros(B, dtype=dtype, device=device)
    alive = torch.ones(B, dtype=torch.bool, device=device)

    bufs = make_event_buffers(torch, device, B, MAX_EVENTS, dtype=dtype)

    def recover(now, mask):
        nonlocal mana, mana_time
        dt = torch.clamp(now - mana_time, min=0.0)
        room = torch.clamp(mana_max - mana, min=0.0)
        gain = torch.minimum(room, mana_regen * dt)
        mana = torch.where(mask, mana + gain, mana)
        mana_time = torch.where(mask, torch.maximum(mana_time, now), mana_time)

    def mana_back(cost):
        return cost * cast_refund + cast_refund_flat + cast_refund_mastery * mastery

    def try_pay(cost, now, mask):
        """Pay mana for masked rows. Returns success mask (subset of mask)."""
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
        nonlocal busy, sulf_armed
        # arm sulfuras on cast
        sulf_armed = torch.where(mask & (has_sulfuras > 0.5) & (sulf_armed < 0.5), torch.ones_like(sulf_armed), sulf_armed)
        # if already armed, cast() is no-op (does not refresh) — matches Sulfuras.cast
        new_busy = now + cast_time + cast_stun_lock
        busy = torch.where(mask, new_busy, busy)

    def dcs(now):
        value = float(mod.WHITE_BASE) + 0.75 * str_ + damage
        shout_on = now < shout_until
        bonus = torch.where(has_warcry > 0.5, torch.full_like(value, 15.0 + 20.0 * rank), torch.full_like(value, 10.0 + 15.0 * rank))
        return value + torch.where(shout_on, bonus, torch.zeros_like(value))

    def push_deal(mask, when, raw, *, magical=0.0, count=1.0, pot_scale=1.0, auto=0.0, auto_pct_scale=0.0):
        enr = (when < enrage_until).to(torch.float32)
        bufs.push_mask(
            torch,
            mask,
            when,
            raw,
            magical=magical,
            count=count,
            pot_scale=pot_scale,
            auto=auto,
            mastery=mastery,
            enraged=enr,
            auto_pct=auto_pct_scale,
            special=SPEC_NONE,
        )

    def attack_interval(now):
        swing = float(mod.SWING) * torch.where(galactic > 0.5, torch.full_like(galactic, 1.20), torch.ones_like(galactic))
        speed = attack_speed.clone()
        if is_fury:
            enr = now < enrage_until
            speed = torch.where(enr, torch.clamp(speed + 0.15, max=4.0), speed)
        # titans grip: fixed swing
        return torch.where(titans > 0.5, swing, swing / (1.0 + speed))

    def titans_mult(now):
        speed = attack_speed.clone()
        if is_fury:
            enr = now < enrage_until
            speed = torch.where(enr, torch.clamp(speed + 0.15, max=4.0), speed)
        return torch.where(titans > 0.5, 1.0 + speed, torch.ones_like(speed))

    def apply_cd(base, mask, flat=0.0):
        cd = cooldown_torch(base, haste, cd_temp, flat_cdr, flat)
        cd = torch.where(has_double > 0.5, cd * 0.80, cd)
        return cd

    steps = 0
    while bool(alive.any()) and steps < MAX_STEPS:
        steps += 1
        moment, which, active = pick_priority_clock(clocks, busy, fight)
        alive = active
        if not bool(alive.any()):
            break

        # Defer clocks that fire during busy (match CPU: set that clock to busy, continue)
        in_busy = alive & (moment < busy)
        if bool(in_busy.any()):
            for col in range(N_CLOCKS):
                hit = in_busy & (which == col)
                if bool(hit.any()):
                    clocks[:, col] = torch.where(hit, busy, clocks[:, col])
            # After defer, loop again (CPU continues). Skip action this step for those rows
            # by marking them inactive for action handling below.
            alive_actions = alive & ~in_busy
        else:
            alive_actions = alive

        if not bool(alive_actions.any()):
            continue

        # --- Battle Shout ---
        m_shout = alive_actions & (which == C_SHOUT)
        if bool(m_shout.any()):
            ok = try_pay(float(mod.SHOUT_MANA), moment, m_shout)
            fail = m_shout & ~ok
            clocks[:, C_SHOUT] = torch.where(fail, moment + 0.25, clocks[:, C_SHOUT])
            if bool(ok.any()):
                shout_until = torch.where(ok, moment + float(CAST_POINT) + float(mod.SHOUT_DUR), shout_until)
                do_cast(moment, ok)
                cd = apply_cd(shout_cd_base, ok)
                clocks[:, C_SHOUT] = torch.where(ok, moment + cd, clocks[:, C_SHOUT])
                clocks[:, C_ATTACK] = torch.where(ok, torch.maximum(clocks[:, C_ATTACK], busy), clocks[:, C_ATTACK])

        # --- Whirlwind ---
        m_ww = alive_actions & (which == C_WW)
        if bool(m_ww.any()):
            ok = try_pay(float(mod.WW_MANA), moment, m_ww)
            fail = m_ww & ~ok
            clocks[:, C_WW] = torch.where(fail, moment + 0.25, clocks[:, C_WW])
            if bool(ok.any()):
                hit_at = moment + float(CAST_POINT)
                power = dcs(hit_at)
                raw = (65.0 * rank - 10.0) + 0.75 * power
                raw = raw + torch.where(has_pain > 0.5, 0.50 * str_, torch.zeros_like(raw))
                raw = raw * arms_mastery_mult()
                raw = raw * torch.where(ww_item > 0.5, torch.full_like(raw, 1.25), torch.ones_like(raw))
                push_deal(ok, hit_at, raw, magical=0.0, count=targets_f)
                note_dmg_mana(targets, ok)
                do_cast(moment, ok)
                cd = apply_cd(float(mod.WW_CD), ok)
                clocks[:, C_WW] = torch.where(ok, moment + cd, clocks[:, C_WW])
                ww_on_cd_until = torch.where(ok, moment + cd, ww_on_cd_until)
                clocks[:, C_ATTACK] = torch.where(ok, torch.maximum(clocks[:, C_ATTACK], busy), clocks[:, C_ATTACK])

        # --- Bloodthirst ---
        m_bt = alive_actions & (which == C_BT)
        if bool(m_bt.any()):
            ok = try_pay(float(mod.BT_MANA), moment, m_bt)
            fail = m_bt & ~ok
            clocks[:, C_BT] = torch.where(fail, moment + 0.25, clocks[:, C_BT])
            if bool(ok.any()):
                hit_at = moment + float(CAST_POINT)
                power = dcs(hit_at)
                raw = 75.0 * rank + 0.50 * power + 0.05 * hp
                raw = raw + torch.where(has_pain > 0.5, 0.75 * str_, torch.zeros_like(raw))
                raw = raw * arms_mastery_mult()
                push_deal(ok, hit_at, raw, magical=0.0, count=1.0)
                note_dmg_mana(1, ok)
                # Shockwave
                sw = ok & (has_shock > 0.5)
                if bool(sw.any()):
                    wave_raw = 0.15 * raw
                    sw_count = float(max(1, targets - 1))
                    push_deal(sw, hit_at, wave_raw, magical=0.0, count=sw_count)
                    note_dmg_mana(max(1, targets - 1), sw)
                bt_extra = torch.where(ok, torch.ones_like(bt_extra), bt_extra)
                do_cast(moment, ok)
                cd = apply_cd(float(mod.BT_CD), ok)
                clocks[:, C_BT] = torch.where(ok, moment + cd, clocks[:, C_BT])
                clocks[:, C_ATTACK] = torch.where(ok, torch.maximum(clocks[:, C_ATTACK], busy), clocks[:, C_ATTACK])

        # --- Demo (arms only) ---
        m_demo = alive_actions & (which == C_DEMO)
        if is_arms and bool(m_demo.any()):
            ok = try_pay(float(mod.DEMO_MANA), moment, m_demo)
            fail = m_demo & ~ok
            clocks[:, C_DEMO] = torch.where(fail, moment + 0.25, clocks[:, C_DEMO])
            if bool(ok.any()):
                hit_at = moment + float(CAST_POINT)
                power = dcs(hit_at)
                raw = 20.0 + 0.25 * power + 0.05 * hp
                push_deal(ok, hit_at, raw, magical=0.0, count=targets_f)
                note_dmg_mana(targets, ok)
                do_cast(moment, ok)
                cd = apply_cd(demo_cd_base, ok)
                clocks[:, C_DEMO] = torch.where(ok, moment + cd, clocks[:, C_DEMO])
                clocks[:, C_ATTACK] = torch.where(ok, torch.maximum(clocks[:, C_ATTACK], busy), clocks[:, C_ATTACK])

        # --- Auto attack ---
        m_atk = alive_actions & (which == C_ATTACK)
        if bool(m_atk.any()):
            recover(moment, m_atk)
            power = dcs(moment)
            auto_raw = power * titans_mult(moment)
            # auto deal with pot_scale=attack_potency, auto=True, auto_pct_scale=True
            # For scoring, auto_pct is applied via auto_pct_scale flag * stats["auto_pct"]
            # CPU always passes auto_pct_scale=True for white hits.
            push_deal(
                m_atk,
                moment,
                auto_raw,
                magical=0.0,
                count=1.0,
                pot_scale=attack_potency,
                auto=1.0,
                auto_pct_scale=1.0,
            )
            atk_idx = torch.nonzero(m_atk, as_tuple=False).view(-1).tolist()
            from sunken_sim.shadow import attack_mana_gain

            for i in atk_idx:
                s = stats_list[i]
                mana[i] = min(float(mana_max[i]), float(mana[i]) + attack_mana_gain(s))
            note_dmg_mana(1, m_atk)

            # Unbaked cleave before the enrage proc, matching CPU order.
            if targets > 1:
                cleave_chance = (30.0 + 5.0 * rank) / 100.0 * (1.0 + luck)
                cleave_ratio = 0.40 + torch.where(
                    moment < ww_on_cd_until,
                    torch.full_like(moment, 0.10),
                    torch.zeros_like(moment),
                )
                scale = cleave_chance * cleave_ratio
                do_cleave = m_atk & (scale > 0)
                if bool(do_cleave.any()):
                    push_deal(
                        do_cleave,
                        moment,
                        auto_raw * scale,
                        magical=0.0,
                        count=float(targets - 1),
                        pot_scale=attack_potency * scale,
                        auto=1.0,
                        auto_pct_scale=1.0,
                    )
                    note_dmg_mana(targets - 1, do_cleave)

            enrage_attacks = enrage_attacks + m_atk.to(enrage_attacks.dtype)
            proc = m_atk & ((enrage_attacks % 10) == 0)
            enrage_until = torch.where(proc, moment + float(mod.ENRAGE_DUR), enrage_until)

            # bt_extra / orbs / sulfuras / bladestorm — per-row for exact deal() parity
            for i in atk_idx:
                s = stats_list[i]
                now = float(moment[i])
                pow_i = float(power[i])

                # bt extra
                if float(bt_extra[i]) > 0.5:
                    bt_extra[i] = 0.0
                    extra = 20.0 + 20.0 * rank + 0.75 * pow_i
                    if is_fury:
                        extra += 15.0 + 2.0 * s["mastery"]
                    if s["bt_item"]:
                        extra *= 1.50
                    mask_i = torch.zeros(B, dtype=torch.bool, device=device)
                    mask_i[i] = True
                    # deal as auto hit
                    push_deal(
                        mask_i,
                        torch.full((B,), now, dtype=dtype, device=device),
                        torch.full((B,), extra, dtype=dtype, device=device),
                        magical=0.0,
                        count=1.0,
                        pot_scale=s["attack_potency"],
                        auto=1.0,
                        auto_pct_scale=0.0,
                    )
                    if s["damage_mana_pct"]:
                        mana[i] = min(float(mana_max[i]), float(mana[i]) + s["damage_mana_pct"] * s["mana_max"])

                if s["fire_orb"]:
                    mask_i = torch.zeros(B, dtype=torch.bool, device=device)
                    mask_i[i] = True
                    bufs.push_mask(
                        torch,
                        mask_i,
                        torch.full((B,), now, dtype=dtype, device=device),
                        torch.full((B,), 20.0 + 0.35 * s["str"], dtype=dtype, device=device),
                        magical=0.0,
                        count=float(targets),
                        pot_scale=0.0,
                        auto=0.0,
                        mastery=float(mastery[i]),
                        enraged=0.0,
                        auto_pct=0.0,
                        special=SPEC_SPLASH,
                    )
                    if s["damage_mana_pct"]:
                        mana[i] = min(float(mana_max[i]), float(mana[i]) + s["damage_mana_pct"] * s["mana_max"] * targets)

                if float(has_sulfuras[i]) > 0.5:
                    mask_i = torch.zeros(B, dtype=torch.bool, device=device)
                    mask_i[i] = True
                    if float(sulf_armed[i]) > 0.5:
                        sulf_armed[i] = 0.0
                        push_deal(
                            mask_i,
                            torch.full((B,), now, dtype=dtype, device=device),
                            torch.full((B,), s["str"], dtype=dtype, device=device),
                            magical=1.0,
                            count=float(targets),
                            pot_scale=0.0,
                        )
                        if s["damage_mana_pct"]:
                            mana[i] = min(float(mana_max[i]), float(mana[i]) + s["damage_mana_pct"] * s["mana_max"] * targets)
                    bufs.push_mask(
                        torch,
                        mask_i,
                        torch.full((B,), now, dtype=dtype, device=device),
                        torch.full((B,), pow_i * sulfuras_echo_chance(s["luck"]), dtype=dtype, device=device),
                        magical=0.0,
                        count=1.0,
                        pot_scale=0.0,
                        auto=0.0,
                        mastery=float(mastery[i]),
                        enraged=0.0,
                        auto_pct=0.0,
                        special=SPEC_ECHO,
                    )

                if float(has_blade[i]) > 0.5 and float(clocks[i, C_WW]) > now:
                    clocks[i, C_WW] = max(now, float(clocks[i, C_WW]) - 0.20)

            # next attack
            interval = attack_interval(moment)
            clocks[:, C_ATTACK] = torch.where(m_atk, moment + interval, clocks[:, C_ATTACK])

    events_batch = buffers_to_warrior_events(bufs)
    out = []
    for i, build in enumerate(builds):
        out.append((events_batch[i], stats_list[i], taken_list[i], taken_auto_list[i]))
    return out
