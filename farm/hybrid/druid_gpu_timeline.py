# -*- coding: utf-8 -*-
"""Batched next-event timeline for Druid (restoration / balance).

Faithful port of sunken_sim.druid._simulate_druid onto batched torch: one row per
(build, bound_key). Pending heap -> fixed slots ordered by (time, push order);
wisps / starfalls -> expiring slot tables. f64 clocks on CPU (DirectML lacks f64);
kind-score stays in farm.hybrid.druid (DirectML). Output events have the CPU shape
(when, name, raw, count, mastery_scale, attack, has_wisp, extra, special).

Feral Druid (O00R) is a separate class (farm/hybrid/feral_druid.py), not here.
"""
from __future__ import annotations

MAX_STEPS = 200000
MAX_PENDING = 256
MAX_WISPS = 128
MAX_FALLS = 64
EV_CAP0 = 1024

# button columns
B_STARFIRE = 0
B_STARFALL = 1
B_ENTANGLE = 2
B_WISP = 3
BUTTON_KEYS = ("starfire", "starfall", "entangle", "wisp")
COSTS = (20.0, 30.0, 35.0, 40.0)  # sunken_sim.druid cast_cost

# pending kinds
P_CAST = 0
P_ECHO = 1
P_STAR = 2
P_MISSILE = 3
P_ROOT = 4
P_TREANT = 5

# event names
N_AUTO = 0
N_STARFIRE = 1
N_ECHO = 2
N_STARFALL = 3
N_ENTANGLE = 4
N_TREANTS = 5
N_WISP = 6
N_FIRE = 7
N_SULF = 8
N_SULF_ECHO = 9
NAMES = {
    N_AUTO: "\u0410\u0432\u0442\u043e\u0430\u0442\u0430\u043a\u0430",
    N_STARFIRE: "Starfire",
    N_ECHO: "Starfire (\u044d\u0445\u043e)",
    N_STARFALL: "Starfall",
    N_ENTANGLE: "Mass Entanglement",
    N_TREANTS: "Treants",
    N_WISP: "Wisp Guardian",
    N_FIRE: "\u0412\u0441\u043f\u043b\u0435\u0441\u043a \u043e\u0433\u043d\u044f",
    N_SULF: "Sulfuras",
    N_SULF_ECHO: "Sulfuras (\u0443\u0434\u0430\u0440)",
}
S_NONE = 0
SPECIALS = {0: None, 1: "splash", 2: "echo", 3: "treant", 4: "sulfuras"}


class _Overflow(Exception):
    pass


def generate_druid_timelines(torch, device, rows, spec: str, targets: int):
    """rows: list[(build, bound_key)]. Returns list[(events, stats)] aligned with rows."""
    if spec not in ("restoration", "balance"):
        raise ValueError(f"druid GPU timeline specs restoration/balance, got {spec}")
    if not rows:
        return []
    dev_type = getattr(device, "type", str(device))
    if dev_type in ("privateuseone", "dml") or "privateuseone" in str(device):
        device = torch.device("cpu")
    try:
        return _druid_batch(torch, device, torch.float64, rows, spec, int(targets))
    except _Overflow:
        return _cpu_events_batch(rows, spec, targets)


def _cpu_events_batch(rows, spec, targets):
    from sunken_sim import druid as mod

    out = []
    for build, bound_key in rows:
        stats = mod.sheet(build, spec)
        key = mod._timeline_key(build, stats, spec, targets, bound_key)
        cached = mod._TIMELINE.get(key)
        if cached is None:
            mod._simulate_druid(build, targets, spec, bound_key)
            cached = mod._TIMELINE[key]
        out.append((list(cached[0]), stats))
    return out


def _row_consts(mod, build, spec, targets, bound_key):
    """Per-row constants computed with the exact CPU float expressions."""
    from sunken_sim.shadow import attack_mana_gain, cast_mana_back

    stats = mod.sheet(build, spec)
    has = lambda code: mod._has(build, code)  # noqa: E731
    wears = lambda code: mod._wears(build, code)  # noqa: E731
    surge = 1.5 if has(mod.TALENT_STARSURGE) else 1.0
    starlight = has(mod.TALENT_STARLIGHT)
    wisp_talent = has(mod.TALENT_WISP)
    luck_mult = 1.0 + stats["luck"]
    proc = lambda pct: min(1.0, pct / 100.0 * luck_mult)  # noqa: E731
    cooldown = mod._common(build, stats, bound_key)
    mm = stats["mana_max"]
    c = {}
    c["mana_max"] = mm
    c["mana_regen"] = stats["mana_regen"]
    c["dmp"] = stats.get("damage_mana_pct") or 0.0
    c["dmp_on"] = 1.0 if stats.get("damage_mana_pct") else 0.0
    c["stun"] = stats["cast_stun_lock"]
    c["swing"] = stats["swing"]
    c["ad"] = stats["ad"]
    c["auto_count"] = stats["auto_pct"] if stats["auto_pct"] != 1.0 else 1.0
    c["amg"] = attack_mana_gain(stats)
    for i, key in enumerate(BUTTON_KEYS):
        c[f"back{i}"] = cast_mana_back(COSTS[i], stats)
    sf_base = 8.0 - (1.5 if starlight else 0.0) - (2.0 if wears(mod.MOON_ITEM) else 0.0)
    c["cd0"] = cooldown(sf_base, "starfire")
    c["cd1"] = cooldown(14.0, "starfall")
    c["cd2"] = cooldown(10.0, "entangle")
    c["cd3"] = cooldown(12.0, "wisp")
    c["wrath"] = 1.0 if has(mod.TALENT_NATURES_WRATH) else 0.0
    c["wisp_life"] = mod.WISP_LIFE + (4.0 if wisp_talent else 0.0)
    c["entangle_t"] = 1.0 if has(mod.TALENT_ENTANGLE) else 0.0
    c["treants"] = 1.0 if (has(mod.TALENT_FORCE) or wears(mod.TREANT_ITEM)) else 0.0
    c["spread"] = 1.0 if has(mod.TALENT_WISP_SPREAD) else 0.0
    c["echo_t"] = 1.0 if has(mod.TALENT_STELLAR_ECHO) else 0.0
    c["missile"] = 1.0 if has(mod.TALENT_STARFALL_MISSILE) else 0.0
    c["bscale"] = (1.05 + 0.007 * stats["mastery"]) if spec == "balance" else 1.0
    c["root_raw"] = 10.0 + 0.015 * mm * surge
    c["root_double"] = 1.0 + (proc(20.0) if c["entangle_t"] else 0.0)
    star = 10.0 + 0.30 * stats["int"]
    if starlight:
        star *= 1.15
    c["star_raw"] = star
    wraw = 30.0 + 0.10 * mm * surge
    if wisp_talent:
        wraw *= 1.25
    c["wisp_raw"] = wraw
    c["wisp_hits"] = 1.0 + (proc(25.0) if wears(mod.WISP_ITEM) else 0.0)
    c["spread_ch"] = proc(30.0)
    c["fall_dur"] = 7.0 + 0.002 * mm * surge
    c["half_fall"] = 0.5 * (7.0 + 0.002 * mm * surge)
    c["sf_raw"] = 120.0 + 1.5 * stats["int"] + 0.05 * mm * surge
    c["inst_raw"] = 40.0 + 0.10 * mm * surge
    c["fire"] = 1.0 if wears(mod.FIRE_ORB) else 0.0
    c["fire_raw"] = (20.0 + 0.35 * stats["int"]) * targets
    c["sulf"] = 1.0 if wears(mod.SULFURAS_CODE) else 0.0
    c["sulf_raw"] = stats["int"]
    c["sulf_echo_raw"] = stats["ad"]
    return c, stats


def _druid_batch(torch, device, dtype, rows, spec, T):
    from sunken_sim import druid as mod
    from sunken_sim.shadow import CAST_BACKSWING, CAST_POINT, FIGHT

    B = len(rows)
    fight = float(FIGHT)
    cast_point = float(CAST_POINT)
    cast_time = float(CAST_POINT + CAST_BACKSWING)
    balance = spec == "balance"
    targets_f = float(T)
    BIG = 1e18

    consts = []
    stats_list = []
    for build, bound_key in rows:
        c, s = _row_consts(mod, build, spec, T, bound_key)
        consts.append(c)
        stats_list.append(s)

    def vec(key):
        return torch.tensor([c[key] for c in consts], dtype=dtype, device=device)

    def flag(key):
        return vec(key) > 0.5

    zeros = torch.zeros(B, dtype=dtype, device=device)
    ones = torch.ones(B, dtype=dtype, device=device)
    rix = torch.arange(B, device=device)
    mana_max = vec("mana_max")
    mana_regen = vec("mana_regen")
    dmp = vec("dmp")
    dmp_on = flag("dmp_on")
    any_dmp = bool(dmp_on.any())
    stun = vec("stun")
    swing = vec("swing")
    cds = torch.stack([vec("cd0"), vec("cd1"), vec("cd2"), vec("cd3")], dim=1)
    backs = torch.stack([vec("back0"), vec("back1"), vec("back2"), vec("back3")], dim=1)
    costs = torch.tensor(COSTS, dtype=dtype, device=device)
    wrath = flag("wrath")
    wisp_life = vec("wisp_life")
    entangle_t = flag("entangle_t")
    treants_on = flag("treants")
    spread = flag("spread")
    echo_t = flag("echo_t")
    missile = flag("missile")
    bscale = vec("bscale")
    fire_on = flag("fire")
    sulf_on = flag("sulf")
    K = {k: vec(k) for k in (
        "ad", "auto_count", "amg", "root_raw", "root_double", "star_raw", "wisp_raw",
        "wisp_hits", "spread_ch", "fall_dur", "half_fall", "sf_raw", "inst_raw",
        "fire_raw", "sulf_raw", "sulf_echo_raw",
    )}

    has_btn = torch.ones(4, dtype=torch.bool, device=device)
    if not balance:
        has_btn[B_STARFALL] = False

    st = {
        "mana": mana_max.clone(),
        "mana_time": zeros.clone(),
        "ready": torch.where(has_btn.view(1, 4).expand(B, 4), zeros.view(B, 1).expand(B, 4).clone(),
                             torch.full((B, 4), BIG, dtype=dtype, device=device)).clone(),
        "root_until": torch.full((B,), -1.0, dtype=dtype, device=device),
        "hero_ready": zeros.clone(),
        "next_attack": zeros.clone(),
        "armed": torch.zeros(B, dtype=torch.bool, device=device),
        "order": torch.zeros(B, dtype=torch.int64, device=device),
        "p_time": torch.full((B, MAX_PENDING), BIG, dtype=dtype, device=device),
        "p_order": torch.zeros((B, MAX_PENDING), dtype=torch.int64, device=device),
        "p_kind": torch.zeros((B, MAX_PENDING), dtype=torch.int64, device=device),
        "p_pay": torch.zeros((B, MAX_PENDING), dtype=dtype, device=device),
        "w_end": torch.full((B, MAX_WISPS), -BIG, dtype=dtype, device=device),
        "w_w": torch.zeros((B, MAX_WISPS), dtype=dtype, device=device),
        "w_main": torch.zeros((B, MAX_WISPS), dtype=torch.bool, device=device),
        "f_end": torch.full((B, MAX_FALLS), -BIG, dtype=dtype, device=device),
    }
    ev = {
        "cap": EV_CAP0,
        "len": torch.zeros(B, dtype=torch.int64, device=device),
        "when": torch.zeros((B, EV_CAP0), dtype=dtype, device=device),
        "raw": torch.zeros((B, EV_CAP0), dtype=dtype, device=device),
        "count": torch.zeros((B, EV_CAP0), dtype=dtype, device=device),
        "ms": torch.zeros((B, EV_CAP0), dtype=dtype, device=device),
        "extra": torch.zeros((B, EV_CAP0), dtype=dtype, device=device),
        "name": torch.zeros((B, EV_CAP0), dtype=torch.int64, device=device),
        "spec": torch.zeros((B, EV_CAP0), dtype=torch.int64, device=device),
        "attack": torch.zeros((B, EV_CAP0), dtype=torch.bool, device=device),
        "wisp": torch.zeros((B, EV_CAP0), dtype=torch.bool, device=device),
    }

    def full(v, like=zeros):
        return v if isinstance(v, torch.Tensor) else torch.full_like(like, float(v))

    def emit(mask, when, name, raw, count, ms, attack, has_wisp, extra, special):
        if not bool(mask.any()):
            return
        if int(ev["len"].max()) >= ev["cap"]:
            cap = ev["cap"]
            for k in ("when", "raw", "count", "ms", "extra", "name", "spec", "attack", "wisp"):
                old = ev[k]
                new = torch.zeros((B, cap * 2), dtype=old.dtype, device=device)
                new[:, :cap] = old
                ev[k] = new
            ev["cap"] = cap * 2
        r = rix[mask]
        i = ev["len"][mask]
        ev["when"][r, i] = full(when)[mask]
        ev["raw"][r, i] = full(raw)[mask]
        ev["count"][r, i] = full(count)[mask]
        ev["ms"][r, i] = full(ms)[mask]
        ev["extra"][r, i] = full(extra)[mask]
        ev["name"][r, i] = int(name)
        ev["spec"][r, i] = int(special)
        ev["attack"][r, i] = bool(attack)
        ev["wisp"][r, i] = bool(has_wisp)
        ev["len"] = ev["len"] + mask.to(torch.int64)

    def push(mask, when, kind, payload=0.0):
        when = full(when)
        m = mask & (when < fight)
        if not bool(m.any()):
            return
        free = st["p_time"] >= BIG
        has_free = free.any(dim=1)
        if bool((m & ~has_free).any()):
            raise _Overflow("pending")
        slot = torch.argmax(free.to(torch.int8), dim=1)
        r = rix[m]
        s = slot[m]
        st["order"] = st["order"] + m.to(torch.int64)
        st["p_time"][r, s] = when[m]
        st["p_order"][r, s] = st["order"][m]
        st["p_kind"][r, s] = int(kind)
        st["p_pay"][r, s] = full(payload)[m]

    def peek():
        t = st["p_time"].min(dim=1).values
        return torch.where(t >= BIG, torch.full_like(t, fight), t)

    def pop(mask):
        tmin = st["p_time"].min(dim=1, keepdim=True).values
        cand = st["p_time"] == tmin
        big_o = torch.iinfo(torch.int64).max
        o = torch.where(cand, st["p_order"], torch.full_like(st["p_order"], big_o))
        slot = torch.argmin(o, dim=1)
        now = st["p_time"][rix, slot].clone()
        kind = st["p_kind"][rix, slot].clone()
        pay = st["p_pay"][rix, slot].clone()
        r = rix[mask]
        st["p_time"][r, slot[mask]] = BIG
        return now, kind, pay

    def main_wisp(now):
        live = st["w_main"] & (now.view(B, 1) < st["w_end"])
        return torch.clamp(torch.where(live, st["w_w"], torch.zeros_like(st["w_w"])).sum(dim=1), max=1.0)

    def wisp_count(now):
        live = now.view(B, 1) < st["w_end"]
        return torch.clamp(torch.where(live, st["w_w"], torch.zeros_like(st["w_w"])).sum(dim=1), max=targets_f)

    def add_wisp(mask, now, end, weight, is_main):
        if not bool(mask.any()):
            return
        free = st["w_end"] <= now.view(B, 1)
        if bool((mask & ~free.any(dim=1)).any()):
            raise _Overflow("wisps")
        slot = torch.argmax(free.to(torch.int8), dim=1)
        r = rix[mask]
        s = slot[mask]
        st["w_end"][r, s] = end[mask]
        st["w_w"][r, s] = full(weight)[mask]
        st["w_main"][r, s] = is_main[mask]

    def active_falls(now):
        return (now.view(B, 1) < st["f_end"]).sum(dim=1).to(dtype)

    def rooted(now):
        return now < st["root_until"]

    def recover(now, mask):
        add = mask & (now > st["mana_time"]) & (st["mana"] < mana_max)
        val = torch.minimum(mana_max, st["mana"] + mana_regen * (now - st["mana_time"]))
        st["mana"] = torch.where(add, val, st["mana"])
        st["mana_time"] = torch.where(mask, torch.maximum(st["mana_time"], now), st["mana_time"])

    def deal(mask, name, raw, now, count, attack, share, ms=None):
        count = full(count)
        m = mask & (count > 0) & (now < fight)
        if not bool(m.any()):
            return
        ms_t = ones if ms is None else ms
        share = torch.clamp(full(share), 0.0, 1.0)
        rt = rooted(now)
        for part, has_wisp in ((share, True), (1.0 - share, False)):
            extra = zeros.clone()
            extra = torch.where(wrath, extra + (0.15 if has_wisp else 0.0), extra)
            extra = torch.where(wrath & rt, extra + 0.10, extra)
            emit(m & (part > 0), now, name, raw, count * part, ms_t, attack, has_wisp, extra, S_NONE)
        if any_dmp:
            mm = m & dmp_on
            st["mana"] = torch.where(mm, torch.minimum(mana_max, st["mana"] + dmp * mana_max * count), st["mana"])

    def add_special(mask, now, name, raw, count, special):
        raw = full(raw)
        count = full(count)
        emit(mask & (raw != 0) & (count != 0), now, name, raw, count, ones, False, False, zeros, special)

    def spread_share(now):
        return wisp_count(now) / T

    def root_tick(mask, now, count, share):
        deal(mask, N_ENTANGLE, K["root_raw"], now, full(count) * K["root_double"], False, share)

    def spawn_fall(mask, now, duration):
        if not bool(mask.any()):
            return
        end = now + duration
        free = st["f_end"] <= now.view(B, 1)
        if bool((mask & ~free.any(dim=1)).any()):
            raise _Overflow("falls")
        slot = torch.argmax(free.to(torch.int8), dim=1)
        st["f_end"][rix[mask], slot[mask]] = end[mask]
        push(mask, now + mod.STARFALL_GAP, P_STAR, end)
        push(mask & missile, now + mod.MISSILE_GAP, P_MISSILE, end)

    def star_hit(mask, now):
        deal(mask, N_STARFALL, K["star_raw"], now, 1.0, False, spread_share(now), bscale)

    def on_spellcast(mask, now):
        cnt = wisp_count(now)
        m = mask & (cnt > 0)
        if bool(m.any()):
            deal(m, N_WISP, K["wisp_raw"], now, cnt * K["wisp_hits"], False, 1.0)
        ms = mask & spread & (K["spread_ch"] > 0) & (wisp_count(now) < targets_f)
        if bool(ms.any()):
            add_wisp(ms, now, now + wisp_life, K["spread_ch"], torch.zeros(B, dtype=torch.bool, device=device))

    def resolve(mask, spell, now):
        on_spellcast(mask, now)
        m = mask & (spell == B_WISP)
        if bool(m.any()):
            add_wisp(m, now, now + wisp_life, 1.0, main_wisp(now) <= 0)
        m = mask & (spell == B_STARFALL)
        if bool(m.any()):
            spawn_fall(m, now, K["fall_dur"])
        m = mask & (spell == B_STARFIRE)
        if bool(m.any()):
            if balance:
                spawn_fall(m, now, K["half_fall"])
            raw = K["sf_raw"] * (1.0 + 0.12 * active_falls(now))
            deal(m, N_STARFIRE, raw, now, 1.0, False, main_wisp(now), bscale)
            push(m & echo_t, now + 1.5, P_ECHO, raw * 0.35)
        m = mask & (spell == B_ENTANGLE)
        if bool(m.any()):
            share = spread_share(now)
            rt = rooted(now)
            root_tick(m & rt, now, targets_f, share)
            deal(m & entangle_t, N_ENTANGLE, K["inst_raw"], now, targets_f, False, share)
            first = m & ~rt
            st["root_until"] = torch.where(m, now + mod.ROOT_LIFE, st["root_until"])
            push(first, now + mod.ROOT_GAP, P_ROOT)
            mt = m & treants_on
            for _ in range(2):
                push(mt, now + mod.TREANT_SWING, P_TREANT, now + mod.TREANT_LIFE)

    def on_attack(mask, now):
        recover(now, mask)
        deal(mask, N_AUTO, K["ad"], now, K["auto_count"], True, main_wisp(now))
        st["mana"] = torch.where(mask, torch.minimum(mana_max, st["mana"] + K["amg"]), st["mana"])
        add_special(mask & fire_on, now, N_FIRE, K["fire_raw"], 1.0, 1)
        ms = mask & sulf_on
        if bool(ms.any()):
            fire = ms & st["armed"]
            st["armed"] = st["armed"] & ~fire
            add_special(fire, now, N_SULF, K["sulf_raw"], targets_f, 4)
            add_special(ms, now, N_SULF_ECHO, K["sulf_echo_raw"], 1.0, 2)

    def choose(now):
        mw = main_wisp(now)
        wc = wisp_count(now)
        rdy = has_btn.view(1, 4) & (st["ready"] <= now.view(B, 1))
        choice = torch.full((B,), -1, dtype=torch.int64, device=device)
        # order: [wisp if main<=0], starfall, starfire, entangle, wisp(skip if main>0 & full)
        cands = [
            (B_WISP, rdy[:, B_WISP] & (mw <= 0)),
            (B_STARFALL, rdy[:, B_STARFALL]),
            (B_STARFIRE, rdy[:, B_STARFIRE]),
            (B_ENTANGLE, rdy[:, B_ENTANGLE]),
            (B_WISP, rdy[:, B_WISP] & ~((mw > 0) & (wc >= targets_f))),
        ]
        for col, ok in reversed(cands):
            choice = torch.where(ok, torch.full_like(choice, col), choice)
        return choice

    alive = torch.ones(B, dtype=torch.bool, device=device)
    steps = 0
    while bool(alive.any()):
        steps += 1
        if steps > MAX_STEPS:
            raise _Overflow("steps")
        hr = st["hero_ready"]
        pk = peek()
        moment = torch.minimum(st["next_attack"], pk)
        A = alive & (hr <= moment) & (hr < fight)
        fall_through = alive & ~A
        if bool(A.any()):
            spell = torch.where(A, choose(hr), torch.full((B,), -1, dtype=torch.int64, device=device))
            S = A & (spell >= 0)
            if bool(S.any()):
                sp = torch.clamp(spell, min=0)
                cost = costs[sp]
                recover(hr, S)
                ok = S & ~(st["mana"] < cost)
                st["mana"] = torch.where(ok, torch.minimum(mana_max, (st["mana"] - cost) + backs[rix, sp]), st["mana"])
                fail = S & ~ok
                onehot = torch.nn.functional.one_hot(sp, 4).to(torch.bool)
                st["ready"] = torch.where(fail.view(B, 1) & onehot, (hr + 0.25).view(B, 1), st["ready"])
                st["ready"] = torch.where(ok.view(B, 1) & onehot, (hr + cds[rix, sp]).view(B, 1), st["ready"])
                st["armed"] = st["armed"] | (ok & sulf_on)
                push(ok, hr + cast_point, P_CAST, sp.to(dtype))
                busy = hr + cast_time + stun
                st["hero_ready"] = torch.where(ok, busy, st["hero_ready"])
                st["next_attack"] = torch.where(ok, torch.maximum(st["next_attack"], busy), st["next_attack"])
            N = A & (spell < 0)
            if bool(N.any()):
                fut = has_btn.view(1, 4) & (st["ready"] > (hr + 1e-9).view(B, 1))
                wake = torch.where(fut, st["ready"], torch.full_like(st["ready"], BIG)).min(dim=1).values
                wake = torch.where(wake >= BIG, torch.full_like(wake, fight), wake)
                w1 = N & (wake <= moment)
                st["hero_ready"] = torch.where(w1, wake, st["hero_ready"])
                w2 = N & ~(wake <= moment)
                st["hero_ready"] = torch.where(
                    w2, torch.maximum(hr, torch.clamp(wake, max=fight)), st["hero_ready"]
                )
                fall_through = fall_through | w2
        done = fall_through & (moment >= fight)
        alive = alive & ~done
        E = fall_through & ~done
        if not bool(E.any()):
            continue
        atk = E & (st["next_attack"] < pk)
        if bool(atk.any()):
            on_attack(atk, moment)
            st["next_attack"] = torch.where(atk, moment + swing, st["next_attack"])
        P = E & ~atk
        if not bool(P.any()):
            continue
        now, kind, pay = pop(P)
        m = P & (kind == P_CAST)
        if bool(m.any()):
            resolve(m, pay.round().to(torch.int64), now)
        m = P & (kind == P_ECHO)
        if bool(m.any()):
            deal(m, N_ECHO, pay, now, 1.0, False, main_wisp(now), bscale)
        for pk_kind, gap in ((P_STAR, mod.STARFALL_GAP), (P_MISSILE, mod.MISSILE_GAP)):
            m = P & (kind == pk_kind) & (now < pay + 1e-9)
            if bool(m.any()):
                star_hit(m, now)
                push(m & (now + gap <= pay + 1e-9), now + gap, pk_kind, pay)
        m = P & (kind == P_ROOT) & rooted(now + 1e-9)
        if bool(m.any()):
            root_tick(m, now, targets_f, spread_share(now))
            push(m, now + mod.ROOT_GAP, P_ROOT)
        m = P & (kind == P_TREANT) & (now <= pay + 1e-9)
        if bool(m.any()):
            add_special(m, now, N_TREANTS, mod.TREANT_HIT, 1.0, 3)
            root_tick(m & rooted(now), now, 1.0, main_wisp(now))
            push(m & (now + mod.TREANT_SWING <= pay + 1e-9), now + mod.TREANT_SWING, P_TREANT, pay)

    return list(zip(_to_events(ev, B), stats_list))


def _to_events(ev, B):
    cols = {k: ev[k].detach().cpu().tolist() for k in
            ("when", "raw", "count", "ms", "extra", "name", "spec", "attack", "wisp")}
    lengths = ev["len"].detach().cpu().tolist()
    out = []
    for b in range(B):
        n = lengths[b]
        out.append([
            (cols["when"][b][i], NAMES[cols["name"][b][i]], cols["raw"][b][i], cols["count"][b][i],
             cols["ms"][b][i], bool(cols["attack"][b][i]), bool(cols["wisp"][b][i]),
             cols["extra"][b][i], SPECIALS[cols["spec"][b][i]])
            for i in range(n)
        ])
    return out
