"""Fire resource preflight in a short-lived process; no numerical substitutions."""
from __future__ import annotations
import multiprocessing as mp
import os


def _fire_preflight_child(job, connection):
    try:
        import torch
        torch.set_num_threads(1)
        from farm.catalog import load
        from farm.hybrid.device import detect
        from farm.hybrid.runner import PREP_SPAN, prep_check, fight_check
        device = detect("mage", "fire")
        meta = dict(device=device.kind, name=device.name, reason=device.reason)
        if not device.gpu:
            connection.send(dict(ok=False, reason=device.reason or "GPU unavailable", meta=meta))
            return
        space, items = load("mage", "fire", job["pool"], job.get("preset") or None, job.get("top") or None)
        start = int(job["start"])
        meta["prep"] = prep_check(space, items, device, start, min(int(job["end"])+1, start+PREP_SPAN))
        meta["fights"] = fight_check(device, "mage", "fire", int(job["targets"]), job.get("top") or None, job["pool"])
        ok = meta["prep"].get("parity", False) and meta["fights"]["ok"]
        connection.send(dict(ok=ok, reason="" if ok else "item/fight parity failed", meta=meta))
    except BaseException as exc:
        connection.send(dict(ok=False, reason=f"{type(exc).__name__}: {exc}", meta={}))
    finally:
        connection.close()


def isolated_fire_preflight(job: dict, timeout: float = 120.0) -> dict:
    """Return only plain metadata AFTER the owner process exited, never a GPUhandle."""
    if (job.get("hero"), job.get("spec")) != ("mage", "fire"):
        raise ValueError("isolated_fire_preflight is Fire-only")
    ctx = mp.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_fire_preflight_child, args=(dict(job), send), name="fire-dml-preflight")
    process.start()
    send.close()
    try:
        if not receive.poll(timeout):
            raise TimeoutError("Fire GPU preflight timed out; no worker pool was started")
        result = receive.recv()
        process.join(10)
        if process.is_alive() or process.exitcode != 0:
            raise RuntimeError("Fire preflight did not exit cleanly; no worker pool was started")
        result["lifecycle"] = dict(pid=process.pid, exited=True, exitcode=process.exitcode, isolated=True)
        return result
    finally:
        receive.close()
        if process.is_alive():
            # Exact process handle owned by this function; no user farm exists in this child.
            process.terminate()
            process.join(10)
            if process.is_alive():
                raise RuntimeError("Could not release owned Fire preflight process")
