# -*- coding: utf-8 -*-
"""ESC / stat-kernel helpers for hybrid DirectML greedy.

Exact event-reuse rescoring is unsafe for most heroes: flat/cleave/splash raws
often bake crit/potency/luck at emit time (see warrior Whirlwind cleave). A true
closed-form stat-kernel needs per-class event algebra; until that lands, greedy
stays on full dps_many batches with structural attr skips + zero-delta skip.

Structural skips (never trial):
  - healing_power: no DPS class sim reads stats["healing_power"]
  - pet_damage: only heroes that scale pets/summons (see PET_DAMAGE_HEROES)

Zero-delta skip: after a step that finds a real improvement, attrs that tied the
pre-step baseline are dropped for later steps (they cannot win a strict '>' pick
while a positive attr exists). When every trial ties the baseline, behaviour
matches sunken_sim.esc.greedy_points (spend on the first under-cap attr).
"""

from __future__ import annotations

from sunken_sim.esc import ESC_ATTRS, ESC_CAP, apply_points, empty_points
from sunken_sim.shadow import SKILL_POINTS

_EPS = 1e-12

# Heroes whose sim multiplies pet/summon damage by stats["pet_damage"].
PET_DAMAGE_HEROES = frozenset({
    "hunter",
    "necromancer",
    "siren",
    "tidewarrior",
    "tinker",
    "warlock",
    "witch_doctor",
})


def structural_skip_attrs(hero: str | None) -> frozenset[str]:
    """Attrs that cannot change DPS for this hero (skip every greedy step)."""
    skip = {"healing_power"}
    if hero is None or hero not in PET_DAMAGE_HEROES:
        skip.add("pet_damage")
    return frozenset(skip)


def greedy_points_batched(
    dps_many,
    build,
    *,
    total: int | None = None,
    cap: int = ESC_CAP,
    hero: str | None = None,
):
    """Batched ESC greedy with structural + zero-delta attr skips."""
    if total is None:
        total = SKILL_POINTS
    counts = empty_points()
    best = float(dps_many([apply_points(build, counts)])[0])
    skip: set[str] = set(structural_skip_attrs(hero))
    for _ in range(total):
        names = [name for name in ESC_ATTRS if counts[name] < cap and name not in skip]
        if not names:
            break
        trials = [apply_points(build, {**counts, name: counts[name] + 1}) for name in names]
        scores = [float(x) for x in dps_many(trials)]
        pick, pick_dps = None, -1.0
        noop: set[str] = set()
        scale = max(1.0, abs(best))
        for name, dps in zip(names, scores):
            if abs(dps - best) <= _EPS * scale:
                noop.add(name)
            if dps > pick_dps:
                pick, pick_dps = name, dps
        if pick is None:
            break
        counts[pick] += 1
        if pick_dps > best + _EPS * scale:
            skip |= noop - {pick}
            best = pick_dps
        else:
            # no real gain: keep CPU tie behaviour, do not grow skip
            best = pick_dps
    return best, counts
