"""Hybrid entry: worker "local-hybrid". Opt-in only.

v1: GPU (DirectML) does batched item-stat prep + parity self-check on the first span.
v2: for Mage Fire/Frost (farm.hybrid.fight.GPU_FIGHT_SPECS) fights go through
farm.hybrid.fight.eval_span: CPU timeline, GPU compile sums, CPU closed-form score.
A parent parity check vs the CPU sim must pass, else the job runs the old CPU path.
Other specs: fights are the old CPU sim. Arcane Mage never touches the GPU path.
"""

from __future__ import annotations

import time

from farm.hybrid import HYBRID_WORKER
from farm.hybrid.device import detect
from farm.hybrid.lock import cpu_locked
from farm.hybrid.fight import gpu_fights_for

PREP_SPAN = 4096


def prep_check(space, items: dict, device, start: int, stop: int) -> dict:
    """Run the stat kernel on [start, stop) on CPU and on device; compare."""
    from farm.hybrid.kernel import decode_rows, item_table, parity, stat_fields, totals_cpu, totals_device
    from sunken_sim.library import Item

    fields = stat_fields(Item)
    index, table = item_table(items, fields)
    rows = decode_rows(space, index, start, stop)
    t0 = time.perf_counter()
    ref = totals_cpu(table, rows)
    t1 = time.perf_counter()
    if not device.gpu:
        return {"device": "cpu", "rows": len(rows), "cpu_s": round(t1 - t0, 4), "parity": True, "worst": 0.0}
    dev = totals_device(table, rows, device)
    t2 = time.perf_counter()
    ok, worst = parity(ref, dev)
    return {
        "device": device.kind,
        "name": device.name,
        "rows": len(rows),
        "cpu_s": round(t1 - t0, 4),
        "gpu_s": round(t2 - t1, 4),
        "parity": ok,
        "worst": worst,
    }


FIGHT_CHECK = 64


def fight_check(device, hero: str, spec: str, targets: int, top: int | None = 80, pool: str = "mixed") -> dict:
    """Parent-side parity: FIGHT_CHECK seeded builds, CPU sim vs GPU fights."""
    import random

    from farm.catalog import load
    from farm.hybrid.fight import GpuFights, compare, cpu_dps
    from sunken_sim.shadow import Build

    space, items = load(hero, spec, pool, None, top)
    rng = random.Random(15)
    builds = []
    for i in range(FIGHT_CHECK):
        equipped = tuple(items[code] for code in space.decode(rng.randrange(space.total))[0])
        talents = frozenset(rng.sample(list(space.talents), space.picks_with)) if i % 2 else frozenset()
        builds.append(Build(talents, frozenset(), equipped, 0, 0, 0, 0))
    t0 = time.perf_counter()
    ref = [cpu_dps(b, targets, spec) for b in builds]
    t1 = time.perf_counter()
    got = GpuFights(device, hero, spec, targets).dps_many(builds)
    t2 = time.perf_counter()
    res = compare(ref, got)
    res.update({"device": device.kind, "cpu_s": round(t1 - t0, 3), "gpu_s": round(t2 - t1, 3)})
    return res


def run_job(job: dict, box: dict, tick) -> dict:
    from farm import runner as cpu_runner

    hero, spec = job["hero"], job["spec"]
    if cpu_locked(hero, spec):
        # Hard lock: old CPU sim, no device detection, no torch import.
        return cpu_runner.run_job(job, box, tick)

    device = detect(hero, spec)
    info = {"hybrid": {"worker": job.get("worker", HYBRID_WORKER), "device": device.kind, "name": device.name, "reason": device.reason}}
    try:
        from farm.catalog import load

        space, items = load(hero, spec, job["pool"], job.get("preset") or None, job.get("top") or None)
        start = int(job["start"])
        stop = min(int(job["end"]) + 1, start + PREP_SPAN)
        info["hybrid"]["prep"] = prep_check(space, items, device, start, stop)
        if not info["hybrid"]["prep"].get("parity", False):
            info["hybrid"]["fallback"] = "parity failed, CPU only"
    except Exception as exc:  # prep must never break the farm
        info["hybrid"]["prep_error"] = f"{exc.__class__.__name__}: {exc}"
    eval_fn = None
    if gpu_fights_for(hero, spec) and "fallback" not in info["hybrid"]:
        try:
            info["hybrid"]["fights"] = fight_check(device, hero, spec, int(job["targets"]), job.get("top") or None, job["pool"])
            if info["hybrid"]["fights"]["ok"]:
                from farm.hybrid.fight import eval_span as hybrid_eval_span

                eval_fn = hybrid_eval_span
            else:
                info["hybrid"]["fallback"] = "fight parity failed, CPU fights"
        except Exception as exc:
            info["hybrid"]["fight_error"] = f"{exc.__class__.__name__}: {exc}"
    info["hybrid"]["gpu_fights"] = eval_fn is not None
    tick(info)
    if eval_fn is None:
        # Fights: unchanged CPU ProcessPool sim.
        return cpu_runner.run_job(job, box, tick)
    return cpu_runner.run_job(job, box, tick, eval_fn=eval_fn)


def dispatch(job: dict):
    """Worker name -> run_job. Anything that is not local-hybrid is the old path."""
    from farm import runner as cpu_runner

    if job.get("worker") == HYBRID_WORKER and not cpu_locked(job["hero"], job["spec"]):
        return run_job
    return cpu_runner.run_job