"""Run a full Mage or Priest farm job locally with every fight on OpenCL (no Discord).

    .venv-dml\\Scripts\\python.exe tools\\run_opencl.py --hero priest --spec shadow --top 80
    .venv-dml\\Scripts\\python.exe tools\\run_opencl.py --hero mage --spec frost --top 100 --workers 4

Specs: mage fire/frost/arcane, priest shadow/discipline/holy,
shaman restoration/enhancement/elemental, paladin retribution/protection/holy,
druid restoration/balance (the caster Druid; feral_druid is a separate class).  Data (checkpoints,
results, runtime.json) go to sunken-sim-runs/<hero>-<spec>-opencl-top<N>/.  Running the same command again resumes
from the checkpoint.  To pause: create a file named request-stop in that
folder (or press Ctrl+C); the checkpoint is kept.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hero", required=True, choices=("mage", "priest", "shaman", "paladin", "druid"))
    ap.add_argument("--spec", required=True)
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--workers", type=int, default=4, help="worker processes, each with its own OpenCL context")
    ap.add_argument("--span", type=int, default=16384,
                    help="chunks per span; admitted chunks bunch at the start, small spans share their refinement")
    ap.add_argument("--targets", type=int, default=5)
    ap.add_argument("--name", default="", help="data folder name (default <hero>-<spec>-opencl-top<N>)")
    ap.add_argument("--data", default="", help="explicit data folder (overrides --name)")
    ap.add_argument("--budget", type=float, default=0.0, help="pause with checkpoint after this many seconds")
    ap.add_argument("--allow-fallback", action="store_true",
                    help="if the GPU parity preflight fails, run the job on the old hybrid route instead of stopping")
    args = ap.parse_args()
    from farm.hybrid.opencl_route import SPECS

    if (args.hero, args.spec) not in SPECS:
        ap.error(f"no OpenCL engine for {args.hero}/{args.spec}")
    from farm import admission as A

    gate = A.policy({"hero": args.hero})
    # bare-top50 runs get their own folder: an old bare-top10 job.json in the same folder would be resumed as is
    name = args.name or f"{args.hero}-{args.spec}-opencl-top{args.top}" + ("-gate50" if gate == A.BARE50 else "")
    data = Path(args.data) if args.data else REPO.parent / "sunken-sim-runs" / name
    data.mkdir(parents=True, exist_ok=True)
    os.environ["FARM_DATA"] = str(data)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[key] = "1"

    from farm.catalog import load
    from farm.hybrid import runner as H

    space, _items = load(args.hero, args.spec, "mixed", None, args.top)
    job_path = data / "job.json"
    if job_path.exists():
        job = json.loads(job_path.read_text(encoding="utf-8"))
    else:
        job = dict(id=data.name, worker="local-hybrid", hero=args.hero, spec=args.spec, pool="mixed", top=args.top,
                   targets=args.targets, start=0, end=space.total - 1, admission_policy=gate,
                   backend="opencl")
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    job.update(fire_cl_workers=args.workers, fire_cl_span=args.span)
    total = int(job["end"]) - int(job["start"]) + 1
    state = {"status": "starting", "pid": os.getpid(), "job": job, "N": total, "started_unix": time.time()}
    box = {"stop": False}
    lock = threading.Lock()

    from farm.paths import atomic_write

    def save():
        # Status file only: a reader holding runtime.json (Windows then denies the replace) must never stop the job.
        try:
            atomic_write(data / "runtime.json", json.dumps(state, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(f"runtime.json not updated: {type(exc).__name__}: {exc}", flush=True)

    def tick(value):
        try:
            _tick(value)
        except Exception as exc:  # progress reporting never stops the farm job
            print(f"status update skipped: {type(exc).__name__}: {exc}", flush=True)

    def _tick(value):
        with lock:
            state["updated_unix"] = time.time()
            if isinstance(value, dict):
                state["meta"] = value
            else:
                text = str(value)
                state["status_text"] = text
                m = re.search(r"посчитано\s+([0-9   ]+)", text)
                if m:
                    state["done"] = int("".join(c for c in m.group(1) if c.isdigit()))
                print(text.splitlines()[0] if text else text, flush=True)
            state["status"] = "running"
            save()

    began = time.time()

    def watch():
        while not box["stop"]:
            if (data / "request-stop").exists():
                print("request-stop found: pausing with checkpoint", flush=True)
                box["stop"] = True
            if args.budget and time.time() - began > args.budget:
                print("time budget reached: pausing with checkpoint", flush=True)
                box["stop"] = True
            time.sleep(1)

    threading.Thread(target=watch, daemon=True).start()
    print(f"{args.hero} {args.spec} Top-{args.top}: {total:,} chunks -> {data}", flush=True)
    if not args.allow_fallback:
        from farm import admission as A
        from farm.hybrid import mage_cl

        try:
            checked = mage_cl.preflight(dict(job, admission_policy=A.policy(job)))
        except Exception as exc:
            checked = dict(ok=False, reason=f"{type(exc).__name__}: {exc}")
        if not checked.get("ok"):
            state.update(status="preflight-failed", preflight=checked)
            save()
            print(f"GPU parity preflight failed, not running (use --allow-fallback for the hybrid route): "
                  f"{json.dumps(checked, ensure_ascii=False, default=str)[:2000]}", flush=True)
            return 2
        print(f"GPU parity preflight: exact on {checked.get('name')} ({checked.get('seconds')} s)", flush=True)
    t0 = time.time()
    try:
        result = H.run_job(job, box, tick)
    except KeyboardInterrupt:
        box["stop"] = True
        state["status"] = "interrupted"
        save()
        print("interrupted; the last checkpoint is kept", flush=True)
        return 1
    state.update(result=result, status="complete" if result.get("left") == 0 and not result.get("errors") else "stopped",
                 finished_unix=time.time(), wall_hours=round((time.time() - t0) / 3600, 3))
    save()
    print(json.dumps(result, ensure_ascii=False), flush=True)
    print(f"wall {(time.time() - t0) / 3600:.2f} h", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
