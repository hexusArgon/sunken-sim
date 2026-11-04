"""Hybrid entry: worker "local-hybrid". Opt-in only.

v1: GPU (DirectML) does batched item-stat prep + parity self-check on the first
span; every fight is still the old CPU sim via farm.runner.run_job, so DPS
results are identical to "local-esc". Arcane Mage never touches the GPU path.
"""

from __future__ import annotations

import time

from farm.hybrid import HYBRID_WORKER
from farm.hybrid.device import detect
from farm.hybrid.lock import cpu_locked

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
    tick(info)
    # Fights: unchanged CPU ProcessPool sim.
    return cpu_runner.run_job(job, box, tick)


def dispatch(job: dict):
    """Worker name -> run_job. Anything that is not local-hybrid is the old path."""
    from farm import runner as cpu_runner

    if job.get("worker") == HYBRID_WORKER and not cpu_locked(job["hero"], job["spec"]):
        return run_job
    return cpu_runner.run_job