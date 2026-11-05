"""Class-agnostic hybrid engine: batch interface, parity compare, worker eval_span.

A GPU engine (farm.hybrid.registry.make_engine) only has to implement
dps_many(builds) -> list[float] with the same numbers as the CPU fight
(farm.score._fight). The talent / glyph / ESC search on top of it is here, with
the same rules as farm.score.finish_sextuple: strict '>' so the first combo wins
ties, same fight counts.

Worker side: the first SUB_SPAN bare fights of every process are checked against
the CPU sim (SELF_CHECK). Any mismatch or exception -> that worker uses the old
farm.runner.eval_span for the rest of the job.
"""

from __future__ import annotations

import itertools

DPS_TOL = 1e-4  # relative; DirectML sums in float32
SUB_SPAN = 256  # chunks per device batch inside one eval_span
SELF_CHECK = 8  # bare fights checked against the CPU sim per process


def compare(reference: list[float], other: list[float]) -> dict:
    worst_abs = 0.0
    worst_rel = 0.0
    for a, b in zip(reference, other):
        diff = abs(a - b)
        worst_abs = max(worst_abs, diff)
        worst_rel = max(worst_rel, diff / max(1.0, abs(a)))
    return {
        "n": len(reference),
        "max_abs": worst_abs,
        "max_rel": worst_rel,
        "tol_rel": DPS_TOL,
        "ok": len(reference) == len(other) and worst_rel <= DPS_TOL,
    }


class BatchFights:
    """Search on top of dps_many. Subclasses set hero/spec/targets/fights."""

    hero: str
    spec: str
    targets: int
    fights: int = 0

    def dps_many(self, builds: list) -> list[float]:  # pragma: no cover - interface
        raise NotImplementedError

    def greedy_points(self, build) -> tuple[float, dict[str, int]]:
        """sunken_sim.esc.greedy_points with each step's trials in one batch."""
        from sunken_sim.esc import ESC_ATTRS, ESC_CAP, apply_points, empty_points
        from sunken_sim.shadow import SKILL_POINTS

        counts = empty_points()
        best = self.dps_many([apply_points(build, counts)])[0]
        for _ in range(SKILL_POINTS):
            names = [name for name in ESC_ATTRS if counts[name] < ESC_CAP]
            if not names:
                break
            trials = []
            for name in names:
                trial = dict(counts)
                trial[name] += 1
                trials.append(apply_points(build, trial))
            scores = self.dps_many(trials)
            pick, pick_dps = None, -1.0
            for name, dps in zip(names, scores):
                if dps > pick_dps:
                    pick, pick_dps = name, dps
            counts[pick] += 1
            best = pick_dps
        return best, counts

    def finish_sextuple(self, equipped, talent_codes, glyph_codes, picks_without, picks_with, glyph_picks):
        """farm.score.finish_sextuple, batched. Same return shape and fight count."""
        from sunken_sim.esc import ESC_ATTRS, points_payload
        from sunken_sim.shadow import MIND_AMPLIFIER, SKILL_POINTS, Build

        picks = picks_with if any(item.rawcode == MIND_AMPLIFIER for item in equipped) else picks_without
        combos = list(itertools.combinations(talent_codes, picks))
        scores = self.dps_many([Build(frozenset(c), frozenset(), equipped, 0, 0, 0, 0) for c in combos])
        best_dps, best_talents = -1.0, ()
        for combo, dps in zip(combos, scores):
            if dps > best_dps:
                best_dps, best_talents = dps, combo
        glyph_combos = list(itertools.combinations(glyph_codes, glyph_picks))
        scores = self.dps_many(
            [Build(frozenset(best_talents), frozenset(c), equipped, 0, 0, 0, 0) for c in glyph_combos]
        )
        best_glyphs = ()
        for combo, dps in zip(glyph_combos, scores):
            if dps > best_dps:
                best_dps, best_glyphs = dps, combo
        pointed, points = self.greedy_points(Build(frozenset(best_talents), frozenset(best_glyphs), equipped, 0, 0, 0, 0))
        fights = len(combos) + len(glyph_combos) + SKILL_POINTS * len(ESC_ATTRS)
        return pointed, best_talents, best_glyphs, points_payload(points), fights


# --- farm worker side -------------------------------------------------------

_ENGINE = None
_ENGINE_STATE = None  # None: not built, "pending": built, self-check due, "gpu": ok, "cpu": old eval_span
_ENGINE_NOTE = ""


def reset() -> None:
    global _ENGINE, _ENGINE_STATE, _ENGINE_NOTE
    _ENGINE, _ENGINE_STATE, _ENGINE_NOTE = None, None, ""


def _to_cpu(note: str) -> None:
    global _ENGINE, _ENGINE_STATE, _ENGINE_NOTE
    _ENGINE, _ENGINE_STATE, _ENGINE_NOTE = None, "cpu", note
    print(f"hybrid: CPU fights in this worker ({note})", flush=True)


def _engine():
    global _ENGINE, _ENGINE_STATE
    if _ENGINE_STATE is not None:
        return _ENGINE if _ENGINE_STATE in ("gpu", "pending") else None
    from farm import runner as R
    from farm.hybrid import registry

    try:
        if not registry.gpu_engine_for(R._HERO, R._SPEC):
            raise ValueError(f"{R._HERO}/{R._SPEC} is {registry.status(R._HERO, R._SPEC)}")
        import torch

        torch.set_num_threads(1)
        from farm.hybrid.device import detect

        _ENGINE = registry.make_engine(detect(R._HERO, R._SPEC), R._HERO, R._SPEC, R._TARGETS)
        _ENGINE_STATE = "pending"
    except Exception as exc:
        _to_cpu(f"{exc.__class__.__name__}: {exc}")
    return _ENGINE


def _self_check(builds, got) -> bool:
    global _ENGINE_STATE
    from farm import runner as R
    from farm.hybrid.registry import cpu_dps

    ref = [cpu_dps(R._HERO, R._SPEC, R._TARGETS, b) for b in builds[:SELF_CHECK]]
    res = compare(ref, got[:SELF_CHECK])
    if res["ok"]:
        _ENGINE_STATE = "gpu"
        return True
    _to_cpu(f"self-check failed max_rel={res['max_rel']:.3g}")
    return False


def eval_span(start: int, stop: int) -> dict:
    """farm.runner.eval_span with batched GPU fights. Same payload, same top-10 gate."""
    from farm import runner as R
    from farm.score import finish_sextuple
    from sunken_sim.shadow import Build

    engine = _engine()
    if engine is None:
        return R.eval_span(start, stop)
    space = R._SPACE
    hits: list[dict] = []
    fights = 0
    errors = 0
    error = ""
    done = start
    index = start
    while index < stop:
        if R._STOP is not None and R._STOP.is_set():
            break
        end = min(stop, index + SUB_SPAN)
        try:
            rows = []
            for chunk in range(index, end):
                item_codes, _t, _g = space.decode(chunk)
                equipped = tuple(R._ITEMS[code] for code in item_codes)
                sources = [R._SOURCES.get(item.rawcode, "drop") for item in equipped]
                rows.append((chunk, equipped, sources, R.build_group(sources)))
            bare_builds = [Build(frozenset(), frozenset(), row[1], 0, 0, 0, 0) for row in rows]
            bares = engine.dps_many(bare_builds)
            if _ENGINE_STATE == "pending" and not _self_check(bare_builds, bares):
                sub = R.eval_span(index, stop)
                hits.extend(sub["hits"])
                fights += sub["fights"]
                errors += sub["errors"]
                error = error or sub["error"]
                done = sub["done"]
                break
        except Exception as exc:
            sub = R.eval_span(index, end)
            hits.extend(sub["hits"])
            fights += sub["fights"]
            errors += sub["errors"]
            error = error or sub["error"] or f"hybrid batch {index}: {exc}"
            done = sub["done"]
            if done < end:
                break
            index = end
            continue
        for (chunk, equipped, sources, group), bare in zip(rows, bares):
            fights += 1
            if not R.claim_item_bars(bare, group):
                continue
            call = (equipped, space.talents, space.glyphs, space.picks_without, space.picks_with, space.glyph_picks)
            try:
                try:
                    dps, talent_codes, glyph_codes, points, extra = engine.finish_sextuple(*call)
                except Exception:
                    dps, talent_codes, glyph_codes, points, extra = finish_sextuple(R._HERO, R._SPEC, R._TARGETS, *call)
                fights += extra
                hits.append(
                    {
                        "dps": dps,
                        "item_dps": bare,
                        "fights": extra + 1,
                        "chunk": chunk,
                        "group": group,
                        "items": [
                            {"name": item.name, "code": item.rawcode, "source": source}
                            for item, source in zip(equipped, sources)
                        ],
                        "talents": sorted(space.talent_names.get(code, code) for code in talent_codes),
                        "glyphs": sorted(space.glyph_names.get(code, code) for code in glyph_codes),
                        "points": dict(points),
                    }
                )
            except Exception as exc:
                errors += 1
                if not error:
                    error = f"{chunk}: {exc}"
        done = end
        index = end
    return {"start": start, "done": done, "fights": fights, "hits": R._compact(hits), "errors": errors, "error": error}
