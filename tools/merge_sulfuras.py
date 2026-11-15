"""Replace the Sulfuras builds of a finished Top-150 run with a forced-Sulfuras run.

    python tools/merge_sulfuras.py HERO SPEC MAIN_DIR SULF_DIR OUT_DIR [CODE]

Every list entry of MAIN that wears CODE (default I0BR, Sulfuras) is dropped (it was scored with
the old splash crit), then tools/merge_runs.py pools what is left with the forced run (every build
of SULF wears CODE) and keeps the best 20 per list.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_runs import LISTS, main as merge  # noqa: E402


def one(run_dir: str) -> str:
    found = sorted(glob.glob(str(Path(run_dir) / "results" / "*.json")))
    if len(found) != 1:
        raise SystemExit(f"{run_dir}: {len(found)} result files")
    return found[0]


def run(hero: str, spec: str, main_dir: str, sulf_dir: str, out_dir: str, code: str = "I0BR") -> None:
    main_file, sulf_file = one(main_dir), one(sulf_dir)
    data = json.loads(Path(main_file).read_text(encoding="utf-8"))
    if (data["hero"], data["spec"]) != (hero, spec):
        raise SystemExit("main run is another hero/spec")
    dropped = {}
    for key in LISTS:
        keep = [e for e in data.get(key) or [] if code not in {i["code"] for i in e["items"]}]
        dropped[key] = len(data.get(key) or []) - len(keep)
        data[key] = keep
    sulf = json.loads(Path(sulf_file).read_text(encoding="utf-8"))
    bad = [e for k in LISTS for e in sulf.get(k) or [] if code not in {i["code"] for i in e["items"]}]
    if bad:
        raise SystemExit(f"forced run has builds without {code}")
    out = Path(out_dir) / "results"
    out.mkdir(parents=True, exist_ok=True)
    filtered = Path(out_dir) / f"main-without-{code}.json"
    data["filtered_from"] = str(Path(main_file).as_posix())
    filtered.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(hero, spec, "dropped from main:", dropped)
    merge(str(out / "merged-top150-sulfuras.json"), str(filtered), sulf_file)


if __name__ == "__main__":
    if len(sys.argv) < 6:
        raise SystemExit(__doc__)
    run(*sys.argv[1:])
