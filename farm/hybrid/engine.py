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
import os

DPS_TOL = 1e-4  # relative; DirectML sums in float32
SUB_SPAN = 256  # chunks per device batch inside one eval_span
CROSS_ROWS = 16  # admitted sextuples finished together, queued across sub-spans (FARM_HYBRID_CROSS_BUILD, default on)
CROSS_MAX_BUILDS = 1024  # builds per dps_many call in the cross-build path
SELF_CHECK = 8  # bare fights checked against the CPU sim per process


class _UseBatched(Exception):
    """Strategy router picked the batched greedy."""


def _cross_build_enabled() -> bool:
    """FARM_HYBRID_CROSS_BUILD (default on; 0/off disables): finish several admitted sextuples in shared device batches."""
    import os

    return os.environ.get("FARM_HYBRID_CROSS_BUILD", "1").strip().lower() not in ("0", "false", "off", "no")


def chunked_many(dps_many, builds: list, limit: int = CROSS_MAX_BUILDS) -> list[float]:
    """dps_many over `builds` in calls of <= limit builds, never a 1-build call.

    DirectML takes another bmm kernel at batch 1 (f32 result differs by ulps), so a
    lone build is fought as a duplicated pair and a 1-build tail is merged into the
    previous chunk (that chunk is limit+1). Order of results == order of builds.
    """
    n = len(builds)
    if n == 0:
        return []
    if n == 1:
        return [float(dps_many([builds[0], builds[0]])[0])]
    limit = max(2, int(limit))
    cuts = list(range(0, n, limit)) + [n]
    if cuts[-1] - cuts[-2] == 1:  # 1-build tail -> merge into the previous chunk
        del cuts[-2]
    out: list[float] = []
    for a, b in zip(cuts, cuts[1:]):
        out.extend(float(x) for x in dps_many(builds[a:b]))
    return out


def _esc_algebra_enabled() -> bool:
    """FARM_HYBRID_ESC_ALGEBRA=1: opt-in guarded event-algebra ESC pilot (esc_algebra.py)."""
    import os

    return os.environ.get("FARM_HYBRID_ESC_ALGEBRA", "0").strip().lower() in ("1", "true", "on")


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

    def _canonical_fire_esc(self, builds, results, limit=CROSS_MAX_BUILDS):
        # Algebra chooses points with its existing guards/tie policy; its projected
        # score is not the canonical final Fire DPS. Re-score only selected builds.
        if (getattr(self, "hero", None), getattr(self, "spec", None)) != ("mage", "fire"):
            return results
        from sunken_sim.esc import apply_points
        selected = [apply_points(build, points) for build, (_score, points) in zip(builds, results)]
        values = chunked_many(self.dps_many, selected, limit)
        return [(value, points) for value, (_score, points) in zip(values, results)]

    def greedy_points(self, build) -> tuple[float, dict[str, int]]:
        """sunken_sim.esc.greedy_points (exact); structural attrs not fought, scored as current.

        FARM_HYBRID_ESC_ALGEBRA=1: guarded event-algebra ESC pilot (esc_algebra.py);
        =auto: measured-cost choice batched vs algebra per hero/spec (esc_device.Router);
        default off. FARM_HYBRID_ESC_ALGEBRA_DEVICE=cpu|gpu|auto (default cpu): weight
        algebra route (esc_device.py; guards always CPU float64). Both arms are exact.
        """
        import time

        from farm.hybrid.stat_kernel import greedy_points_batched

        hero = getattr(self, "hero", None)
        try:
            from farm.hybrid import esc_device as ed

            amode = ed.algebra_mode()
        except Exception:  # pragma: no cover - pilot module missing/broken
            amode = "off"
        strategy = None
        if amode != "off" and hero is not None:
            try:
                from farm.hybrid.esc_algebra import ALGEBRA_HEROES, greedy_points_algebra, score_engine
                from farm.hybrid.stat_kernel import structural_skip_attrs

                if hero in ALGEBRA_HEROES:
                    torch, target = getattr(self, "torch", None), getattr(self, "target", None)
                    if amode == "auto":  # measured batched vs algebra per hero/spec (both exact)
                        strategy = ed.router_for((hero, self.spec, str(target)), "auto", arms=("batched", "algebra"),
                                                 hysteresis=0.9)
                        if strategy.choose() == "batched":
                            raise _UseBatched
                    scorer = None
                    if torch is not None and target is not None:
                        scorer = lambda tr, W: score_engine(tr, W, torch, target)  # noqa: E731
                    mode = ed.device_mode()  # FARM_HYBRID_ESC_ALGEBRA_DEVICE=cpu|gpu|auto, default cpu
                    device = router = None
                    if mode != "cpu" and torch is not None and target is not None:
                        device = (torch, target)
                        router = ed.router_for((hero, self.spec, str(target)), mode)
                    t0 = time.perf_counter()
                    best, counts, _info = greedy_points_algebra(
                        self.dps_many, build, hero, self.spec, self.targets,
                        scorer=scorer, skip=structural_skip_attrs(hero),
                        device=device, router=router,
                    )
                    if strategy is not None:
                        strategy.record("algebra", time.perf_counter() - t0)
                    return self._canonical_fire_esc([build], [(best, counts)])[0]
            except _UseBatched:
                pass
            except Exception as exc:  # pilot must never break a job: exact batched path
                strategy = None
                print(f"hybrid: ESC algebra fallback ({exc.__class__.__name__}: {exc})", flush=True)
        t0 = time.perf_counter()
        out = greedy_points_batched(self.dps_many, build, hero=hero)
        if strategy is not None:
            strategy.record("batched", time.perf_counter() - t0)
        return out

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


    def finish_many(self, calls: list, limit: int = CROSS_MAX_BUILDS, esc: str | None = None) -> list:
        """[finish_sextuple(*call)] for independent calls of this hero/spec, batched ACROSS calls.

        Same three phases per call as finish_sextuple (talent combos, glyph combos
        on that call's best talents, lockstep exact ESC greedy), but each phase of
        all calls shares device batches (chunked_many). Selection per call keeps
        the strict '>' first-wins rule; fights formula unchanged. ESC here is the
        exact batched greedy (stat_kernel.greedy_points_many), or with esc="algebra"
        (when FARM_HYBRID_ESC_ALGEBRA=1, or auto after the batched-vs-algebra router) one guarded-algebra greedy per
        call, run in lockstep (farm/hybrid/lockstep.py) so the fights all those
        greedies still need share device batches.
        """
        from farm.hybrid.stat_kernel import greedy_points_many
        from sunken_sim.esc import ESC_ATTRS, points_payload
        from sunken_sim.shadow import MIND_AMPLIFIER, SKILL_POINTS, Build

        many = lambda builds: chunked_many(self.dps_many, builds, limit)  # noqa: E731
        rows = []
        flat = []
        for equipped, talent_codes, glyph_codes, picks_without, picks_with, glyph_picks in calls:
            picks = picks_with if any(item.rawcode == MIND_AMPLIFIER for item in equipped) else picks_without
            combos = list(itertools.combinations(talent_codes, picks))
            rows.append([equipped, combos, list(itertools.combinations(glyph_codes, glyph_picks)), len(flat)])
            flat.extend(Build(frozenset(c), frozenset(), equipped, 0, 0, 0, 0) for c in combos)
        scores = many(flat)
        state = []
        flat = []
        for equipped, combos, glyph_combos, off in rows:
            best_dps, best_talents = -1.0, ()
            for combo, dps in zip(combos, scores[off : off + len(combos)]):
                if dps > best_dps:
                    best_dps, best_talents = dps, combo
            state.append([best_dps, best_talents, len(flat)])
            flat.extend(Build(frozenset(best_talents), frozenset(c), equipped, 0, 0, 0, 0) for c in glyph_combos)
        scores = many(flat)
        finals = []
        for (equipped, _combos, glyph_combos, _o), st in zip(rows, state):
            best_dps, best_talents, off = st
            best_glyphs = ()
            for combo, dps in zip(glyph_combos, scores[off : off + len(glyph_combos)]):
                if dps > best_dps:
                    best_dps, best_glyphs = dps, combo
            st.append(best_glyphs)
            finals.append(Build(frozenset(best_talents), frozenset(best_glyphs), equipped, 0, 0, 0, 0))
        import time

        hero = getattr(self, "hero", None)
        strategy = None
        if esc is None:
            try:
                from farm.hybrid import esc_device as ed
                from farm.hybrid.esc_algebra import ALGEBRA_HEROES

                amode = ed.algebra_mode()
                if amode != "off" and hero in ALGEBRA_HEROES:
                    if amode == "auto":
                        strategy = ed.router_for(
                            (hero, self.spec, "cross"), "auto", arms=("batched", "algebra"), hysteresis=0.9
                        )
                        esc = strategy.choose()
                    else:
                        esc = "algebra"
                else:
                    esc = "batched"
            except Exception:  # pragma: no cover
                esc = "batched"
        t0 = time.perf_counter()
        if esc == "algebra":
            greedy = self._greedy_algebra_many(finals, limit)
            if strategy is not None:
                strategy.record("algebra", time.perf_counter() - t0)
        else:
            greedy = greedy_points_many(many, finals, hero=hero)
            if strategy is not None:
                strategy.record("batched", time.perf_counter() - t0)
        out = []
        for (equipped, combos, glyph_combos, _o), st, (pointed, points) in zip(rows, state, greedy):
            fights = len(combos) + len(glyph_combos) + SKILL_POINTS * len(ESC_ATTRS)
            out.append((pointed, st[1], st[3], points_payload(points), fights))
        return out


    def _greedy_algebra_many(self, builds: list, limit: int = CROSS_MAX_BUILDS) -> list:
        """Guarded-algebra ESC greedy per build (CPU f64 algebra, engine kind-score), lockstep."""
        from farm.hybrid.esc_algebra import greedy_points_algebra, score_engine
        from farm.hybrid.lockstep import run_lockstep
        from farm.hybrid.stat_kernel import structural_skip_attrs

        hero = self.hero
        torch, target = getattr(self, "torch", None), getattr(self, "target", None)
        scorer = None
        if torch is not None and target is not None:
            scorer = lambda tr, W: score_engine(tr, W, torch, target)  # noqa: E731
        skip = structural_skip_attrs(hero)

        def search(b):
            def run(proxy):
                best, counts, _info = greedy_points_algebra(
                    proxy, b, hero, self.spec, self.targets, scorer=scorer, skip=skip
                )
                return best, counts

            return run

        out, _stats = run_lockstep(
            [search(b) for b in builds], self.dps_many, lambda many, bs: chunked_many(many, bs, limit)
        )
        return self._canonical_fire_esc(builds, out, limit)


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

    if (R._HERO, R._SPEC) == ("mage", "fire") and not getattr(R, "_FIRE_DML_ALLOWED", True):
        _to_cpu("DirectML Fire context budget exhausted; explicit CPU oracle fallback")
        return None
    try:
        if not registry.gpu_engine_for(R._HERO, R._SPEC):
            raise ValueError(f"{R._HERO}/{R._SPEC} is {registry.status(R._HERO, R._SPEC)}")
        import torch

        torch.set_num_threads(1)
        from farm.hybrid.device import detect

        device = detect(R._HERO, R._SPEC)
        if not device.gpu:
            raise RuntimeError(f"worker GPU unavailable: {device.reason}")
        _ENGINE = registry.make_engine(device, R._HERO, R._SPEC, R._TARGETS)
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
    fire=(R._HERO,R._SPEC)==('mage','fire')
    fallbacks=[]
    counters=getattr(engine,'score_counts',{})
    before_gpu=counters.get('gpu_compile_rows',0);before_cpu=counters.get('cpu_compile_rows',0)
    def execution(payload):
        if fire:
            counts=getattr(engine,'score_counts',{})
            gpu=counts.get('gpu_compile_rows',0)-before_gpu;cpu=counts.get('cpu_compile_rows',0)-before_cpu
            actual=('mixed' if gpu else 'cpu-fallback') if fallbacks or cpu else 'hybrid'
            payload['fire_execution']=dict(actual=actual,gpu_compile_rows=gpu,cpu_compile_rows=cpu,reasons=list(fallbacks),pid=os.getpid(),engine_state=_ENGINE_STATE)
        return payload
    if engine is None:
        fallbacks.append(_ENGINE_NOTE or 'worker GPU unavailable')
        return execution(R.eval_span(start, stop))
    space = R._SPACE
    hits: list[dict] = []
    cross = _cross_build_enabled()
    queue: list = []  # admitted (chunk, equipped, sources, group, bare) waiting for finish_many

    def flush() -> None:
        """Finish every queued sextuple (groups of CROSS_ROWS), hits in chunk order."""
        nonlocal fights, errors, error
        rows_q = list(queue)
        queue.clear()
        calls = [
            (equipped, space.talents, space.glyphs, space.picks_without, space.picks_with, space.glyph_picks)
            for _c, equipped, _s, _g, _b in rows_q
        ]
        results: list = [None] * len(rows_q)
        for g in range(0, len(rows_q), CROSS_ROWS):
            try:
                results[g : g + CROSS_ROWS] = engine.finish_many(calls[g : g + CROSS_ROWS])
            except Exception as exc:  # whole group -> per-sextuple path below
                print(f"hybrid: cross-build fallback ({exc.__class__.__name__}: {exc})", flush=True)
        for (chunk, equipped, sources, group, bare), call, res in zip(rows_q, calls, results):
            try:
                if res is None:
                    try:
                        res = engine.finish_sextuple(*call)
                    except Exception as exc:
                        fallbacks.append('refinement CPU fallback: '+str(exc))
                        res = finish_sextuple(R._HERO, R._SPEC, R._TARGETS, *call)
                dps, talent_codes, glyph_codes, points, extra = res
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
                fallbacks.append(_ENGINE_NOTE or 'worker self-check failed')
                sub = R.eval_span(index, stop)
                hits.extend(sub["hits"])
                fights += sub["fights"]
                errors += sub["errors"]
                error = error or sub["error"]
                done = sub["done"]
                break
        except Exception as exc:
            fallbacks.append('span CPU fallback: '+str(exc))
            print(f"hybrid: exact CPU span fallback {index}:{end} ({type(exc).__name__}: {exc})", flush=True)
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
        if cross:  # opt-in: admitted sextuples queued across sub-spans, finished in shared batches
            for (chunk, equipped, sources, group), bare in zip(rows, bares):
                fights += 1
                if R.claim_item_bars(bare, group, chunk):  # same claims, same order; gate reads only bare
                    queue.append((chunk, equipped, sources, group, bare))
            if len(queue) >= CROSS_ROWS:
                flush()
            done = end
            index = end
            continue
        for (chunk, equipped, sources, group), bare in zip(rows, bares):
            fights += 1
            if not R.claim_item_bars(bare, group, chunk):
                continue
            call = (equipped, space.talents, space.glyphs, space.picks_without, space.picks_with, space.glyph_picks)
            try:
                try:
                    dps, talent_codes, glyph_codes, points, extra = engine.finish_sextuple(*call)
                except Exception as exc:
                    fallbacks.append('refinement CPU fallback: '+str(exc))
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
    if queue:  # sextuples admitted in [start, done) are always finished before returning
        flush()
    return execution({"start": start, "done": done, "fights": fights, "hits": R._compact(hits), "errors": errors, "error": error})

