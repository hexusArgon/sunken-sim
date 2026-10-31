"""Local Shadow priest top-80 farm at lvl15 + greedy ESC. Separate FARM_DATA."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["FARM_DATA"] = str(ROOT / "farm-data-shadow-esc")

from farm.catalog import load
from farm.runner import run_job


def main() -> None:
    # Drop stale top80 space pickle so ranks follow new one-slot-classes.json
    cache = ROOT / "farm-data" / "cache"
    for path in cache.glob("priest-shadow-mixed-top80-*.pkl"):
        path.unlink(missing_ok=True)
        print("dropped", path.name, flush=True)
    shadow_cache = Path(os.environ["FARM_DATA"]) / "cache"
    if shadow_cache.exists():
        for path in shadow_cache.glob("priest-shadow-mixed-top80-*.pkl"):
            path.unlink(missing_ok=True)
            print("dropped", path.name, flush=True)

    space, _items = load(hero="priest", spec="shadow", pool="mixed", top=80)
    job = {
        "id": f"shadow-esc-{uuid.uuid4().hex[:8]}",
        "worker": "local-esc",
        "start": 0,
        "end": space.total - 1,
        "hero": "priest",
        "spec": "shadow",
        "pool": "mixed",
        "targets": 5,
        "channel": "",
        "status": "",
        "top": 80,
        "preset": "",
    }
    box = {"stop": False, "job_id": job["id"]}
    log = Path(os.environ["FARM_DATA"]) / "run.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    meta = Path(os.environ["FARM_DATA"]) / "job.json"
    meta.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

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
