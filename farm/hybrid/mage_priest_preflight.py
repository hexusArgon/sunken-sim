"""Scoped isolated preflight; never keep a coordinator device alive during a worker pool."""
from __future__ import annotations
import multiprocessing as mp
from farm.hybrid.mage_priest_resources import scoped

def _child(job, connection):
    try:
        import torch
        torch.set_num_threads(1)
        from farm.catalog import load
        from farm.hybrid.device import detect
        from farm.hybrid.runner import PREP_SPAN, prep_check, fight_check
        hero, spec = job["hero"], job["spec"]
        device = detect(hero, spec)
        meta = dict(device=device.kind, name=device.name, reason=device.reason)
        if not device.gpu:
            connection.send(dict(ok=False, reason=device.reason or "GPU unavailable", meta=meta))
            return
        space, items = load(hero, spec, job["pool"], job.get("preset") or None, job.get("top") or None)
        start = int(job["start"])
        meta["prep"] = prep_check(space, items, device, start, min(int(job["end"])+1, start+PREP_SPAN))
        meta["fights"] = fight_check(device, hero, spec, int(job["targets"]), job.get("top") or None, job["pool"])
        ok = meta["prep"].get("parity", False) and meta["fights"]["ok"]
        connection.send(dict(ok=ok, reason="" if ok else "item/fight parity failed", meta=meta))
    except BaseException as exc:
        connection.send(dict(ok=False, reason=f"{type(exc).__name__}: {exc}", meta={}))
    finally:
        connection.close()

def isolated_preflight(job, timeout=120.0):
    if not scoped(job.get("hero"), job.get("spec")):
        raise ValueError("Mage Frost/Arcane or Priest only")
    ctx = mp.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child, args=(dict(job), send), name="mage-priest-dml-preflight")
    process.start()
    send.close()
    try:
        if not receive.poll(timeout):
            raise TimeoutError("Scoped preflight timeout; no worker pool started")
        result = receive.recv()
        process.join(10)
        if process.is_alive() or process.exitcode != 0:
            raise RuntimeError("Scoped preflight must exit before worker pool")
        result["lifecycle"] = dict(pid=process.pid, exited=True, exitcode=process.exitcode, isolated=True)
        return result
    finally:
        receive.close()
        if process.is_alive():
            process.terminate()  # exact owned child handle; never a farm/foreign PID
            process.join(10)
            if process.is_alive():
                raise RuntimeError("Owned scoped preflight did not exit")
