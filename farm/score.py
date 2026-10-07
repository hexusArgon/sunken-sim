"""DPS of one chunk, including the best five skill points."""

from __future__ import annotations

from sunken_sim.shadow import Build


def score_build(hero: str, spec: str, targets: int, build: Build) -> tuple[float, tuple[int, int, int, int]]:
    if hero == "mage":
        return _mage(spec, targets, build)
    return _priest(spec, targets, build)


def _priest(spec: str, targets: int, build: Build) -> tuple[float, tuple[int, int, int, int]]:
    from sunken_sim.search import POINT_SPLITS
    from sunken_sim.shadow import FIGHT, SKILL_POINTS, character, compile_events, score_compiled, simulate

    bare = Build(build.talents, build.glyphs, build.items, 0, 0, 0, 0)
    stats = character(bare)
    best_dps = -1.0
    best = (0, SKILL_POINTS, 0, 0)
    compiled_by_crit: dict[int, dict] = {}
    for crit_points, potency_points, luck_points, mastery_points in POINT_SPLITS:
        compiled = compiled_by_crit.get(crit_points)
        if compiled is None:
            pointed = Build(build.talents, build.glyphs, build.items, 0, 0, crit_points, 0)
            fresh: dict = {"targets": targets}
            simulate(pointed, targets, fresh, spec=spec, use_history=False)
            if "events" not in fresh:
                raise RuntimeError("сим не вернул события")
            compiled = compile_events(fresh["events"], bare, stats, spec, fresh.get("windows"))
            compiled_by_crit[crit_points] = compiled
        dps = (
            score_compiled(
                compiled,
                stats,
                stats["potency"] + 0.5 * potency_points,
                min(100.0, stats["crit"] + crit_points),
                stats["mastery"] + mastery_points,
                stats["luck"] + 0.01 * luck_points,
            )
            / FIGHT
        )
        if dps > best_dps:
            best_dps = dps
            best = (crit_points, potency_points, luck_points, mastery_points)
    return best_dps, best


def _mage(spec: str, targets: int, build: Build) -> tuple[float, tuple[int, int, int, int]]:
    from sunken_sim.mage import simulate
    from sunken_sim.search import POINT_SPLITS
    from sunken_sim.shadow import SKILL_POINTS

    best_dps = -1.0
    best = (0, SKILL_POINTS, 0, 0)
    for crit_points, potency_points, luck_points, mastery_points in POINT_SPLITS:
        trial = Build(
            build.talents,
            build.glyphs,
            build.items,
            potency_points,
            mastery_points,
            crit_points,
            luck_points,
        )
        report = simulate(trial, targets, spec=spec, use_history=False)
        if report.dps > best_dps:
            best_dps = report.dps
            best = (crit_points, potency_points, luck_points, mastery_points)
    return best_dps, best
