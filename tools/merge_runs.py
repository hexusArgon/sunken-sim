"""Merge finished farm results of one hero/spec into one result file (top-20 per list).

    python tools/merge_runs.py OUT.json MAIN.json EXTRA.json [EXTRA.json ...]

Lists top / top_shop_random / top_shop / top_random of every input are pooled, one entry per item set
(sorted rawcodes): a later input wins over an earlier one (an extra run made with a newer sim replaces
the main run's value for the same items), then the best LIMIT by dps are kept and renumbered.
Header fields come from MAIN; "done" sums the inputs; "merged_from" lists them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LISTS = ("top", "top_shop_random", "top_shop", "top_random")
LIMIT = 20


def main(out: str, *inputs: str) -> None:
    runs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in inputs]
    base = dict(runs[0])
    for r in runs[1:]:
        if (r["hero"], r["spec"], r["targets"]) != (base["hero"], base["spec"], base["targets"]):
            raise SystemExit("inputs are not one hero/spec/targets")
    for key in LISTS:
        pool: dict[tuple, dict] = {}
        for r in runs:
            for entry in r.get(key) or []:
                pool[tuple(sorted(i["code"] for i in entry["items"]))] = entry
        best = sorted(pool.values(), key=lambda e: -e["dps"])[:LIMIT]
        base[key] = [dict(e, place=i + 1) for i, e in enumerate(best)]
    base["done"] = sum(int(r["done"]) for r in runs)
    base["errors"] = sum(int(r["errors"]) for r in runs)
    base["stopped"] = any(r["stopped"] for r in runs)
    base["merged_from"] = [str(Path(p).as_posix()) for p in inputs]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(base, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out, {k: len(base[k]) for k in LISTS})


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
