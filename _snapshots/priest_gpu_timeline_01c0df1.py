# -*- coding: utf-8 -*-
"""Batched GPU timeline for Priest (shadow / discipline / holy).

Float64 clocks on CPU (DirectML lacks reliable f64); events match
sunken_sim.shadow._fight_events: (when, kind, hits). Windows list for Holy Fire.
"""
from __future__ import annotations

MAX_EVENTS = 1024
MAX_STEPS = 200000
MAX_T = 12
MAX_WINDOWS = 32

S_NONE = 0
S_SWP = 1
S_MIND = 2
S_VOID = 3
S_IMAGE = 4
S_RAD = 5
S_RENEW = 6

SPELL_NAMES = {
    S_SWP: "Shadow Word: Pain",
    S_MIND: "Mind Spike",
    S_VOID: "Void Rift",
    S_IMAGE: "Divine Image",
    S_RAD: "Radiance",
    S_RENEW: "Renew",
}

K_AUTO = 0
K_SPLASH = 1
K_SULF = 2
K_SULF_ECHO = 3
K_HELL = 4
K_SWP = 5
K_SWP_I = 6
K_MIND = 7
K_VOID = 8
K_NAARU = 9
K_THUNDER = 10
K_BLAZE = 11
K_RAD = 12
K_SMITE = 13

KIND_NAMES = {
    K_AUTO: "auto",
    K_SPLASH: "splash",
    K_SULF: "sulfuras",
    K_SULF_ECHO: "sulfuras_echo",
    K_HELL: "hellfire",
    K_SWP: "swp",
    K_SWP_I: "swp_i",
    K_MIND: "mind",
    K_VOID: "void",
    K_NAARU: "naaru",
    K_THUNDER: "thunder",
    K_BLAZE: "blaze",
    K_RAD: "radiance",
    K_SMITE: "smite",
}


def _stat_vec(torch, device, dtype, stats_list, key, default=0.0):
    return torch.tensor([float(s.get(key, default)) for s in stats_list], dtype=dtype, device=device)


def _flag_vec(torch, device, dtype, builds, pred):
    return torch.tensor([1.0 if pred(b) else 0.0 for b in builds], dtype=dtype, device=device)


def generate_priest_timelines(torch, device, builds, spec: str, targets: int, bound_keys=None):
    """Return list[(events, stats, windows, bound)] aligned with builds."""
    from sunken_sim import shadow as mod

    if spec not in ("shadow", "discipline", "holy"):
        raise ValueError(f"priest GPU timeline specs shadow/disc/holy, got {spec}")
    B = len(builds)
    if B == 0:
        return []
    if bound_keys is None:
        bound_keys = [None] * B
    if len(bound_keys) != B:
        raise ValueError("bound_keys length mismatch")
    if targets > MAX_T:
        raise ValueError(f"targets {targets} > MAX_T {MAX_T}")

    dtype = torch.float64
    dev_type = getattr(device, "type", str(device))
    if dev_type in ("privateuseone", "dml") or "privateuseone" in str(device):
        device = torch.device("cpu")

    try:
        return _priest_batch(torch, device, dtype, builds, spec, targets, bound_keys)
    except Exception:
        return _cpu_events_batch(builds, spec, targets, bound_keys)


def _cpu_events_batch(builds, spec, targets, bound_keys):
    from sunken_sim import shadow as mod

    out = []
    for build, bk in zip(builds, bound_keys):
        stats = mod.character(build)
        events, _actions, windows, _mana = mod._fight_events(build, stats, spec, targets, bk)
        out.append((events, stats, windows, bk))
    return out


def _make_bufs(torch, device, B, dtype):
    z = lambda: torch.zeros((B, MAX_EVENTS), dtype=dtype, device=device)
    return {
        "when": z(),
        "kind": torch.zeros((B, MAX_EVENTS), dtype=torch.int64, device=device),
        "hits": z(),
        "length": torch.zeros(B, dtype=torch.int64, device=device),
    }


def _push(torch, bufs, mask, when, hits, kind_id):
    if not bool(mask.any()):
        return
    B = int(mask.shape[0])
    active = mask & (bufs["length"] < MAX_EVENTS)
    if not bool(active.any()):
        return
    rows = torch.arange(B, device=when.device)
    idx = bufs["length"]
    for buf, value in (
        (bufs["when"], when),
        (bufs["hits"], hits if isinstance(hits, torch.Tensor) else torch.full((B,), float(hits), dtype=when.dtype, device=when.device)),
    ):
        buf[rows[active], idx[active]] = value[active]
    kid = kind_id if isinstance(kind_id, torch.Tensor) else torch.full((B,), int(kind_id), dtype=torch.int64, device=when.device)
    bufs["kind"][rows[active], idx[active]] = kid[active]
    bufs["length"] = bufs["length"] + active.to(bufs["length"].dtype)


def _buffers_to_events(bufs):
    when = bufs["when"].detach().cpu()
    kind = bufs["kind"].detach().cpu()
    hits = bufs["hits"].detach().cpu()
    length = bufs["length"].detach().cpu()
    out = []
    for b in range(when.shape[0]):
        n = int(length[b].item())
        ev = []
        for i in range(n):
            kid = int(kind[b, i].item())
            ev.append((float(when[b, i]), KIND_NAMES.get(kid, "auto"), float(hits[b, i])))
        out.append(ev)
    return out


def _priest_batch(torch, device, dtype, builds, spec, targets, bound_keys):
    from sunken_sim import shadow as mod
    from sunken_sim.shadow import CAST_BACKSWING, CAST_POINT, FIGHT, cast_mana_back, attack_mana_gain, sulfuras_echo_chance

    B = len(builds)
    T = int(targets)
    CAST_TIME = CAST_POINT + CAST_BACKSWING
    fight = float(FIGHT)
    targets_f = float(T)
    is_shadow = spec == "shadow"
    is_disc = spec == "discipline"

    stats_list = [mod.character(b) for b in builds]
    ones = torch.ones(B, dtype=dtype, device=device)
    zeros = torch.zeros(B, dtype=dtype, device=device)
    true = torch.ones(B, dtype=torch.bool, device=device)
    false = torch.zeros(B, dtype=torch.bool, device=device)

    haste = _stat_vec(torch, device, dtype, stats_list, "haste")
    # spell CD uses _ability_cd internally via stats keys
    mana_max = _stat_vec(torch, device, dtype, stats_list, "mana_max")
    mana_regen = _stat_vec(torch, device, dtype, stats_list, "mana_regen")
    cast_stun_lock = _stat_vec(torch, device, dtype, stats_list, "cast_stun_lock")
    damage_mana_pct = _stat_vec(torch, device, dtype, stats_list, "damage_mana_pct")
    swing = _stat_vec(torch, device, dtype, stats_list, "swing")
    stun_per_swing = _stat_vec(torch, device, dtype, stats_list, "stun_per_swing")
    luck = _stat_vec(torch, device, dtype, stats_list, "luck")
    swp_period = _stat_vec(torch, device, dtype, stats_list, "swp_period")

    i0hl = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0HL"))
    i0sb = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0SB"))
    i0sc = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0SC"))
    i0kf = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0KF"))
    i0h5 = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0H5"))
    i0hp = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0HP"))
    i0mj = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0MJ"))
    i0kh = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0KH"))
    i0h3 = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0H3"))
    splash_ring = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I07O"))
    has_sulf = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, mod.SULFURAS))

    duration = torch.where(i0hl > 0.5, torch.full((B,), 12.0, dtype=dtype, device=device), torch.full((B,), 10.0, dtype=dtype, device=device))
    void_delay = torch.where(i0hp > 0.5, torch.full((B,), 1.5, dtype=dtype, device=device), torch.full((B,), 2.0, dtype=dtype, device=device))
    blaze_span = torch.where(i0kh > 0.5, torch.full((B,), 6.0, dtype=dtype, device=device), torch.full((B,), 4.0, dtype=dtype, device=device))

    # per-build spell availability + CDs (bound scale)
    def ability_cd(base, bound_name):
        # mirror shadow._ability_cd
        from sunken_sim.shadow import _ability_cd
        vals = []
        for b, st, bk in zip(builds, stats_list, bound_keys):
            vals.append(float(_ability_cd(base, st, bk == bound_name)))
        return torch.tensor(vals, dtype=dtype, device=device)

    cd_swp = ability_cd(6.0, "Shadow Word: Pain")
    cd_mind = ability_cd(8.0, "Mind Spike")
    cd_void = ability_cd(10.0, "Void Rift")
    cd_image = torch.tensor([
        float(mod._ability_cd(
            16.0 - (1.0 if mod._has(b, "I0SB") else 0.0) - (1.0 if mod._has(b, "I0SC") else 0.0),
            st,
            bk == "Divine Image",
        ))
        for b, st, bk in zip(builds, stats_list, bound_keys)
    ], dtype=dtype, device=device)
    cd_rad = ability_cd(8.0, "Radiance")
    cd_renew = ability_cd(6.0, "Renew")

    cost_swp = torch.full((B,), 15.0, dtype=dtype, device=device)
    cost_mind = torch.full((B,), 25.0, dtype=dtype, device=device)
    cost_void = torch.full((B,), 40.0, dtype=dtype, device=device)
    cost_image = torch.full((B,), 30.0, dtype=dtype, device=device)
    cost_rad = torch.full((B,), 35.0, dtype=dtype, device=device)
    cost_renew = torch.full((B,), 20.0, dtype=dtype, device=device)

    # which spells exist per build (mirror shadow._cast_spells)
    spell_sets = [set(mod._cast_spells(b, spec)) for b in builds]
    has_swp = torch.tensor(["Shadow Word: Pain" in s for s in spell_sets], dtype=torch.bool, device=device)
    has_mind = torch.tensor(["Mind Spike" in s for s in spell_sets], dtype=torch.bool, device=device)
    has_void = torch.tensor(["Void Rift" in s for s in spell_sets], dtype=torch.bool, device=device)
    has_image = torch.tensor(["Divine Image" in s for s in spell_sets], dtype=torch.bool, device=device)
    has_rad = torch.tensor(["Radiance" in s for s in spell_sets], dtype=torch.bool, device=device)
    has_renew = torch.tensor(["Renew" in s for s in spell_sets], dtype=torch.bool, device=device)

    mana = mana_max.clone()
    mana_time = torch.zeros(B, dtype=dtype, device=device)
    hero_ready = torch.zeros(B, dtype=dtype, device=device)
    busy_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    next_swing = torch.zeros(B, dtype=dtype, device=device)
    next_hell = torch.where(i0h3 > 0.5, zeros, torch.full((B,), fight, dtype=dtype, device=device))
    next_swp_tick = torch.full((B,), fight, dtype=dtype, device=device)
    swp_ticking = torch.zeros(B, dtype=torch.bool, device=device)
    void_at = torch.full((B,), fight, dtype=dtype, device=device)
    naaru_at = torch.full((B,), fight, dtype=dtype, device=device)
    blaze_at = torch.full((B,), fight, dtype=dtype, device=device)
    naaru_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    blaze_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    renew_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    sulf_armed = torch.zeros(B, dtype=dtype, device=device)

    ready_swp = torch.zeros(B, dtype=dtype, device=device)
    ready_mind = torch.zeros(B, dtype=dtype, device=device)
    ready_void = torch.zeros(B, dtype=dtype, device=device)
    ready_image = torch.zeros(B, dtype=dtype, device=device)
    ready_rad = torch.zeros(B, dtype=dtype, device=device)
    ready_renew = torch.zeros(B, dtype=dtype, device=device)

    pending_active = torch.zeros(B, dtype=torch.bool, device=device)
    pending_at = torch.full((B,), fight, dtype=dtype, device=device)
    pending_spell = torch.zeros(B, dtype=torch.int64, device=device)

    swp_exp = torch.zeros((B, MAX_T), dtype=dtype, device=device)
    swp_w = torch.zeros((B, MAX_T), dtype=dtype, device=device)
    valid_t = torch.zeros((B, MAX_T), dtype=torch.bool, device=device)
    valid_t[:, :T] = True

    # windows: start/end buffers
    win_start = torch.full((B, MAX_WINDOWS), fight, dtype=dtype, device=device)
    win_end = torch.full((B, MAX_WINDOWS), fight, dtype=dtype, device=device)
    win_len = torch.zeros(B, dtype=torch.int64, device=device)

    bufs = _make_bufs(torch, device, B, dtype)
    alive = torch.ones(B, dtype=torch.bool, device=device)

    refund_cache = None

    def recover(now, mask=None):
        nonlocal mana, mana_time
        if mask is None:
            mask = true
        dt = torch.clamp(now - mana_time, min=0.0)
        need = mask & (mana < mana_max)
        mana = torch.where(need, torch.minimum(mana_max, mana + mana_regen * dt), mana)
        mana_time = torch.where(mask, now, mana_time)

    def note_dmg_mana(mask):
        nonlocal mana
        mana = torch.where(
            mask & (damage_mana_pct > 0),
            torch.minimum(mana_max, mana + damage_mana_pct * mana_max),
            mana,
        )

    def record(mask, when, kind_id, hits=1.0):
        if not bool(mask.any()):
            return
        if not isinstance(hits, torch.Tensor):
            hits = torch.full((B,), float(hits), dtype=dtype, device=device)
        do = mask & (hits > 0) & (when < fight)
        if not bool(do.any()):
            return
        note_dmg_mana(do)
        _push(torch, bufs, do, when, hits, kind_id)

    def pay(mask, cost, now):
        nonlocal mana
        recover(now, mask)
        ok = mask & (mana >= cost)
        refund = []
        for i, s in enumerate(stats_list):
            c = float(cost[i]) if isinstance(cost, torch.Tensor) else float(cost)
            refund.append(float(cast_mana_back(c, s)))
        refund_t = torch.tensor(refund, dtype=dtype, device=device)
        mana = torch.where(ok, torch.minimum(mana_max, mana - cost + refund_t), mana)
        return ok

    def attack_mana_vec():
        return torch.tensor([float(attack_mana_gain(s)) for s in stats_list], dtype=dtype, device=device)

    def add_window(mask, start, end):
        nonlocal win_start, win_end, win_len
        if not bool(mask.any()):
            return
        rows = torch.arange(B, device=device)
        for r in rows[mask].tolist():
            r = int(r)
            j = int(win_len[r].item())
            if j >= MAX_WINDOWS:
                continue
            win_start[r, j] = float(start[r])
            win_end[r, j] = float(end[r])
            win_len[r] = j + 1

    def swp_apply(mask, index_t, now):
        nonlocal swp_exp, swp_w, next_swp_tick, swp_ticking
        if not bool(mask.any()):
            return
        rows = torch.arange(B, device=device)
        # use per-row now for comparison (now is B-vector)
        now_b = now if isinstance(now, torch.Tensor) and now.shape == (B,) else torch.full((B,), float(now), dtype=dtype, device=device)
        already = swp_exp[rows, index_t] > now_b
        record(mask & already, now_b, K_SWP_I, ones)
        any_up = ((swp_exp > now_b.unsqueeze(1)) & valid_t).any(dim=1)
        arm = mask & ~any_up
        fresh = arm & ~swp_ticking
        swp_ticking = swp_ticking | arm
        next_swp_tick = torch.where(fresh, now_b + swp_period, next_swp_tick)
        # safe row-wise write
        for r in rows[mask].tolist():
            r = int(r)
            ti = int(index_t[r].item())
            swp_exp[r, ti] = float(now_b[r] + duration[r])
            swp_w[r, ti] = 1.0

    def naaru_hit(mask, now):
        nonlocal ready_mind
        if not bool(mask.any()):
            return
        record(mask, now, K_NAARU, ones)
        # I0SC CDR on Mind Spike
        cdr = torch.where(
            torch.full((B,), is_disc, dtype=torch.bool, device=device),
            torch.full((B,), 0.20, dtype=dtype, device=device),
            torch.full((B,), 0.40, dtype=dtype, device=device),
        )
        do = mask & (i0sc > 0.5)
        ready_mind = torch.where(do, torch.maximum(now, ready_mind - cdr), ready_mind)

    def thunder(mask, now):
        record(mask & (i0h5 > 0.5), now, K_THUNDER, torch.full((B,), 0.18 * targets_f, dtype=dtype, device=device))

    def do_resolve(mask, spell, now):
        nonlocal naaru_until, blaze_until, renew_until, void_at, naaru_at, blaze_at
        if not bool(mask.any()):
            return
        # Mind Spike
        m = mask & (spell == S_MIND)
        if bool(m.any()):
            record(m, now, K_MIND, ones)
            idx0 = torch.zeros(B, dtype=torch.int64, device=device)
            swp_apply(m & (i0kf > 0.5) & has_swp, idx0, now)
            thunder(m, now)
        # Void
        m = mask & (spell == S_VOID)
        if bool(m.any()):
            void_at = torch.where(m, now + void_delay, void_at)
            thunder(m, now)
        # SWP
        m = mask & (spell == S_SWP)
        if bool(m.any()):
            # weakest = argmin swp_exp among valid
            # set invalid high
            keyed = torch.where(valid_t, swp_exp, torch.full_like(swp_exp, 1e9))
            idx = keyed[:, :T].argmin(dim=1)
            swp_apply(m, idx, now)
            thunder(m, now)
        # Divine Image
        m = mask & (spell == S_IMAGE)
        if bool(m.any()):
            naaru_until = torch.where(m, now + 10.0, naaru_until)
            naaru_at = torch.where(m, now + 1.0, naaru_at)
        # Radiance
        m = mask & (spell == S_RAD)
        if bool(m.any()):
            disc = torch.full((B,), is_disc, dtype=torch.bool, device=device)
            record(m & disc, now, K_RAD, torch.full((B,), targets_f, dtype=dtype, device=device))
            blaze_m = m & (i0mj > 0.5)
            if bool(blaze_m.any()):
                need_push = blaze_m & (blaze_until <= now)
                blaze_at = torch.where(need_push, now + 1.0, blaze_at)
                new_until = now + blaze_span
                blaze_until = torch.where(blaze_m, new_until, blaze_until)
                add_window(blaze_m, now, new_until)
            thunder(m, now)
        # Renew
        m = mask & (spell == S_RENEW)
        if bool(m.any()):
            record(m & (renew_until > now), now, K_SMITE, torch.full((B,), targets_f, dtype=dtype, device=device))
            renew_until = torch.where(m, now + 9.0, renew_until)
            thunder(m, now)
        # I0SB echo naaru on non-image casts while naaru up
        echo = mask & (spell != S_IMAGE) & (i0sb > 0.5) & (now < naaru_until)
        naaru_hit(echo, now)

    def do_cast(mask, spell, now):
        nonlocal hero_ready, busy_until, sulf_armed
        nonlocal ready_swp, ready_mind, ready_void, ready_image, ready_rad, ready_renew
        nonlocal pending_active, pending_at, pending_spell
        if not bool(mask.any()):
            return
        cost = zeros.clone()
        cost = torch.where(spell == S_SWP, cost_swp, cost)
        cost = torch.where(spell == S_MIND, cost_mind, cost)
        cost = torch.where(spell == S_VOID, cost_void, cost)
        cost = torch.where(spell == S_IMAGE, cost_image, cost)
        cost = torch.where(spell == S_RAD, cost_rad, cost)
        cost = torch.where(spell == S_RENEW, cost_renew, cost)
        ok = pay(mask, cost, now)
        if not bool(ok.any()):
            return
        dur = zeros.clone()
        dur = torch.where(spell == S_SWP, cd_swp, dur)
        dur = torch.where(spell == S_MIND, cd_mind, dur)
        dur = torch.where(spell == S_VOID, cd_void, dur)
        dur = torch.where(spell == S_IMAGE, cd_image, dur)
        dur = torch.where(spell == S_RAD, cd_rad, dur)
        dur = torch.where(spell == S_RENEW, cd_renew, dur)
        ready_swp = torch.where(ok & (spell == S_SWP), now + dur, ready_swp)
        ready_mind = torch.where(ok & (spell == S_MIND), now + dur, ready_mind)
        ready_void = torch.where(ok & (spell == S_VOID), now + dur, ready_void)
        ready_image = torch.where(ok & (spell == S_IMAGE), now + dur, ready_image)
        ready_rad = torch.where(ok & (spell == S_RAD), now + dur, ready_rad)
        ready_renew = torch.where(ok & (spell == S_RENEW), now + dur, ready_renew)
        sulf_armed = torch.where(ok & (has_sulf > 0.5) & (sulf_armed < 0.5), ones, sulf_armed)
        busy = now + CAST_TIME + cast_stun_lock
        busy_until = torch.where(ok, busy, busy_until)
        hero_ready = torch.where(ok, busy, hero_ready)
        pending_active = torch.where(ok, true, pending_active)
        pending_at = torch.where(ok, now + CAST_POINT, pending_at)
        pending_spell = torch.where(ok, spell, pending_spell)

    def choose(now):
        spell = torch.zeros(B, dtype=torch.int64, device=device)
        has = torch.zeros(B, dtype=torch.bool, device=device)
        # SWP first if any expiry < now+1
        swp_soon = ((swp_exp < (now + 1.0).unsqueeze(1)) & valid_t).any(dim=1)
        take = has_swp & swp_soon & (ready_swp <= now) & (mana >= cost_swp)
        spell = torch.where(take, torch.full_like(spell, S_SWP), spell)
        has = has | take
        if is_shadow:
            order = [(S_IMAGE, has_image, ready_image, cost_image),
                     (S_MIND, has_mind, ready_mind, cost_mind),
                     (S_VOID, has_void, ready_void, cost_void)]
        else:
            order = [(S_IMAGE, has_image, ready_image, cost_image),
                     (S_RAD, has_rad, ready_rad, cost_rad),
                     (S_MIND, has_mind, ready_mind, cost_mind),
                     (S_RENEW, has_renew, ready_renew, cost_renew)]
        for sid, avail, ready, cost in order:
            take = ~has & avail & (ready <= now) & (mana >= cost)
            if sid == S_IMAGE:
                take = take & (naaru_until <= now)
            spell = torch.where(take, torch.full_like(spell, sid), spell)
            has = has | take
        return spell, has

    def on_swing(mask, now):
        nonlocal next_swing, hero_ready, sulf_armed, mana
        if not bool(mask.any()):
            return
        defer = mask & (now < busy_until)
        next_swing = torch.where(defer, busy_until, next_swing)
        do = mask & ~defer
        if not bool(do.any()):
            return
        record(do, now, K_AUTO, ones)
        mana = torch.where(do, torch.minimum(mana_max, mana + attack_mana_vec()), mana)
        sulf_m = do & (has_sulf > 0.5) & (sulf_armed > 0.5)
        sulf_armed = torch.where(sulf_m, zeros, sulf_armed)
        record(sulf_m, now, K_SULF, torch.full((B,), targets_f, dtype=dtype, device=device))
        echo = torch.tensor([float(sulfuras_echo_chance(float(luck[i]))) for i in range(B)], dtype=dtype, device=device)
        # CPU always records sulfuras_echo when sulfuras equipped (hits default 1; score uses chance)
        record(do & (has_sulf > 0.5), now, K_SULF_ECHO, ones)
        record(do & (splash_ring > 0.5), now, K_SPLASH, torch.full((B,), targets_f, dtype=dtype, device=device))
        hero_ready = torch.where(do, torch.maximum(hero_ready, now + stun_per_swing), hero_ready)
        next_swing = torch.where(do, now + swing + stun_per_swing, next_swing)

    def on_swp(mask, now):
        nonlocal next_swp_tick, swp_ticking, swp_w
        if not bool(mask.any()):
            return
        # zero weights for expired — ONLY on rows whose SWP tick fires now
        # (other rows may sit past expiry until their own tick or a void refresh)
        now_c = now.unsqueeze(1)
        expired = mask.unsqueeze(1) & valid_t & (swp_exp <= now_c)
        swp_w = torch.where(expired, torch.zeros_like(swp_w), swp_w)
        active = (swp_w * (swp_exp > now_c).to(dtype) * valid_t.to(dtype)).sum(dim=1)
        do = mask & (active > 1e-9)
        stop = mask & ~do
        swp_ticking = torch.where(stop, false, swp_ticking)
        next_swp_tick = torch.where(stop, torch.full((B,), fight, dtype=dtype, device=device), next_swp_tick)
        if bool(do.any()):
            record(do, now, K_SWP, active)
            next_swp_tick = torch.where(do, now + swp_period, next_swp_tick)

    def on_void(mask, now):
        nonlocal void_at, swp_exp, swp_w, next_swp_tick, swp_ticking
        if not bool(mask.any()):
            return
        record(mask, now, K_VOID, torch.full((B,), targets_f, dtype=dtype, device=device))
        void_at = torch.where(mask, torch.full((B,), fight, dtype=dtype, device=device), void_at)
        do = mask & (i0hp > 0.5)
        if bool(do.any()):
            p = 0.25 * (1.0 + luck)
            for ti in range(T):
                up = swp_exp[:, ti] > now
                record(do & up, now, K_SWP_I, p * swp_w[:, ti])
            any_up = ((swp_exp > now.unsqueeze(1)) & valid_t).any(dim=1)
            arm = do & ~any_up & (p > 0)
            fresh = arm & ~swp_ticking
            swp_ticking = swp_ticking | arm
            next_swp_tick = torch.where(fresh, now + swp_period, next_swp_tick)
            for ti in range(T):
                # EV update — clone to avoid any view aliasing
                new_w = swp_w[:, ti] + p * (1.0 - swp_w[:, ti])
                swp_w[:, ti] = torch.where(do, new_w, swp_w[:, ti])
                new_e = now + duration
                swp_exp[:, ti] = torch.where(do & (swp_w[:, ti] > 0), new_e, swp_exp[:, ti])

    def on_naaru(mask, now):
        nonlocal naaru_at
        if not bool(mask.any()):
            return
        do = mask & (now <= naaru_until)
        naaru_hit(do, now)
        cont = do & (now + 1.0 <= naaru_until)
        naaru_at = torch.where(cont, now + 1.0, torch.where(mask, torch.full((B,), fight, dtype=dtype, device=device), naaru_at))

    def on_blaze(mask, now):
        nonlocal blaze_at
        if not bool(mask.any()):
            return
        do = mask & (now <= blaze_until)
        record(do, now, K_BLAZE, torch.full((B,), targets_f, dtype=dtype, device=device))
        cont = do & (now + 1.0 <= blaze_until)
        blaze_at = torch.where(cont, now + 1.0, torch.where(mask, torch.full((B,), fight, dtype=dtype, device=device), blaze_at))

    def on_hell(mask, now):
        nonlocal next_hell
        if not bool(mask.any()):
            return
        record(mask, now, K_HELL, torch.full((B,), targets_f, dtype=dtype, device=device))
        next_hell = torch.where(mask, now + 1.25, next_hell)

    steps = 0
    while bool(alive.any()) and steps < MAX_STEPS:
        steps += 1
        pending_t = torch.where(pending_active, pending_at, torch.full_like(pending_at, fight))
        moment = next_swing.clone()
        for clock in (next_hell, next_swp_tick, void_at, naaru_at, blaze_at, pending_t):
            moment = torch.minimum(moment, clock)
        alive = alive & (moment < fight)

        m_pend = alive & pending_active & (pending_at <= moment) & (pending_at < fight)
        m_hero = alive & (hero_ready <= moment) & (hero_ready < fight)
        m_acted = false.clone()
        if bool(m_hero.any()):
            recover(hero_ready, m_hero)
            spell, has_spell = choose(hero_ready)
            cast_m = m_hero & has_spell
            if bool(cast_m.any()):
                do_cast(cast_m, spell, hero_ready)
                m_acted = m_acted | cast_m

        m_fire = alive & ~m_acted & (moment < fight)
        if bool(m_fire.any()):
            recover(moment, m_fire)
            on_swing(m_fire & (next_swing == moment), moment)
            on_hell(m_fire & (next_hell == moment), moment)
            on_swp(m_fire & (next_swp_tick == moment), moment)
            on_void(m_fire & (void_at == moment), moment)
            on_naaru(m_fire & (naaru_at == moment), moment)
            on_blaze(m_fire & (blaze_at == moment), moment)

        if bool(m_pend.any()):
            still = m_pend & ~m_acted
            if bool(still.any()):
                recover(pending_at, still)
                do_resolve(still, pending_spell, pending_at)
                m_acted = m_acted | still
            pending_active = torch.where(m_pend, false, pending_active)
            pending_at = torch.where(m_pend, torch.full_like(pending_at, fight), pending_at)

        alive = alive & (m_acted | (moment < fight))

    if bool(alive.any()):
        raise RuntimeError(f"priest GPU timeline hit MAX_STEPS={MAX_STEPS}")
    recover(torch.full((B,), fight, dtype=dtype, device=device), true)
    events_list = _buffers_to_events(bufs)
    # windows per row
    wins = []
    for b in range(B):
        n = int(win_len[b].item())
        wins.append([(float(win_start[b, i]), float(win_end[b, i])) for i in range(n)])
    return [(events_list[i], stats_list[i], wins[i], bound_keys[i]) for i in range(B)]
