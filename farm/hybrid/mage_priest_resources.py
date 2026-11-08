"""Scoped Mage/Priest resource safety; no changes to Fire/other class semantics."""
from __future__ import annotations
import math
SCOPED_SPECS = frozenset({("mage", "frost"), ("mage", "arcane"), ("priest", "shadow"), ("priest", "discipline"), ("priest", "holy")})

def notice(message):
    try:
        print(message, flush=True)
    except Exception:
        pass  # Logging itself is an observer, never a numerical failure.

def scoped(hero, spec):
    return (hero, spec) in SCOPED_SPECS

def worker_count(job):
    value = job.get("hybrid_dml_workers", 1)
    # Only containment is established here. Fire's measured six is NOT a proof for these specs.
    if type(value) is not int or value != 1:
        raise ValueError("hybrid_dml_workers must be 1 for Mage Frost/Arcane and Priest; higher counts require per-spec hardware validation")
    return value

def canonical_final_dps(hero, spec, targets, build):
    """Same selected-build scoring route as farm.score.score_build, no repeated search."""
    if hero != "priest":
        from farm.hybrid.registry import cpu_dps
        return cpu_dps(hero, spec, targets, build)
    from sunken_sim.shadow import FIGHT, character, compile_events, score_compiled, simulate
    fresh = {"targets": targets}
    simulate(build, targets, fresh, spec=spec, use_history=False)
    if "events" not in fresh:
        return -1.0  # same sentinel as farm.score._priest's score closure
    stats = character(build)
    compiled = compile_events(fresh["events"], build, stats, spec, fresh.get("windows"))
    return score_compiled(compiled, stats, stats["potency"], min(100.0, stats["crit"]), stats["mastery"], stats["luck"]) / FIGHT

def canonical_esc(engine, builds, results):
    if not scoped(getattr(engine, "hero", None), getattr(engine, "spec", None)):
        return results
    from sunken_sim.esc import apply_points
    if len(builds) != len(results):
        raise ValueError("ESC result length mismatch")
    out = []
    for build, (_projected, points) in zip(builds, results):
        score = canonical_final_dps(engine.hero, engine.spec, engine.targets, apply_points(build, points))
        if not math.isfinite(score):
            raise ValueError("non-finite canonical ESC score")
        out.append((score, points))
    try:
        if hasattr(engine, "score_counts"):
            engine.score_counts["canonical_final_builds"] += len(out)
    except Exception as exc:
        notice(f"hybrid: final-score telemetry unavailable ({type(exc).__name__})")
    return out

def record_execution(job, payload):
    """Best-effort observer: failure never escapes into span completion/search accounting."""
    try:
        execution = payload.get("hybrid_execution")
        meta = job.get("hybrid")
        if execution is None or meta is None:
            return
        processes = meta.setdefault("worker_processes", {})
        row = processes.setdefault(str(execution["pid"]), dict(returned_spans=0, gpu_compile_rows=0, cpu_compile_rows=0, canonical_final_builds=0))
        row.update(actual=execution["actual"], engine_state=execution["engine_state"], lease_allowed=execution["lease_allowed"])
        for key in ("gpu_compile_rows", "cpu_compile_rows", "canonical_final_builds"):
            row[key] += int(execution.get(key, 0))
        row["returned_spans"] += 1
        paths = meta.setdefault("worker_paths", {})
        paths[execution["actual"]] = paths.get(execution["actual"], 0) + 1
        cpu = bool(paths.get("cpu-fallback") or paths.get("mixed"))
        gpu = bool(paths.get("hybrid") or paths.get("mixed"))
        if cpu:
            meta.setdefault("attempted_device", dict(device=meta.get("device"), name=meta.get("name")))
            meta.update(status="hybrid-with-cpu-fallback" if gpu else "cpu-fallback", device="mixed" if gpu else "cpu", gpu_fights=gpu)
        meta["worker_fallbacks"] = list(dict.fromkeys(meta.get("worker_fallbacks", []) + execution.get("reasons", [])))
    except Exception as exc:
        notice(f"hybrid: execution telemetry unavailable ({type(exc).__name__})")

def emit_tick(tick, meta):
    try:
        tick({"hybrid": meta})
    except Exception as exc:
        notice(f"hybrid: execution observer unavailable ({type(exc).__name__})")
