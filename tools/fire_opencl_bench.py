"""Check and time the exact OpenCL Fire scan on this PC. Changes nothing in farm data.

    .venv-dml\\Scripts\\python.exe tools\\fire_opencl_bench.py
    .venv-dml\\Scripts\\python.exe tools\\fire_opencl_bench.py --top 100 --parity 3000

1. Lists OpenCL devices with float64.
2. Bit-exact parity: kernel vs the Python sim on random chunks (and on the
   stored bare values of the finished Top-80 checkpoint, when present).
3. Throughput of 1, 2, 4 and 8 concurrent worker processes on the GPU.
4. Full-space estimate for the chosen Top-N.

Writes sunken-sim-runs/opencl-fire-dev/bench-<time>.json next to the repo.
"""
from __future__ import annotations

import argparse
import glob
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO.parent / "sunken-sim-runs" / "opencl-fire-dev"
sys.path.insert(0, str(REPO))
os.environ.setdefault("FARM_DATA", str(OUT / "bench-data"))


def _child(top, rows, launch, barrier, queue):
    from farm.catalog import load
    from farm.runner import source_map
    from farm.hybrid.fire_cl import FireCL

    space, items = load("mage", "fire", "mixed", None, top)
    engine = FireCL(space, items, source_map(items), 5)
    engine.bare(0, 1024)
    start = (os.getpid() * 7919) % max(1, space.total - rows)
    barrier.wait()
    t0 = time.perf_counter()
    done = 0
    worst = 0.0
    while done < rows:
        n = min(launch, rows - done)
        t1 = time.perf_counter()
        engine.bare(start + done, n)
        worst = max(worst, time.perf_counter() - t1)
        done += n
    queue.put((done, time.perf_counter() - t0, worst))


def concurrent(top, procs, rows, launch):
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(procs + 1)
    queue = ctx.Queue()
    ps = [ctx.Process(target=_child, args=(top, rows, launch, barrier, queue)) for _ in range(procs)]
    for p in ps:
        p.start()
    barrier.wait()
    t0 = time.perf_counter()
    results = [queue.get(timeout=900) for _ in ps]
    wall = time.perf_counter() - t0
    for p in ps:
        p.join(30)
    total = sum(r[0] for r in results)
    return {"procs": procs, "rows": total, "wall_s": round(wall, 2), "rows_per_s": round(total / wall),
            "worst_launch_s": round(max(r[2] for r in results), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--parity", type=int, default=2000, help="random chunks checked against the Python sim")
    ap.add_argument("--procs", default="1,2,4,8")
    ap.add_argument("--rows", type=int, default=400000, help="rows per process in the throughput test")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "top": args.top}

    from farm.hybrid.fire_cl import FireCL, _import_cl, parity, pick_device, sample
    cl = _import_cl()
    devices = []
    for platform in cl.get_platforms():
        for d in platform.get_devices():
            devices.append({"platform": platform.name.strip(), "name": d.name.strip(), "driver": d.driver_version,
                            "fp64": "cl_khr_fp64" in d.extensions, "compute_units": d.max_compute_units,
                            "gpu": bool(d.type & cl.device_type.GPU)})
    report["devices"] = devices
    print("OpenCL devices:")
    for d in devices:
        print(f"  {d['name']} | {d['platform']} | driver {d['driver']} | fp64={d['fp64']} | CUs={d['compute_units']}")
    device = pick_device(cl)
    print("chosen:", device.name.strip())

    from farm.catalog import load
    from farm.runner import source_map
    space, items = load("mage", "fire", "mixed", None, args.top)
    sources = source_map(items)
    t0 = time.perf_counter()
    engine = FireCL(space, items, sources, 5, device=device)
    report["build_s"] = round(time.perf_counter() - t0, 2)
    print(f"kernel built in {report['build_s']} s; chunks in Top-{args.top}: {space.total:,}")

    t0 = time.perf_counter()
    check = parity(engine, space, items, sources, 5, sample(space, args.parity, 2026))
    report["parity_random"] = check
    print(f"parity vs Python sim: {check['rows']} chunks, mismatches {check['mismatches']}, "
          f"oracle-only rows {check['status_rows']} ({time.perf_counter() - t0:.1f} s)")
    stored = glob.glob(str(REPO.parent / "sunken-sim-runs" / "fire-top80-*-r1" / "checkpoints" / "*0f065922c975b683.json"))
    if args.top == 80 and stored:
        saved = json.loads(Path(stored[0]).read_text(encoding="utf-8"))
        rows = [(r["chunk"], r["dps"]) for v in saved["item_observations"].values() for r in v]
        rows += [(r["chunk"], r["item_dps"]) for k in ("top", "top_shop", "top_random", "top_shop_random") for r in saved[k]]
        bad = 0
        for chunk, value in rows:
            dps, _g, status = engine.bare(int(chunk), 1)
            bad += int(status[0] != 0 or float(dps[0]).hex() != float(value).hex())
        report["parity_checkpoint"] = {"rows": len(rows), "mismatches": bad}
        print(f"parity vs finished Top-80 checkpoint: {len(rows)} stored bare values, mismatches {bad}")
    from farm.hybrid.fire_cl import parity_full, random_builds
    t0 = time.perf_counter()
    full = parity_full(engine, space, items, 5, random_builds(space, max(200, args.parity // 2), 2027))
    report["parity_talents_glyphs_esc"] = full
    print(f"parity with talents/glyphs/ESC: {full['rows']} fights, mismatches {full['mismatches']}, "
          f"oracle-only rows {full['status_rows']} ({time.perf_counter() - t0:.1f} s)")
    if args.top == 80:
        chunk = 56_041_056  # Top-80 winner, 5245.217380671008 after refinement
        equipped = tuple(items[c] for c in space.decode(chunk)[0])
        t0 = time.perf_counter()
        got = engine.refine(chunk, equipped, space.talents, space.glyphs, space.picks_without, space.picks_with,
                            space.glyph_picks)
        dt = time.perf_counter() - t0
        report["refine_winner"] = {"dps": got[0], "seconds": round(dt, 3), "exact": float(got[0]).hex() == (5245.217380671008).hex()}
        print(f"refinement of the Top-80 winner on the device: {got[0]!r} in {dt:.3f} s "
              f"({'exact' if report['refine_winner']['exact'] else 'DIFFERENT'} vs the 42 h run)")
    check["ok"] = check["ok"] and full["ok"]
    if not check["ok"]:
        print("PARITY FAILED - the OpenCL route must not be used on this device.")
        (OUT / f"bench-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 1

    # single-process launch sizes (small first: Windows resets a GPU kernel that runs > 2 s)
    sizes = []
    launch = 4096
    best = None
    while launch <= (1 << 20):
        engine.bare(1000, min(launch, 4096))
        t1 = time.perf_counter()
        engine.bare(5_000_000 % space.total, launch)
        dt = time.perf_counter() - t1
        sizes.append({"rows": launch, "seconds": round(dt, 4), "rows_per_s": round(launch / dt)})
        print(f"  launch {launch:>8} rows: {dt:.3f} s -> {launch / dt:,.0f} rows/s")
        if best is None or launch / dt > best[1]:
            best = (launch, launch / dt)
        if dt > 0.25:
            break
        launch *= 4
    report["launch_sizes"] = sizes
    del engine

    procs = [int(x) for x in args.procs.split(",") if x.strip()]
    report["concurrent"] = []
    for n in procs:
        r = concurrent(args.top, n, args.rows, best[0])
        report["concurrent"].append(r)
        print(f"  {n} worker process(es): {r['rows_per_s']:,} rows/s total (worst launch {r['worst_launch_s']} s)")
    top_rate = max(r["rows_per_s"] for r in report["concurrent"])
    report["full_space_hours_scan_only"] = round(space.total / top_rate / 3600, 2)
    print(f"Top-{args.top} bare scan: ~{space.total / top_rate / 60:.1f} min at {top_rate:,} rows/s "
          f"(plus refinement of admitted chunks, also on the device: Top-80 had 825 in scan order).")
    path = OUT / f"bench-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("saved", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
