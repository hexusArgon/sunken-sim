"""Tiny hybrid smoke (worker local-hybrid). Never Arcane Mage.

  .venv-dml\Scripts\python.exe tools\run_hybrid_smoke.py            # DirectML if present
  python tools\run_hybrid_smoke.py --hero mage --spec fire --count 500
  .venv-dml\Scripts\python.exe tools\run_hybrid_smoke.py --count 2000 --compare   # + same span on local-esc

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
    parser.add_argument("--compare", action="store_true", help="also run the span on the old CPU path and diff results")
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
    hybrid_s = round(time.time() - started, 1)
    print("DONE", json.dumps({"elapsed_s": hybrid_s, **{k: result.get(k) for k in keys}}, ensure_ascii=False))
    if not args.compare:
        return
    from farm import runner as cpu_runner

    cpu_job = dict(job, id=job["id"] + "-cpu", worker="local-esc-smoke")
    began = time.time()
    cpu_result = cpu_runner.run_job(cpu_job, {"stop": False, "job_id": cpu_job["id"]}, lambda _p: None)
    cpu_s = round(time.time() - began, 1)
    print(json.dumps(diff_results(result["path"], cpu_result["path"], hybrid_s, cpu_s), ensure_ascii=False, indent=2))


def diff_results(hybrid_path: str, cpu_path: str, hybrid_s: float, cpu_s: float) -> dict:
    a = json.loads(Path(hybrid_path).read_text(encoding="utf-8"))
    b = json.loads(Path(cpu_path).read_text(encoding="utf-8"))
    out = {"hybrid_s": hybrid_s, "cpu_s": cpu_s, "boards": {}}
    worst = 0.0
    for board in ("top", "top_shop_random", "top_shop", "top_random"):
        ra, rb = a.get(board) or [], b.get(board) or []
        same_chunks = [r.get("chunk") for r in ra] == [r.get("chunk") for r in rb]
        rel = max((abs(x["dps"] - y["dps"]) / max(1.0, abs(y["dps"])) for x, y in zip(ra, rb)), default=0.0)
        worst = max(worst, rel)
        out["boards"][board] = {"rows": [len(ra), len(rb)], "same_chunks": same_chunks, "max_rel": rel}
    out["max_rel"] = worst
    out["ok"] = all(v["same_chunks"] for v in out["boards"].values()) and worst <= 1e-4
    return out


if __name__ == "__main__":
    main()