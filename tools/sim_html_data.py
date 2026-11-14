"""Copy docs/sim-html/sources/<hero>-<spec>-enriched.json into the page data constants of docs/sim-html/sources/<hero>.tsx.

    python tools/sim_html_data.py            # every page
    python tools/sim_html_data.py mage druid

The enriched JSON comes from tools/mage_html_enrich.py, tools/priest_html_enrich.py or
tools/class_html_enrich.py. The page UI is shared (docs/sim-html/sources/sims-ui.tsx); a page file
holds TALENTS, GLYPHS, one <SPEC>_DATA constant per spec, ITEM_TIPS and NAME_TIPS. Then build:
    cd docs/sim-html/build && node build.mjs && python build_index.py ..
Shadow keeps runs.lantern (tools/priest_html_lantern_enrich.py) from the JSON as it is.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "docs" / "sim-html" / "sources"
PAGES = {
    "mage": {"fire": "DATA", "frost": "FROST_DATA", "arcane": "ARCANE_DATA"},
    "priest": {"shadow": "DATA", "discipline": "DISCIPLINE_DATA", "holy": "HOLY_DATA"},
    "shaman": {"restoration": "RESTORATION_DATA", "enhancement": "ENHANCEMENT_DATA", "elemental": "ELEMENTAL_DATA"},
    "paladin": {"retribution": "RETRIBUTION_DATA", "protection": "PROTECTION_DATA", "holy": "HOLY_DATA"},
    "druid": {"restoration": "RESTORATION_DATA", "balance": "BALANCE_DATA"},
    "berserker": {"headhunter": "HEADHUNTER_DATA", "poison": "POISON_DATA", "fury": "FURY_DATA"},
    "hunter": {"marksmanship": "MARKSMANSHIP_DATA", "beast_mastery": "BEAST_MASTERY_DATA", "survival": "SURVIVAL_DATA"},
}


def main(pages: list[str]) -> None:
    for page in pages or list(PAGES):
        path = SRC / f"{page}.tsx"
        text = path.read_text(encoding="utf-8")
        tips = json.loads(re.search(r"^const ITEM_TIPS: [^=]*=\s*(.*?);\s*$", text, re.M).group(1))
        for spec, name in PAGES[page].items():
            data = json.loads((SRC / f"{page}-{spec}-enriched.json").read_text(encoding="utf-8"))
            line = f"const {name}: Data = " + json.dumps(data, ensure_ascii=False) + ";"
            text, n = re.subn(r"^const " + name + r": Data = [^\n]*;$", lambda m: line, text, count=1, flags=re.M)
            if n != 1:
                raise SystemExit(f"{path.name}: no const {name}")
            missing = sorted({i["code"] for rs in data["runs"].values() for r in rs for i in r["items"]} - set(tips))
            if missing:
                print(f"{page} {spec}: no ITEM_TIPS for {missing} (tooltip will be plain text)")
        path.write_text(text, encoding="utf-8")
        print("updated", path.name)


if __name__ == "__main__":
    main(sys.argv[1:])
