"""Druid fight for Sunken City, level 6.

Druid E009 (intellect). Strength 14 + 1.4, agility 8 + 0.8, intellect 28 + 2.8.
White hit is 10 + 1 die, attack cooldown 2.0, attack type magic, range 800.
Spec level on A0E0: 1 Restoration, 2 Balance.

Feral Druid (O00R) is a separate class and gets its own script later; it is not simulated here.

Ability rank is 1. Healing and survivability are not scored.
"""

from __future__ import annotations

import heapq

from sunken_sim.shadow import (
    CAST_BACKSWING,
    CAST_POINT,
    DUMMY_ARMOR,
    FIGHT,
    LEVEL,
    ORB_MODE,
    Build,
    Report,
    Sulfuras,
    _crit_factor,
    _execute_factor,
    _has,
    _magical_multiplier,
    _wears,
    armor_taken,
    attack_mana_gain,
    cast_mana_back,
    character,
    sulfuras_echo_chance,
)

CAST_TIME = CAST_POINT + CAST_BACKSWING

# Druid E009
DRUID_STR = int(14 + (LEVEL - 1) * 1.4)
DRUID_AGI = int(8 + (LEVEL - 1) * 0.8)
DRUID_INT = int(28 + (LEVEL - 1) * 2.8)
DRUID_WHITE = 11.0
DRUID_SWING = 2.0

DRUID_SPECS = ("restoration", "balance")
SPECS = DRUID_SPECS
HERO_CLASS = "Druid"  # item pool class for E009

# Druid talents (Talents_Unit[3])
TALENT_REJUVENATION = "I0K5"
TALENT_LIFEBLOOM = "I0K2"
TALENT_BARKSKIN = "I02F"
TALENT_STELLAR_ECHO = "I0K4"
TALENT_K3 = "I0K3"
TALENT_STARFALL_MISSILE = "I0K1"
TALENT_STARSURGE = "I0K0"
TALENT_NATURES_WRATH = "I0P8"
TALENT_ENTANGLE = "I0JZ"
TALENT_WISP = "I0P5"
TALENT_ML = "I0ML"
TALENT_DRUIDISM = "I0MS"
TALENT_STARLIGHT = "I0JY"
TALENT_P4 = "I0P4"
TALENT_FORCE = "I0P7"
TALENT_WISP_SPREAD = "I08O"
TALENT_8Q = "I08Q"
TALENT_8S = "I08S"

DRUID_TALENTS = {
    TALENT_REJUVENATION: "I0K5 (лечение)",
    TALENT_LIFEBLOOM: "I0K2 (лечение)",
    TALENT_BARKSKIN: "I02F (при получении урона)",
    TALENT_STELLAR_ECHO: "Starfire Echo (I0K4)",
    TALENT_K3: "I0K3 (лечение)",
    TALENT_STARFALL_MISSILE: "Starfall Missile (I0K1)",
    TALENT_STARSURGE: "Starsurge (I0K0)",
    TALENT_NATURES_WRATH: "Nature's Wrath (I0P8)",
    TALENT_ENTANGLE: "Entangle (I0JZ)",
    TALENT_WISP: "Wisp (I0P5)",
    TALENT_ML: "I0ML (союзники)",
    TALENT_DRUIDISM: "Druidism (I0MS)",
    TALENT_STARLIGHT: "Starlight (I0JY)",
    TALENT_P4: "I0P4 (лечение)",
    TALENT_FORCE: "Force of Nature (I0P7)",
    TALENT_WISP_SPREAD: "Wisp Spread (I08O)",
    TALENT_8Q: "I08Q (лечение)",
    TALENT_8S: "I08S (лечение)",
}
TALENTS = DRUID_TALENTS
IGNORED_TALENTS = frozenset(
    {
        TALENT_REJUVENATION,
        TALENT_LIFEBLOOM,
        TALENT_BARKSKIN,
        TALENT_K3,
        TALENT_ML,
        TALENT_P4,
        TALENT_8Q,
        TALENT_8S,
    }
)


def talents_for(spec: str) -> dict[str, str]:
    if spec not in SPECS:
        raise ValueError(spec)
    return DRUID_TALENTS


# Class items
MOON_ITEM = "I0R1"  # +8 int, +200 mana, Starfire cd -2
WISP_ITEM = "I0R3"  # +12 int, +10% haste, Wisp second hit
SEED_ITEM = "I0R2"  # mastery + mp5, heal part ignored
TREANT_ITEM = "I0R4"  # +180 mana, +5 potency, Force of Nature
HEAL_ITEM = "I0V0"

GALACTIC_FURY = "I0JO"
FIRE_ORB = "I07O"
DIAMOND = "I00D"
PIPE = "I00L"
SULFURAS_CODE = "I0BR"

BOUND_NAME = {
    "starfire": "Starfire",
    "starfall": "Starfall",
    "entangle": "Mass Entanglement",
    "wisp": "Wisp Guardian",
}

STARFALL_GAP = 1.0  # A002 Phoenix Fire, acdn not set: engine default 1.0 (tooltip says 0.5)
MISSILE_GAP = 1.5  # A014 acdn 1.5 with I0K1
ROOT_LIFE = 6.0
ROOT_GAP = 1.0
TREANT_LIFE = 10.0
TREANT_SWING = 1.65
TREANT_HIT = 12.0
WISP_LIFE = 8.0
WISP_ARMOR = 3.0

def sheet(build: Build, spec: str = "balance") -> dict[str, float]:
    if spec not in SPECS:
        raise ValueError(spec)
    galactic = 1.20 if _wears(build, GALACTIC_FURY) else 1.0
    stats = character(build, DRUID_STR, DRUID_AGI, DRUID_INT, DRUID_WHITE, bake_timed_buffs=False)
    stats["attack_base"] = DRUID_SWING * galactic
    if _has(build, TALENT_DRUIDISM):
        stats["potency"] += 2.0 + stats["mana_max"] / 200.0
    stats["swing"] = stats["attack_base"] / (1.0 + stats["attack_speed"])
    return stats


def buttons(spec: str) -> tuple[str, ...]:
    if spec == "balance":
        return ("starfire", "starfall", "entangle", "wisp")
    if spec == "restoration":
        return ("starfire", "entangle", "wisp")
    raise ValueError(spec)


def _bound_key(bound_spell: str | None) -> str | None:
    if not bound_spell:
        return None
    for key, name in BOUND_NAME.items():
        if bound_spell == key or bound_spell == name:
            return key
    raise ValueError(bound_spell)


def simulate(build: Build, targets: int = 5, spec: str = "balance", bound_spell: str | None = None) -> Report:
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    if _wears(build, DIAMOND) and bound_spell is None:
        best = None
        for spell in buttons(spec):
            report = simulate(build, targets, spec, BOUND_NAME[spell])
            if best is None or report.dps > best.dps:
                best = report
        return best
    return _simulate_druid(build, targets, spec, _bound_key(bound_spell))


class _Clock:
    """Event queue: (time, order, kind, payload)."""

    def __init__(self) -> None:
        self.heap: list = []
        self.order = 0

    def push(self, when: float, kind: str, payload=None) -> None:
        if when >= FIGHT:
            return
        self.order += 1
        heapq.heappush(self.heap, (when, self.order, kind, payload))

    def peek(self) -> float:
        return self.heap[0][0] if self.heap else FIGHT

    def pop(self):
        return heapq.heappop(self.heap)


def _common(build: Build, stats: dict, bound_key: str | None):
    def cooldown(base: float, key: str, flat: float = 0.0) -> float:
        temp = stats["cd_temp"] * (0.70 if bound_key == key else 1.0)
        return max(0.5, (base * temp - stats["flat_cdr"] - flat) / (1.0 + stats["haste"]))

    return cooldown


def _report(build, total_sources, actions, stats, targets, bound_key, mana) -> Report:
    total = sum(total_sources.values())
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    mode = next((name for code, name in ORB_MODE.items() if _wears(build, code)), None)
    return Report(
        build,
        total / FIGHT,
        total,
        total_sources,
        actions,
        stats,
        targets,
        orb_mode=mode,
        bound_spell=BOUND_NAME.get(bound_key or "", None),
        mana_left=mana_left,
    )


def _simulate_druid(build: Build, targets: int, spec: str, bound_key: str | None) -> Report:
    stats = sheet(build, spec)
    codes = frozenset(item.rawcode for item in build.items) | build.talents | build.glyphs
    cooldown = _common(build, stats, bound_key)
    balance = spec == "balance"
    surge = 1.5 if _has(build, TALENT_STARSURGE) else 1.0
    wrath = _has(build, TALENT_NATURES_WRATH)
    starlight = _has(build, TALENT_STARLIGHT)
    wisp_talent = _has(build, TALENT_WISP)
    entangle_talent = _has(build, TALENT_ENTANGLE)
    treants_on = _has(build, TALENT_FORCE) or _wears(build, TREANT_ITEM)
    spread = _has(build, TALENT_WISP_SPREAD)
    echo_talent = _has(build, TALENT_STELLAR_ECHO)
    missile = _has(build, TALENT_STARFALL_MISSILE)
    pen = stats["armor_pen"]
    taken_plain = armor_taken(DUMMY_ARMOR - pen)
    taken_wisp = armor_taken(DUMMY_ARMOR - pen - WISP_ARMOR)
    wisp_life = WISP_LIFE + (4.0 if wisp_talent else 0.0)

    sources: dict[str, float] = {
        "Автоатака": 0.0,
        "Starfire": 0.0,
        "Starfire (эхо)": 0.0,
        "Starfall": 0.0,
        "Mass Entanglement": 0.0,
        "Treants": 0.0,
        "Wisp Guardian": 0.0,
        "Всплеск огня": 0.0,
    }
    actions: list[tuple[float, str]] = []
    clock = _Clock()
    state = {"mana": stats["mana_max"], "mana_time": 0.0}
    ready = {key: 0.0 for key in buttons(spec)}
    root_until = -1.0
    wisps: list[list[float]] = []  # [expire, weight, is_main]
    starfalls: list[dict] = []
    sulfuras = Sulfuras() if _wears(build, SULFURAS_CODE) else None
    fire_orb = _wears(build, FIRE_ORB)
    hero_ready = 0.0
    next_attack = 0.0

    def luck_mult() -> float:
        return 1.0 + stats["luck"]

    def proc(percent: float) -> float:
        return min(1.0, percent / 100.0 * luck_mult())

    def recover(now: float) -> None:
        if now > state["mana_time"] and state["mana"] < stats["mana_max"]:
            state["mana"] = min(stats["mana_max"], state["mana"] + stats["mana_regen"] * (now - state["mana_time"]))
        state["mana_time"] = max(state["mana_time"], now)

    def pay(cost: float, now: float) -> bool:
        recover(now)
        if state["mana"] < cost:
            return False
        state["mana"] -= cost
        state["mana"] = min(stats["mana_max"], state["mana"] + cast_mana_back(cost, stats))
        return True

    def main_wisp(now: float) -> float:
        return min(1.0, sum(w for end, w, main in wisps if main and now < end))

    def wisp_count(now: float) -> float:
        return min(float(targets), sum(w for end, w, _main in wisps if now < end))

    def rooted(now: float) -> bool:
        return now < root_until

    def deal(name: str, raw: float, now: float, count: float, attack: bool, wisp_share: float, mastery_scale: float = 1.0) -> None:
        """Magical damage from the Druid. wisp_share is the part of hits on Wisp targets."""
        if count <= 0 or now >= FIGHT:
            return
        mastery = stats["mastery"]
        wisp_share = max(0.0, min(1.0, wisp_share))
        amount = 0.0
        for share, has_wisp in ((wisp_share, True), (1.0 - wisp_share, False)):
            if share <= 0:
                continue
            extra = 0.0
            if wrath:
                extra += 0.15 if has_wisp else 0.0
                extra += 0.10 if rooted(now) else 0.0
            part = (raw * mastery_scale + stats["potency"]) * _magical_multiplier(codes, now, mastery, extra)
            part *= taken_wisp if has_wisp else taken_plain
            amount += share * part
        if attack:
            amount *= _crit_factor(stats["crit"], 2.0 + stats["rating"])
        elif stats["spell_crit"]:
            amount *= _crit_factor(stats["crit"], stats["spell_mult"] + stats["rating"])
        amount *= _execute_factor(stats, now)
        sources[name] = sources.get(name, 0.0) + amount * count
        if stats.get("damage_mana_pct"):
            state["mana"] = min(stats["mana_max"], state["mana"] + stats["damage_mana_pct"] * stats["mana_max"] * count)

    def balance_scale() -> float:
        return (1.05 + 0.007 * stats["mastery"]) if balance else 1.0

    def spread_share(now: float) -> float:
        return wisp_count(now) / targets

    def root_tick(now: float, count: float, share: float) -> None:
        raw = 10.0 + 0.015 * stats["mana_max"] * surge
        double = 1.0 + (proc(20.0) if entangle_talent else 0.0)
        deal("Mass Entanglement", raw, now, count * double, False, share)

    def spawn_starfall(now: float, duration: float) -> None:
        fall = {"end": now + duration}
        starfalls.append(fall)
        clock.push(now + STARFALL_GAP, "star", fall)
        if missile:
            clock.push(now + MISSILE_GAP, "missile", fall)

    def active_starfalls(now: float) -> int:
        return sum(1 for fall in starfalls if now < fall["end"])

    def star_hit(now: float) -> None:
        raw = 10.0 + 0.30 * stats["int"]
        if starlight:
            raw *= 1.15
        deal("Starfall", raw, now, 1.0, False, spread_share(now), balance_scale())

    def wisp_trigger(now: float) -> None:
        count = wisp_count(now)
        if count <= 0:
            return
        raw = 30.0 + 0.10 * stats["mana_max"] * surge
        if wisp_talent:
            raw *= 1.25
        hits = count * (1.0 + (proc(25.0) if _wears(build, WISP_ITEM) else 0.0))
        deal("Wisp Guardian", raw, now, hits, False, 1.0)

    def on_spellcast(now: float) -> None:
        wisp_trigger(now)
        if spread:
            chance = proc(30.0)
            if chance > 0 and wisp_count(now) < targets:
                wisps.append([now + wisp_life, chance, False])

    def cast_cost(name: str) -> float:
        return {"starfire": 20.0, "starfall": 30.0, "entangle": 35.0, "wisp": 40.0}[name]

    def cast_cd(name: str) -> float:
        if name == "starfire":
            base = 8.0 - (1.5 if starlight else 0.0) - (2.0 if _wears(build, MOON_ITEM) else 0.0)
            return cooldown(base, name)
        if name == "starfall":
            return cooldown(14.0, name)
        if name == "entangle":
            return cooldown(10.0, name)
        return cooldown(12.0, name)

    def choose(now: float) -> str | None:
        order = ["wisp"] if main_wisp(now) <= 0 else []
        order += ["starfall", "starfire", "entangle", "wisp"]
        for name in order:
            if name in ready and ready[name] <= now:
                if name == "wisp" and main_wisp(now) > 0 and wisp_count(now) >= targets:
                    continue
                return name
        return None

    def resolve(name: str, now: float) -> None:
        nonlocal root_until
        on_spellcast(now)
        if name == "wisp":
            wisps.append([now + wisp_life, 1.0, main_wisp(now) <= 0])
        elif name == "starfall":
            spawn_starfall(now, 7.0 + 0.002 * stats["mana_max"] * surge)
        elif name == "starfire":
            if balance:
                spawn_starfall(now, 0.5 * (7.0 + 0.002 * stats["mana_max"] * surge))
            raw = 120.0 + 1.5 * stats["int"] + 0.05 * stats["mana_max"] * surge
            raw *= 1.0 + 0.12 * active_starfalls(now)
            deal("Starfire", raw, now, 1.0, False, main_wisp(now), balance_scale())
            if echo_talent:
                clock.push(now + 1.5, "echo", raw * 0.35)
        elif name == "entangle":
            share = spread_share(now)
            if rooted(now):
                root_tick(now, targets, share)
            if entangle_talent:
                instant = 40.0 + 0.10 * stats["mana_max"] * surge
                deal("Mass Entanglement", instant, now, targets, False, share)
            first = not rooted(now)
            root_until = now + ROOT_LIFE
            if first:
                clock.push(now + ROOT_GAP, "root", None)
            if treants_on:
                for _ in range(2):
                    clock.push(now + TREANT_SWING, "treant", now + TREANT_LIFE)

    def on_attack(now: float) -> None:
        recover(now)
        before = sources["Автоатака"]
        deal("Автоатака", stats["ad"], now, 1.0, True, main_wisp(now))
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        state["mana"] = min(stats["mana_max"], state["mana"] + attack_mana_gain(stats))
        execute = _execute_factor(stats, now)
        if fire_orb:
            sources["Всплеск огня"] += (20.0 + 0.35 * stats["int"]) * targets * taken_plain * execute
        if sulfuras is not None:
            if sulfuras.attack():
                splash = (
                    stats["int"]
                    * _magical_multiplier(codes, now, stats["mastery"])
                    * (_crit_factor(stats["crit"], stats["spell_mult"] + stats["rating"]) if stats["spell_crit"] else 1.0)
                    * taken_plain
                    * execute
                    * targets
                )
                sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
            echo = stats["ad"] * taken_plain * execute * sulfuras_echo_chance(stats["luck"])
            sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo

    guard = 0
    while guard < 200000:
        guard += 1
        moment = min(next_attack, clock.peek())
        if hero_ready <= moment and hero_ready < FIGHT:
            spell = choose(hero_ready)
            if spell is not None:
                if not pay(cast_cost(spell), hero_ready):
                    ready[spell] = hero_ready + 0.25
                    continue
                actions.append((hero_ready, BOUND_NAME[spell]))
                ready[spell] = hero_ready + cast_cd(spell)
                if sulfuras is not None:
                    sulfuras.cast()
                clock.push(hero_ready + CAST_POINT, "cast", spell)
                busy = hero_ready + CAST_TIME + stats["cast_stun_lock"]
                hero_ready = busy
                next_attack = max(next_attack, busy)
                continue
            future = [t for t in ready.values() if t > hero_ready + 1e-9]
            wake = min(future) if future else FIGHT
            if wake <= moment:
                hero_ready = wake
                continue
            hero_ready = max(hero_ready, min(wake, FIGHT))
        if moment >= FIGHT:
            break
        if moment == next_attack and (not clock.heap or next_attack < clock.peek()):
            on_attack(moment)
            next_attack = moment + stats["swing"]
            continue
        now, _order, kind, payload = clock.pop()
        if kind == "cast":
            resolve(payload, now)
        elif kind == "echo":
            deal("Starfire (эхо)", payload, now, 1.0, False, main_wisp(now), balance_scale())
        elif kind in ("star", "missile"):
            if now < payload["end"] + 1e-9:
                star_hit(now)
                gap = STARFALL_GAP if kind == "star" else MISSILE_GAP
                if now + gap <= payload["end"] + 1e-9:
                    clock.push(now + gap, kind, payload)
        elif kind == "root":
            if rooted(now + 1e-9):
                root_tick(now, targets, spread_share(now))
                clock.push(now + ROOT_GAP, "root", None)
        elif kind == "treant":
            expire = payload
            if now <= expire + 1e-9:
                hit = TREANT_HIT * taken_plain * _execute_factor(stats, now)
                sources["Treants"] += hit
                if rooted(now):
                    root_tick(now, 1.0, main_wisp(now))
                if now + TREANT_SWING <= expire + 1e-9:
                    clock.push(now + TREANT_SWING, "treant", expire)

    recover(FIGHT)
    return _report(build, sources, actions, stats, targets, bound_key, state["mana"])


def best_points(build: Build, targets: int, spec: str) -> tuple[float, tuple[int, int, int, int]]:
    from sunken_sim.search import POINT_SPLITS

    best_dps = -1.0
    best = (0, 5, 0, 0)
    for crit, potency, luck, mastery in POINT_SPLITS:
        trial = Build(build.talents, build.glyphs, build.items, potency, mastery, crit, luck)
        report = simulate(trial, targets, spec)
        if report.dps > best_dps:
            best_dps = report.dps
            best = (crit, potency, luck, mastery)
    return best_dps, best
