"""Re-run talents, glyphs and greedy ESC on the sextuples a finished farm result already lists.

    python tools/rescore_top.py <results.json> [--out <file>]

For every sextuple in top / top_shop / top_random / top_shop_random the refinement
(farm.score.finish_sextuple, on the exact OpenCL engine when one is available, else the CPU)
runs again with the current sims, then each list is re-sorted by the new DPS. Used after a
change of the sims' timeline keys (2026-11-12: crit, potency and luck points in the key), so
the stored best builds are scored the way a fresh run would score them. The item sweep and
the bare admission are not repeated: the lists keep their sextuples.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LISTS = ("top", "top_shop", "top_random", "top_shop_random")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("--out", default="")
    ap.add_argument("--cpu", action="store_true", help="CPU finish_sextuple instead of the OpenCL engine")
    args = ap.parse_args()
    src = Path(args.result)
    data = json.loads(src.read_text(encoding="utf-8"))
    hero, spec, top = data["hero"], data["spec"], int(data.get("top_n") or 0)
    if not top:
        import re
        top = int(re.search(r"-top(\d+)-", src.name).group(1))
    from farm.catalog import load
    from farm.runner import source_map
    from farm.score import finish_sextuple

    space, items = load(hero, spec, data.get("pool", "mixed"), None, top)
    targets = int(data["targets"])
    engine = None
    if not args.cpu:
        try:
            from farm.hybrid.mage_cl import make_engine
            engine = make_engine(hero, space, items, source_map(items), targets, spec)
            print("refinement on", engine.name, flush=True)
        except Exception as exc:
            print(f"OpenCL unavailable ({type(exc).__name__}: {exc}); CPU refinement", flush=True)
    a = (space.talents, space.glyphs, space.picks_without, space.picks_with, space.glyph_picks)
    done: dict[int, dict] = {}
    t0 = time.time()
    changed = 0
    for key in LISTS:
        for row in data.get(key) or []:
            chunk = int(row["chunk"])
            if chunk in done:
                continue
            codes = space.decode(chunk)[0]
            if [i["code"] for i in row["items"]] != list(codes):
                raise SystemExit(f"chunk {chunk} does not decode to the stored items; wrong space")
            equipped = tuple(items[c] for c in codes)
            if engine is not None:
                total, tal, gly, points, extra = engine.refine(chunk, equipped, *a)
            else:
                total, tal, gly, points, extra = finish_sextuple(hero, spec, targets, equipped, *a)
            new = dict(row)
            new.pop("place", None)
            new.update(dps=total, fights=extra + 1, points=dict(points),
                       talents=sorted(space.talent_names.get(c, c) for c in tal),
                       glyphs=sorted(space.glyph_names.get(c, c) for c in gly))
            if new["dps"] != row["dps"] or new["points"] != row["points"] or new["talents"] != row["talents"] or new["glyphs"] != row["glyphs"]:
                changed += 1
                new["previous"] = {k: row[k] for k in ("dps", "talents", "glyphs", "points")}
            done[chunk] = new
    out = dict(data)
    for key in LISTS:
        rows = sorted((done[int(r["chunk"])] for r in data.get(key) or []), key=lambda r: (-r["dps"], r["chunk"]))
        out[key] = [dict(r, place=i) for i, r in enumerate(rows, start=1)]
    out["rescored"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "source": src.name, "sextuples": len(done),
                       "changed": changed, "reason": "timeline keys hold crit, potency and luck ESC points (2026-11-12)"}
    dst = Path(args.out) if args.out else src.with_name("rescored-" + src.name)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{hero} {spec}: {len(done)} sextuples, {changed} changed, {time.time() - t0:.1f} s -> {dst}", flush=True)
    for key in ("top", "top_shop", "top_random"):
        if data.get(key):
            print(f"  {key}: {data[key][0]['dps']:.4f} -> {out[key][0]['dps']:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
