"""Hybrid entry: worker "local-hybrid". Opt-in only.

Every class and spec runs here (farm.hybrid.registry has the status matrix):

  v1 (all specs but locked): GPU (DirectML) batched item-stat prep + parity check.
  hybrid-timeline (Mage Fire/Frost) and hybrid-compile (Priest): fights go through
     farm.hybrid.engine.eval_span with the spec's engine (registry.make_engine):
     CPU timeline, GPU compile sums, CPU closed-form score. A parent parity check
     vs the CPU sim (farm.score._fight) must pass, else the job runs the old CPU
     path; every worker process also self-checks its first fights.
  cpu-only: fights are the module's own CPU simulate (same payload).
  locked (Arcane Mage): old CPU runner, no device detection, no torch import.
"""

from __future__ import annotations

import time

from farm.hybrid import HYBRID_WORKER
from farm.hybrid.device import detect
from farm.hybrid.lock import cpu_locked
from farm.hybrid import registry

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
    from farm.hybrid.engine import compare
    from sunken_sim.shadow import Build

    space, items = load(hero, spec, pool, None, top)
    rng = random.Random(15)
    builds = []
    for i in range(FIGHT_CHECK):
        equipped = tuple(items[code] for code in space.decode(rng.randrange(space.total))[0])
        talents = frozenset(rng.sample(list(space.talents), space.picks_with)) if i % 2 else frozenset()
        builds.append(Build(talents, frozenset(), equipped, 0, 0, 0, 0))
    t0 = time.perf_counter()
    ref = [registry.cpu_dps(hero, spec, targets, b) for b in builds]
    t1 = time.perf_counter()
    got = registry.make_engine(device, hero, spec, targets).dps_many(builds)
    t2 = time.perf_counter()
    res = compare(ref, got)
    res.update({"device": device.kind, "cpu_s": round(t1 - t0, 3), "gpu_s": round(t2 - t1, 3)})
    return res


def run_job(job: dict, box: dict, tick) -> dict:
    from farm import runner as cpu_runner

    hero, spec = job["hero"], job["spec"]
    meta = {
        "worker": job.get("worker", HYBRID_WORKER),
        "status": registry.status(hero, spec),
        "device": "cpu",
        "name": "cpu",
        "gpu_fights": False,
    }

    def cpu(reason):
        if meta.get('selection') is not None:
            meta['selection'] = dict(meta['selection'], actual='cpu')
            meta.setdefault('registry_status',meta['status'])
            meta['status'] = 'cpu-selected'
            if meta['device'] != 'cpu':
                meta['attempted_device'] = dict(device=meta['device'],name=meta['name'])
            meta.update(device='cpu',name='cpu',gpu_fights=False)
        meta["fallback"] = reason
        tick({"hybrid": meta})
        if (hero,spec)==('mage','fire'):
            from farm.hybrid.fire_cpu import enabled,eval_span as staged_eval_span
            if enabled(job):
                meta['actual_planner']='cpu-staged-scalar'
                return cpu_runner.run_job(dict(job,hybrid=dict(meta)),box,tick,eval_fn=staged_eval_span)
        return cpu_runner.run_job(dict(job, hybrid=dict(meta)), box, tick)

    # Never import torch/detect a device for locked/unsupported heroes/specs.
    if cpu_locked(hero, spec):
        return cpu(f"{hero}/{spec} locked to CPU")
    if not registry.gpu_engine_for(hero, spec):
        return cpu(f"{hero}/{spec}: no supported hybrid fight engine")
    from farm.hybrid.fire_route import select
    selection = select(job)
    if selection is not None:
        meta['selection'] = selection
        if selection['selected'] == 'cpu':
            meta['registry_status'] = meta['status']
            meta['status'] = 'cpu-selected'
            return cpu(selection['policy'])
        import os
        meta['planner'] = os.environ.get('FARM_FIRE_PLANNER', 'scalar')
    try:
        device = detect(hero, spec)
    except Exception as exc:
        return cpu(f"device detection failed: {type(exc).__name__}: {exc}")
    meta.update(device=device.kind, name=device.name, reason=device.reason)
    if not device.gpu:
        return cpu(device.reason or "GPU unavailable")
    try:
        from farm.catalog import load
        space, items = load(hero, spec, job["pool"], job.get("preset") or None, job.get("top") or None)
        start = int(job["start"])
        stop = min(int(job["end"]) + 1, start + PREP_SPAN)
        meta["prep"] = prep_check(space, items, device, start, stop)
        if not meta["prep"].get("parity", False):
            return cpu("item-stat parity failed")
    except Exception as exc:
        return cpu(f"item-stat prep failed: {type(exc).__name__}: {exc}")
    try:
        meta["fights"] = fight_check(device, hero, spec, int(job["targets"]), job.get("top") or None, job["pool"])
        if not meta["fights"]["ok"]:
            return cpu("fight parity failed")
        from farm.hybrid.engine import eval_span as hybrid_eval_span
    except Exception as exc:
        return cpu(f"fight parity failed: {type(exc).__name__}: {exc}")
    meta["gpu_fights"] = True
    if meta.get('selection') is not None:
        meta['selection'] = dict(meta['selection'],actual='hybrid')
        meta['actual_planner'] = 'scalar' if meta['planner'] in ('auto','scalar') or os.environ.get('FARM_HYBRID_GPU_TIMELINE','auto').strip().lower() in ('0','false','off','cpu') else 'vector+exact-scalar-verification'
    tick({"hybrid": meta})
    return cpu_runner.run_job(dict(job, hybrid=dict(meta)), box, tick, eval_fn=hybrid_eval_span)


def dispatch(job: dict):
    """Worker name -> run_job. Anything that is not local-hybrid is the old path."""
    from farm import runner as cpu_runner

    if job.get("worker") == HYBRID_WORKER and not cpu_locked(job["hero"], job["spec"]):
        return run_job
    return cpu_runner.run_job