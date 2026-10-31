"""Item DPS of one sextuple, then talents, glyphs and skill points if it wins."""

from __future__ import annotations

import itertools

from sunken_sim.esc import ESC_ATTRS
from sunken_sim.shadow import MIND_AMPLIFIER, SKILL_POINTS, Build


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
) -> tuple[float, tuple[str, ...], tuple[str, ...], dict[str, int], int]:
    """Best talents, then glyphs, then greedy ESC points. One fight each for talent/glyph."""
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


def score_build(hero: str, spec: str, targets: int, build: Build) -> tuple[float, dict[str, int], int]:
    if hero == "mage":
        return _mage(spec, targets, build)
    if hero == "priest":
        return _priest(spec, targets, build)
    return _generic(hero, spec, targets, build)


def _generic(hero: str, spec: str, targets: int, build: Build) -> tuple[float, dict[str, int], int]:
    dps, points = _module(hero).best_points(build, targets, spec)
    spent = sum(int(v) for v in points.values()) if isinstance(points, dict) else sum(points)
    fights = 1 if spent == 0 else SKILL_POINTS * len(ESC_ATTRS)
    return dps, points, fights


def _priest(spec: str, targets: int, build: Build) -> tuple[float, dict[str, int], int]:
    from sunken_sim.esc import apply_points, greedy_points, points_payload
    from sunken_sim.shadow import FIGHT, character, compile_events, score_compiled, simulate

    def score(pts: dict) -> float:
        trial = apply_points(build, pts)
        fresh: dict = {"targets": targets}
        simulate(trial, targets, fresh, spec=spec, use_history=False)
        if "events" not in fresh:
            return -1.0
        st = character(trial)
        compiled = compile_events(fresh["events"], trial, st, spec, fresh.get("windows"))
        return (
            score_compiled(
                compiled,
                st,
                st["potency"],
                min(100.0, st["crit"]),
                st["mastery"],
                st["luck"],
            )
            / FIGHT
        )

    dps, pts = greedy_points(score)
    return dps, points_payload(pts), SKILL_POINTS * len(ESC_ATTRS)


def _mage(spec: str, targets: int, build: Build) -> tuple[float, dict[str, int], int]:
    from sunken_sim.esc import apply_points, greedy_points, points_payload
    from sunken_sim.mage import simulate

    def score(pts: dict) -> float:
        trial = apply_points(build, pts)
        report = simulate(trial, targets, spec=spec, use_history=False)
        return report.dps

    dps, pts = greedy_points(score)
    return dps, points_payload(pts), SKILL_POINTS * len(ESC_ATTRS)
