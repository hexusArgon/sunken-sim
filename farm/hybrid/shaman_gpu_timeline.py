# -*- coding: utf-8 -*-
"""GPU next-event timeline for Shaman.

Elemental: batched float64 state machine (pending + choose + attack/incoming/bolt).
Restoration / Enhancement: CPU events_for until spirit slots pass parity.

Clocks run float64 on CPU when DirectML lacks f64; kind-score stays on DirectML.
CPU simulate() / events_for remains the parity oracle (rel/abs <= 1e-4).

Event tuples match sunken_sim.shaman.events_for for farm.hybrid.shaman kind-score:
  ("deal", name, raw, now, count, attack, magical, mastery, crit, fusion, auto_scale)
  ("splash", name, raw, now, count)
  ("echo", name, raw, now)
"""

from __future__ import annotations

MAX_EVENTS = 768
MAX_STEPS = 200000
MAX_BL = 48  # bloodlust windows

# Spell ids for pending / choose
S_NONE = 0
S_CHAIN = 1
S_SHIELD = 2
S_LAVA = 3
S_TOTEM = 4
S_SPIRIT = 5

# Buffer kind
K_DEAL = 0.0
K_SPLASH = 1.0
K_ECHO = 2.0


def _stat_vec(torch, device, dtype, stats_list, key, default=0.0):
    return torch.tensor([float(s.get(key, default)) for s in stats_list], dtype=dtype, device=device)


def _flag_vec(torch, device, dtype, builds, pred):
    return torch.tensor([1.0 if pred(b) else 0.0 for b in builds], dtype=dtype, device=device)


def generate_shaman_timelines(torch, device, builds, spec: str, targets: int, bound_keys=None):
    """Return list[(events, stats, codes, taken)] aligned with builds.

    bound_keys: optional list[str|None] parallel to builds (Diamond I00D expand).
    """
    from sunken_sim import shaman as mod

    if spec not in mod.SPECS:
        raise ValueError(spec)
    B = len(builds)
    if B == 0:
        return []
    if bound_keys is None:
        bound_keys = [None] * B
    if len(bound_keys) != B:
        raise ValueError("bound_keys length mismatch")

    dtype = torch.float64
    dev_type = getattr(device, "type", str(device))
    if dev_type in ("privateuseone", "dml") or "privateuseone" in str(device):
        device = torch.device("cpu")

    if spec != "elemental":
        return _cpu_events_batch(builds, spec, targets, bound_keys)

    try:
        return _elemental_batch(torch, device, dtype, builds, targets, bound_keys)
    except Exception:
        # Never ship a silent wrong timeline; fall back to CPU oracle.
        return _cpu_events_batch(builds, "elemental", targets, bound_keys)


def _cpu_events_batch(builds, spec, targets, bound_keys):
    from sunken_sim import shaman as mod

    out = []
    for build, bk in zip(builds, bound_keys):
        bound = None if bk is None else mod.BOUND_NAME.get(bk, bk)
        if mod._wears(build, mod.DIAMOND) and bound is None:
            best = None
            for spell in mod.buttons(spec):
                bname = mod.BOUND_NAME[spell]
                events, _a, _m, stats, codes, taken, _bk, _rep = mod.events_for(
                    build, targets, spec, bname
                )
                total = sum(mod.score_events(events, stats, codes, taken).values())
                if best is None or total > best[0]:
                    best = (total, events, stats, codes, taken)
            out.append((best[1], best[2], best[3], best[4]))
        else:
            events, _a, _m, stats, codes, taken, _bk, _rep = mod.events_for(
                build, targets, spec, bound
            )
            out.append((events, stats, codes, taken))
    return out


def _buffers_to_events(bufs, names_deal):
    """Convert shaman event buffers to events_for tuples."""
    when = bufs["when"].detach().cpu().numpy()
    raw = bufs["raw"].detach().cpu().numpy()
    count = bufs["count"].detach().cpu().numpy()
    mastery = bufs["mastery"].detach().cpu().numpy()
    crit = bufs["crit"].detach().cpu().numpy()
    fusion = bufs["fusion"].detach().cpu().numpy()
    attack = bufs["attack"].detach().cpu().numpy()
    magical = bufs["magical"].detach().cpu().numpy()
    auto_scale = bufs["auto_scale"].detach().cpu().numpy()
    kind = bufs["kind"].detach().cpu().numpy()
    name_id = bufs["name_id"].detach().cpu().numpy()
    length = bufs["length"].detach().cpu().numpy()
    out = []
    for b in range(when.shape[0]):
        n = int(length[b])
        evs = []
        for i in range(n):
            k = float(kind[b, i])
            nid = int(name_id[b, i])
            name = names_deal.get(nid, "")
            if k == K_SPLASH:
                evs.append(("splash", name or "Всплеск огня", float(raw[b, i]), float(when[b, i]), float(count[b, i])))
            elif k == K_ECHO:
                evs.append(("echo", name or "Sulfuras (удар)", float(raw[b, i]), float(when[b, i])))
            else:
                evs.append(
                    (
                        "deal",
                        name,
                        float(raw[b, i]),
                        float(when[b, i]),
                        float(count[b, i]),
                        bool(attack[b, i] >= 0.5),
                        bool(magical[b, i] >= 0.5),
                        float(mastery[b, i]),
                        float(crit[b, i]),
                        float(fusion[b, i]),
                        bool(auto_scale[b, i] >= 0.5),
                    )
                )
        out.append(evs)
    return out


# name_id codes for deal/splash/echo labels (score path mostly ignores names)
N_AUTO = 1
N_CHAIN = 2
N_LESSER = 3
N_STORMFURY = 4
N_SHIELD = 5
N_LAVA = 6
N_MAGMA = 7
N_THUNDER = 8
N_FIRE = 9
N_SULF = 10
N_SULF_ECHO = 11
N_SPIRIT = 12

NAMES = {
    N_AUTO: "Автоатака",
    N_CHAIN: "Chain Lightning",
    N_LESSER: "Lesser Chain Lightning",
    N_STORMFURY: "Stormfury",
    N_SHIELD: "Lightning Shield",
    N_LAVA: "Lava Burst",
    N_MAGMA: "Liquid Magma",
    N_THUNDER: "Thunderstorm",
    N_FIRE: "Всплеск огня",
    N_SULF: "Sulfuras",
    N_SULF_ECHO: "Sulfuras (удар)",
    N_SPIRIT: "Feral Spirit",
}


def _make_bufs(torch, device, B, dtype):
    z = lambda: torch.zeros((B, MAX_EVENTS), dtype=dtype, device=device)
    return {
        "when": z(),
        "raw": z(),
        "count": z(),
        "mastery": z(),
        "crit": z(),
        "fusion": z(),
        "attack": z(),
        "magical": z(),
        "auto_scale": z(),
        "kind": z(),
        "name_id": z(),
        "length": torch.zeros(B, dtype=torch.int64, device=device),
    }


def _push(torch, bufs, mask, when, raw, *, count=1.0, mastery=0.0, crit=0.0, fusion=0.0,
          attack=0.0, magical=1.0, auto_scale=0.0, kind=K_DEAL, name_id=0):
    if not bool(mask.any()):
        return
    B = int(mask.shape[0])
    idx = bufs["length"].clamp(max=MAX_EVENTS - 1)
    rows = torch.arange(B, device=mask.device)
    active = mask & (bufs["length"] < MAX_EVENTS)

    def put(key, value):
        buf = bufs[key]
        if not isinstance(value, torch.Tensor):
            value = torch.full((B,), float(value), dtype=buf.dtype, device=buf.device)
        else:
            value = value.to(dtype=buf.dtype)
        buf[rows[active], idx[active]] = value[active]

    put("when", when)
    put("raw", raw)
    put("count", count)
    put("mastery", mastery)
    put("crit", crit)
    put("fusion", fusion)
    put("attack", attack)
    put("magical", magical)
    put("auto_scale", auto_scale)
    put("kind", kind)
    put("name_id", name_id)
    bufs["length"] = bufs["length"] + active.to(bufs["length"].dtype)


def _elemental_batch(torch, device, dtype, builds, targets, bound_keys):
    from sunken_sim import shaman as mod
    from sunken_sim.shadow import (
        CAST_BACKSWING,
        CAST_POINT,
        DUMMY_ARMOR,
        FIGHT,
        armor_taken,
        cast_mana_back,
        sulfuras_echo_chance,
        attack_mana_gain,
    )
    from sunken_sim.pressure import ATTACK_INTERVAL

    B = len(builds)
    CAST_TIME = CAST_POINT + CAST_BACKSWING
    fight = float(FIGHT)
    targets_f = float(targets)
    chain_count = float(min(targets, mod.CHAIN_HITS))
    lesser_count = float(min(targets, mod.LESSER_HITS))

    stats_list = [mod.sheet(b) for b in builds]
    codes_list = [
        frozenset(item.rawcode for item in b.items) | b.talents | b.glyphs for b in builds
    ]
    taken_list = [armor_taken(DUMMY_ARMOR - s["armor_pen"]) for s in stats_list]

    # stats
    haste = _stat_vec(torch, device, dtype, stats_list, "haste")
    cd_temp = _stat_vec(torch, device, dtype, stats_list, "cd_temp", 1.0)
    flat_cdr = _stat_vec(torch, device, dtype, stats_list, "flat_cdr")
    mana_max = _stat_vec(torch, device, dtype, stats_list, "mana_max")
    mana_regen = _stat_vec(torch, device, dtype, stats_list, "mana_regen")
    cast_stun_lock = _stat_vec(torch, device, dtype, stats_list, "cast_stun_lock")
    damage_mana_pct = _stat_vec(torch, device, dtype, stats_list, "damage_mana_pct")
    intel = _stat_vec(torch, device, dtype, stats_list, "int")
    agi = _stat_vec(torch, device, dtype, stats_list, "agi")
    ad = _stat_vec(torch, device, dtype, stats_list, "ad")
    mastery0 = _stat_vec(torch, device, dtype, stats_list, "mastery")
    crit0 = _stat_vec(torch, device, dtype, stats_list, "crit")
    luck = _stat_vec(torch, device, dtype, stats_list, "luck")
    potency = _stat_vec(torch, device, dtype, stats_list, "potency")
    attack_speed = _stat_vec(torch, device, dtype, stats_list, "attack_speed")
    attack_base = _stat_vec(torch, device, dtype, stats_list, "attack_base")
    auto_pct = _stat_vec(torch, device, dtype, stats_list, "auto_pct", 1.0)

    # refund pieces for cast_mana_back
    cast_refund = _stat_vec(torch, device, dtype, stats_list, "cast_refund")
    cast_refund_flat = _stat_vec(torch, device, dtype, stats_list, "cast_refund_flat")
    cast_refund_mastery = _stat_vec(torch, device, dtype, stats_list, "cast_refund_mastery")
    attack_mana = _stat_vec(torch, device, dtype, stats_list, "attack_mana")
    attack_mana_pct = _stat_vec(torch, device, dtype, stats_list, "attack_mana_pct")
    attack_mana_crit = _stat_vec(torch, device, dtype, stats_list, "attack_mana_crit")

    overcharge = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_OVERCHARGE))
    storm_ward = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_STORM_WARD))
    flash = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_FLASH))
    fury = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_FURY))
    fusion_talent = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_FUSION))
    wrath = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_WRATH))
    thunder = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_THUNDERSTORM))
    molten_blast = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_MOLTEN_BLAST))
    totem_mastery = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_TOTEM_MASTERY))
    bloodlust_on = _flag_vec(
        torch, device, dtype, builds,
        lambda b: mod._has(b, mod.TALENT_BLOODLUST) or mod._wears(b, mod.TRIBAL_FURY),
    )
    belt = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, mod.MOLTEN_BELT))
    ten_storms = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, mod.TEN_STORMS_HELM))
    mulgore = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, mod.MULGORE))
    epaulets = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, mod.EPAULETS))
    fire_orb = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, mod.FIRE_ORB))
    has_sulf = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, mod.SULFURAS_CODE))
    stormstrike = _flag_vec(torch, device, dtype, builds, lambda b: mod._has(b, mod.TALENT_STORMSTRIKE))

    cast_charges = torch.full((B,), float(mod.SHIELD_CAST), dtype=dtype, device=device) + 3.0 * storm_ward
    max_charges = torch.full((B,), float(mod.SHIELD_MAX), dtype=dtype, device=device) + 3.0 * storm_ward
    totem_life = torch.full((B,), float(mod.TOTEM_LIFE), dtype=dtype, device=device) + 4.0 * mulgore

    # bound cd_temp scale per ability
    bk_chain = torch.tensor([0.70 if k == "chain" else 1.0 for k in bound_keys], dtype=dtype, device=device)
    bk_shield = torch.tensor([0.70 if k == "shield" else 1.0 for k in bound_keys], dtype=dtype, device=device)
    bk_lava = torch.tensor([0.70 if k == "lava" else 1.0 for k in bound_keys], dtype=dtype, device=device)
    bk_totem = torch.tensor([0.70 if k == "totem" else 1.0 for k in bound_keys], dtype=dtype, device=device)

    def cooldown(base, key_scale, flat=0.0):
        if not isinstance(base, torch.Tensor):
            base = torch.full((B,), float(base), dtype=dtype, device=device)
        if not isinstance(flat, torch.Tensor):
            flat = torch.full((B,), float(flat), dtype=dtype, device=device)
        temp = cd_temp * key_scale
        return torch.clamp((base * temp - flat_cdr - flat) / (1.0 + haste), min=0.5)

    mana = mana_max.clone()
    mana_time = torch.zeros(B, dtype=dtype, device=device)
    hero_ready = torch.zeros(B, dtype=dtype, device=device)
    next_attack = torch.zeros(B, dtype=dtype, device=device)
    next_chain = torch.zeros(B, dtype=dtype, device=device)
    next_shield = torch.zeros(B, dtype=dtype, device=device)
    next_lava = torch.zeros(B, dtype=dtype, device=device)
    next_totem = torch.zeros(B, dtype=dtype, device=device)
    chain_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    shield_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    charges = torch.zeros(B, dtype=dtype, device=device)
    next_incoming = torch.full((B,), fight, dtype=dtype, device=device)
    totem_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    next_bolt = torch.full((B,), fight, dtype=dtype, device=device)
    fusion_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    fusion_seen = torch.zeros(B, dtype=torch.int64, device=device)  # bits
    sulf_armed = torch.zeros(B, dtype=dtype, device=device)

    pending_active = torch.zeros(B, dtype=torch.bool, device=device)
    pending_at = torch.full((B,), fight, dtype=dtype, device=device)
    pending_spell = torch.zeros(B, dtype=torch.int64, device=device)

    # bloodlust windows [B, MAX_BL]
    bl_start = torch.zeros((B, MAX_BL), dtype=dtype, device=device)
    bl_end = torch.zeros((B, MAX_BL), dtype=dtype, device=device)
    bl_chance = torch.zeros((B, MAX_BL), dtype=dtype, device=device)
    bl_len = torch.zeros(B, dtype=torch.int64, device=device)

    bufs = _make_bufs(torch, device, B, dtype)
    alive = torch.ones(B, dtype=torch.bool, device=device)
    ones = torch.ones(B, dtype=dtype, device=device)
    zeros = torch.zeros(B, dtype=dtype, device=device)

    def luck_mult():
        return 1.0 + luck

    def proc(percent):
        if not isinstance(percent, torch.Tensor):
            percent = torch.full((B,), float(percent), dtype=dtype, device=device)
        return torch.clamp(percent / 100.0 * luck_mult(), max=1.0)

    def mastery_of(now):
        bonus = torch.where((wrath > 0.5) & (now < totem_until), 6.0 * ones, zeros)
        return mastery0 + bonus

    def crit_of(now):
        bonus = torch.where((wrath > 0.5) & (now < totem_until), 8.0 * ones, zeros)
        return torch.clamp(crit0 + bonus, max=100.0)

    def fusion_up(now):
        return (now < fusion_until).to(dtype)

    def blood_factor(now):
        # weight = sum of chances for active windows
        now_c = now.unsqueeze(1)
        active = (bl_start <= now_c) & (now_c < bl_end) & (
            torch.arange(MAX_BL, device=device).unsqueeze(0) < bl_len.unsqueeze(1)
        )
        weight = (bl_chance * active.to(dtype)).sum(dim=1)
        return 1.0 - 0.18 * torch.clamp(weight, max=1.0)

    def attack_interval(now):
        # elemental: no spirit_as
        speed = torch.clamp(attack_speed, min=-0.8, max=4.0)
        return attack_base * blood_factor(now) / (1.0 + speed)

    def recover(now):
        nonlocal mana, mana_time
        dt = torch.clamp(now - mana_time, min=0.0)
        need = mana < mana_max
        mana = torch.where(need, torch.minimum(mana_max, mana + mana_regen * dt), mana)
        mana_time = now

    def pay(cost, now, mask):
        nonlocal mana
        recover(now)
        ok = mask & (mana >= cost)
        refund = cost * cast_refund + cast_refund_flat + cast_refund_mastery * mastery0
        mana = torch.where(ok, torch.minimum(mana_max, mana - cost + refund), mana)
        return ok

    def note_dmg_mana(count, mask):
        nonlocal mana
        gain = damage_mana_pct * mana_max * count
        mana = torch.where(mask & (damage_mana_pct > 0), torch.minimum(mana_max, mana + gain), mana)

    def push_deal(mask, when, raw, count, *, attack=0.0, magical=1.0, auto_scale=0.0, name_id=0, from_thunder=False):
        if not bool(mask.any()):
            return
        mast = mastery_of(when)
        crit = crit_of(when)
        fus = fusion_up(when)
        _push(
            torch, bufs, mask, when, raw,
            count=count, mastery=mast, crit=crit, fusion=fus,
            attack=attack, magical=magical, auto_scale=auto_scale,
            kind=K_DEAL, name_id=name_id,
        )
        cnt_t = count if isinstance(count, torch.Tensor) else torch.full((B,), float(count), dtype=dtype, device=device)
        note_dmg_mana(cnt_t, mask)
        # Thunderstorm proc: count * chance * targets (matches sunken_sim.shaman.deal)
        if not from_thunder:
            th = mask & (thunder > 0.5)
            if bool(th.any()):
                ch = proc(2.0)
                raw_th = 30.0 + 1.80 * intel
                cnt = cnt_t * ch * targets_f
                th2 = th & (ch > 0) & (cnt > 0)
                push_deal(th2, when, raw_th, cnt, attack=0.0, magical=1.0, name_id=N_THUNDER, from_thunder=True)

    def shield_raw(now):
        raw = 20.0 + 0.30 * intel
        raw = raw * (1.05 + 0.006 * mastery_of(now))  # elemental always
        raw = torch.where(storm_ward > 0.5, raw * 1.10, raw)
        return raw

    def chain_raw(now):
        return 70.0 + 1.60 * intel  # enhancement mastery N/A for elemental

    def add_flash(now, hits, mask):
        nonlocal charges, shield_until, next_incoming
        do = mask & (flash > 0.5) & (hits > 0)
        if not bool(do.any()):
            return
        gained = hits * proc(15.0)
        do = do & (gained > 0)
        if not bool(do.any()):
            return
        fresh = do & (now >= shield_until)
        charges = torch.where(fresh, zeros, charges)
        shield_until = torch.where(fresh, now + 20.0, shield_until)
        # arm_incoming for fresh
        if bool(fresh.any()):
            arm_incoming(now, fresh)
        charges = torch.where(do, torch.minimum(max_charges, charges + gained), charges)

    def monster_hit_at(now):
        step = float(ATTACK_INTERVAL)
        index = torch.floor((now + 1e-9) / step).to(dtype)
        hit = index * step
        hit = torch.where(hit + 1e-9 < now, hit + step, hit)
        return hit

    def arm_incoming(now, mask):
        nonlocal next_incoming
        hit = monster_hit_at(now)
        better = mask & ((next_incoming >= fight) | (hit < next_incoming))
        next_incoming = torch.where(better, hit, next_incoming)

    def chain_package(mask, now, scale, count, name_id, weight=1.0):
        if not bool(mask.any()):
            return
        if not isinstance(scale, torch.Tensor):
            scale = torch.full((B,), float(scale), dtype=dtype, device=device)
        if not isinstance(count, torch.Tensor):
            count = torch.full((B,), float(count), dtype=dtype, device=device)
        if not isinstance(weight, torch.Tensor):
            weight = torch.full((B,), float(weight), dtype=dtype, device=device)
        do = mask & (count > 0) & (weight > 0)
        if not bool(do.any()):
            return
        raw = chain_raw(now)
        oc = torch.where(overcharge > 0.5, 1.40 * ones, ones)
        primary = raw * oc * scale
        push_deal(do, now, primary, weight, name_id=name_id)
        more = do & (count > 1)
        push_deal(more, now, raw * scale, weight * (count - 1.0), name_id=name_id)
        add_flash(now, weight * count, do)

    def note_fusion(mask, key_bit, now):
        nonlocal fusion_until, fusion_seen
        do = mask & (fusion_talent > 0.5)
        if not bool(do.any()):
            return
        already = (fusion_seen & key_bit) != 0
        do = do & ~already
        if not bool(do.any()):
            return
        fusion_seen = torch.where(do, fusion_seen | key_bit, fusion_seen)
        # count bits
        bits = fusion_seen
        # popcount via bit tricks for 4 bits
        nbits = ((bits >> 0) & 1) + ((bits >> 1) & 1) + ((bits >> 2) & 1) + ((bits >> 3) & 1)
        trip = do & (nbits >= 3)
        fusion_seen = torch.where(trip, torch.zeros_like(fusion_seen), fusion_seen)
        fusion_until = torch.where(trip, now + 4.0, fusion_until)

    def note_bloodlust(mask, now):
        nonlocal bl_start, bl_end, bl_chance, bl_len
        do = mask & (bloodlust_on > 0.5)
        if not bool(do.any()):
            return
        chance = proc(30.0)
        do = do & (chance > 0)
        if not bool(do.any()):
            return
        duration = 8.0  # elemental (not restoration)
        idx = bl_len.clamp(max=MAX_BL - 1)
        rows = torch.arange(B, device=device)
        room = do & (bl_len < MAX_BL)
        bl_start[rows[room], idx[room]] = now[room]
        bl_end[rows[room], idx[room]] = (now + duration)[room]
        bl_chance[rows[room], idx[room]] = chance[room]
        bl_len = bl_len + room.to(bl_len.dtype)

    def do_cast(mask, spell, now):
        nonlocal hero_ready, next_attack, next_chain, next_shield, next_lava, next_totem
        nonlocal pending_active, pending_at, pending_spell, sulf_armed
        costs = {
            S_CHAIN: 20.0,
            S_SHIELD: 25.0,
            S_LAVA: 20.0,
            S_TOTEM: 40.0,
        }
        # pay per spell type — cast one spell id per row
        for sid, cost in costs.items():
            m = mask & (spell == sid)
            if not bool(m.any()):
                continue
            ok = pay(cost, now, m)
            fail = m & ~ok
            if sid == S_CHAIN:
                next_chain = torch.where(fail, now + 0.25, next_chain)
            elif sid == S_SHIELD:
                next_shield = torch.where(fail, now + 0.25, next_shield)
            elif sid == S_LAVA:
                next_lava = torch.where(fail, now + 0.25, next_lava)
            else:
                next_totem = torch.where(fail, now + 0.25, next_totem)
            okm = ok
            if not bool(okm.any()):
                continue
            if sid == S_CHAIN:
                next_chain = torch.where(okm, now + cooldown(7.0, bk_chain), next_chain)
            elif sid == S_SHIELD:
                base = 13.0 - 3.0 * ten_storms
                next_shield = torch.where(okm, now + cooldown(base, bk_shield), next_shield)
            elif sid == S_LAVA:
                base = 8.0 - 1.2 * fury
                next_lava = torch.where(okm, now + cooldown(base, bk_lava), next_lava)
            else:
                base = 16.0 - 5.0 * totem_mastery
                next_totem = torch.where(okm, now + cooldown(base, bk_totem), next_totem)
            sulf_armed = torch.where(okm & (has_sulf > 0.5) & (sulf_armed < 0.5), ones, sulf_armed)
            # pending
            pending_active = torch.where(okm, torch.ones_like(pending_active), pending_active)
            pending_at = torch.where(okm, now + CAST_POINT, pending_at)
            pending_spell = torch.where(okm, torch.full_like(pending_spell, sid), pending_spell)
            busy = now + CAST_TIME + cast_stun_lock
            hero_ready = torch.where(okm, busy, hero_ready)
            next_attack = torch.where(okm, torch.maximum(next_attack, busy), next_attack)

    def do_resolve(mask, spell, now):
        nonlocal chain_until, shield_until, charges, next_incoming, totem_until
        nonlocal next_bolt, next_shield, next_lava
        # chain
        m = mask & (spell == S_CHAIN)
        if bool(m.any()):
            note_fusion(m, 1, now)  # chain bit 0
            note_bloodlust(m, now)
            chain_until = torch.where(m, now + 4.0, chain_until)
        # shield
        m = mask & (spell == S_SHIELD)
        if bool(m.any()):
            note_fusion(m, 2, now)  # shield bit 1
            note_bloodlust(m, now)
            shield_until = torch.where(m, now + 20.0, shield_until)
            charges = torch.where(m, cast_charges, charges)
            arm_incoming(now, m)
            next_lava = torch.where(m & (belt > 0.5), now, next_lava)
        # lava
        m = mask & (spell == S_LAVA)
        if bool(m.any()):
            note_fusion(m, 4, now)  # summon bit 2
            note_bloodlust(m, now)
            spent = torch.where(now < shield_until, charges, zeros)
            spent = torch.where(m, spent, zeros)
            has_spent = m & (spent > 0)
            push_deal(has_spent, now, shield_raw(now), spent, name_id=N_SHIELD)
            charges = torch.where(has_spent, zeros, charges)
            shield_until = torch.where(has_spent, -ones, shield_until)
            next_shield = torch.where(
                has_spent & (molten_blast > 0.5) & (spent >= 1.0),
                torch.maximum(now, next_shield - 4.0),
                next_shield,
            )
            raw = 100.0 + 2.50 * intel
            raw = raw * (1.0 + 0.008 * mastery_of(now))
            raw = torch.where(fury > 0.5, raw * 1.18, raw)
            raw = raw * (1.0 + 0.08 * spent)
            push_deal(m, now, raw, ones, name_id=N_LAVA)
        # totem
        m = mask & (spell == S_TOTEM)
        if bool(m.any()):
            note_fusion(m, 8, now)  # totem bit 3
            note_bloodlust(m, now)
            totem_until = torch.where(m, now + totem_life, totem_until)
            next_bolt = torch.where(m, now + float(mod.MAGMA_GAP), next_bolt)

    def choose(now):
        lava_ready = next_lava <= now
        shield_ready = next_shield <= now
        need_shield = (now >= shield_until) | (charges < 1.0)
        chain_ready = (next_chain <= now) & (now >= chain_until)
        totem_ready = (next_totem <= now) & (now >= totem_until)
        # priority for elemental
        spell = torch.zeros(B, dtype=torch.int64, device=device)
        # 1 lava if charges
        take = lava_ready & (charges >= 1.0) & (now < shield_until)
        spell = torch.where(take, torch.full_like(spell, S_LAVA), spell)
        used = take
        # 2 shield if need
        take = ~used & need_shield & shield_ready
        spell = torch.where(take, torch.full_like(spell, S_SHIELD), spell)
        used = used | take
        # 3 chain
        take = ~used & chain_ready
        spell = torch.where(take, torch.full_like(spell, S_CHAIN), spell)
        used = used | take
        # 4 totem
        take = ~used & totem_ready
        spell = torch.where(take, torch.full_like(spell, S_TOTEM), spell)
        used = used | take
        # 5 lava
        take = ~used & lava_ready
        spell = torch.where(take, torch.full_like(spell, S_LAVA), spell)
        used = used | take
        # 6 shield need
        take = ~used & shield_ready & need_shield
        spell = torch.where(take, torch.full_like(spell, S_SHIELD), spell)
        used = used | take
        return spell, used  # used=False means None

    def next_ready(now):
        t_chain = torch.maximum(next_chain, chain_until)
        t_shield = next_shield
        t_totem = torch.maximum(next_totem, totem_until)
        t_lava = next_lava
        # future > now+1e-9
        def fut(t):
            return torch.where(t > now + 1e-9, t, torch.full_like(t, fight + 1.0))

        stacked = torch.stack([fut(t_chain), fut(t_shield), fut(t_totem), fut(t_lava)], dim=1)
        wake, _ = stacked.min(dim=1)
        valid = wake <= fight
        return wake, valid

    def on_attack(mask, now):
        nonlocal next_attack, chain_until, charges, shield_until, mana, sulf_armed
        recover(now)
        # consume chain
        ch = mask & (chain_until >= now)
        chain_until = torch.where(ch, -ones, chain_until)
        chain_package(ch, now, 1.0, chain_count, N_CHAIN)
        # lesser proc
        chance = 8.0 + 0.15 * agi
        chance = torch.where(epaulets > 0.5, chance + 8.0, chance)
        chance = torch.where(stormstrike > 0.5, chance * 1.20, chance)
        lesser_p = proc(chance)
        lp = mask & (lesser_p > 0)
        chain_package(lp, now, 0.50, lesser_count, N_LESSER, lesser_p)
        # shield tick on attack
        sh = mask & (now < shield_until) & (charges > 0)
        spent = torch.minimum(ones, charges)
        push_deal(sh, now, shield_raw(now), spent, name_id=N_SHIELD)
        charges = torch.where(sh, charges - spent, charges)
        empty = sh & (charges <= 1e-9)
        charges = torch.where(empty, zeros, charges)
        shield_until = torch.where(empty, -ones, shield_until)
        # auto
        push_deal(mask, now, ad, ones, attack=1.0, magical=1.0, auto_scale=1.0, name_id=N_AUTO)
        # attack mana
        gain = attack_mana + attack_mana_pct * mana_max
        gain = torch.where(attack_mana_crit > 0.5, gain * (1.0 + torch.clamp(crit0, max=100.0) / 100.0), gain)
        mana = torch.where(mask, torch.minimum(mana_max, mana + gain), mana)
        # fire orb
        fo = mask & (fire_orb > 0.5)
        _push(torch, bufs, fo, now, 20.0 + 0.35 * intel, count=targets_f, kind=K_SPLASH, name_id=N_FIRE)
        # sulfuras
        sul = mask & (has_sulf > 0.5) & (sulf_armed > 0.5)
        sulf_armed = torch.where(sul, zeros, sulf_armed)
        # deal with raw=int-potency to cancel +potency in score
        push_deal(sul, now, intel - potency, targets_f * ones, name_id=N_SULF)
        echo_raw = ad * (0.10 * (1.0 + luck))
        _push(torch, bufs, mask & (has_sulf > 0.5), now, echo_raw, kind=K_ECHO, name_id=N_SULF_ECHO)
        next_attack = torch.where(mask, now + attack_interval(now), next_attack)

    def on_incoming(mask, now):
        nonlocal charges, shield_until, next_incoming
        active = mask & (now < shield_until) & (charges > 0)
        dead = mask & ~active
        next_incoming = torch.where(dead, torch.full_like(next_incoming, fight), next_incoming)
        if not bool(active.any()):
            return
        spent = torch.minimum(ones, charges)
        push_deal(active, now, shield_raw(now), spent, name_id=N_SHIELD)
        charges = torch.where(active, charges - spent, charges)
        empty = active & (charges <= 1e-9)
        charges = torch.where(empty, zeros, charges)
        shield_until = torch.where(empty, -ones, shield_until)
        next_incoming = torch.where(empty, torch.full_like(next_incoming, fight), next_incoming)
        more = active & ~empty
        next_incoming = torch.where(more, monster_hit_at(now + float(mod.INCOMING_GAP)), next_incoming)

    def on_bolt(mask, now):
        nonlocal next_bolt, next_lava, next_shield
        live = mask & (now < totem_until)
        dead = mask & ~live
        next_bolt = torch.where(dead, torch.full_like(next_bolt, fight), next_bolt)
        if not bool(live.any()):
            return
        raw = 20.0 + 0.50 * intel + mastery_of(now)
        push_deal(live, now, raw, ones, name_id=N_MAGMA)
        cut = 0.50 * proc(50.0)
        do_cut = live & (cut > 0)
        lava_left = next_lava - now
        shield_left = next_shield - now
        prefer_lava = do_cut & (lava_left > shield_left) & (lava_left > 0)
        prefer_shield = do_cut & ~prefer_lava & (shield_left > 0)
        prefer_lava2 = do_cut & ~prefer_lava & ~prefer_shield & (lava_left > 0)
        next_lava = torch.where(prefer_lava | prefer_lava2, torch.maximum(now, next_lava - cut), next_lava)
        next_shield = torch.where(prefer_shield, torch.maximum(now, next_shield - cut), next_shield)
        next_bolt = torch.where(live, now + float(mod.MAGMA_GAP), next_bolt)

    # --- main loop ---
    steps = 0
    while bool(alive.any()) and steps < MAX_STEPS:
        steps += 1
        next_bolt = torch.where(next_bolt >= totem_until, torch.full_like(next_bolt, fight), next_bolt)
        next_incoming = torch.where(
            next_incoming >= shield_until, torch.full_like(next_incoming, fight), next_incoming
        )
        pending_t = torch.where(pending_active, pending_at, torch.full_like(pending_at, fight))
        moment = torch.minimum(
            torch.minimum(next_attack, next_bolt),
            torch.minimum(next_incoming, pending_t),
        )

        # 1) pending resolve
        m_pend = alive & pending_active & (pending_at <= moment) & (pending_at < fight)
        if bool(m_pend.any()):
            do_resolve(m_pend, pending_spell, pending_at)
            pending_active = torch.where(m_pend, torch.zeros_like(pending_active), pending_active)
            pending_at = torch.where(m_pend, torch.full_like(pending_at, fight), pending_at)

        # 2) hero choose / cast / wake
        m_hero = alive & ~m_pend & (hero_ready <= moment) & (hero_ready < fight)
        m_acted = m_pend.clone()
        if bool(m_hero.any()):
            spell, has_spell = choose(hero_ready)
            cast_m = m_hero & has_spell
            if bool(cast_m.any()):
                do_cast(cast_m, spell, hero_ready)
                m_acted = m_acted | cast_m
            rest = m_hero & ~has_spell
            if bool(rest.any()):
                wake, wake_ok = next_ready(hero_ready)
                adv = rest & wake_ok & (wake <= moment)
                hero_ready = torch.where(adv, wake, hero_ready)
                m_acted = m_acted | adv

        # 3) fire events
        m_fire = alive & ~m_acted & (moment < fight)
        if bool(m_fire.any()):
            on_attack(m_fire & (next_attack == moment), moment)
            on_incoming(m_fire & (next_incoming == moment), moment)
            on_bolt(m_fire & (next_bolt == moment), moment)

        alive = alive & (m_acted | (moment < fight))

    recover(torch.full((B,), fight, dtype=dtype, device=device))
    events_list = _buffers_to_events(bufs, NAMES)
    return [
        (events_list[i], stats_list[i], codes_list[i], taken_list[i])
        for i in range(B)
    ]
