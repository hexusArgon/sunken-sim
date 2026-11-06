# -*- coding: utf-8 -*-
"""Live farm-worker bench: farm.hybrid.runner.run_job on a short span, flags off vs on.

Isolated: FARM_DATA points at a scratch dir (fresh per config), so no real checkpoint /
result is touched. Configs run sequentially in child processes (env differs per config).
Compares wall time, done count and the written leaderboards (identical = same builds,
points and dps within 1e-4).

.venv-dml\\Scripts\\python.exe tools\\_bench_live_worker.py --hero witch_doctor --spec voodoo --start 0 --end 63 --workers 2
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = {
    "off": {"FARM_HYBRID_CROSS_BUILD": "0", "FARM_HYBRID_ESC_ALGEBRA": "0"},
    "cross": {"FARM_HYBRID_CROSS_BUILD": "1", "FARM_HYBRID_ESC_ALGEBRA": "0"},
    "alg_auto": {"FARM_HYBRID_CROSS_BUILD": "0", "FARM_HYBRID_ESC_ALGEBRA": "auto"},
    "cross_alg": {"FARM_HYBRID_CROSS_BUILD": "1", "FARM_HYBRID_ESC_ALGEBRA": "auto"},
}
FLAGS = ("FARM_HYBRID_CROSS_BUILD", "FARM_HYBRID_ESC_ALGEBRA", "FARM_HYBRID_ESC_ALGEBRA_DEVICE")


def child(args) -> int:
    sys.path.insert(0, str(ROOT))
    from farm.hybrid import runner

    job = {
        "id": f"bench-live-{args.hero}-{args.spec}",
        "worker": "local-hybrid",
        "hero": args.hero,
        "spec": args.spec,
        "pool": args.pool,
        "start": args.start,
        "end": args.end,
        "targets": args.targets,
    }
    if args.top:
        job["top"] = args.top
    ticks = []
    t0 = time.perf_counter()
    out = runner.run_job(job, {}, ticks.append)
    wall = time.perf_counter() - t0
    hy = next((t.get("hybrid") for t in ticks if isinstance(t, dict) and "hybrid" in t), {})
    print("RESULT " + json.dumps({"wall": wall, "out": out, "gpu_fights": hy.get("gpu_fights"), "fallback": hy.get("fallback")}), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hero", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--pool", default="mixed")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=63)
    ap.add_argument("--targets", type=int, default=5)
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--configs", default="off,cross,alg_auto,cross_alg")
    ap.add_argument("--scratch", default=os.path.join(os.environ.get("TEMP", "/tmp"), "ss_alg", "farmdata_bench"))
    ap.add_argument("--child", action="store_true")
    args = ap.parse_args()
    if args.child:
        return child(args)
    res = {}
    for name in args.configs.split(","):
        data = Path(args.scratch) / name
        shutil.rmtree(data, ignore_errors=True)
        env = {k: v for k, v in os.environ.items() if k not in FLAGS}
        env.update(CONFIGS[name])
        env["FARM_DATA"] = str(data)
        env["FARM_WORKERS"] = str(args.workers)
        cmd = [sys.executable, __file__, "--child"] + [a for a in sys.argv[1:] if a != "--child"]
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT ")), None)
        if line is None:
            print(f"{name}: FAILED rc={proc.returncode}\n{proc.stderr[-2000:]}")
            continue
        info = json.loads(line[7:])
        files = sorted((data / "results").glob("*.json"))
        board = json.loads(files[0].read_text(encoding="utf-8")) if files else {}
        res[name] = (info, board)
        print(f"{name}: wall={info['wall']:.1f}s proc={time.perf_counter() - t0:.1f}s done={info['out'].get('done')} "
              f"errors={info['out'].get('errors')} gpu_fights={info['gpu_fights']} fallback={info['fallback']}", flush=True)
    if "off" in res:
        base_info, base = res["off"]
        for name, (info, board) in res.items():
            if name == "off":
                continue
            same = True
            for key in ("top", "top_shop", "top_random", "top_shop_random"):
                a, b = base.get(key) or [], board.get(key) or []
                if len(a) != len(b):
                    same = False
                    continue
                for x, y in zip(a, b):
                    xs = {k: v for k, v in x.items() if k != "dps"} if isinstance(x, dict) else x
                    ys = {k: v for k, v in y.items() if k != "dps"} if isinstance(y, dict) else y
                    if xs != ys:
                        same = False
                    if isinstance(x, dict) and "dps" in x and abs(float(x["dps"]) - float(y["dps"])) > 1e-4 * max(1.0, abs(float(x["dps"]))):
                        same = False
            print(f"{name}: speedup vs off {base_info['wall'] / info['wall']:.2f}x | leaderboards identical={same}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
