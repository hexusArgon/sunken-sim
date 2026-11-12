"""Check and time the exact OpenCL engines on this PC: Mage Frost/Arcane (and Fire), Priest Shadow/Discipline/Holy.

    .venv-dml\\Scripts\\python.exe tools\\opencl_check.py
    .venv-dml\\Scripts\\python.exe tools\\opencl_check.py --specs priest:shadow --parity 5000 --refines 10

Changes nothing in farm data.  For every spec:

1. bit-exact parity of the item-only scan against farm.score.item_dps on random
   chunks and on chunks that cover every item of the pool;
2. bit-exact parity of talent/glyph/ESC fights (Priest: simulate().dps, the
   ESC score of farm.score._priest, and fights on a replayed timeline);
3. device refinement against farm.score.finish_sextuple on random chunks (and
   the Shadow ESC winner sextuple, 3739.780235469132 since the 2026-11-12 Cosmic Horrors / luck fixes);
4. launch sizes, rows/s of 1 and N worker processes, refinement seconds, and
   an estimate for the whole Top-N space.

Writes sunken-sim-runs/opencl-dev/check-<time>.json next to the repo.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO.parent / "sunken-sim-runs" / "opencl-dev"
sys.path.insert(0, str(REPO))
os.environ.setdefault("FARM_DATA", str(OUT / "check-data"))

DEFAULT_SPECS = "mage:frost,mage:arcane,priest:shadow,priest:discipline,priest:holy"
SHADOW_WINNER = (["I00D", "I048", "I0FW", "I0JO", "I0NT", "fgrd"], 3739.780235469132)


def _load(hero, spec, top):
    from farm.catalog import load
    from farm.runner import source_map

    space, items = load(hero, spec, "mixed", None, top)
    return space, items, source_map(items)


def _child(hero, spec, top, rows, launch, barrier, queue):
    from farm.hybrid.mage_cl import make_engine

    space, items, sources = _load(hero, spec, top)
    engine = make_engine(hero, space, items, sources, 5, spec)
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


def concurrent(hero, spec, top, procs, rows, launch):
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(procs + 1)
    queue = ctx.Queue()
    ps = [ctx.Process(target=_child, args=(hero, spec, top, rows, launch, barrier, queue)) for _ in range(procs)]
    for p in ps:
        p.start()
    barrier.wait()
    t0 = time.perf_counter()
    results = [queue.get(timeout=1800) for _ in ps]
    wall = time.perf_counter() - t0
    for p in ps:
        p.join(30)
    total = sum(r[0] for r in results)
    return {"procs": procs, "rows": total, "wall_s": round(wall, 2), "rows_per_s": round(total / wall),
            "worst_launch_s": round(max(r[2] for r in results), 3)}


def _coverage_rows(space, need_each, seed):
    rng = random.Random(seed)
    need = {p.code: 0 for p in space.pieces}
    rows = []
    while any(v < need_each for v in need.values()) and len(rows) < 20000:
        i = rng.randrange(space.total)
        codes = set(space.decode(i)[0])
        if any(need[c] < need_each for c in codes):
            rows.append(i)
            for c in codes:
                need[c] += 1
    return rows


def check_spec(hero, spec, args, device):
    from farm.hybrid import mage_cl
    from farm.hybrid import priest_cl

    out = {"hero": hero, "spec": spec}
    space, items, sources = _load(hero, spec, args.top)
    t0 = time.perf_counter()
    engine = mage_cl.make_engine(hero, space, items, sources, 5, spec, device=device)
    out["build_s"] = round(time.perf_counter() - t0, 2)
    out["chunks"] = space.total
    tag = f"{hero} {spec}"
    print(f"\n== {tag}: kernel built in {out['build_s']} s on {engine.name}; Top-{args.top} chunks {space.total:,}", flush=True)
    mod = mage_cl.engine_module(engine)

    t0 = time.perf_counter()
    rows = mage_cl.sample(space, args.parity, 2026) + _coverage_rows(space, 5, 2027)
    check = mod.parity(engine, space, items, sources, 5, rows)
    out["parity_bare"] = check
    print(f"   item-only scan: {check['rows']} chunks (every item >= 5 times), mismatches {check['mismatches']}, "
          f"CPU-oracle rows {check['status_rows']} ({time.perf_counter() - t0:.1f} s)", flush=True)
    builds = mod.random_builds(space, max(200, args.parity // 2), 2028)
    t0 = time.perf_counter()
    if hero == "priest":
        parts = {"simulate": priest_cl.parity_full(engine, space, items, 5, builds, 0),
                 "esc_score": priest_cl.parity_full(engine, space, items, 5, builds, 1),
                 "timeline_replay": priest_cl.parity_timeline(engine, space, items, 5, builds, 2029)}
    elif hero in ("shaman", "paladin", "druid", "berserker", "death_knight", "demon_hunter", "dragon_sentinel"):
        parts = {"simulate": mod.parity_full(engine, space, items, 5, builds),
                 "timeline_replay": mod.parity_full(engine, space, items, 5, builds, 2029)}
    else:
        parts = {"simulate": mage_cl.parity_full(engine, space, items, 5, builds)}
    out["parity_fights"] = parts
    bad = sum(p["mismatches"] for p in parts.values())
    print(f"   talent/glyph/ESC fights: {sum(p['rows'] for p in parts.values())} ({', '.join(parts)}), "
          f"mismatches {bad} ({time.perf_counter() - t0:.1f} s)", flush=True)

    # device refinement against finish_sextuple
    from farm.score import finish_sextuple

    chunks = mage_cl.sample(space, args.refines, 2030)
    known = None
    if (hero, spec) == ("priest", "shadow"):
        try:
            known = priest_cl.find_chunk(space, SHADOW_WINNER[0])
            chunks = [known] + chunks
        except KeyError:
            pass
    refine = []
    for chunk in chunks:
        equipped = tuple(items[c] for c in space.decode(chunk)[0])
        a = (space.talents, space.glyphs, space.picks_without, space.picks_with, space.glyph_picks)
        t1 = time.perf_counter()
        got = engine.refine(chunk, equipped, *a)
        gpu_s = time.perf_counter() - t1
        t1 = time.perf_counter()
        if hero == "priest":
            want = priest_cl.finish_reference(spec, 5, equipped, space)
        elif hero in ("shaman", "paladin", "druid", "berserker", "death_knight", "demon_hunter", "dragon_sentinel"):
            from farm.hybrid import class_cl

            want = class_cl.finish_reference(hero, spec, 5, equipped, space)
        else:
            want = finish_sextuple(hero, spec, 5, equipped, *a)
        cpu_s = time.perf_counter() - t1
        same = (float(got[0]).hex() == float(want[0]).hex() and tuple(got[1]) == tuple(want[1])
                and tuple(got[2]) == tuple(want[2]) and got[3] == want[3] and got[4] == want[4])
        row = {"chunk": chunk, "dps": got[0], "exact": same, "gpu_s": round(gpu_s, 3), "cpu_s": round(cpu_s, 3)}
        if chunk == known:
            row["stored_winner"] = SHADOW_WINNER[1]
            row["exact"] = same and got[0] == SHADOW_WINNER[1]
        refine.append(row)
    out["refine"] = refine
    ok_ref = all(r["exact"] for r in refine)
    gpu_mean = sum(r["gpu_s"] for r in refine) / max(1, len(refine))
    cpu_mean = sum(r["cpu_s"] for r in refine) / max(1, len(refine))
    print(f"   refinement (talents+glyphs+30 ESC steps): {len(refine)} sextuples, "
          f"{'all exact' if ok_ref else 'DIFFERENT'}; device {gpu_mean:.2f} s vs CPU {cpu_mean:.2f} s each"
          + (f"; stored Shadow winner {refine[0]['dps']!r}" if known is not None else ""), flush=True)
    out["ok"] = check["ok"] and bad == 0 and ok_ref
    if not out["ok"]:
        print(f"   PARITY FAILED for {tag}: the OpenCL route must not be used for it on this device.", flush=True)
        return out

    sizes = []
    launch = 4096
    best = None
    while launch <= (1 << 20):
        engine.bare(1000, min(launch, 4096))
        t1 = time.perf_counter()
        engine.bare(5_000_000 % space.total, launch)
        dt = time.perf_counter() - t1
        sizes.append({"rows": launch, "seconds": round(dt, 4), "rows_per_s": round(launch / dt)})
        if best is None or launch / dt > best[1]:
            best = (launch, launch / dt)
        if dt > 0.25:
            break
        launch *= 4
    out["launch_sizes"] = sizes
    print("   launches: " + ", ".join(f"{s['rows']}: {s['seconds']:.3f} s" for s in sizes), flush=True)
    del engine
    out["concurrent"] = []
    for n in [int(x) for x in args.procs.split(",") if x.strip()]:
        r = concurrent(hero, spec, args.top, n, args.rows, best[0])
        out["concurrent"].append(r)
        print(f"   {n} worker process(es): {r['rows_per_s']:,} rows/s (worst launch {r['worst_launch_s']} s)", flush=True)
    rate = max([r["rows_per_s"] for r in out["concurrent"]] or [round(best[1])])
    out["scan_minutes"] = round(space.total / rate / 60, 1)
    print(f"   whole Top-{args.top} item-only scan ~{out['scan_minutes']} min at {rate:,} rows/s "
          f"(+ refinement of the admitted chunks, {gpu_mean:.2f} s each)", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", default=DEFAULT_SPECS, help="comma list of hero:spec (mage:fire also works)")
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--parity", type=int, default=1500, help="random chunks checked against the Python sim")
    ap.add_argument("--refines", type=int, default=3, help="random sextuples refined on the device and on the CPU")
    ap.add_argument("--procs", default="1,4")
    ap.add_argument("--rows", type=int, default=300000, help="rows per process in the throughput test")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "top": args.top, "python": sys.version, "specs": []}

    from farm.hybrid.mage_cl import _import_cl, pick_device

    cl = _import_cl()
    print("OpenCL devices:")
    for platform in cl.get_platforms():
        for d in platform.get_devices():
            print(f"  {d.name.strip()} | {platform.name.strip()} | driver {d.driver_version} | "
                  f"fp64={'cl_khr_fp64' in d.extensions} | CUs={d.max_compute_units}")
    device = pick_device(cl)
    report["device"] = device.name.strip()
    print("chosen:", report["device"], flush=True)
    for item in [s.strip() for s in args.specs.split(",") if s.strip()]:
        hero, spec = item.split(":")
        try:
            report["specs"].append(check_spec(hero, spec, args, device))
        except Exception as exc:
            import traceback

            traceback.print_exc()
            report["specs"].append({"hero": hero, "spec": spec, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        path = OUT / f"check-{report['started'].replace(':', '').replace(' ', '-')}.json"
        path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\nsummary:")
    for r in report["specs"]:
        print(f"  {r['hero']:>6} {r['spec']:<10} {'EXACT' if r.get('ok') else 'FAILED'}"
              + (f"  scan ~{r['scan_minutes']} min" if r.get("scan_minutes") is not None else "")
              + (f"  {r['error']}" if r.get("error") else ""))
    print("saved", path)
    return 0 if all(r.get("ok") for r in report["specs"]) else 1


if __name__ == "__main__":
    sys.exit(main())
