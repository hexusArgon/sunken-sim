"""Add the Soul Lantern (I06D) forced run to priest-shadow-enriched.json as runs.lantern."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from priest_html_enrich import OUT, enrich  # noqa: E402

LANTERN = ROOT / "farm-data-shadow-lantern" / "results" / "local-esc-lantern-priest-shadow-mixed-top80-5-0-23049557.json"


def main() -> None:
    farm = json.loads(LANTERN.read_text(encoding="utf-8"))
    data = json.loads(OUT.read_text(encoding="utf-8"))
    rows = []
    for i, entry in enumerate(farm["top"][:10]):
        t0 = time.time()
        row = enrich(entry)
        rows.append(row)
        print(f"lantern {i + 1}: farm {row['farm_dps']} resim {row['dps']} mana {row['manaLeft']}% bind {row['bound_spell']} ({time.time() - t0:.1f}s)", flush=True)
    data["runs"]["lantern"] = rows
    data["lantern_file"] = str(LANTERN.relative_to(ROOT)).replace("\\", "/")
    data["lantern_done"] = farm["done"]
    data["lantern_errors"] = farm["errors"]
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()