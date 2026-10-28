"""Feral Druid fight for Sunken City, level 6.

Feral Druid O00R (agility). Strength 14 + 1.4, agility 25 + 2.5, intellect 11 + 1.1.
White hit is 31 + 1 die, attack cooldown 1.7 (Cat O00J 1.4), base mana 120.
Spec level on A0MP: 1 Primal (Tauren O00R), 2 Guardian (Bear O01B), 3 Savage (Cat O00J).
The fight starts already in the form of its spec.

Ability rank is 1. Healing and survivability are not scored.
"""

from __future__ import annotations

import heapq
import re

from sunken_sim.pressure import AGI_ARMOR, max_hp
from sunken_sim.shadow import (
    CAST_BACKSWING,
    CAST_POINT,
    DUMMY_ARMOR,
    FIGHT,
    LEVEL,
    ORB_MODE,
    PHYSICAL_ADDS,
    Build,
    Report,
    Sulfuras,
    _crit_factor,
    _execute_factor,
    _has,
    _magical_multiplier,
    _mana_regen,
    _type_add,
    _wears,
    armor_taken,
    attack_mana_gain,
    cast_mana_back,
    character,
    sulfuras_echo_chance,
    target_hp,
)

CAST_TIME = CAST_POINT + CAST_BACKSWING

FERAL_STR = int(14 + (LEVEL - 1) * 1.4)
FERAL_AGI = int(25 + (LEVEL - 1) * 2.5)
FERAL_INT = int(11 + (LEVEL - 1) * 1.1)
FERAL_WHITE = 32.0
FERAL_SWING = 1.7
CAT_SWING = 1.4
FERAL_BASE_MANA = 120.0
FERAL_BASE_HP = 250.0
FERAL_BASE_ARMOR = 1.0

SPECS = ("primal", "guardian", "savage")
HERO_CLASS = "FeralDruid"

TALENT_DREAMWALKER = "I0KN"
TALENT_PRIMAL_FURY = "I0KJ"
TALENT_RAZOR_CLAWS = "I0NO"
TALENT_SAVAGE_ROAR = "I0MN"
TALENT_MAIM = "I0KL"
TALENT_FERAL_FRENZY = "I0PX"
TALENT_GUARDIAN_ELUNE = "I0KK"
TALENT_STRENGTH_WILD = "I0PZ"
TALENT_GRIZZLY = "I0RU"
TALENT_MOMENTUM = "I0Q0"
TALENT_REND = "I09M"
TALENT_FITTEST = "I0A1"
TALENT_URSOC = "I0KM"
TALENT_OPEN_WOUNDS = "I0KI"
TALENT_SHRED = "I0PY"
TALENT_FRESH_WOUND = "I0AE"
TALENT_PRIMAL_INSTINCT = "I0RS"
TALENT_LUNAR = "I0RT"

TALENTS = {
    TALENT_DREAMWALKER: "Dreamwalker",
    TALENT_PRIMAL_FURY: "Primal Fury",
    TALENT_RAZOR_CLAWS: "Razor Claws",
    TALENT_SAVAGE_ROAR: "Savage Roar",
    TALENT_MAIM: "Maim",
    TALENT_FERAL_FRENZY: "Feral Frenzy",
    TALENT_GUARDIAN_ELUNE: "Guardian of Elune",
    TALENT_STRENGTH_WILD: "Strength of the Wild",
    TALENT_GRIZZLY: "Grizzly Bear",
    TALENT_MOMENTUM: "Savage Momentum",
    TALENT_REND: "Rend and Tear",
    TALENT_FITTEST: "Survival of the Fittest",
    TALENT_URSOC: "Son of Ursoc",
    TALENT_OPEN_WOUNDS: "Open Wounds",
    TALENT_SHRED: "Shred",
    TALENT_FRESH_WOUND: "Fresh Wound",
    TALENT_PRIMAL_INSTINCT: "Primal Instinct",
    TALENT_LUNAR: "Lunar Inspiration",
}
IGNORED_TALENTS = frozenset(
    {
        TALENT_DREAMWALKER,
        TALENT_GUARDIAN_ELUNE,
        TALENT_FITTEST,
        TALENT_PRIMAL_INSTINCT,
    }
)

ASHAMANE = "I0RV"
GUISE = "I0RX"
SHOULDERPADS = "I0RW"
PACKLEADER = "I0RY"
STAVE = "I0UZ"

GALACTIC_FURY = "I0JO"
FIRE_ORB = "I07O"
DIAMOND = "I00D"
PIPE = "I00L"
SULFURAS_CODE = "I0BR"

BOUND_NAME = {
    "swipe": "Swipe",
    "bite": "Savage Bite",
    "roar": "Stampeding Roar",
}

RAKE_LIFE = 4.0
BERSERK_LIFE = 5.0
ROAR_LIFE = 7.0
MAIM_LIFE = 5.0
MAIM_ARMOR = 4.0
REND_LIFE = 2.0

_HEALTH = re.compile(r"\+(\d+) (?:Maximum )?(?:Health|HP)\b", re.I)


def _item_health(build: Build) -> float:
    total = 0.0
    seen: set[str] = set()
    for item in build.items:
        if item.rawcode in seen:
            continue
        seen.add(item.rawcode)
        total += sum(float(n) for n in _HEALTH.findall(item.tip or ""))
    return total


def sheet(build: Build, spec: str = "primal") -> dict[str, float]:
    galactic = 1.20 if _wears(build, GALACTIC_FURY) else 1.0
    stats = character(build, FERAL_STR, FERAL_AGI, FERAL_INT, FERAL_WHITE, bake_timed_buffs=False)
    item_damage = stats["ad"] - FERAL_WHITE - 0.75 * stats["int"]
    stats["ad"] = FERAL_WHITE + 0.75 * stats["agi"] + item_damage
    stats["mana_max"] -= 175.0 - FERAL_BASE_MANA
    stats["mana_regen"] = _mana_regen(build, stats["int"], stats["mana_max"], build.items)
    swing = CAT_SWING if spec == "savage" else FERAL_SWING
    stats["attack_base"] = swing * galactic
    health = max_hp(FERAL_BASE_HP, stats["str"]) + _item_health(build)
    if spec == "guardian":
        health += 180.0 + 20.0 * LEVEL
    stats["max_hp"] = health
    armor = FERAL_BASE_ARMOR + AGI_ARMOR * stats["agi"]
    armor += sum(item.armor for item in {i.rawcode: i for i in build.items}.values())
    stats["armor"] = armor
    stats["swing"] = stats["attack_base"] / (1.0 + stats["attack_speed"])
    return stats


def buttons(spec: str) -> tuple[str, ...]:
    return ("swipe", "bite", "roar")


def _bound_key(bound_spell: str | None) -> str | None:
    if not bound_spell:
        return None
    for key, name in BOUND_NAME.items():
        if bound_spell == key or bound_spell == name:
            return key
    raise ValueError(bound_spell)


def simulate(build: Build, targets: int = 5, spec: str = "primal", bound_spell: str | None = None) -> Report:
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
    return _simulate_feral(build, targets, spec, _bound_key(bound_spell))


class _Clock:
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

def _simulate_feral(build: Build, targets: int, spec: str, bound_key: str | None) -> Report:
    stats = sheet(build, spec)
    codes = frozenset(item.rawcode for item in build.items) | build.talents | build.glyphs
    cooldown = _common(build, stats, bound_key)
    primal = spec == "primal"
    bear = spec == "guardian"
    cat = spec == "savage"
    shifted = bear or cat
    ferocity_on = primal or (bear and _has(build, TALENT_GRIZZLY))
    lunar = cat and _has(build, TALENT_LUNAR)
    ursoc = _has(build, TALENT_URSOC) or _wears(build, SHOULDERPADS)
    momentum = _has(build, TALENT_MOMENTUM)
    rend = _has(build, TALENT_REND)
    maim = _has(build, TALENT_MAIM)
    wild = _has(build, TALENT_STRENGTH_WILD)
    razor = _has(build, TALENT_RAZOR_CLAWS)
    frenzy = _has(build, TALENT_FERAL_FRENZY)
    pen = stats["armor_pen"]
    taken_plain = armor_taken(DUMMY_ARMOR - pen)
    taken_maim = armor_taken(DUMMY_ARMOR - pen - MAIM_ARMOR)
    fer_max = (100.0 + stats["mastery"] + (25.0 if _has(build, TALENT_PRIMAL_FURY) else 0.0)) if ferocity_on else 0.0
    fer_rate = 12.0 * (1.0 + stats["haste"]) * (1.0 + 0.01 * stats["mastery"]) if ferocity_on else 0.0
    rake_period = 1.0 / (1.0 + stats["haste"] + (0.25 if _has(build, TALENT_OPEN_WOUNDS) else 0.0))
    attack_inc = 0.0
    if cat:
        attack_inc += 0.05 + 0.005 * stats["mastery"]
    if _has(build, TALENT_SHRED):
        attack_inc += 0.10
    crit_bonus = 0.0
    rating_bonus = 0.0
    if cat:
        crit_bonus += 10.0
        if ursoc:
            crit_bonus += min(25.0, stats["armor"])
        if lunar:
            rating_bonus += 0.15

    sources: dict[str, float] = {
        "Автоатака": 0.0,
        "Swipe": 0.0,
        "Savage Bite": 0.0,
        "Rake": 0.0,
        "Feral Frenzy": 0.0,
        "Всплеск огня": 0.0,
    }
    actions: list[tuple[float, str]] = []
    clock = _Clock()
    state = {"mana": stats["mana_max"], "mana_time": 0.0, "fer": 0.0, "fer_time": 0.0}
    ready = {key: 0.0 for key in buttons(spec)}
    rake = [-1.0] * targets
    berserk_until = -1.0
    roar_until = -1.0
    maim_until = -1.0
    bite_window = -1.0  # Rend and Tear: next Bite x1.35 until
    swipe_window = -1.0  # Rend and Tear: next Swipe x1.25 until
    next_hit_bonus = 0.0
    sulfuras = Sulfuras() if _wears(build, SULFURAS_CODE) else None
    fire_orb = _wears(build, FIRE_ORB)
    hero_ready = 0.0
    next_attack = 0.0
    rake_clock = False

    def luck_mult() -> float:
        return 1.0 + stats["luck"]

    def proc(percent: float) -> float:
        return min(1.0, percent / 100.0 * luck_mult())

    def recover(now: float) -> None:
        if now > state["mana_time"] and state["mana"] < stats["mana_max"]:
            state["mana"] = min(stats["mana_max"], state["mana"] + stats["mana_regen"] * (now - state["mana_time"]))
        state["mana_time"] = max(state["mana_time"], now)
        if ferocity_on and now > state["fer_time"]:
            state["fer"] = min(fer_max, state["fer"] + fer_rate * (now - state["fer_time"]))
            state["fer_time"] = now

    def pay(cost: float, now: float) -> bool:
        recover(now)
        if state["mana"] < cost:
            return False
        state["mana"] -= cost
        state["mana"] = min(stats["mana_max"], state["mana"] + cast_mana_back(cost, stats))
        return True

    def dcs(now: float) -> float:
        if now < berserk_until and (cat or momentum):
            bonus = 0.20 + (0.15 if momentum and shifted else 0.0)
            return stats["ad"] * (1.0 + bonus)
        return stats["ad"]

    def crit_of() -> float:
        return min(100.0, stats["crit"] + crit_bonus)

    def physical(now: float) -> float:
        extra = 0.10 if _has(build, TALENT_PRIMAL_FURY) else 0.0
        if _wears(build, PACKLEADER) and now < roar_until:
            extra += 0.15
        bonus = 1.0 + _type_add(codes, PHYSICAL_ADDS, now) + extra
        if "I0JA" in codes:
            bonus *= 1.15
        return bonus

    def taken_main(now: float) -> float:
        return taken_maim if now < maim_until else taken_plain

    def deal(
        name: str,
        raw: float,
        now: float,
        count: float,
        attack: bool,
        main_share: float,
        attack_share: float = 0.0,
        magical: bool | None = None,
        potency_scale: float = 1.0,
    ) -> None:
        """Feral damage. main_share is the part of hits on the main (Maim) target."""
        if count <= 0 or now >= FIGHT:
            return
        is_magic = lunar if magical is None else magical
        amount = raw + stats["potency"] * potency_scale
        if is_magic:
            amount *= _magical_multiplier(codes, now, stats["mastery"])
        else:
            amount *= physical(now)
        attack_mult = (1.0 + attack_inc) * _crit_factor(crit_of(), 2.0 + stats["rating"] + rating_bonus)
        if stats["spell_crit"]:
            spell_mult = _crit_factor(crit_of(), stats["spell_mult"] + stats["rating"] + rating_bonus)
        else:
            spell_mult = 1.0
        if attack:
            amount *= attack_mult
        else:
            amount *= attack_share * attack_mult + (1.0 - attack_share) * spell_mult
        share = max(0.0, min(1.0, main_share))
        amount *= share * taken_main(now) + (1.0 - share) * taken_plain
        amount *= _execute_factor(stats, now)
        sources[name] = sources.get(name, 0.0) + amount * count
        if stats.get("damage_mana_pct"):
            state["mana"] = min(stats["mana_max"], state["mana"] + stats["damage_mana_pct"] * stats["mana_max"] * count)

    def apply_rake(now: float, indexes) -> None:
        nonlocal rake_clock
        for index in indexes:
            rake[index] = now + RAKE_LIFE
        if not rake_clock:
            rake_clock = True
            clock.push(now + rake_period, "rake", None)

    def swipe_raw(now: float) -> float:
        power = dcs(now)
        raw = 30.0 + 1.15 * power
        if primal:
            raw += 0.55 * stats["agi"] + 0.20 * power
            if ursoc:
                raw *= 1.0 + 0.005 * stats["str"]
        elif bear:
            raw += 0.03 * stats["max_hp"]
        elif cat:
            raw += 0.40 * stats["agi"]
        if _wears(build, ASHAMANE):
            raw *= 1.25
        return raw

    def swipe_hit(now: float, raw: float, name: str, weight: float) -> None:
        low = 1.15 if target_hp(now) * 100.0 <= crit_of() else 1.0
        share = 0.10 * luck_mult() if razor else 0.0
        deal(name, raw * low, now, targets * weight, False, 1.0 / targets, min(1.0, share))

    def cast_cost(name: str) -> float:
        return {"swipe": 15.0, "bite": 10.0, "roar": 20.0}[name]

    def cast_cd(name: str) -> float:
        flat = 1.0 if wild else 0.0
        if name == "swipe":
            return cooldown(6.0, name, flat)
        if name == "bite":
            return cooldown(10.0 - (2.0 if maim else 0.0), name, flat)
        return cooldown(12.0, name, flat)

    def choose(now: float) -> str | None:
        for name in ("swipe", "bite", "roar"):
            if ready[name] <= now:
                return name
        return None

    def on_cast(name: str, now: float) -> None:
        """Instant part at cast start (Ferocity cut on Savage Bite cooldown)."""
        nonlocal next_hit_bonus
        recover(now)
        if name == "bite" and ferocity_on and state["fer"] >= 40.0:
            left = ready["bite"] - now
            spent = min(state["fer"], 80.0, left * 10.0)
            state["fer"] -= spent
            ready["bite"] = max(now + 0.5, ready["bite"] - spent / 10.0)
        bonus = 0.0
        if wild:
            bonus += 25.0 + 0.75 * stats["agi"]
        if name == "roar" and cat:
            bonus += 50.0 + 1.5 * stats["agi"]
        next_hit_bonus = bonus

    def resolve(name: str, now: float) -> None:
        nonlocal berserk_until, roar_until, maim_until, bite_window, swipe_window
        recover(now)
        if name == "swipe":
            raw = swipe_raw(now)
            if rend and now < swipe_window:
                raw *= 1.25
                swipe_window = -1.0
            if ferocity_on and state["fer"] >= 40.0:
                spent = min(state["fer"], 80.0)
                state["fer"] -= spent
                raw *= 1.0 + 0.01 * spent
            swipe_hit(now, raw, "Swipe", 1.0)
            apply_rake(now, range(targets))
            if rend:
                bite_window = now + REND_LIFE
        elif name == "bite":
            raw = 100.0 + 1.5 * dcs(now)
            if primal:
                raw *= 1.25
                if ursoc:
                    raw *= 1.0 + 0.005 * stats["str"]
            if rend and now < bite_window:
                raw *= 1.35
                bite_window = -1.0
            if maim:
                maim_until = now + MAIM_LIFE
            deal("Savage Bite", raw, now, 1.0, False, 1.0)
            if shifted or momentum:
                berserk_until = now + BERSERK_LIFE
            apply_rake(now, [0])
            if rend:
                swipe_window = now + REND_LIFE
        elif name == "roar":
            roar_until = now + ROAR_LIFE
            if ferocity_on:
                state["fer"] = min(fer_max, state["fer"] + 0.25 * fer_max)

    def attack_interval(now: float) -> float:
        speed = stats["attack_speed"]
        if _has(build, TALENT_SAVAGE_ROAR) and now < roar_until:
            speed += 0.28
        speed = min(4.0, max(-0.8, speed))
        return stats["attack_base"] / (1.0 + speed)

    def on_attack(now: float) -> None:
        nonlocal next_hit_bonus
        recover(now)
        raw = dcs(now) + next_hit_bonus
        next_hit_bonus = 0.0
        if _has(build, TALENT_FRESH_WOUND):
            raw += 0.02 * stats["max_hp"]
        before = sources["Автоатака"]
        deal("Автоатака", raw, now, 1.0, True, 1.0, magical=False, potency_scale=stats["attack_potency"])
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        state["mana"] = min(stats["mana_max"], state["mana"] + attack_mana_gain(stats))
        if cat and now >= rake[0]:
            apply_rake(now, [0])
        if frenzy:
            crit_p = crit_of() / 100.0
            chance = (1.0 - crit_p) * proc(5.0) + crit_p * proc(7.5)
            if chance > 0:
                swipe_hit(now, swipe_raw(now), "Feral Frenzy", chance)
        execute = _execute_factor(stats, now)
        if fire_orb:
            sources["Всплеск огня"] += (20.0 + 0.35 * stats["int"]) * targets * taken_plain * execute
        if sulfuras is not None:
            if sulfuras.attack():
                splash = (
                    stats["agi"]
                    * _magical_multiplier(codes, now, stats["mastery"])
                    * (_crit_factor(crit_of(), stats["spell_mult"] + stats["rating"]) if stats["spell_crit"] else 1.0)
                    * taken_plain
                    * execute
                    * targets
                )
                sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
            echo = dcs(now) * taken_plain * execute * sulfuras_echo_chance(stats["luck"])
            sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo

    def on_rake(now: float) -> None:
        nonlocal rake_clock
        live = [index for index in range(targets) if now <= rake[index] + 1e-9]
        if not live:
            rake_clock = False
            return
        raw = 10.0 + 0.10 * dcs(now)
        if primal:
            chance = proc(30.0)
            raw *= 1.0 + 0.35 * chance
            if ferocity_on:
                recover(now)
                state["fer"] = min(fer_max, state["fer"] + 2.0 * chance * len(live))
        share = min(1.0, 0.15 * luck_mult()) if razor else 0.0
        main = 1.0 / len(live) if 0 in live else 0.0
        deal("Rake", raw, now, float(len(live)), False, main, share)
        clock.push(now + rake_period, "rake", None)

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
                on_cast(spell, hero_ready)
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
            next_attack = moment + attack_interval(moment)
            continue
        now, _order, kind, payload = clock.pop()
        if kind == "cast":
            resolve(payload, now)
        elif kind == "rake":
            on_rake(now)

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
