# -*- coding: utf-8 -*-
"""Batched next-event timeline for Rogue (subtlety / combat).

Faithful port of sunken_sim.rogue.simulate onto batched torch (f64 clocks on
CPU when DirectML lacks f64). Events: (when, name, weight, kind) matching
farm.hybrid.rogue kind-score.

Do NOT register GPU_TIMELINE_SPECS until tools/_parity_rogue_gpu_tl.py is green.
"""
from __future__ import annotations

MAX_EVENTS = 2048
MAX_STEPS = 400000

C_INSPECT = 0
C_VENDETTA = 1
C_SHADOWSTEP = 2
C_STEALTH = 3
C_STRIKE = 4
C_FOK = 5
N_CAST = 6

N_AUTO = 0
N_STRIKE = 1
N_SHADOWSTEP = 2
N_FOK = 3
N_RUPTURE = 4
N_VENDETTA = 5
N_PARANOIA = 6
N_HIDDEN = 7
N_COUP = 8
N_FIRE = 9
N_SULF = 10
N_SULF_ECHO = 11

KIND_PHYS = 0.0
KIND_EXEC = 1.0
KIND_MAG = 2.0
KIND_FLAT = 3.0


def _stat_vec(torch, device, dtype, stats_list, key, default=0.0):
    return torch.tensor([float(s.get(key, default)) for s in stats_list], dtype=dtype, device=device)


def _flag_vec(torch, device, dtype, builds, pred):
    return torch.tensor([1.0 if pred(b) else 0.0 for b in builds], dtype=dtype, device=device)


def generate_rogue_timelines(torch, device, builds, spec: str, targets: int, bound_keys=None):
    """Return list[(events, stats)] aligned with builds."""
    if spec not in ("subtlety", "combat"):
        raise ValueError(f"rogue GPU timeline specs subtlety/combat, got {spec}")
    if not builds:
        return []
    dtype = torch.float64
    dev_type = getattr(device, "type", str(device))
    if dev_type in ("privateuseone", "dml") or "privateuseone" in str(device):
        device = torch.device("cpu")
    try:
        return _rogue_batch(torch, device, dtype, builds, spec, targets)
    except Exception:
        return _cpu_events_batch(builds, spec, targets)


def _cpu_events_batch(builds, spec, targets):
    from sunken_sim import rogue as mod

    out = []
    for build in builds:
        stats = mod.stats_of(build)
        key = mod._timeline_key(build, stats, spec, targets)
        cached = mod._TIMELINE.get(key)
        if cached is None:
            mod.simulate(build, targets, spec)
            cached = mod._TIMELINE[key]
        events, _actions, _mana = cached
        out.append((list(events), stats))
    return out


def _make_bufs(torch, device, B, dtype):
    z = lambda: torch.zeros((B, MAX_EVENTS), dtype=dtype, device=device)
    return {
        "when": z(),
        "name": torch.zeros((B, MAX_EVENTS), dtype=torch.int64, device=device),
        "weight": z(),
        "kind": z(),
        "pot": z(),
        "length": torch.zeros(B, dtype=torch.int64, device=device),
    }


def _push(torch, bufs, mask, when, weight, name_id, kind, pot=None):
    if not bool(mask.any()):
        return
    B = int(mask.shape[0])
    active = mask & (bufs["length"] < MAX_EVENTS)
    if not bool(active.any()):
        return
    rows = torch.arange(B, device=weight.device if isinstance(weight, torch.Tensor) else bufs["when"].device)
    idx = bufs["length"]
    w = weight if isinstance(weight, torch.Tensor) else torch.full((B,), float(weight), dtype=bufs["when"].dtype, device=bufs["when"].device)
    pot_t = pot if pot is not None else torch.zeros_like(w)
    if not isinstance(pot_t, torch.Tensor):
        pot_t = torch.full_like(w, float(pot_t))
    wh = when if isinstance(when, torch.Tensor) else torch.full((B,), float(when), dtype=w.dtype, device=w.device)
    bufs["when"][rows[active], idx[active]] = wh[active]
    bufs["weight"][rows[active], idx[active]] = w[active]
    bufs["pot"][rows[active], idx[active]] = pot_t[active]
    nid = name_id if isinstance(name_id, torch.Tensor) else torch.full((B,), int(name_id), dtype=torch.int64, device=w.device)
    kid = kind if isinstance(kind, torch.Tensor) else torch.full((B,), float(kind), dtype=w.dtype, device=w.device)
    bufs["name"][rows[active], idx[active]] = nid[active]
    bufs["kind"][rows[active], idx[active]] = kid[active]
    bufs["length"] = bufs["length"] + active.to(bufs["length"].dtype)


def _buffers_to_events(bufs, strike_name: str):
    AUTO = "\u0410\u0432\u0442\u043e\u0430\u0442\u0430\u043a\u0430"
    FIRE = "\u0412\u0441\u043f\u043b\u0435\u0441\u043a \u043e\u0433\u043d\u044f"
    SULF_ECHO = "Sulfuras (\u0443\u0434\u0430\u0440)"
    names = {
        N_AUTO: AUTO,
        N_STRIKE: strike_name,
        N_SHADOWSTEP: "Shadowstep",
        N_FOK: "Fan of Knives",
        N_RUPTURE: "Rupture",
        N_VENDETTA: "Vendetta",
        N_PARANOIA: "Paranoia",
        N_HIDDEN: "Hidden Blades",
        N_COUP: "Coup de Grace",
        N_FIRE: FIRE,
        N_SULF: "Sulfuras",
        N_SULF_ECHO: SULF_ECHO,
    }
    when = bufs["when"].detach().cpu()
    name = bufs["name"].detach().cpu()
    weight = bufs["weight"].detach().cpu()
    kind = bufs["kind"].detach().cpu()
    pot = bufs["pot"].detach().cpu()
    length = bufs["length"].detach().cpu()
    out = []
    for b in range(when.shape[0]):
        n = int(length[b].item())
        ev = []
        for i in range(n):
            nid = int(name[b, i].item())
            ev.append((float(when[b, i]), names.get(nid, AUTO), float(weight[b, i]), float(kind[b, i]), float(pot[b, i])))
        out.append(ev)
    return out


def _rogue_batch(torch, device, dtype, builds, spec, targets):
    """Batched pending+choose. Damage helpers are vectorized; Sulfuras/fire use masks."""
    from sunken_sim import rogue as mod
    from sunken_sim.shadow import (
        CAST_POINT,
        CAST_BACKSWING,
        DUMMY_ARMOR,
        FIGHT,
        _crit_factor,
        _execute_factor,
        armor_taken,
        attack_mana_gain,
        cast_mana_back,
        sulfuras_echo_chance,
        target_hp,
    )

    B = len(builds)
    T = int(targets)
    targets_f = float(T)
    fight = float(FIGHT)
    cast_time = float(CAST_POINT + CAST_BACKSWING)
    is_subtlety = spec == "subtlety"
    is_combat = spec == "combat"
    strike_name = "Sinister Strike" if is_subtlety else "Dispatch"
    strike_phys = 0.15 if is_subtlety else 0.0
    rank = float(mod.RANK)

    stats_list = [mod.stats_of(b) for b in builds]
    zeros = torch.zeros(B, dtype=dtype, device=device)
    ones = torch.ones(B, dtype=dtype, device=device)

    agi = _stat_vec(torch, device, dtype, stats_list, "agi")
    mastery = _stat_vec(torch, device, dtype, stats_list, "mastery")
    haste = _stat_vec(torch, device, dtype, stats_list, "haste")
    mana_max = _stat_vec(torch, device, dtype, stats_list, "mana_max")
    mana_regen = _stat_vec(torch, device, dtype, stats_list, "mana_regen")
    cast_stun_lock = _stat_vec(torch, device, dtype, stats_list, "cast_stun_lock")
    damage_mana_pct = _stat_vec(torch, device, dtype, stats_list, "damage_mana_pct")
    damage = _stat_vec(torch, device, dtype, stats_list, "damage")
    potency = _stat_vec(torch, device, dtype, stats_list, "potency")
    attack_potency = _stat_vec(torch, device, dtype, stats_list, "attack_potency")
    attack_speed = _stat_vec(torch, device, dtype, stats_list, "attack_speed")
    auto_pct = _stat_vec(torch, device, dtype, stats_list, "auto_pct", 1.0)
    luck = _stat_vec(torch, device, dtype, stats_list, "luck")
    crit = _stat_vec(torch, device, dtype, stats_list, "crit")
    rating = _stat_vec(torch, device, dtype, stats_list, "rating")
    armor_pen = _stat_vec(torch, device, dtype, stats_list, "armor_pen")
    phys_add = _stat_vec(torch, device, dtype, stats_list, "phys_add")
    cd_temp = _stat_vec(torch, device, dtype, stats_list, "cd_temp", 1.0)
    flat_cdr = _stat_vec(torch, device, dtype, stats_list, "flat_cdr")
    luck_mult = 1.0 + luck
    vendetta_feed = 0.50 + 0.01 * mastery

    def flag(code):
        return _flag_vec(torch, device, dtype, builds, lambda b, c=code: mod._has(b, c))

    t_phantom = flag(mod.TALENT_PHANTOM_ASSASSIN)
    t_fw = flag(mod.TALENT_FIND_WEAKNESS)
    t_dance = flag(mod.TALENT_SHADOW_DANCE)
    t_honor = flag(mod.TALENT_HONOR_AMONG_THIEVES)
    t_potency = flag(mod.TALENT_COMBAT_POTENCY)
    t_paranoia = flag(mod.TALENT_PARANOIA)
    t_subterfuge = flag(mod.TALENT_SUBTERFUGE)
    t_vanish = flag(mod.TALENT_VANISH)
    t_coup = flag(mod.TALENT_COUP_DE_GRACE)
    t_night = flag(mod.TALENT_NIGHTSTRIKE)
    t_surprise = flag(mod.TALENT_SURPRISE_ATTACK)
    t_spree = flag(mod.TALENT_KILLING_SPREE)
    t_dirty = flag(mod.TALENT_DIRTY_TRICKS)
    t_hidden = flag(mod.TALENT_HIDDEN_BLADES)
    t_marked = flag(mod.TALENT_MARKED_FOR_DEATH)
    t_planning = flag(mod.TALENT_ELABORATE_PLANNING)
    t_storm = flag(mod.TALENT_SHURIKEN_STORM)

    shadowguise = _stat_vec(torch, device, dtype, stats_list, "shadowguise")
    bounty = _stat_vec(torch, device, dtype, stats_list, "bounty_blades")
    cutthroat = _stat_vec(torch, device, dtype, stats_list, "cutthroat_shiv")
    belt = _stat_vec(torch, device, dtype, stats_list, "shadowcraft_belt")
    galactic = _stat_vec(torch, device, dtype, stats_list, "galactic")
    sulfuron = _stat_vec(torch, device, dtype, stats_list, "sulfuron")
    glass = _stat_vec(torch, device, dtype, stats_list, "glass")
    fire_orb = _stat_vec(torch, device, dtype, stats_list, "fire_orb")
    has_sulfuras = _flag_vec(torch, device, dtype, builds, lambda b: mod._wears(b, "I0BR"))

    taken_base = []
    taken_vend0 = []
    taken_enh = armor_taken(float(DUMMY_ARMOR))
    for i in range(B):
        ap = float(armor_pen[i])
        fw = 5.0 if float(t_fw[i]) > 0.5 else 0.0
        taken_base.append(armor_taken(float(DUMMY_ARMOR) - ap - fw))
        mk = 4.0 if float(t_marked[i]) > 0.5 else 0.0
        taken_vend0.append(armor_taken(float(DUMMY_ARMOR) - ap - fw - mk))
    taken_base_t = torch.tensor(taken_base, dtype=dtype, device=device)
    taken_vend0_t = torch.tensor(taken_vend0, dtype=dtype, device=device)
    taken_enh_t = torch.full((B,), taken_enh, dtype=dtype, device=device)
    taken_enh_marked_t = torch.full((B,), armor_taken(float(DUMMY_ARMOR) - 4.0), dtype=dtype, device=device)

    # cast_mana_back coefficients
    cast_refund = _stat_vec(torch, device, dtype, stats_list, "cast_refund")
    cast_refund_flat = _stat_vec(torch, device, dtype, stats_list, "cast_refund_flat")
    cast_refund_mastery = _stat_vec(torch, device, dtype, stats_list, "cast_refund_mastery")

    strike_flat = torch.where(t_dirty > 0.5, torch.full_like(ones, 1.0), zeros)
    stealth_flat = torch.where(t_dirty > 0.5, torch.full_like(ones, 1.5), zeros)
    vendetta_flat = torch.where(t_marked > 0.5, torch.full_like(ones, 6.0), zeros)
    shadowstep_mult = torch.where(shadowguise > 0.5, torch.full_like(ones, 1.25), ones)

    mana = mana_max.clone()
    mana_time = zeros.clone()
    busy = zeros.clone()
    next_attack = zeros.clone()
    clocks = torch.zeros((B, N_CAST), dtype=dtype, device=device)
    clocks[:, C_INSPECT] = torch.where(t_planning > 0.5, zeros, torch.full_like(zeros, fight * 10.0))
    vend_start = torch.full((B,), -1.0, dtype=dtype, device=device)
    vend_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    vend_acc = zeros.clone()
    vend_pot = zeros.clone()
    planning_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    ambush_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    spree_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    strike_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    stealth_pending = torch.zeros(B, dtype=torch.bool, device=device)
    behind_pending = torch.zeros(B, dtype=torch.bool, device=device)
    ruptured = torch.zeros(B, dtype=torch.bool, device=device)
    dance_pending = torch.zeros(B, dtype=torch.bool, device=device)
    storm_acc = zeros.clone()
    vanish_ready = zeros.clone()
    vanish_acc = zeros.clone()
    next_pressure = torch.where(
        t_vanish > 0.5,
        torch.full_like(zeros, float(mod.PRESSURE_STEP)),
        torch.full_like(zeros, fight * 10.0),
    )
    sulf_armed = zeros.clone()
    alive = torch.ones(B, dtype=torch.bool, device=device)
    bufs = _make_bufs(torch, device, B, dtype)

    # --- helpers using nonlocal state ---
    st = {
        "mana": mana, "mana_time": mana_time, "busy": busy, "next_attack": next_attack,
        "vend_start": vend_start, "vend_until": vend_until, "vend_acc": vend_acc, "vend_pot": vend_pot,
        "planning_until": planning_until, "ambush_until": ambush_until,
        "spree_until": spree_until, "strike_until": strike_until,
        "stealth_pending": stealth_pending, "behind_pending": behind_pending,
        "ruptured": ruptured, "dance_pending": dance_pending, "storm_acc": storm_acc,
        "vanish_ready": vanish_ready, "vanish_acc": vanish_acc, "next_pressure": next_pressure,
        "sulf_armed": sulf_armed, "clocks": clocks,
    }

    def recover(now, mask):
        # Match CPU: regen only when now > mana_time, then always stamp mana_time=now
        # (CPU can rewind mana_time when hit_at < a prior recover, keeping extra mana).
        dt = torch.clamp(now - st["mana_time"], min=0.0)
        room = torch.clamp(mana_max - st["mana"], min=0.0)
        gain = torch.minimum(room, mana_regen * dt)
        # strict now > mana_time like CPU
        add = mask & (now > st["mana_time"])
        st["mana"] = torch.where(add, st["mana"] + gain, st["mana"])
        st["mana_time"] = torch.where(mask, now, st["mana_time"])

    def gain_mana(amount, mask):
        st["mana"] = torch.where(mask, torch.minimum(mana_max, st["mana"] + amount), st["mana"])

    def try_pay(cost, now, mask):
        recover(now, mask)
        cost_t = cost if isinstance(cost, torch.Tensor) else torch.full_like(st["mana"], float(cost))
        can = mask & (st["mana"] + 1e-12 >= cost_t)
        back = cost_t * cast_refund + cast_refund_flat + cast_refund_mastery * mastery
        st["mana"] = torch.where(can, st["mana"] - cost_t + back, st["mana"])
        return can

    def note_dmg_mana(count, mask):
        if float(damage_mana_pct.max()) <= 0:
            return
        cnt = count if isinstance(count, torch.Tensor) else torch.full_like(st["mana"], float(count))
        st["mana"] = torch.where(mask, torch.minimum(mana_max, st["mana"] + damage_mana_pct * mana_max * cnt), st["mana"])

    def cd(base, flat=None):
        flat_t = flat if flat is not None else zeros
        return torch.clamp((float(base) * cd_temp - flat_cdr - flat_t) / (1.0 + haste), min=0.5)

    def chance(v):
        return torch.clamp(v, 0.0, 1.0)

    def vend_on(now):
        return (st["vend_start"] <= now) & (now < st["vend_until"])

    def taken_for(index, now, enhanced=False):
        # Marked-for-Death -4 applies even on enhanced path (coup), while Vendetta
        # release uses plain DUMMY_ARMOR via taken_enh_t directly.
        if enhanced:
            if index == 0:
                return torch.where(vend_on(now) & (t_marked > 0.5), taken_enh_marked_t, taken_enh_t)
            return taken_enh_t
        if index == 0:
            return torch.where(vend_on(now) & (t_marked > 0.5), taken_vend0_t, taken_base_t)
        return taken_base_t

    def increase(now, mask=None):
        if mask is None:
            mask = torch.ones(B, dtype=torch.bool, device=device)
        recover(now, mask)
        value = ones.clone()
        value = torch.where(t_subterfuge > 0.5, value + 0.08 + 0.01 * (st["mana"] / 50.0), value)
        value = torch.where((t_planning > 0.5) & (now < st["planning_until"]), value + 0.15, value)
        return value

    def physical(now):
        bonus = 1.0 + phys_add + strike_phys
        thp = torch.tensor([target_hp(float(now[i].item())) for i in range(B)], dtype=dtype, device=device)
        bonus = torch.where(sulfuron > 0.5, bonus + 0.13 + 0.25 * thp, bonus)
        bonus = torch.where(glass > 0.5, bonus * 1.15, bonus)
        return bonus

    def dcs(now):
        value = float(mod.WHITE_BASE) + 0.75 * agi + damage
        return torch.where(now < st["spree_until"], value * 1.30, value)

    def do_cast(now, mask, extra=0.0):
        st["sulf_armed"] = torch.where(
            mask & (has_sulfuras > 0.5) & (st["sulf_armed"] < 0.5), ones, st["sulf_armed"]
        )
        extra_t = extra if isinstance(extra, torch.Tensor) else torch.full_like(now, float(extra))
        st["busy"] = torch.where(mask, now + cast_time + extra_t + cast_stun_lock, st["busy"])

    def push_flat0(mask, weight, name_id, pot=None):
        """add_damage: when stamped 0.0"""
        pot_t = pot if pot is not None else zeros
        m = mask & ((weight > 0) | (pot_t > 0))
        _push(torch, bufs, m, zeros, weight, name_id, KIND_FLAT, pot=pot_t)

    def push_k(mask, when, weight, name_id, kind, pot=None):
        pot_t = pot if pot is not None else zeros
        m = mask & ((weight > 0) | (pot_t > 0))
        _push(torch, bufs, m, when, weight, name_id, kind, pot=pot_t)

    def coup(now, attack, count, mask):
        m = mask & (t_coup > 0.5) & ((st["vend_acc"] > 0) | (st["vend_pot"] > 0))
        if not bool(m.any()):
            return
        rate = 0.07 if attack else 0.04
        cnt = count if isinstance(count, torch.Tensor) else torch.full_like(st["vend_acc"], float(count))
        ch = chance(rate * luck_mult) * cnt
        take = taken_for(0, now, enhanced=True)
        dealt = st["vend_acc"] * take * ch
        dealt_p = st["vend_pot"] * take * ch
        push_flat0(m, dealt, N_COUP, pot=dealt_p)
        st["vend_acc"] = torch.where(m, st["vend_acc"] + vendetta_feed * dealt, st["vend_acc"])
        st["vend_pot"] = torch.where(m, st["vend_pot"] + vendetta_feed * dealt_p, st["vend_pot"])

    def landed(dealt, dealt_pot, index, now, attack, count, mask):
        if index != 0:
            return
        m = mask & vend_on(now)
        if not bool(m.any()):
            return
        st["vend_acc"] = torch.where(m, st["vend_acc"] + vendetta_feed * dealt, st["vend_acc"])
        st["vend_pot"] = torch.where(m, st["vend_pot"] + vendetta_feed * dealt_pot, st["vend_pot"])
        coup(now, attack, count, m)

    def hit(name_id, raw, now, mask, *, index=0, attack=False, count=1.0,
            potency_scale=None, attack_inc=None, crit_bonus=0.0, sure_crit=False, apply_auto_pct=False):
        if not bool(mask.any()):
            return zeros.clone(), zeros.clone()
        pot_s = potency_scale if potency_scale is not None else ones
        atk_inc = attack_inc if attack_inc is not None else ones
        cnt = count if isinstance(count, torch.Tensor) else torch.full_like(raw if isinstance(raw, torch.Tensor) else ones, float(count))
        raw_t = raw if isinstance(raw, torch.Tensor) else torch.full_like(ones, float(raw))
        inc = increase(now, mask)
        raw_part = raw_t * inc
        pot_part = pot_s * inc
        armor = taken_for(index, now)
        share = zeros.clone()
        bounty_pre = zeros.clone()
        if attack:
            raw_part = raw_part * atk_inc
            pot_part = pot_part * atk_inc
            if sure_crit:
                chance_c = torch.full_like(crit, 100.0)
            else:
                cb = crit_bonus if isinstance(crit_bonus, torch.Tensor) else torch.full_like(crit, float(crit_bonus))
                chance_c = crit + cb
            chance_c = torch.where(t_fw > 0.5, chance_c + 5.0, chance_c)
            chance_c = torch.where((now < st["ambush_until"]) & (t_surprise > 0.5), chance_c + 15.0, chance_c)
            share = torch.clamp(chance_c, 0.0, 100.0) / 100.0
            mult = 2.0 + rating
            cf = torch.tensor(
                [_crit_factor(float(chance_c[i].item()), float(mult[i].item())) for i in range(B)],
                dtype=dtype, device=device,
            )
            pre = raw_part * armor * cf
            pre_pot = pot_part * armor * cf
            if float(bounty.max()) > 0:
                if index == 0:
                    flat = torch.where(vend_on(now), torch.full_like(ones, 40.0), torch.full_like(ones, 15.0))
                else:
                    flat = torch.full_like(ones, 15.0)
                bounty_pre = torch.where(bounty > 0.5, share * flat * mult, zeros)
        else:
            pre = raw_part * armor
            pre_pot = pot_part * armor

        w = pre * cnt
        wp = pre_pot * cnt
        bw = bounty_pre * cnt
        if apply_auto_pct:
            w = w * auto_pct
            wp = wp * auto_pct
            bw = bw * auto_pct
        push_k(mask, now, w, name_id, KIND_PHYS, pot=wp)
        if float(bounty.max()) > 0:
            push_k(mask & (bounty > 0.5), now, bw, name_id, KIND_EXEC)

        phys = physical(now)
        ex = torch.tensor(
            [_execute_factor(stats_list[i], float(now[i].item())) for i in range(B)],
            dtype=dtype, device=device,
        )
        dealt = pre * phys * ex + bounty_pre * ex
        dealt_pot = pre_pot * phys * ex
        landed(dealt, dealt_pot, index, now, attack, cnt, mask)
        return dealt, share

    def rupture(now, count, from_potency, mask):
        if not bool(mask.any()):
            return
        power = dcs(now)
        raw = 10.0 + 2.25 * power
        raw = torch.where(t_dance > 0.5, raw * 1.15, raw)
        raw = torch.where(cutthroat > 0.5, raw * 1.25, raw)
        cnt = count if isinstance(count, torch.Tensor) else torch.full_like(raw, float(count))
        if is_combat:
            _d, share = hit(N_RUPTURE, raw, now, mask, attack=True, count=cnt)
            if not from_potency:
                m2 = mask & (t_potency > 0.5)
                if bool(m2.any()):
                    ch = chance(0.08 * (1.0 + 0.5 * share) * luck_mult)
                    rupture(now, cnt * ch, True, m2)
        else:
            hit(N_RUPTURE, raw, now, mask, count=cnt)

    def fan(now, name_id, scale, count, mask):
        if not bool(mask.any()):
            return
        power = dcs(now)
        raw = (70.0 * rank + 0.75 * power) * float(scale)
        raw = torch.where(belt > 0.5, raw * 1.25, raw)
        cnt = count if isinstance(count, torch.Tensor) else torch.full_like(raw, float(count))
        for index in range(T):
            hit(name_id, raw, now, mask, index=index, count=cnt)
        note_dmg_mana(targets_f * cnt, mask)
        m_storm = mask & (t_storm > 0.5)
        if bool(m_storm.any()):
            p = chance(0.08 * luck_mult)
            st["storm_acc"] = torch.where(m_storm, st["storm_acc"] + cnt * (1.0 - (1.0 - p) ** T), st["storm_acc"])

    def class_cast(now, mask):
        m_par = mask & (t_paranoia > 0.5) & vend_on(now)
        if bool(m_par.any()):
            hit(N_PARANOIA, 25.0 + 0.40 * dcs(now), now, m_par)
            note_dmg_mana(1.0, m_par)
        m_hid = mask & (t_hidden > 0.5)
        if bool(m_hid.any()):
            fan(now, N_HIDDEN, 0.5, chance(0.35 * luck_mult), m_hid)

    def attack_interval(now):
        swing = float(mod.SWING) * torch.where(galactic > 0.5, torch.full_like(ones, 1.20), ones)
        speed = attack_speed.clone()
        speed = torch.where(now < st["ambush_until"], speed + float(mod.AMBUSH_SPEED), speed)
        speed = torch.clamp(speed, min=-0.8, max=4.0)
        return swing / (1.0 + speed)

    def release(now, mask):
        amt = st["vend_acc"] * taken_enh_t
        amt_pot = st["vend_pot"] * taken_enh_t
        push_flat0(mask, amt, N_VENDETTA, pot=amt_pot)
        st["vend_acc"] = torch.where(mask, zeros, st["vend_acc"])
        st["vend_pot"] = torch.where(mask, zeros, st["vend_pot"])
        st["vend_start"] = torch.where(mask, torch.full_like(st["vend_start"], -1.0), st["vend_start"])
        st["vend_until"] = torch.where(mask, torch.full_like(st["vend_until"], -1.0), st["vend_until"])
        m_hon = mask & (t_honor > 0.5)
        if bool(m_hon.any()):
            recover(now, m_hon)
            gain_mana(0.12 * mana_max, m_hon)

    # ---- main loop ----
    BIG = fight * 10.0
    steps = 0
    while bool(alive.any()) and steps < MAX_STEPS:
        steps += 1
        attack_at = torch.maximum(st["next_attack"], st["busy"])
        # cast choice
        cast_at = torch.full((B,), BIG, dtype=dtype, device=device)
        choice = torch.full((B,), -1, dtype=torch.int64, device=device)
        can_cast = alive & ~st["stealth_pending"]
        for col in range(N_CAST):
            ready = st["clocks"][:, col]
            if col == C_INSPECT:
                ready = torch.maximum(ready, st["planning_until"])
            ready = torch.maximum(ready, st["busy"])
            better = can_cast & (ready < cast_at - 1e-9)
            cast_at = torch.where(better, ready, cast_at)
            choice = torch.where(better, torch.full_like(choice, col), choice)

        release_at = torch.where(st["vend_until"] >= 0, st["vend_until"], torch.full_like(zeros, BIG))
        pressure_at = st["next_pressure"]
        moment = torch.minimum(torch.minimum(attack_at, cast_at), torch.minimum(release_at, pressure_at))
        alive = alive & (moment < fight)
        if not bool(alive.any()):
            break

        # priority: release > pressure > cast (if cast<=attack) > attack
        is_rel = alive & (torch.abs(moment - release_at) < 1e-12)
        is_pres = alive & ~is_rel & (torch.abs(moment - pressure_at) < 1e-12)
        is_cast = alive & ~is_rel & ~is_pres & (cast_at <= attack_at + 1e-15) & (choice >= 0) & (torch.abs(moment - cast_at) < 1e-12)
        is_atk = alive & ~is_rel & ~is_pres & ~is_cast

        if bool(is_rel.any()):
            release(moment, is_rel)

        if bool(is_pres.any()):
            m = is_pres
            ready_v = m & (moment >= st["vanish_ready"])
            st["vanish_acc"] = torch.where(ready_v, st["vanish_acc"] + float(mod.EVADE), st["vanish_acc"])
            fire = ready_v & (st["vanish_acc"] >= 1.0)
            st["vanish_acc"] = torch.where(fire, zeros, st["vanish_acc"])
            st["vanish_ready"] = torch.where(fire, moment + float(mod.VANISH_ICD), st["vanish_ready"])
            st["clocks"][:, C_STEALTH] = torch.where(
                fire, torch.minimum(st["clocks"][:, C_STEALTH], moment), st["clocks"][:, C_STEALTH]
            )
            if bool(fire.any()):
                recover(moment, fire)
                gain_mana(0.10 * mana_max, fire)
            st["next_pressure"] = torch.where(m, st["next_pressure"] + float(mod.PRESSURE_STEP), st["next_pressure"])

        # casts
        if bool(is_cast.any()):
            hit_at = moment + float(CAST_POINT)
            # Inspect
            m = is_cast & (choice == C_INSPECT)
            if bool(m.any()):
                ok = try_pay(0.0, moment, m)
                fail = m & ~ok
                st["clocks"][:, C_INSPECT] = torch.where(fail, moment + 0.25, st["clocks"][:, C_INSPECT])
                if bool(ok.any()):
                    do_cast(moment, ok, float(mod.INSPECT_FOLLOW))
                    st["planning_until"] = torch.where(ok, hit_at + float(mod.PLANNING_DUR), st["planning_until"])
                    st["clocks"][:, C_INSPECT] = torch.where(ok, moment + cd(mod.INSPECT_CD), st["clocks"][:, C_INSPECT])
                    st["next_attack"] = torch.where(ok, torch.maximum(st["next_attack"], st["busy"]), st["next_attack"])

            # Vendetta
            m = is_cast & (choice == C_VENDETTA)
            if bool(m.any()):
                ok = try_pay(float(mod.VENDETTA_MANA), moment, m)
                fail = m & ~ok
                st["clocks"][:, C_VENDETTA] = torch.where(fail, moment + 0.25, st["clocks"][:, C_VENDETTA])
                if bool(ok.any()):
                    do_cast(moment, ok, float(mod.VENDETTA_FOLLOW))
                    st["vend_start"] = torch.where(ok, hit_at, st["vend_start"])
                    st["vend_until"] = torch.where(ok, hit_at + float(mod.VENDETTA_DUR), st["vend_until"])
                    st["vend_acc"] = torch.where(ok, zeros, st["vend_acc"])
                    st["vend_pot"] = torch.where(ok, zeros, st["vend_pot"])
                    st["clocks"][:, C_VENDETTA] = torch.where(
                        ok, moment + cd(mod.VENDETTA_CD, vendetta_flat), st["clocks"][:, C_VENDETTA]
                    )
                    m_hid = ok & (t_hidden > 0.5)
                    if bool(m_hid.any()):
                        fan(hit_at, N_HIDDEN, 0.5, chance(0.35 * luck_mult), m_hid)
                    st["next_attack"] = torch.where(ok, torch.maximum(st["next_attack"], st["busy"]), st["next_attack"])

            # Shadowstep
            m = is_cast & (choice == C_SHADOWSTEP)
            if bool(m.any()):
                ok = try_pay(float(mod.SHADOWSTEP_MANA), moment, m)
                fail = m & ~ok
                st["clocks"][:, C_SHADOWSTEP] = torch.where(fail, moment + 0.25, st["clocks"][:, C_SHADOWSTEP])
                if bool(ok.any()):
                    do_cast(moment, ok)
                    class_cast(hit_at, ok)
                    power = dcs(hit_at)
                    raw = 10.0 + 90.0 * rank + 1.40 * power
                    amb = hit_at < st["ambush_until"]
                    amb_mult = (1.15 + 0.05 * rank) + torch.where(t_night > 0.5, torch.full_like(ones, 0.30), zeros)
                    raw = torch.where(amb, raw * amb_mult, raw)
                    # clear ambush if no surprise
                    st["ambush_until"] = torch.where(
                        ok & amb & (t_surprise < 0.5), hit_at, st["ambush_until"]
                    )
                    raw = raw * shadowstep_mult
                    need_rup = ok & (~st["ruptured"] | st["dance_pending"])
                    st["ruptured"] = torch.where(need_rup, torch.ones_like(st["ruptured"]), st["ruptured"])
                    st["dance_pending"] = torch.where(need_rup, torch.zeros_like(st["dance_pending"]), st["dance_pending"])
                    if bool(need_rup.any()):
                        rupture(hit_at, 1.0, False, need_rup)
                    hit(N_SHADOWSTEP, raw, hit_at, ok)
                    note_dmg_mana(1.0, ok)
                    st["spree_until"] = torch.where(
                        ok & (t_spree > 0.5), hit_at + float(mod.SPREE_DUR), st["spree_until"]
                    )
                    st["behind_pending"] = torch.where(ok, torch.ones_like(st["behind_pending"]), st["behind_pending"])
                    st["clocks"][:, C_SHADOWSTEP] = torch.where(ok, moment + cd(mod.SHADOWSTEP_CD), st["clocks"][:, C_SHADOWSTEP])
                    st["next_attack"] = torch.where(ok, torch.maximum(st["next_attack"], st["busy"]), st["next_attack"])

            # Stealth
            m = is_cast & (choice == C_STEALTH)
            if bool(m.any()):
                ok = try_pay(float(mod.STEALTH_MANA), moment, m)
                fail = m & ~ok
                st["clocks"][:, C_STEALTH] = torch.where(fail, moment + 0.25, st["clocks"][:, C_STEALTH])
                if bool(ok.any()):
                    do_cast(moment, ok)
                    class_cast(hit_at, ok)
                    st["stealth_pending"] = torch.where(ok, torch.ones_like(st["stealth_pending"]), st["stealth_pending"])
                    st["ambush_until"] = torch.where(ok, hit_at + float(mod.AMBUSH_DUR), st["ambush_until"])
                    st["dance_pending"] = torch.where(
                        ok & (t_dance > 0.5), torch.ones_like(st["dance_pending"]), st["dance_pending"]
                    )
                    if is_subtlety:
                        st["clocks"][:, C_SHADOWSTEP] = torch.where(
                            ok, torch.minimum(st["clocks"][:, C_SHADOWSTEP], moment), st["clocks"][:, C_SHADOWSTEP]
                        )
                    st["clocks"][:, C_STEALTH] = torch.where(
                        ok, moment + cd(mod.STEALTH_CD, stealth_flat), st["clocks"][:, C_STEALTH]
                    )
                    st["next_attack"] = torch.where(ok, torch.maximum(st["next_attack"], st["busy"]), st["next_attack"])

            # Strike
            m = is_cast & (choice == C_STRIKE)
            if bool(m.any()):
                ok = try_pay(float(mod.STRIKE_MANA), moment, m)
                fail = m & ~ok
                st["clocks"][:, C_STRIKE] = torch.where(fail, moment + 0.25, st["clocks"][:, C_STRIKE])
                if bool(ok.any()):
                    do_cast(moment, ok)
                    class_cast(hit_at, ok)
                    st["strike_until"] = torch.where(ok, hit_at + float(mod.STRIKE_BUFF), st["strike_until"])
                    st["clocks"][:, C_STRIKE] = torch.where(
                        ok, moment + cd(mod.STRIKE_CD, strike_flat), st["clocks"][:, C_STRIKE]
                    )
                    st["next_attack"] = torch.where(ok, torch.maximum(st["next_attack"], st["busy"]), st["next_attack"])

            # Fan of Knives
            m = is_cast & (choice == C_FOK)
            if bool(m.any()):
                ok = try_pay(float(mod.FOK_MANA), moment, m)
                fail = m & ~ok
                st["clocks"][:, C_FOK] = torch.where(fail, moment + 0.25, st["clocks"][:, C_FOK])
                if bool(ok.any()):
                    do_cast(moment, ok)
                    class_cast(hit_at, ok)
                    fan(hit_at, N_FOK, 1.0, 1.0, ok)
                    st["clocks"][:, C_FOK] = torch.where(ok, moment + cd(mod.FOK_CD), st["clocks"][:, C_FOK])
                    st["next_attack"] = torch.where(ok, torch.maximum(st["next_attack"], st["busy"]), st["next_attack"])

            # storm refund
            storm_fire = is_cast & (st["storm_acc"] >= 1.0)
            # storm checked after each successful cast in CPU — only rows that cast this step
            # CPU: if storm_acc >= 1 after the cast block
            # Approximate: any is_cast row that paid successfully already updated storm via fan.
            m_storm = alive & (st["storm_acc"] >= 1.0)
            # Only consume on cast steps that just happened — match CPU: checked after cast branch
            m_storm = is_cast & (st["storm_acc"] >= 1.0)
            if bool(m_storm.any()):
                st["storm_acc"] = torch.where(m_storm, st["storm_acc"] - 1.0, st["storm_acc"])
                st["clocks"][:, C_FOK] = torch.where(
                    m_storm, torch.minimum(st["clocks"][:, C_FOK], st["busy"]), st["clocks"][:, C_FOK]
                )

        # Auto-attack
        if bool(is_atk.any()):
            m = is_atk
            recover(moment, m)
            power = dcs(moment)
            raw = power + torch.where(st["stealth_pending"], torch.full_like(power, float(mod.BACKSTAB) * rank), zeros)
            attack_inc = ones.clone()
            attack_inc = torch.where(
                (t_phantom > 0.5) & st["behind_pending"], attack_inc + 0.25, attack_inc
            )
            dispatch = torch.full((B,), is_combat, dtype=torch.bool, device=device) & (moment < st["strike_until"])
            chance_now = crit + torch.where(t_fw > 0.5, torch.full_like(crit, 5.0), zeros)
            attack_inc = torch.where(dispatch, attack_inc + 0.40 + 0.01 * chance_now, attack_inc)
            name_id = torch.where(dispatch, torch.full_like(choice, N_STRIKE), torch.full_like(choice, N_AUTO))
            # hit with per-row name — do auto and dispatch separately
            m_disp = m & dispatch
            m_auto = m & ~dispatch
            share = zeros.clone()
            if bool(m_auto.any()):
                _d, sh = hit(
                    N_AUTO, raw, moment, m_auto, attack=True,
                    potency_scale=attack_potency, attack_inc=attack_inc,
                    apply_auto_pct=True,
                )
                share = torch.where(m_auto, sh, share)
            if bool(m_disp.any()):
                _d, sh = hit(
                    N_STRIKE, raw, moment, m_disp, attack=True,
                    potency_scale=attack_potency, attack_inc=attack_inc,
                    sure_crit=True, apply_auto_pct=True,
                )
                share = torch.where(m_disp, sh, share)
                st["strike_until"] = torch.where(m_disp, torch.full_like(st["strike_until"], -1.0), st["strike_until"])

            # subtlety strike buff
            if is_subtlety:
                m_ss = m & (moment < st["strike_until"])
                st["strike_until"] = torch.where(m_ss, torch.full_like(st["strike_until"], -1.0), st["strike_until"])
                if bool(m_ss.any()):
                    hit(N_STRIKE, 35.0 + 1.10 * power + 0.50 * agi, moment, m_ss)
                    note_dmg_mana(1.0, m_ss)

            st["stealth_pending"] = torch.where(m, torch.zeros_like(st["stealth_pending"]), st["stealth_pending"])
            st["behind_pending"] = torch.where(m, torch.zeros_like(st["behind_pending"]), st["behind_pending"])

            need_rup = m & (~st["ruptured"] | st["dance_pending"])
            st["ruptured"] = torch.where(need_rup, torch.ones_like(st["ruptured"]), st["ruptured"])
            st["dance_pending"] = torch.where(need_rup, torch.zeros_like(st["dance_pending"]), st["dance_pending"])
            if bool(need_rup.any()):
                rupture(moment, 1.0, False, need_rup)
            m_cp = m & ~need_rup & (t_potency > 0.5)
            if bool(m_cp.any()):
                ch = chance(0.08 * (1.0 + 0.5 * share) * luck_mult)
                rupture(moment, ch, True, m_cp)

            # attack mana
            amg = torch.tensor([attack_mana_gain(stats_list[i]) for i in range(B)], dtype=dtype, device=device)
            gain_mana(amg, m)
            note_dmg_mana(1.0, m)

            m_fire = m & (fire_orb > 0.5)
            if bool(m_fire.any()):
                splash_w = (20.0 + 0.35 * agi) * targets_f * taken_for(1, moment)
                push_k(m_fire, moment, splash_w, N_FIRE, KIND_EXEC)
                note_dmg_mana(targets_f, m_fire)

            m_sulf = m & (has_sulfuras > 0.5)
            if bool(m_sulf.any()):
                taken0 = taken_for(0, moment)
                splash = m_sulf & (st["sulf_armed"] > 0.5)
                st["sulf_armed"] = torch.where(splash, zeros, st["sulf_armed"])
                # non-splash keeps armed state (attack returned False)
                # Wait: attack() clears only if armed. If not armed, stays False.
                # sulf_armed already 0 for non-armed; splash clears armed ones. Good.
                # But rows that are m_sulf but not armed: sulf_armed stays 0. Good.
                # Rows m_sulf and armed: cleared. Good.
                if bool(splash.any()):
                    push_k(splash, moment, agi * taken0 * targets_f, N_SULF, KIND_MAG)
                    note_dmg_mana(targets_f, splash)
                echo_ch = torch.tensor(
                    [sulfuras_echo_chance(float(luck[i].item())) for i in range(B)],
                    dtype=dtype, device=device,
                )
                push_k(m_sulf, moment, power * taken0 * echo_ch, N_SULF_ECHO, KIND_EXEC)

            st["next_attack"] = torch.where(m, moment + attack_interval(moment), st["next_attack"])

    events_list = _buffers_to_events(bufs, strike_name)
    return list(zip(events_list, stats_list))
