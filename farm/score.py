"""Item DPS of one sextuple, then talents, glyphs and skill points if it wins."""

from __future__ import annotations

import itertools

from sunken_sim.shadow import MIND_AMPLIFIER, Build


def item_dps(hero: str, spec: str, targets: int, items: tuple) -> float:
    bare = Build(frozenset(), frozenset(), items, 0, 0, 0, 0)
    return _fight(hero, spec, targets, bare)


def greedy_floor(hero: str, spec: str, targets: int, pieces: list, items: dict) -> float:
    """Same gate as run_hp: six greedy slots, no talents and no glyphs."""
    chosen: list = []
    best = 0.0
    for _slot in range(6):
        best_piece = None
        best_dps = -1.0
        for piece in pieces:
            if not _can_take(chosen, piece):
                continue
            trial = tuple(chosen + [items[piece.code]])
            dps = item_dps(hero, spec, targets, trial)
            if dps > best_dps:
                best_dps = dps
                best_piece = piece
        if best_piece is None:
            break
        chosen.append(items[best_piece.code])
        best = best_dps
    return best


def finish_sextuple(
    hero: str,
    spec: str,
    targets: int,
    equipped: tuple,
    talent_codes: list[str],
    glyph_codes: list[str],
    picks_without: int,
    picks_with: int,
    glyph_picks: int,
) -> tuple[float, tuple[str, ...], tuple[str, ...], tuple[int, int, int, int], int]:
    """Best talents, then glyphs, then five skill points. One fight each."""
    picks = picks_with if any(item.rawcode == MIND_AMPLIFIER for item in equipped) else picks_without
    fights = 0
    best_talents: tuple[str, ...] = ()
    best_dps = -1.0
    for combo in itertools.combinations(talent_codes, picks):
        dps = _fight(hero, spec, targets, Build(frozenset(combo), frozenset(), equipped, 0, 0, 0, 0))
        fights += 1
        if dps > best_dps:
            best_dps = dps
            best_talents = combo
    best_glyphs: tuple[str, ...] = ()
    for combo in itertools.combinations(glyph_codes, glyph_picks):
        dps = _fight(hero, spec, targets, Build(frozenset(best_talents), frozenset(combo), equipped, 0, 0, 0, 0))
        fights += 1
        if dps > best_dps:
            best_dps = dps
            best_glyphs = combo
    pointed, points, point_fights = score_build(
        hero,
        spec,
        targets,
        Build(frozenset(best_talents), frozenset(best_glyphs), equipped, 0, 0, 0, 0),
    )
    return pointed, best_talents, best_glyphs, points, fights + point_fights


def _can_take(chosen: list, piece) -> bool:
    codes = [item.rawcode for item in chosen]
    if piece.amp or piece.kind in ("leg", "orb", "one"):
        return piece.code not in codes
    return piece.kind == "stack"


def _module(hero: str):
    import importlib

    return importlib.import_module(f"sunken_sim.{hero}")


def _fight(hero: str, spec: str, targets: int, build: Build) -> float:
    if hero == "mage":
        from sunken_sim.mage import simulate

        return simulate(build, targets, spec=spec, use_history=False).dps
    if hero == "priest":
        from sunken_sim.shadow import simulate

        return simulate(build, targets, spec=spec, use_history=False).dps
    return _module(hero).simulate(build, targets, spec).dps


def score_build(hero: str, spec: str, targets: int, build: Build) -> tuple[float, tuple[int, int, int, int], int]:
    if hero == "mage":
        return _mage(spec, targets, build)
    if hero == "priest":
        return _priest(spec, targets, build)
    return _generic(hero, spec, targets, build)


def _generic(hero: str, spec: str, targets: int, build: Build) -> tuple[float, tuple[int, int, int, int], int]:
    from sunken_sim.search import POINT_SPLITS

    dps, points = _module(hero).best_points(build, targets, spec)
    # (0, 0, 0, 0) is not a real split: such modules fight once and skip skill points.
    fights = 1 if tuple(points) == (0, 0, 0, 0) else len(POINT_SPLITS)
    return dps, points, fights


def _shaman(spec: str, targets: int, build: Build) -> tuple[float, tuple[int, int, int, int], int]:
    from sunken_sim.search import POINT_SPLITS
    from sunken_sim.shaman import best_points

    dps, points = best_points(build, targets, spec)
    return dps, points, len(POINT_SPLITS)


def _paladin(spec: str, targets: int, build: Build) -> tuple[float, tuple[int, int, int, int], int]:
    from sunken_sim.paladin import best_points
    from sunken_sim.search import POINT_SPLITS

    dps, points = best_points(build, targets, spec)
    return dps, points, len(POINT_SPLITS)


def _priest(spec: str, targets: int, build: Build) -> tuple[float, tuple[int, int, int, int], int]:
    from sunken_sim.search import POINT_SPLITS
    from sunken_sim.shadow import FIGHT, SKILL_POINTS, character, compile_events, score_compiled, simulate

    bare = Build(build.talents, build.glyphs, build.items, 0, 0, 0, 0)
    stats = character(bare)
    best_dps = -1.0
    best = (0, SKILL_POINTS, 0, 0)
    compiled_by_crit: dict[int, dict] = {}
    fights = 0
    for crit_points, potency_points, luck_points, mastery_points in POINT_SPLITS:
        compiled = compiled_by_crit.get(crit_points)
        if compiled is None:
            pointed = Build(build.talents, build.glyphs, build.items, 0, 0, crit_points, 0)
            fresh: dict = {"targets": targets}
            simulate(pointed, targets, fresh, spec=spec, use_history=False)
            fights += 1
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
    return best_dps, best, fights


def _mage(spec: str, targets: int, build: Build) -> tuple[float, tuple[int, int, int, int], int]:
    from sunken_sim.mage import simulate
    from sunken_sim.search import POINT_SPLITS
    from sunken_sim.shadow import SKILL_POINTS

    best_dps = -1.0
    best = (0, SKILL_POINTS, 0, 0)
    fights = 0
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
        fights += 1
        if report.dps > best_dps:
            best_dps = report.dps
            best = (crit_points, potency_points, luck_points, mastery_points)
    return best_dps, best, fights
