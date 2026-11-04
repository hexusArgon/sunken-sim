"""Tiny hybrid smoke (worker local-hybrid). Never Arcane Mage.

  .venv-dml\Scripts\python.exe tools\run_hybrid_smoke.py            # DirectML if present
  python tools\run_hybrid_smoke.py --hero mage --spec fire --count 500

Separate FARM_DATA (farm-data-hybrid-smoke), FARM_WORKERS=2 by default so a
running farm keeps its CPU.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FARM_DATA", str(ROOT / "farm-data-hybrid-smoke"))
os.environ.setdefault("FARM_WORKERS", "2")

from farm.hybrid import HYBRID_WORKER, cpu_locked
from farm.hybrid.runner import run_job


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hero", default="mage")
    parser.add_argument("--spec", default="fire")
    parser.add_argument("--pool", default="mixed")
    parser.add_argument("--top", type=int, default=80)
    parser.add_argument("--targets", type=int, default=5)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=2000)
    args = parser.parse_args()
    if cpu_locked(args.hero, args.spec):
        raise SystemExit(f"{args.hero}/{args.spec} is locked to the old CPU sim; use its own runner")

    job = {
        "id": f"hybrid-smoke-{uuid.uuid4().hex[:8]}",
        "worker": HYBRID_WORKER,
        "start": args.start,
        "end": args.start + args.count - 1,
        "hero": args.hero,
        "spec": args.spec,
        "pool": args.pool,
        "targets": args.targets,
        "channel": "",
        "status": "",
        "top": args.top,
        "preset": "",
    }
    started = time.time()

    def tick(payload: dict) -> None:
        print(json.dumps(payload, ensure_ascii=False), flush=True)

    result = run_job(job, {"stop": False, "job_id": job["id"]}, tick)
    keys = ("path", "done", "errors", "stopped")
    print("DONE", json.dumps({"elapsed_s": round(time.time() - started, 1), **{k: result.get(k) for k in keys}}, ensure_ascii=False))


if __name__ == "__main__":
    main()