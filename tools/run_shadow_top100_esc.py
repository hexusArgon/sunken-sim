"""Shadow priest top-100 ESC farm on local-hybrid (DirectML)."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["FARM_DATA"] = str(ROOT / "farm-data-shadow-top100")
# Prefer DirectML venv when launched via that interpreter.

from farm.catalog import load
from farm.hybrid import HYBRID_WORKER
from farm.runner import run_job


def main() -> None:
    cache = ROOT / "farm-data" / "cache"
    for path in cache.glob("priest-shadow-mixed-top100-*.pkl"):
        path.unlink(missing_ok=True)
        print("dropped", path.name, flush=True)
    farm = Path(os.environ["FARM_DATA"])
    farm.mkdir(parents=True, exist_ok=True)
    shadow_cache = farm / "cache"
    shadow_cache.mkdir(parents=True, exist_ok=True)
    for path in shadow_cache.glob("priest-shadow-mixed-top100-*.pkl"):
        path.unlink(missing_ok=True)
        print("dropped", path.name, flush=True)

    space, _items = load(hero="priest", spec="shadow", pool="mixed", top=100)
    job = {
        "id": f"shadow-top100-hybrid-{uuid.uuid4().hex[:8]}",
        "worker": HYBRID_WORKER,
        "start": 0,
        "end": space.total - 1,
        "hero": "priest",
        "spec": "shadow",
        "pool": "mixed",
        "targets": 5,
        "channel": "",
        "status": "",
        "top": 100,
        "preset": "",
    }
    box = {"stop": False, "job_id": job["id"]}
    log = farm / "run.log"
    meta = farm / "job.json"
    meta.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    print("job", job["id"], "worker", job["worker"], "chunks", space.total, flush=True)

    def tick(payload: dict) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        print(line, flush=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    started = time.time()
    result = run_job(job, box, tick)
    print(
        "DONE",
        json.dumps(
            {
                "elapsed_s": round(time.time() - started, 1),
                **(
                    {k: result.get(k) for k in ("path", "done", "errors", "stopped")}
                    if isinstance(result, dict)
                    else {"result": str(result)}
                ),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
