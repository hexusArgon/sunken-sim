"""Resume Shadow top-100 local-hybrid from existing job.json / checkpoint."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["FARM_DATA"] = str(ROOT / "farm-data-shadow-top100")

from farm.runner import run_job


def main() -> None:
    farm = Path(os.environ["FARM_DATA"])
    meta = farm / "job.json"
    job = json.loads(meta.read_text(encoding="utf-8"))
    assert job["worker"] == "local-hybrid", job["worker"]
    assert job["spec"] == "shadow", job["spec"]
    box = {"stop": False, "job_id": job["id"]}
    log = farm / "run.log"
    print("RESUME", job["id"], "worker", job["worker"], flush=True)

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
