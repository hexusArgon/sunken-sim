"""GPU run time behind every sim-html spec page -> docs/sim-html/sources/run_times.json.

    python tools/sim_run_times.py [RUNS_DIR]

For each docs/sim-html/sources/<hero>-<spec>-enriched.json the farm result it was built from is
followed back to its run folders (merged results: every input of "merged_from"; a filtered main run:
its "filtered_from"), and the wall time of each run is summed (runtime.json "wall_hours", the time of
the last process). Runs that were stopped and resumed add their earlier segments from RESUMED.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "sim-html" / "sources"

# Earlier segments of resumed runs (minutes), read from the queue logs in sunken-sim-runs/opencl-dev.
RESUMED = {
    # sulf-monk-necro-1114.log: "== monk windwalker" 15.11 4:52:09; the PC was switched off after the last log write
    # at 5:55:34 (file time), resumed 6:28:41 from the checkpoint
    "monk-windwalker-opencl-top150-gate50-1114": (63.42, False),
    # top150-all-1113.log: "== mage frost" 14.11 1:33:06 -> exit 1:36:34, resumed 1:39:36
    "mage-frost-opencl-top150-gate50-1113": (3.47, False),
    # started 13.11 19:05:44, stopped with no log line at 4 386 111 488 of 14 659 159 858 chunks, resumed 23:55;
    # the resumed segment did the other 10 273 048 370 in 14.6 min -> the first one is estimated pro rata.
    "demon_hunter-devourer-opencl-top150-gate50-1113": (14.58 * 4386111488 / 10273048370, True),
}


def run_dir(runs: Path, path: str) -> Path:
    p = Path(path.replace("\\", "/"))
    parts = p.parts
    i = max(i for i, part in enumerate(parts) if part == "results") if "results" in parts else len(parts) - 1
    return runs / parts[i - 1]


def inputs(runs: Path, result: Path) -> list[Path]:
    data = json.loads(result.read_text(encoding="utf-8"))
    if data.get("filtered_from"):
        return [run_dir(runs, data["filtered_from"].split("sunken-sim-runs/")[-1])]
    if data.get("merged_from"):
        out = []
        for p in data["merged_from"]:
            q = Path(p.replace("\\", "/"))
            q = q if q.is_absolute() and q.exists() else runs / p.split("sunken-sim-runs/")[-1]
            if not q.exists():
                q = result.parent / Path(p).name if (result.parent / Path(p).name).exists() else result.parent.parent / Path(p).name
            out += inputs(runs, q)
        return out
    return [result.parent.parent]


def main(runs: Path) -> None:
    out = {}
    for f in sorted(SRC.glob("*-enriched.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        ff = d["farm_file"].replace("\\", "/")
        result = runs / ff.split("sunken-sim-runs/")[-1]
        parts, estimated = [], False
        for r in inputs(runs, result):
            rt = json.loads((r / "runtime.json").read_text(encoding="utf-8"))
            if rt.get("status") != "complete":
                raise SystemExit(f"{r.name}: run is {rt.get('status')}")
            minutes = 60.0 * float(rt["wall_hours"])
            extra, est = RESUMED.get(r.name, (0.0, False))
            estimated |= est
            parts.append({"run": r.name, "minutes": round(minutes + extra, 1)})
        out[f.name[:-len("-enriched.json")]] = {"minutes": round(sum(p["minutes"] for p in parts), 1),
                                           "estimated": estimated, "runs": parts}
    (SRC / "run_times.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in out.items():
        print(f"{k:28s} {v['minutes']:7.1f} min{' ~' if v['estimated'] else ''}  " + " + ".join(p["run"] for p in v["runs"]))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "sunken-sim-runs")
