# -*- coding: utf-8 -*-
"""GPU next-event timeline for Mage Fire / Frost.

Batched float64 state machine (pending cast + swing/bomb/hydra/hellfire/wave/ring
clocks + per-target bomb/chill/freeze). Arcane: Evocation + mana ticks, arcane reset
chance (mastery + splinter) and Blast stacks; parity-gated (tools/_parity_mage_arcane.py).

Clocks run float64 on CPU when DirectML lacks f64; existing fight.compile_sums
kind-compile stays on DirectML. CPU mage.simulate() remains the parity oracle
(rel/abs <= 1e-4).

Event tuples match sunken_sim.mage.simulate:
  (when, kind, hits, raw_w, pot_w, extra_dict)
"""

from __future__ import annotations

from collections import Counter

# Per-process cumulative diagnostics; engines also pass their own accumulator.
TIMELINE_COUNTS = Counter()


class TimelineCapacityError(RuntimeError):
    """Rejected rows plus complete, non-truncated rows from the same batch."""

    def __init__(self, reasons, partial=None):
        self.reasons = dict(reasons)
        self.partial = partial
        super().__init__(f"mage timeline capacity: {dict(Counter(self.reasons.values()))}")


MAX_EVENTS = 2048
MAX_STEPS = 400000
MAX_T = 8          # per-target bomb/chill/freeze
MAX_HYDRA = 256    # hydra expiry groups (lava appends often)
MAX_WAVES = 24     # blizzard wave slots
MAX_BOMB_CHAINS = 4  # concurrent bomb tick heaps (CPU can dual-arm)
MAX_MANA = 32     # pending Evocation mana ticks (arcane)
MAX_PENDING = 16  # queued cast finishes (CPU inner cast loop uses a stale heap time)

# Spell ids for pending / choose
S_NONE = 0
S_BOMB = 1
S_RING = 2
S_BLIZ = 3
S_HYDRA = 4
S_BLAST = 5
S_EVO = 6

SPELL_NAME = {
    S_BOMB: "Living Bomb",
    S_RING: "Ring of Frost",
    S_BLIZ: "Blizzard",
    S_HYDRA: "Hydra",
    S_BLAST: "Arcane Blast",
    S_EVO: "Evocation",
}

# kind string ids for event buffer
K_AUTO = 1
K_SPLASH = 2
K_HELL = 3
K_PYRO = 4
K_HYDRA = 5
K_CLEAVE = 6
K_SULF = 7
K_SULF_ECHO = 8
K_BOMB = 9
K_BURST = 10
K_FIREBOMB = 11
K_RING = 12
K_BLAST = 13
K_NOVA = 14
K_LANCE = 15
K_BOLT = 16
K_BOLT_SPLASH = 17
K_THUNDER = 18
K_BLIZ = 19

KIND_STR = {
    K_AUTO: "auto",
    K_SPLASH: "splash",
    K_HELL: "hellfire",
    K_PYRO: "pyro",
    K_HYDRA: "hydra",
    K_CLEAVE: "cleave",
    K_SULF: "sulfuras",
    K_SULF_ECHO: "sulfuras_echo",
    K_BOMB: "bomb",
    K_BURST: "burst",
    K_FIREBOMB: "firebomb",
    K_RING: "ring",
    K_BLAST: "blast",
    K_NOVA: "nova",
    K_LANCE: "lance",
    K_BOLT: "bolt",
    K_BOLT_SPLASH: "bolt_splash",
    K_THUNDER: "thunder",
    K_BLIZ: "blizzard",
}


def _stat_vec(torch, device, dtype, stats_list, key, default=0.0):
    return torch.tensor([float(s.get(key, default)) for s in stats_list], dtype=dtype, device=device)


def _flag_vec(torch, device, dtype, builds, pred):
    return torch.tensor([1.0 if pred(b) else 0.0 for b in builds], dtype=dtype, device=device)


def generate_mage_timelines(torch, device, builds, spec: str, targets: int, bound_keys=None, diagnostics=None, prepared_stats=None):
    """Return list[(events, stats, used_spec, evocation)] aligned with builds.

    bound_keys: optional list[str|None] parallel to builds (Diamond I00D expand).
    """
    from sunken_sim import mage as mod

    if spec not in ("fire", "frost", "arcane"):
        raise ValueError(f"mage GPU timeline only fire/frost/arcane, got {spec}")
    B = len(builds)
    if B == 0:
        return []
    if bound_keys is None:
        bound_keys = [None] * B
    if len(bound_keys) != B:
        raise ValueError("bound_keys length mismatch")
    if prepared_stats is not None and len(prepared_stats) != B:
        raise ValueError("prepared_stats length mismatch")
    if targets > MAX_T:
        raise ValueError(f"targets {targets} > MAX_T {MAX_T}")

    dtype = torch.float64
    dev_type = getattr(device, "type", str(device))
    if dev_type in ("privateuseone", "dml") or "privateuseone" in str(device):
        device = torch.device("cpu")

    def count(key, n=1):
        TIMELINE_COUNTS[key] += n
        if diagnostics is not None and diagnostics is not TIMELINE_COUNTS:
            diagnostics[key] = diagnostics.get(key, 0) + n

    count("calls")
    count("requested_rows", B)
    try:
        kwargs = {} if prepared_stats is None else {"prepared_stats": prepared_stats}
        result = _mage_batch(torch, device, dtype, builds, spec, targets, bound_keys, **kwargs)
    except TimelineCapacityError as exc:
        # Never expose the rejected tape. Re-simulate only failed rows, retaining
        # each row's Build (including ESC), spec, targets and ring binding.
        result = exc.partial if exc.partial is not None else [None] * B
        reasons = exc.reasons if exc.partial is not None else {
            i: exc.reasons.get(i, "capacity_batch") for i in range(B)
        }
        rejected = sorted(reasons)
        exact = _cpu_events_batch(
            [builds[i] for i in rejected], spec, targets, [bound_keys[i] for i in rejected]
        )
        for i, row in zip(rejected, exact):
            result[i] = row
        count("vector_rows", B - len(rejected))
        count("cpu_fallback_rows", len(rejected))
        for reason, n in Counter(reasons.values()).items():
            count(reason, n)
        print(f"mage timeline exact CPU fallback: {dict(Counter(reasons.values()))}", flush=True)
        return result
    except Exception as exc:
        # Other finite queue capacities/unsupported kernels fail closed too.
        reason = "batch_exception:" + type(exc).__name__
        count("cpu_fallback_rows", B)
        count(reason, B)
        print(f"mage timeline exact CPU fallback: {reason}, rows={B}", flush=True)
        return _cpu_events_batch(builds, spec, targets, bound_keys)
    count("vector_rows", B)
    return result


def _cpu_events_batch(builds, spec, targets, bound_keys):
    from sunken_sim import mage as mod

    out = []
    for build, bk in zip(builds, bound_keys):
        sink = []

        def grab(events, build_, stats, used_spec, evocation):
            sink.append((events, stats, used_spec, evocation))

        # reuse fight._capture pattern
        from farm.hybrid import fight as fight_mod
        old = getattr(mod, "_compile", None)
        # call simulate with counter to get events via patch
        # simpler: use fight.timelines without cache
        tls = fight_mod.timelines(build, targets, spec, cache=False)
        # timelines expands I00D; pick matching bound
        if bk is None:
            # first / only
            tl = tls[0]
        else:
            tl = next(t for t in tls if t.bound == bk)
        out.append((list(tl.events), tl.stats, tl.spec, tl.evocation))
    return out


def _make_bufs(torch, device, B, dtype):
    z = lambda: torch.zeros((B, MAX_EVENTS), dtype=dtype, device=device)
    return {
        "when": z(),
        "hits": z(),
        "raw": z(),
        "pot": z(),
        "mana": z(),
        "splinter": z(),
        "magical": z(),  # 1 if pyro magical flag set, else -1 sentinel unused
        "kind": z(),
        "length": torch.zeros(B, dtype=torch.int64, device=device),
        "overflow": torch.zeros(B, dtype=torch.bool, device=device),
    }


def _push(torch, bufs, mask, when, hits, raw, pot, mana, splinter, kind_id, magical=None):
    # Profiling: repeated masked Torch indexing here was 30% of cold planning.
    # Scheduler is explicitly CPU float64 on DirectML. Shared NumPy views perform
    # the same selected-row assignments without 24 tiny Torch indexing dispatches.
    import os
    if mask.device.type == "cpu" and os.environ.get("FARM_MAGE_FAST_PUSH", "1") != "0":
        import numpy as np
        selected = mask.detach().numpy()
        length = bufs["length"].detach().numpy()
        bufs["overflow"].numpy()[:] |= selected & (length >= MAX_EVENTS)
        rows = np.flatnonzero(selected & (length < MAX_EVENTS))
        if not len(rows): return
        indices = length[rows]
        values = (when,hits,raw,pot,mana,splinter,kind_id,-1. if magical is None else magical)
        for key,value in zip(("when","hits","raw","pot","mana","splinter","kind","magical"),values):
            if isinstance(value,torch.Tensor):
                value = value.detach().numpy()
                if value.ndim: value = value[rows]
            bufs[key].numpy()[rows,indices] = value
        length[rows] += 1
        TIMELINE_COUNTS['cpu_fast_push_calls'] += 1
        return
    if not bool(mask.any()):
        return
    B = int(mask.shape[0])
    idx = bufs["length"].clamp(max=MAX_EVENTS - 1)
    rows = torch.arange(B, device=mask.device)
    bufs["overflow"] |= mask & (bufs["length"] >= MAX_EVENTS)
    active = mask & (bufs["length"] < MAX_EVENTS)

    def put(key, value):
        buf = bufs[key]
        if not isinstance(value, torch.Tensor):
            value = torch.full((B,), float(value), dtype=buf.dtype, device=buf.device)
        else:
            value = value.to(dtype=buf.dtype)
        buf[rows[active], idx[active]] = value[active]

    put("when", when)
    put("hits", hits)
    put("raw", raw)
    put("pot", pot)
    put("mana", mana)
    put("splinter", splinter)
    put("kind", kind_id)
    if magical is None:
        put("magical", -1.0)
    else:
        put("magical", magical)
    bufs["length"] = bufs["length"] + active.to(bufs["length"].dtype)


def _buffers_to_events(bufs):
    bad = bufs["overflow"].detach().cpu().tolist()
    if any(bad):
        raise TimelineCapacityError({i: "event_capacity" for i, value in enumerate(bad) if value})
    when = bufs["when"].detach().cpu().numpy()
    hits = bufs["hits"].detach().cpu().numpy()
    raw = bufs["raw"].detach().cpu().numpy()
    pot = bufs["pot"].detach().cpu().numpy()
    mana = bufs["mana"].detach().cpu().numpy()
    splinter = bufs["splinter"].detach().cpu().numpy()
    magical = bufs["magical"].detach().cpu().numpy()
    kind = bufs["kind"].detach().cpu().numpy()
    length = bufs["length"].detach().cpu().numpy()
    out = []
    for b in range(when.shape[0]):
        n = int(length[b])
        evs = []
        for i in range(n):
            kid = int(kind[b, i])
            name = KIND_STR.get(kid, "auto")
            extra = {"mana": float(mana[b, i]), "splinter": float(splinter[b, i])}
            mag = float(magical[b, i])
            if mag >= 0.0:
                extra["magical"] = bool(mag >= 0.5)
            evs.append(
                (
                    float(when[b, i]),
                    name,
                    float(hits[b, i]),
                    float(raw[b, i]),
                    float(pot[b, i]),
                    extra,
                )
            )
        out.append(evs)
    return out


def _mage_batch(torch, device, dtype, builds, spec, targets, bound_keys, prepared_stats=None):
    from sunken_sim import mage as mod
    from sunken_sim.shadow import (
        CAST_BACKSWING,
        CAST_POINT,
        FIGHT,
        cast_mana_back,
        sulfuras_echo_chance,
        attack_mana_gain,
        target_hp,
    )
    from sunken_sim.pressure import hero_hp_ratio, max_hp

    B = len(builds)
    T = int(targets)
    CAST_TIME = CAST_POINT + CAST_BACKSWING
    fight = float(FIGHT)
    targets_f = float(T)
    is_fire = spec == "fire"
    is_frost = spec == "frost"
    is_arcane = spec == "arcane"

    # fire swing keeps attack_base (simulate mutates stats["swing"])
    stats_list = []
    for i,b in enumerate(builds):
        st = mod.sheet(b) if prepared_stats is None else dict(prepared_stats[i])
        if is_fire:
            st = dict(st)
            st["swing"] = st["attack_base"]
        stats_list.append(st)

    ones = torch.ones(B, dtype=dtype, device=device)
    zeros = torch.zeros(B, dtype=dtype, device=device)
    true = torch.ones(B, dtype=torch.bool, device=device)
    false = torch.zeros(B, dtype=torch.bool, device=device)

    haste = _stat_vec(torch, device, dtype, stats_list, "haste")
    cd_temp = _stat_vec(torch, device, dtype, stats_list, "cd_temp", 1.0)
    flat_cdr = _stat_vec(torch, device, dtype, stats_list, "flat_cdr")
    mana_max = _stat_vec(torch, device, dtype, stats_list, "mana_max")
    mana_regen = _stat_vec(torch, device, dtype, stats_list, "mana_regen")
    cast_stun_lock = _stat_vec(torch, device, dtype, stats_list, "cast_stun_lock")
    damage_mana_pct = _stat_vec(torch, device, dtype, stats_list, "damage_mana_pct")
    attack_speed = _stat_vec(torch, device, dtype, stats_list, "attack_speed")
    attack_base = _stat_vec(torch, device, dtype, stats_list, "attack_base")
    luck = _stat_vec(torch, device, dtype, stats_list, "luck")
    mastery = _stat_vec(torch, device, dtype, stats_list, "mastery")
    crit = _stat_vec(torch, device, dtype, stats_list, "crit")
    crit_as = _stat_vec(torch, device, dtype, stats_list, "crit_as")
    crit_as_duration = _stat_vec(torch, device, dtype, stats_list, "crit_as_duration")
    frenzy_flag = _stat_vec(torch, device, dtype, stats_list, "frenzy")
    stun_per_swing = _stat_vec(torch, device, dtype, stats_list, "stun_per_swing")
    strength = _stat_vec(torch, device, dtype, stats_list, "str")
    bomb_period = _stat_vec(torch, device, dtype, stats_list, "bomb_period")

    greater = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0UQ"))
    frostbite = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0KT"))
    freezeburn = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0Q7"))
    lance = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0QA"))
    surge = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0KV"))
    burning = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0NZ"))
    lava = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0UP"))
    nova = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0KP"))
    bolt_talent = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0UO"))
    overpowered = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0QB"))
    girdle = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I0UX"))
    pads = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I0UY"))
    staff = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I0UW"))
    mantle = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I0UU"))
    redirect = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I0UV"))
    thunder = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0H5"))
    hellfire = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0H3"))
    amp = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0O0"))
    hydra_helm = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I0US"))
    blazing = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0KR"))
    gloves = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I0UT"))
    has_sulf = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I0BR"))
    splash_ring = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I07O"))
    bloodhowl = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, mod._BLOODHOWL))
    crimson = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, mod._CRIMSON))
    splinter_tal = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, "I0Q9"))

    # flat health for bloodhowl ratio
    flat_hp = torch.tensor(
        [float(mod._flat_health(b)) for b in builds], dtype=dtype, device=device
    )
    max_health = torch.tensor(
        [float(max_hp(mod.BASE_HP, s["str"])) for s in stats_list], dtype=dtype, device=device
    ) + flat_hp
    crimson_cap = torch.where(crimson > 0.5, torch.full((B,), 0.38, dtype=dtype, device=device), ones)

    fire_f = 1.0 if is_fire else 0.0
    frost_f = 1.0 if is_frost else 0.0
    cinder_on = torch.where(
        (torch.full((B,), fire_f, dtype=dtype, device=device) > 0.5)
        | (overpowered > 0.5)
        | (pads > 0.5),
        ones,
        zeros,
    )
    pyro_on = torch.where(
        (torch.full((B,), fire_f, dtype=dtype, device=device) > 0.5) | (overpowered > 0.5),
        ones,
        zeros,
    )
    arcane_v = torch.full((B,), 1.0 if is_arcane else 0.0, dtype=dtype, device=device)
    stacks_on = torch.where((arcane_v > 0.5) | (girdle > 0.5), ones, zeros)  # arcane or girdle
    split_on = torch.where(
        (torch.full((B,), fire_f, dtype=dtype, device=device) > 0.5) | (girdle > 0.5),
        ones,
        zeros,
    )
    cinder_chance = (0.20 + 0.05 * staff) * (1.0 + luck)
    lava_chance = 0.02 * (1.0 + luck)
    max_charges = torch.where(surge > 0.5, torch.full((B,), 8.0, dtype=dtype, device=device), torch.full((B,), 3.0, dtype=dtype, device=device))
    hydra_duration = torch.where(burning > 0.5, torch.full((B,), 14.0, dtype=dtype, device=device), torch.full((B,), 10.0, dtype=dtype, device=device))
    wave_haste = torch.where(mantle > 0.5, 1.20 + haste, 1.0 + haste)
    waves = torch.floor(5.0 * wave_haste + 0.50)
    wave_gap = 1.0 / (1.0 + haste)
    burst_chance = 0.15 + 0.15 * blazing

    # bound scales
    bk = bound_keys
    def bk_scale(name):
        return torch.tensor(
            [0.70 if k == name else 1.0 for k in bk], dtype=dtype, device=device
        )

    # button names for bound: Living Bomb, Ring of Frost, Blizzard, Hydra, Arcane Blast
    bk_bomb = bk_scale("Living Bomb")
    bk_ring = bk_scale("Ring of Frost")
    bk_bliz = bk_scale("Blizzard")
    bk_hydra = bk_scale("Hydra")
    bk_blast = bk_scale("Arcane Blast")

    def cooldown(base, key_scale, flat=0.0):
        if not isinstance(base, torch.Tensor):
            base = torch.full((B,), float(base), dtype=dtype, device=device)
        if not isinstance(flat, torch.Tensor):
            flat = torch.full((B,), float(flat), dtype=dtype, device=device)
        temp = cd_temp * key_scale
        return torch.clamp((base * temp - flat_cdr - flat) / (1.0 + haste), min=0.5)

    cd_bomb = cooldown(8.0, bk_bomb)
    cd_ring = cooldown(13.0, bk_ring)
    cd_bliz = cooldown(13.0, bk_bliz)
    cd_hydra = cooldown(13.0, bk_hydra, 3.0 * hydra_helm)
    cd_blast = cooldown(8.0, bk_blast, 2.0 * amp)
    cd_evo = cooldown(13.0, bk_scale("Evocation"))

    cost_bomb = torch.full((B,), 30.0, dtype=dtype, device=device)
    cost_ring = torch.full((B,), 40.0, dtype=dtype, device=device)
    cost_bliz = torch.full((B,), 40.0, dtype=dtype, device=device)
    cost_hydra = torch.full((B,), 40.0, dtype=dtype, device=device)

    # state
    mana = mana_max.clone()
    mana_time = torch.zeros(B, dtype=dtype, device=device)
    splinter = torch.zeros(B, dtype=dtype, device=device)
    frenzy_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    frenzy_charge = torch.zeros(B, dtype=dtype, device=device)
    crit_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    crit_charge = torch.zeros(B, dtype=dtype, device=device)
    blast_cost = torch.full((B,), 30.0, dtype=dtype, device=device)
    charges = torch.zeros(B, dtype=dtype, device=device)
    cinder = torch.zeros(B, dtype=dtype, device=device)
    blizzard_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    hero_ready = torch.zeros(B, dtype=dtype, device=device)
    busy_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    sulf_armed = torch.zeros(B, dtype=dtype, device=device)

    ready_bomb = torch.zeros(B, dtype=dtype, device=device)
    ready_ring = torch.zeros(B, dtype=dtype, device=device)
    ready_bliz = torch.zeros(B, dtype=dtype, device=device)
    ready_hydra = torch.zeros(B, dtype=dtype, device=device)
    ready_blast = torch.zeros(B, dtype=dtype, device=device)
    ready_evo = torch.zeros(B, dtype=dtype, device=device)
    mana_at = torch.full((B, MAX_MANA), fight, dtype=dtype, device=device)
    mana_on = torch.zeros((B, MAX_MANA), dtype=torch.bool, device=device)

    next_swing = torch.zeros(B, dtype=dtype, device=device)
    next_hell = torch.where(hellfire > 0.5, zeros, torch.full((B,), fight, dtype=dtype, device=device))
    # Concurrent bomb tick chains (CPU heap keeps old push when a new bomb arms).
    bomb_tick_at = torch.full((B, MAX_BOMB_CHAINS), fight, dtype=dtype, device=device)
    bomb_tick_on = torch.zeros((B, MAX_BOMB_CHAINS), dtype=torch.bool, device=device)
    next_hydra_tick = torch.full((B,), fight, dtype=dtype, device=device)
    hydra_ticking = torch.zeros(B, dtype=torch.bool, device=device)
    ring_at = torch.full((B,), fight, dtype=dtype, device=device)
    bolt2_at = torch.full((B,), fight, dtype=dtype, device=device)

    # pending finishes: a chained cast (stale CPU heap time) can start before earlier
    # finishes resolve, so keep a small queue; the head is the earliest finish.
    pq_on = torch.zeros((B, MAX_PENDING), dtype=torch.bool, device=device)
    pq_at = torch.full((B, MAX_PENDING), fight, dtype=dtype, device=device)
    pq_spell = torch.zeros((B, MAX_PENDING), dtype=torch.int64, device=device)
    rows_b = torch.arange(B, device=device)

    # per-target
    bomb_exp = torch.full((B, MAX_T), -1.0, dtype=dtype, device=device)
    bomb_power = torch.zeros((B, MAX_T), dtype=dtype, device=device)
    chill_exp = torch.full((B, MAX_T), -1.0, dtype=dtype, device=device)
    freeze_exp = torch.full((B, MAX_T), -1.0, dtype=dtype, device=device)
    # only first T columns used
    valid_t = torch.zeros((B, MAX_T), dtype=torch.bool, device=device)
    valid_t[:, :T] = True

    # hydra groups
    hy_expire = torch.full((B, MAX_HYDRA), -1.0, dtype=dtype, device=device)
    hy_count = torch.zeros((B, MAX_HYDRA), dtype=dtype, device=device)
    hy_alive = torch.zeros((B, MAX_HYDRA), dtype=torch.bool, device=device)

    # blizzard waves
    wave_at = torch.full((B, MAX_WAVES), fight, dtype=dtype, device=device)
    wave_alive = torch.zeros((B, MAX_WAVES), dtype=torch.bool, device=device)

    bufs = _make_bufs(torch, device, B, dtype)
    alive = torch.ones(B, dtype=torch.bool, device=device)

    def hero_ratio(now):
        # hero_hp_ratio(when, health, 0.0, cap)
        ratios = []
        # vectorize via python? better: approximate with same formula
        # hero_hp_ratio from pressure
        from sunken_sim.pressure import hero_hp_ratio as hhr
        # batch via list for exact parity on bloodhowl (rare)
        # For speed use closed form if available — call per row when bloodhowl
        out_r = torch.ones(B, dtype=dtype, device=device)
        need = bloodhowl > 0.5
        if bool(need.any()):
            for r in need.nonzero(as_tuple=False).view(-1).tolist():
                r = int(r)
                cap = 0.38 if crimson[r] > 0.5 else 1.0
                out_r[r] = float(hhr(float(now[r]), float(max_health[r]), 0.0, cap))
        # non-bloodhowl still may need for nothing in swing; return ones
        return out_r

    def swing_base(now):
        base = attack_base.clone()
        need = bloodhowl > 0.5
        if bool(need.any()):
            ratio = hero_ratio(now)
            missing = 1.0 - ratio
            base = torch.where(need, base * (1.0 - 0.30 * missing), base)
        return base

    def extra_as(now):
        bonus = torch.where(now < frenzy_until, torch.full((B,), 0.32, dtype=dtype, device=device), zeros)
        bonus = bonus + torch.where(now < crit_until, crit_as, zeros)
        return bonus

    def current_as(now):
        return torch.clamp(attack_speed + extra_as(now), min=-0.8, max=4.0)

    def current_swing(now):
        base = swing_base(now)
        if is_fire:
            return base
        return base / (1.0 + current_as(now))

    def hydra_gap(now):
        if not is_fire:
            return torch.full((B,), 1.55, dtype=dtype, device=device)
        return 1.55 / (1.0 + 0.75 * current_as(now))

    def bite_mat(now):
        # [B, MAX_T]
        now_c = now.unsqueeze(1)
        out = torch.ones((B, MAX_T), dtype=dtype, device=device)
        fb = (frostbite > 0.5).unsqueeze(1)
        fr = fb & (freeze_exp > now_c) & valid_t
        ch = fb & ~fr & (chill_exp > now_c) & valid_t
        out = torch.where(fr, torch.full_like(out, 1.12), out)
        out = torch.where(ch, torch.full_like(out, 1.08), out)
        return out

    def bite_all(now):
        bm = bite_mat(now)
        # average over valid targets
        s = (bm * valid_t.to(dtype)).sum(dim=1)
        return torch.where(frostbite > 0.5, s / targets_f, ones)

    def bite0(now):
        return bite_mat(now)[:, 0]

    def alive_hydras(now):
        now_c = now.unsqueeze(1)
        live = hy_alive & (hy_expire > now_c)
        return (hy_count * live.to(dtype)).sum(dim=1)

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

    def push_ev(mask, when, kind_id, hits, raw, pot, magical=None):
        nonlocal mana
        if not bool(mask.any()):
            return
        note_dmg_mana(mask)
        _push(torch, bufs, mask, when, hits, raw, pot, mana, splinter, kind_id, magical=magical)
        # cinder / lava on non-disease
        # disease=True skips — caller handles via skip_cinder flag
        return

    def gain_cinder(mask, instances, disease, now):
        nonlocal cinder
        if not bool(mask.any()):
            return
        if not isinstance(instances, torch.Tensor):
            instances = torch.full((B,), float(instances), dtype=dtype, device=device)
        do = mask & ~disease & (instances > 0)
        cin = do & (cinder_on > 0.5) & (cinder < 100.0)
        cinder = torch.where(cin, torch.minimum(ones * 100.0, cinder + cinder_chance * instances), cinder)
        lav = do & (lava > 0.5)
        if bool(lav.any()):
            spawn_hydras(lav, now, lava_chance * instances, hydra_duration * 0.5)

    def spawn_hydras(mask, now, count, duration):
        nonlocal hy_expire, hy_count, hy_alive, hydra_ticking, next_hydra_tick
        if not bool(mask.any()):
            return
        if not isinstance(count, torch.Tensor):
            count = torch.full((B,), float(count), dtype=dtype, device=device)
        if not isinstance(duration, torch.Tensor):
            duration = torch.full((B,), float(duration), dtype=dtype, device=device)
        # reclaim expired groups so lava procs can keep appending (CPU list is unbounded).
        # Only touch rows in mask — now may be fight/sentinel for other batch rows.
        now_c = now.unsqueeze(1)
        still = hy_alive & (hy_expire > now_c)
        hy_alive = torch.where(mask.unsqueeze(1), still, hy_alive)
        hy_count = torch.where(hy_alive, hy_count, torch.zeros_like(hy_count))
        room = 10.0 - alive_hydras(now)
        count = torch.minimum(count, torch.clamp(room, min=0.0))
        do = mask & (count > 0)
        if not bool(do.any()):
            return
        rows = torch.arange(B, device=device)
        for r in rows[do].tolist():
            r = int(r)
            free = (~hy_alive[r]).nonzero(as_tuple=False).view(-1)
            if free.numel() == 0:
                continue  # CPU list is unbounded; 256 + reclaim covers lava
            j = int(free[0])
            hy_alive[r, j] = True
            hy_expire[r, j] = float(now[r] + duration[r])
            hy_count[r, j] = float(count[r])
        # arm tick
        fresh = do & ~hydra_ticking
        hydra_ticking = hydra_ticking | do
        next_hydra_tick = torch.where(fresh, now + hydra_gap(now), next_hydra_tick)

    def note_splinter(mask, froze):
        nonlocal splinter
        do = mask & (splinter_tal > 0.5)
        if not bool(do.any()):
            return
        add = torch.where(froze, torch.full((B,), 4.0, dtype=dtype, device=device), torch.full((B,), 2.0, dtype=dtype, device=device))
        splinter = torch.where(do, torch.minimum(torch.full((B,), 30.0, dtype=dtype, device=device), splinter + add), splinter)

    def start_bomb(mask, index_t, now, power):
        """index_t: [B] long target index."""
        nonlocal bomb_exp, bomb_power, bomb_tick_at, bomb_tick_on
        if not bool(mask.any()):
            return
        if not isinstance(power, torch.Tensor):
            power = torch.full((B,), float(power), dtype=dtype, device=device)
        rows = torch.arange(B, device=device)
        # gather current
        cur_exp = bomb_exp[rows, index_t]
        fresh = mask & (cur_exp <= now)
        # if no bomb active at all, arm tick
        any_active = ((bomb_exp > now.unsqueeze(1)) & valid_t).any(dim=1)
        arm = fresh & ~any_active
        if bool(arm.any()):
            # schedule into first free chain slot (CPU push onto heap)
            rows = torch.arange(B, device=device)
            for r in rows[arm].tolist():
                r = int(r)
                free = (~bomb_tick_on[r]).nonzero(as_tuple=False).view(-1)
                if free.numel() == 0:
                    # overwrite soonest
                    j = int(bomb_tick_at[r].argmin().item())
                else:
                    j = int(free[0])
                bomb_tick_on[r, j] = True
                bomb_tick_at[r, j] = float(now[r] + bomb_period[r])
        # set power
        new_pow = torch.where(fresh, power, torch.maximum(bomb_power[rows, index_t], power))
        bomb_power[rows[mask], index_t[mask]] = new_pow[mask]
        bomb_exp[rows[mask], index_t[mask]] = (now + 8.0)[mask]

    def apply_chill(mask, index_t, now, duration, explicit_freeze=0.0):
        nonlocal chill_exp, freeze_exp, bomb_exp, bomb_power
        if not bool(mask.any()):
            return
        if not isinstance(duration, torch.Tensor):
            duration = torch.full((B,), float(duration), dtype=dtype, device=device)
        if not isinstance(explicit_freeze, torch.Tensor):
            explicit_freeze = torch.full((B,), float(explicit_freeze), dtype=dtype, device=device)
        rows = torch.arange(B, device=device)
        cur_chill = chill_exp[rows, index_t]
        fresh = mask & (cur_chill <= now)
        chill_exp[rows[mask], index_t[mask]] = torch.maximum(cur_chill, now + duration)[mask]
        # explicit freeze
        ef = mask & (explicit_freeze > 0)
        if bool(ef.any()):
            freeze_exp[rows[ef], index_t[ef]] = torch.maximum(freeze_exp[rows, index_t], now + explicit_freeze)[ef]
        # frostbite fresh -> 1.5 freeze
        fb = mask & (frostbite > 0.5) & fresh & (explicit_freeze <= 0)
        if bool(fb.any()):
            freeze_exp[rows[fb], index_t[fb]] = torch.maximum(freeze_exp[rows, index_t], now + 1.5)[fb]
        # freezeburn bomb
        fbomb = mask & (freezeburn > 0.5) & (bomb_exp[rows, index_t] <= now)
        if bool(fbomb.any()):
            pow_ = torch.where(fresh, torch.full((B,), 0.20, dtype=dtype, device=device), torch.full((B,), 0.08, dtype=dtype, device=device))
            start_bomb(fbomb, index_t, now, pow_)
        froze = (explicit_freeze > 0) | ((frostbite > 0.5) & fresh)
        note_splinter(mask, froze)

    def apply_chill_all(mask, now, duration, explicit_freeze=0.0):
        for ti in range(T):
            idx = torch.full((B,), ti, dtype=torch.int64, device=device)
            apply_chill(mask, idx, now, duration, explicit_freeze)

    def reset_chance():
        # CPU: 0 unless arcane / Overpowered / pads; 0.15 (+ arcane 0.05 + 0.002*(mastery+splinter)) (+ staff 0.05)
        base = (arcane_v > 0.5) | (overpowered > 0.5) | (pads > 0.5)
        chance = torch.full((B,), 0.15, dtype=dtype, device=device)
        if is_arcane:
            chance = chance + (0.05 + 0.002 * (mastery + splinter))
        chance = torch.where(staff > 0.5, chance + 0.05, chance)
        chance = torch.where(base, chance, zeros)
        return torch.clamp(chance, max=1.0)

    def on_hero_auto(mask, now):
        nonlocal mana, frenzy_charge, frenzy_until, crit_charge, crit_until
        if not bool(mask.any()):
            return
        mana = torch.where(mask, torch.minimum(mana_max, mana + attack_mana_gain_vec()), mana)
        # frenzy
        fr = mask & (frenzy_flag > 0) & (now >= frenzy_until)
        frenzy_charge = torch.where(fr, frenzy_charge + 0.18, frenzy_charge)
        proc_fr = fr & (frenzy_charge >= 1.0)
        frenzy_charge = torch.where(proc_fr, frenzy_charge - 1.0, frenzy_charge)
        frenzy_until = torch.where(proc_fr, now + 5.0, frenzy_until)
        # crit as
        ca = mask & (crit_as > 0) & (crit_as_duration > 0) & (now >= crit_until)
        frenzy_like = torch.minimum(crit, torch.full((B,), 100.0, dtype=dtype, device=device)) / 100.0
        crit_charge = torch.where(ca, crit_charge + frenzy_like, crit_charge)
        proc_ca = ca & (crit_charge >= 1.0)
        crit_charge = torch.where(proc_ca, crit_charge - 1.0, crit_charge)
        crit_until = torch.where(proc_ca, now + crit_as_duration, crit_until)

    def attack_mana_gain_vec():
        # use scalar helper per stats — batch via list
        vals = []
        for s in stats_list:
            vals.append(float(attack_mana_gain(s)))
        return torch.tensor(vals, dtype=dtype, device=device)

    cast_refund_vals = None

    def pay_cast(mask, cost, now):
        nonlocal mana
        recover(now, mask)
        ok = mask & (mana >= cost)
        # cast_mana_back per stats
        refund = []
        for i, s in enumerate(stats_list):
            c = float(cost[i]) if isinstance(cost, torch.Tensor) else float(cost)
            refund.append(float(cast_mana_back(c, s)))
        refund_t = torch.tensor(refund, dtype=dtype, device=device)
        mana = torch.where(ok, torch.minimum(mana_max, mana - cost + refund_t), mana)
        return ok

    def add_ev(mask, when, kind_id, hits, raw, pot, disease=False, magical=None):
        """Mirror simulate.add + gain_cinder."""
        if not bool(mask.any()):
            return
        if not isinstance(hits, torch.Tensor):
            hits = torch.full((B,), float(hits), dtype=dtype, device=device)
        if not isinstance(raw, torch.Tensor):
            raw = torch.full((B,), float(raw), dtype=dtype, device=device)
        if not isinstance(pot, torch.Tensor):
            pot = torch.full((B,), float(pot), dtype=dtype, device=device)
        do = mask & (hits > 0) & (when < fight)
        if not bool(do.any()):
            return
        note_dmg_mana(do)
        mag_v = None
        if magical is not None:
            if isinstance(magical, torch.Tensor):
                mag_v = magical.to(dtype)
            else:
                mag_v = torch.full((B,), 1.0 if magical else 0.0, dtype=dtype, device=device)
        _push(torch, bufs, do, when, hits, raw, pot, mana, splinter, kind_id, magical=mag_v)
        dis = disease if isinstance(disease, torch.Tensor) else (true if disease else false)
        if isinstance(disease, bool):
            dis = true if disease else false
        gain_cinder(do, hits, dis, when)

    # --- resolve helpers ---
    def cast_lance(mask, now):
        if not bool(mask.any()):
            return
        do = mask & (lance > 0.5)
        if not bool(do.any()):
            return
        # pick first index with chill_exp <= now, else 0
        now_c = now.unsqueeze(1)
        cold = (chill_exp <= now_c) & valid_t
        # first True along T, else 0
        # use cumsum trick
        idx = torch.zeros(B, dtype=torch.int64, device=device)
        for ti in range(T - 1, -1, -1):
            idx = torch.where(cold[:, ti], torch.full((B,), ti, dtype=torch.int64, device=device), idx)
        taken = bite_mat(now)[torch.arange(B, device=device), idx]
        add_ev(do, now, K_LANCE, ones, taken, taken)
        apply_chill(do, idx, now, 4.0)

    def finish_blast(mask, now):
        nonlocal charges, cinder, blast_cost, chill_exp, bomb_exp, bomb_power, bolt2_at
        if not bool(mask.any()):
            return
        mult = 1.20 ** charges
        quarter = torch.where(split_on > 0.5, torch.full((B,), 0.25, dtype=dtype, device=device), ones)
        taken = bite_all(now)
        # split blast first
        split_m = mask & (split_on > 0.5)
        add_ev(split_m, now, K_BLAST, torch.full((B,), 3.0, dtype=dtype, device=device), 3.0 * taken * mult * quarter, 3.0 * taken)
        # pyro
        thresh = torch.where(greater > 0.5, torch.full((B,), 50.0, dtype=dtype, device=device), torch.full((B,), 30.0, dtype=dtype, device=device))
        pyro_m = mask & (pyro_on > 0.5) & (cinder >= thresh)
        if bool(pyro_m.any()):
            spent = cinder.clone()
            cinder = torch.where(pyro_m, zeros, cinder)
            mag = greater > 0.5
            add_ev(
                pyro_m, now, K_PYRO, torch.full((B,), targets_f, dtype=dtype, device=device),
                targets_f * taken * spent,
                torch.where(mag, targets_f * taken, zeros),
                disease=true,
                magical=mag.to(dtype),
            )
        # nova
        nova_m = mask & (nova > 0.5)
        if bool(nova_m.any()):
            # target_hp(now)
            thp = torch.tensor([float(target_hp(float(now[i]))) for i in range(B)], dtype=dtype, device=device)
            chance = torch.where(thp > 0.90, ones, torch.full((B,), 0.10, dtype=dtype, device=device))
            weight = targets_f * chance * taken
            add_ev(nova_m, now, K_NOVA, weight, weight, weight)
        # frostfire bolt
        bolt_m = mask & (bolt_talent > 0.5)
        if bool(bolt_m.any()):
            chilled = chill_exp[:, 0] > now
            bombed = bomb_exp[:, 0] > now
            bonus = torch.where(chilled, torch.full((B,), 1.25, dtype=dtype, device=device), ones) * torch.where(
                bombed, torch.full((B,), 1.25, dtype=dtype, device=device), ones
            )
            b0 = bite0(now)
            add_ev(bolt_m, now, K_BOLT, ones, b0 * bonus, b0 * bonus)
            splash_m = bolt_m & chilled & (T > 1)
            if T > 1 and bool(splash_m.any()):
                splash = (targets_f - 1.0) * taken * bonus * 0.15
                add_ev(splash_m, now, K_BOLT_SPLASH, torch.full((B,), targets_f - 1.0, dtype=dtype, device=device), splash, splash)
            both = bolt_m & chilled & bombed
            bolt2_at = torch.where(both, now + 0.5, bolt2_at)
            chill_exp[:, 0] = torch.where(both, now, chill_exp[:, 0])
            bomb_exp[:, 0] = torch.where(both, now, bomb_exp[:, 0])
            bomb_power[:, 0] = torch.where(both, zeros, bomb_power[:, 0])
        # main blast
        add_ev(mask, now, K_BLAST, ones, taken * mult * quarter, taken)
        # stacks — only girdle on fire/frost
        stack_m = mask & (stacks_on > 0.5) & (charges < max_charges)
        gain = torch.where((surge > 0.5) & (charges < 3.0), torch.full((B,), 2.0, dtype=dtype, device=device), ones)
        charges = torch.where(stack_m, torch.minimum(max_charges, charges + gain), charges)
        blast_cost = torch.where(stack_m, 30.0 * (1.15 ** charges), blast_cost)

    def do_resolve(mask, spell, now):
        nonlocal blizzard_until, wave_at, wave_alive, ring_at
        if not bool(mask.any()):
            return
        cast_lance(mask, now)
        th = mask & (thunder > 0.5)
        if bool(th.any()):
            taken = 0.18 * targets_f * bite_all(now)
            add_ev(th, now, K_THUNDER, torch.full((B,), 0.18 * targets_f, dtype=dtype, device=device), taken, taken)
        # Living Bomb
        m = mask & (spell == S_BOMB)
        if bool(m.any()):
            # index = argmin bomb_exp
            idx = bomb_exp[:, :T].argmin(dim=1)
            rows = torch.arange(B, device=device)
            already = bomb_exp[rows, idx] > now
            fb = m & already
            if bool(fb.any()):
                taken = targets_f * bite_all(now)
                add_ev(fb, now, K_FIREBOMB, torch.full((B,), targets_f, dtype=dtype, device=device), taken, taken)
            start_bomb(m, idx, now, 1.0)
            apply_chill(m & (freezeburn > 0.5), idx, now, 4.0)
        # Ring
        m = mask & (spell == S_RING)
        ring_at = torch.where(m, now + 1.65, ring_at)
        # Blizzard
        m = mask & (spell == S_BLIZ)
        if bool(m.any()):
            blizzard_until = torch.where(m, now + waves * wave_gap, blizzard_until)
            # schedule waves — per-row loop for variable wave count
            for r in m.nonzero(as_tuple=False).view(-1).tolist():
                r = int(r)
                n_w = int(waves[r].item())
                n_w = min(n_w, MAX_WAVES)
                gap = float(wave_gap[r])
                t0 = float(now[r])
                for w in range(n_w):
                    wave_alive[r, w] = True
                    wave_at[r, w] = t0 + w * gap
        # Hydra
        m = mask & (spell == S_HYDRA)
        if bool(m.any()):
            spawn_hydras(m, now, 3.0, hydra_duration)
        # Blast
        m = mask & (spell == S_BLAST)
        if bool(m.any()):
            finish_blast(m, now)
        # Evocation: three mana ticks at +1/+2/+3 s (CPU push drops when >= FIGHT)
        m = mask & (spell == S_EVO)
        if bool(m.any()):
            for r in m.nonzero(as_tuple=False).view(-1).tolist():
                r = int(r)
                t0 = float(now[r])
                for k in (1.0, 2.0, 3.0):
                    when = t0 + k
                    if when >= fight:
                        continue
                    free = (~mana_on[r]).nonzero(as_tuple=False).view(-1)
                    if len(free) == 0:
                        raise RuntimeError("MAX_MANA exceeded")
                    j = int(free[0])
                    mana_on[r, j] = True
                    mana_at[r, j] = when

    def do_cast(mask, spell, now):
        nonlocal hero_ready, busy_until, ready_bomb, ready_ring, ready_bliz, ready_hydra, ready_blast, ready_evo
        nonlocal sulf_armed, mana
        if not bool(mask.any()):
            return
        # costs
        cost = torch.zeros(B, dtype=dtype, device=device)
        cost = torch.where(spell == S_BOMB, cost_bomb, cost)
        cost = torch.where(spell == S_RING, cost_ring, cost)
        cost = torch.where(spell == S_BLIZ, cost_bliz, cost)
        cost = torch.where(spell == S_HYDRA, cost_hydra, cost)
        cost = torch.where(spell == S_BLAST, blast_cost, cost)
        ok = pay_cast(mask, cost, now)
        okm = ok
        if not bool(okm.any()):
            return
        # duration
        dur = torch.zeros(B, dtype=dtype, device=device)
        dur = torch.where(spell == S_BOMB, cd_bomb, dur)
        dur = torch.where(spell == S_RING, cd_ring, dur)
        dur = torch.where(spell == S_BLIZ, cd_bliz, dur)
        dur = torch.where(spell == S_HYDRA, cd_hydra, dur)
        dur = torch.where(spell == S_BLAST, cd_blast, dur)
        dur = torch.where(spell == S_EVO, cd_evo, dur)
        sulf_armed = torch.where(okm & (has_sulf > 0.5) & (sulf_armed < 0.5), ones, sulf_armed)
        busy = now + CAST_POINT + CAST_BACKSWING + cast_stun_lock  # CPU summation order (ulp ties)
        busy_until = torch.where(okm, busy, busy_until)
        hero_ready = torch.where(okm, busy, hero_ready)
        chance = reset_chance()
        # redirect to Arcane Blast
        # if redirect and blast in ready: target = blast
        # ready[name] = now + duration * (1-chance) if target==name else now+duration; and reduce blast remaining
        use_redirect = okm & (redirect > 0.5) & (spell != S_BLAST)
        # self reset
        self_reset = okm & ~use_redirect
        factor = 1.0 - chance
        ready_bomb = torch.where(self_reset & (spell == S_BOMB), now + dur * factor, ready_bomb)
        ready_ring = torch.where(self_reset & (spell == S_RING), now + dur * factor, ready_ring)
        ready_bliz = torch.where(self_reset & (spell == S_BLIZ), now + dur * factor, ready_bliz)
        ready_hydra = torch.where(self_reset & (spell == S_HYDRA), now + dur * factor, ready_hydra)
        ready_blast = torch.where(self_reset & (spell == S_BLAST), now + dur * factor, ready_blast)
        ready_evo = torch.where(self_reset & (spell == S_EVO), now + dur * factor, ready_evo)
        # redirect path: name gets full CD, blast remaining * (1-chance)
        ready_bomb = torch.where(use_redirect & (spell == S_BOMB), now + dur, ready_bomb)
        ready_ring = torch.where(use_redirect & (spell == S_RING), now + dur, ready_ring)
        ready_bliz = torch.where(use_redirect & (spell == S_BLIZ), now + dur, ready_bliz)
        ready_hydra = torch.where(use_redirect & (spell == S_HYDRA), now + dur, ready_hydra)
        ready_evo = torch.where(use_redirect & (spell == S_EVO), now + dur, ready_evo)
        rem = torch.clamp(ready_blast - now, min=0.0)
        ready_blast = torch.where(use_redirect, now + rem * factor, ready_blast)
        # pending finish
        full = okm & pq_on.all(dim=1)
        if bool(full.any()):
            raise RuntimeError("mage GPU timeline: MAX_PENDING exceeded")
        slot = (~pq_on).to(torch.int64).argmax(dim=1)  # first free slot
        r = rows_b[okm]
        k = slot[okm]
        pq_on[r, k] = True
        pq_at[r, k] = (now + CAST_POINT)[okm]
        pq_spell[r, k] = spell[okm]

    def choose(now):
        spell = torch.zeros(B, dtype=torch.int64, device=device)
        has = torch.zeros(B, dtype=torch.bool, device=device)
        # order: Living Bomb if any expiry < now+1; Hydra if fire; Blizzard if frost; Arcane Blast; Ring
        bomb_soon = ((bomb_exp < (now + 1.0).unsqueeze(1)) & valid_t).any(dim=1)
        # Living Bomb
        take = bomb_soon & (ready_bomb <= now) & (mana >= cost_bomb)
        spell = torch.where(take, torch.full_like(spell, S_BOMB), spell)
        has = has | take
        if is_frost:
            take = ~has & (ready_bliz <= now) & (now >= blizzard_until) & (mana >= cost_bliz)
            spell = torch.where(take, torch.full_like(spell, S_BLIZ), spell)
            has = has | take
        if is_fire:
            take = ~has & (ready_hydra <= now) & (alive_hydras(now) < 10.0) & (mana >= cost_hydra)
            spell = torch.where(take, torch.full_like(spell, S_HYDRA), spell)
            has = has | take
        take = ~has & (ready_blast <= now) & (mana >= blast_cost)
        spell = torch.where(take, torch.full_like(spell, S_BLAST), spell)
        has = has | take
        take = ~has & (ready_ring <= now) & (mana >= cost_ring)
        spell = torch.where(take, torch.full_like(spell, S_RING), spell)
        has = has | take
        if is_arcane:
            # CPU: some ordered button ready but unaffordable -> Evocation if ready (cost 0)
            waiting = (bomb_soon & (ready_bomb <= now)) | (ready_blast <= now) | (ready_ring <= now)
            take = ~has & waiting & (ready_evo <= now) & (mana >= 0.0)
            spell = torch.where(take, torch.full_like(spell, S_EVO), spell)
            has = has | take
        return spell, has

    def on_swing(mask, now):
        nonlocal next_swing, hero_ready, sulf_armed
        if not bool(mask.any()):
            return
        # if busy, defer
        defer = mask & (now < busy_until)
        next_swing = torch.where(defer, busy_until, next_swing)
        do = mask & ~defer
        if not bool(do.any()):
            return
        on_hero_auto(do, now)
        taken = bite_all(now)
        add_ev(do, now, K_AUTO, ones, taken, taken)
        # sulfuras
        sulf_m = do & (has_sulf > 0.5) & (sulf_armed > 0.5)
        sulf_armed = torch.where(sulf_m, zeros, sulf_armed)
        add_ev(sulf_m, now, K_SULF, torch.full((B,), targets_f, dtype=dtype, device=device), torch.full((B,), targets_f, dtype=dtype, device=device), zeros)
        # echo
        echo = torch.tensor([float(sulfuras_echo_chance(float(luck[i]))) for i in range(B)], dtype=dtype, device=device)
        echo_m = do & (has_sulf > 0.5)
        add_ev(echo_m, now, K_SULF_ECHO, echo, echo, zeros)
        # splash I07O
        add_ev(do & (splash_ring > 0.5), now, K_SPLASH, torch.full((B,), targets_f, dtype=dtype, device=device), torch.full((B,), targets_f, dtype=dtype, device=device), torch.full((B,), targets_f, dtype=dtype, device=device))
        hero_ready = torch.where(do, torch.maximum(hero_ready, now + stun_per_swing), hero_ready)
        next_swing = torch.where(do, now + current_swing(now) + stun_per_swing, next_swing)

    def on_bomb_tick(mask, now):
        nonlocal bomb_tick_at, bomb_tick_on
        if not bool(mask.any()):
            return
        now_c = now.unsqueeze(1)
        due = mask.unsqueeze(1) & bomb_tick_on & (bomb_tick_at <= now_c + 1e-12) & (bomb_tick_at < fight)
        if not bool(due.any()):
            return
        # Emit once per due chain (CPU heap can fire overlapping chains).
        for ci in range(MAX_BOMB_CHAINS):
            d = due[:, ci]
            if not bool(d.any()):
                continue
            active = d.unsqueeze(1) & (bomb_exp > now_c) & (bomb_power > 0) & valid_t
            any_act = active.any(dim=1)
            if bool(active.any()):
                for ti in range(T):
                    m = active[:, ti]
                    if not bool(m.any()):
                        continue
                    power = bomb_power[:, ti]
                    taken = power * bite_mat(now)[:, ti]
                    add_ev(m, now, K_BOMB, power, taken, taken)
                    burst = burst_chance * power * targets_f * bite_all(now)
                    add_ev(m, now, K_BURST, burst_chance * power * targets_f, burst, burst)
            # re-arm this chain if anything was active; else stop chain
            bomb_tick_at[:, ci] = torch.where(
                d & any_act,
                now + bomb_period,
                torch.where(
                    d,
                    torch.full((B,), fight, dtype=dtype, device=device),
                    bomb_tick_at[:, ci],
                ),
            )
            bomb_tick_on[:, ci] = torch.where(d & any_act, true, torch.where(d, false, bomb_tick_on[:, ci]))

    def on_wave(mask, now):
        nonlocal wave_at, wave_alive
        if not bool(mask.any()):
            return
        # find waves due at this moment
        now_c = now.unsqueeze(1)
        due = mask.unsqueeze(1) & wave_alive & (wave_at <= now_c + 1e-12) & (wave_at < fight)
        # process earliest due per row — may have multiple at same time rarely
        for wi in range(MAX_WAVES):
            d = due[:, wi]
            if not bool(d.any()):
                continue
            # only fire if wave_at == moment approximately — caller passes moment match
            for ti in range(T):
                taken = bite_mat(now)[:, ti]
                idx = torch.full((B,), ti, dtype=torch.int64, device=device)
                add_ev(d, now, K_BLIZ, ones, taken, taken)
                apply_chill(d, idx, now, 3.0)
            wave_alive = wave_alive.clone()
            wave_alive[:, wi] = torch.where(d, false, wave_alive[:, wi])
            wave_at[:, wi] = torch.where(d, torch.full((B,), fight, dtype=dtype, device=device), wave_at[:, wi])

    def on_ring(mask, now):
        nonlocal ring_at
        if not bool(mask.any()):
            return
        freeze_for = torch.where(gloves > 0.5, torch.full((B,), 3.0, dtype=dtype, device=device), torch.full((B,), 2.0, dtype=dtype, device=device))
        for ti in range(T):
            idx = torch.full((B,), ti, dtype=torch.int64, device=device)
            already = chill_exp[:, ti] > now
            taken = bite_mat(now)[:, ti]
            add_ev(mask, now, K_RING, ones, taken, taken)
            apply_chill(mask & already, idx, now, 3.5, freeze_for)
            apply_chill(mask & ~already, idx, now, 3.5, 0.0)
        ring_at = torch.where(mask, torch.full((B,), fight, dtype=dtype, device=device), ring_at)

    def on_bolt2(mask, now):
        nonlocal bolt2_at
        if not bool(mask.any()):
            return
        taken = bite0(now)
        add_ev(mask, now, K_BOLT, ones, taken, taken)
        bolt2_at = torch.where(mask, torch.full((B,), fight, dtype=dtype, device=device), bolt2_at)

    def on_hydra(mask, now):
        nonlocal next_hydra_tick, hydra_ticking
        if not bool(mask.any()):
            return
        count = alive_hydras(now)
        stop = mask & (count <= 0)
        hydra_ticking = hydra_ticking & ~stop
        next_hydra_tick = torch.where(stop, torch.full((B,), fight, dtype=dtype, device=device), next_hydra_tick)
        do = mask & (count > 0)
        if not bool(do.any()):
            return
        bitten = bite_all(now)
        primary = count * bitten * torch.where(burning > 0.5, torch.full((B,), 1.20, dtype=dtype, device=device), ones)
        others = max(0, T - 1)
        cleave = count * 0.20 * float(others) * bitten
        add_ev(do, now, K_HYDRA, count, primary, primary)
        if others > 0:
            add_ev(do & (cleave > 0), now, K_CLEAVE, count * float(others), cleave, cleave)
        next_hydra_tick = torch.where(do, now + hydra_gap(now), next_hydra_tick)

    def on_hell(mask, now):
        nonlocal next_hell
        if not bool(mask.any()):
            return
        taken = targets_f * bite_all(now)
        add_ev(mask, now, K_HELL, torch.full((B,), targets_f, dtype=dtype, device=device), taken, taken)
        next_hell = torch.where(mask, now + 1.25, next_hell)

    # --- main loop ---
    # seed swing at 0; hellfire at 0 if talent
    steps = 0
    while bool(alive.any()) and steps < MAX_STEPS:
        steps += 1
        pq_t = torch.where(pq_on, pq_at, torch.full_like(pq_at, fight))
        pq_head = pq_t.argmin(dim=1)  # ties: lowest slot; finishes are strictly increasing
        pending_at = pq_t[rows_b, pq_head]
        pending_spell = pq_spell[rows_b, pq_head]
        pending_active = pq_on[rows_b, pq_head]
        pending_t = torch.where(pending_active, pending_at, torch.full_like(pending_at, fight))
        wave_next = torch.where(
            wave_alive.any(dim=1),
            torch.where(wave_alive, wave_at, torch.full_like(wave_at, fight)).min(dim=1).values,
            torch.full((B,), fight, dtype=dtype, device=device),
        )
        moment = next_swing.clone()
        bomb_next = torch.where(
            bomb_tick_on.any(dim=1),
            torch.where(bomb_tick_on, bomb_tick_at, torch.full_like(bomb_tick_at, fight)).min(dim=1).values,
            torch.full((B,), fight, dtype=dtype, device=device),
        )
        mana_next = torch.where(mana_on, mana_at, torch.full_like(mana_at, fight)).min(dim=1).values
        for clock in (next_hell, bomb_next, next_hydra_tick, ring_at, bolt2_at, pending_t, wave_next, mana_next):
            moment = torch.minimum(moment, clock)

        alive = alive & (moment < fight)

        # CPU order: hero acts while ready <= next heap time, then one heap
        # event. Same-time ties follow push seq (bomb/hydra usually before finish).
        # Match: hero → world clocks → pending finish.
        m_pend = alive & pending_active & (pending_at <= moment) & (pending_at < fight)
        m_hero = alive & (hero_ready <= moment) & (hero_ready < fight)
        m_acted = false.clone()

        def hero_loop(m_try):
            """CPU inner loop: while hero_ready <= heap time read before casting."""
            if not bool(m_try.any()):
                return false
            recover(hero_ready, m_try)
            spell, has_spell = choose(hero_ready)
            cast_m = m_try & has_spell
            if not bool(cast_m.any()):
                return cast_m
            do_cast(cast_m, spell, hero_ready)
            # the heap time is stale: a second cast can land before the first finish.
            chain = cast_m
            while True:
                nxt = chain & (hero_ready <= moment) & (hero_ready < fight)
                if not bool(nxt.any()):
                    break
                recover(hero_ready, nxt)
                spell, has_spell = choose(hero_ready)
                chain = nxt & has_spell
                if not bool(chain.any()):
                    break
                do_cast(chain, spell, hero_ready)
            return cast_m

        if bool(m_hero.any()):
            m_acted = m_acted | hero_loop(m_hero)

        m_fire = alive & ~m_acted & (moment < fight)
        popped = false.clone()

        def pop(m_ev):
            """Before each further same-time heap pop the CPU re-runs the hero loop
            (recover at hero_ready, maybe cast) and recovers to the event time."""
            nonlocal m_fire, m_acted, popped
            m_ev = m_ev & m_fire
            again = m_ev & popped
            if bool(again.any()):
                cast = hero_loop(again & (hero_ready <= moment) & (hero_ready < fight))
                if bool(cast.any()):
                    m_acted = m_acted | cast
                    m_fire = m_fire & ~cast  # rest of this timestamp next step
                    m_ev = m_ev & ~cast
                    again = again & ~cast
                recover(moment, again)
            popped = popped | m_ev
            return m_ev

        if bool(m_fire.any()):
            recover(moment, m_fire)
            # Evocation ticks are pushed 1-3 s ahead, so on exact ties they usually
            # carry the lowest heap seq: pop them first.
            m_mana = pop(mana_next == moment)
            if bool(m_mana.any()):  # one tick per step (CPU pops one heap event per loop)
                slot = torch.where(mana_on, mana_at, torch.full_like(mana_at, fight)).argmin(dim=1)
                rows = torch.arange(B, device=device)
                mana = torch.where(m_mana, mana + 0.10 * (mana_max - mana), mana)
                mana_on[rows[m_mana], slot[m_mana]] = False
                mana_at[rows[m_mana], slot[m_mana]] = fight
            on_swing(pop(next_swing == moment), moment)
            on_hell(pop(next_hell == moment), moment)
            on_hydra(pop(next_hydra_tick == moment), moment)
            on_bomb_tick(pop(bomb_next == moment), moment)
            on_ring(pop(ring_at == moment), moment)
            on_bolt2(pop(bolt2_at == moment), moment)
            on_wave(pop(wave_next == moment), moment)

        if bool(m_pend.any()):
            # finish after world events at the same timestamp (CPU heap seq)
            still = m_pend & ~m_acted
            if bool((still & popped).any()):
                m_fire = m_fire | still  # finish is one more pop at this timestamp
                still = pop(still)
            if bool(still.any()):
                recover(pending_at, still)
                do_resolve(still, pending_spell, pending_at)
                m_acted = m_acted | still
                # pop the head (rows where the hero acted keep theirs for the next step)
                r = rows_b[still]
                k = pq_head[still]
                pq_on[r, k] = False
                pq_at[r, k] = fight

        # An overflowed row is rejected, not allowed to keep producing a clipped
        # tape. Other rows continue independently to completion.
        alive = alive & (m_acted | (moment < fight)) & ~bufs["overflow"]

    recover(torch.full((B,), fight, dtype=dtype, device=device))
    bad = bufs["overflow"] | alive
    indices = (~bad).nonzero(as_tuple=True)[0]
    events_list = _buffers_to_events({key: value[indices] for key, value in bufs.items()})
    out = [None] * B
    for i, events in zip(indices.detach().cpu().tolist(), events_list):
        out[i] = (events, stats_list[i], spec, is_arcane)
    if bool(bad.any()):
        reasons = {
            i: "event_capacity" if overflow else "step_limit"
            for i, (overflow, unfinished) in enumerate(zip(
                bufs["overflow"].detach().cpu().tolist(), alive.detach().cpu().tolist()
            )) if overflow or unfinished
        }
        raise TimelineCapacityError(reasons, out)
    return out
