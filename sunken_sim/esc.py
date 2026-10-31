"""ESC skill points from Sunken City Stats Menu (war3map.j Trig_Stats_Dialog).

Per-point values and cap 20 are from the live map dialog / button actions.
Allocation after gear search: greedy — for each of SKILL_POINTS steps, try +1
on every attr still under ESC_CAP and keep the best DPS.
"""

from __future__ import annotations

from typing import Callable

# Map: udg_ESC_Points_Cap = 20
ESC_CAP = 20

# Order matches Stats Menu buttons (Armor trigger exists but is not in the dialog).
ESC_ATTRS: tuple[str, ...] = (
    "health",  # +30 HP via tech R004
    "mana",  # +20 mana via tech R000
    "healing_power",  # +1 HealingPower_Items (+1% tip)
    "haste",  # +1% haste / CDR (0.01)
    "attack_speed",  # +2% (0.02 AttackSpeed_Items)
    "damage",  # +2 Attack Damage via tech R002
    "crit",  # +1% CriticalStrike_ChanceFlat
    "potency",  # +0.5 Potency_Stat
    "mastery",  # +1 Mastery_Stat
    "luck",  # +0.01 Luck_Items → Luck_Multiplier = 1 + luck
    "pet_damage",  # +1.5 PetDamage_Items (+1.5%)
)

# Build field name for each ESC attr
BUILD_FIELD = {
    "health": "health_points",
    "mana": "mana_points",
    "healing_power": "healing_power_points",
    "haste": "haste_points",
    "attack_speed": "attack_speed_points",
    "damage": "damage_points",
    "crit": "crit_points",
    "potency": "potency_points",
    "mastery": "mastery_points",
    "luck": "luck_points",
    "pet_damage": "pet_damage_points",
}


def empty_points() -> dict[str, int]:
    return {name: 0 for name in ESC_ATTRS}


def points_from_build(build) -> dict[str, int]:
    return {name: int(getattr(build, BUILD_FIELD[name], 0) or 0) for name in ESC_ATTRS}


def apply_points(build, points: dict[str, int]):
    """Return a copy of build with ESC point fields set from points."""
    kwargs = {
        "talents": build.talents,
        "glyphs": build.glyphs,
        "items": build.items,
        "potency_points": int(points.get("potency", 0)),
        "mastery_points": int(points.get("mastery", 0)),
        "crit_points": int(points.get("crit", 0)),
        "luck_points": int(points.get("luck", 0)),
        "haste_points": int(points.get("haste", 0)),
        "attack_speed_points": int(points.get("attack_speed", 0)),
        "damage_points": int(points.get("damage", 0)),
        "health_points": int(points.get("health", 0)),
        "mana_points": int(points.get("mana", 0)),
        "healing_power_points": int(points.get("healing_power", 0)),
        "pet_damage_points": int(points.get("pet_damage", 0)),
    }
    return type(build)(**kwargs)


def legacy_tuple(points: dict[str, int]) -> tuple[int, int, int, int]:
    """Old farm shape: (crit, potency, luck, mastery)."""
    return (
        int(points.get("crit", 0)),
        int(points.get("potency", 0)),
        int(points.get("luck", 0)),
        int(points.get("mastery", 0)),
    )


def points_payload(points: dict[str, int]) -> dict[str, int]:
    """JSON-friendly full ESC split."""
    return {name: int(points.get(name, 0)) for name in ESC_ATTRS}


def greedy_points(
    score_fn: Callable[[dict[str, int]], float],
    total: int | None = None,
    cap: int = ESC_CAP,
    attrs: tuple[str, ...] = ESC_ATTRS,
) -> tuple[float, dict[str, int]]:
    """Spend `total` points one-by-one; each step pick the under-cap attr with best DPS.

    Ties keep the earlier attr in `attrs` order. If every trial is no better than
    the current score, still spend on the first under-cap attr (points are not left
    on the table).
    """
    from sunken_sim.shadow import SKILL_POINTS

    if total is None:
        total = SKILL_POINTS
    counts = empty_points()
    best_dps = float(score_fn(counts))
    for _ in range(total):
        pick: str | None = None
        pick_dps = -1.0
        for name in attrs:
            if counts[name] >= cap:
                continue
            trial = dict(counts)
            trial[name] += 1
            dps = float(score_fn(trial))
            if dps > pick_dps:
                pick_dps = dps
                pick = name
        if pick is None:
            break
        counts[pick] += 1
        best_dps = pick_dps
    return best_dps, counts


def bake_esc_into_stats(stats: dict, build) -> dict:
    """Add ESC bonuses that shared character() does not already fold in.

    shadow.character already applies crit/potency/mastery/luck/haste/AS/damage/mana
    from Build fields. Call this from class-local stat builders that only read the
    four legacy point fields.
    """
    out = dict(stats)
    haste_pts = int(getattr(build, "haste_points", 0) or 0)
    as_pts = int(getattr(build, "attack_speed_points", 0) or 0)
    dmg_pts = int(getattr(build, "damage_points", 0) or 0)
    mana_pts = int(getattr(build, "mana_points", 0) or 0)
    pet_pts = int(getattr(build, "pet_damage_points", 0) or 0)
    heal_pts = int(getattr(build, "healing_power_points", 0) or 0)
    out["haste"] = float(out.get("haste", 0.0)) + 0.01 * haste_pts
    out["attack_speed"] = float(out.get("attack_speed", 0.0)) + 0.02 * as_pts
    if "ad" in out:
        out["ad"] = float(out["ad"]) + 2.0 * dmg_pts
    if "damage" in out:
        out["damage"] = float(out["damage"]) + 2.0 * dmg_pts
    if "mana_max" in out:
        out["mana_max"] = float(out["mana_max"]) + 20.0 * mana_pts
    if "mana" in out and "mana_max" not in out:
        out["mana"] = float(out["mana"]) + 20.0 * mana_pts
    out["pet_damage"] = float(out.get("pet_damage", 0.0)) + 0.015 * pet_pts
    out["healing_power"] = float(out.get("healing_power", 0.0)) + float(heal_pts)
    out["health_points"] = int(getattr(build, "health_points", 0) or 0)
    return out
