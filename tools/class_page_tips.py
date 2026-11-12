"""Write TALENTS, GLYPHS, ITEM_TIPS, NAME_TIPS for a sim-html page from the map tooltips.

    python tools/class_page_tips.py berserker headhunter poison fury

Talents: every farm talent of the listed specs (labels = farm.catalog talent names, as in the runs).
Glyphs: the farm glyphs. Items: every item shown in docs/sim-html/sources/<hero>-<spec>-enriched.json.
Tips are plain text from war3mapSkin.w3t (utub); colors are put back afterwards by
docs/sim-html/build/wc3col (python corpus.py && python apply.py ../../sources/<hero>.tsx).
Replaces the four constants in docs/sim-html/sources/<hero>.tsx in place.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from farm.catalog import load  # noqa: E402
from sunken_sim import library as L  # noqa: E402

SRC = ROOT / "docs" / "sim-html" / "sources"


def clean(t: str) -> str:
    return re.sub(r"\|c[0-9a-fA-F]{8}", "", t).replace("|r", "").replace("|R", "").replace("|n", "\n").strip()


def main(hero: str, specs: list[str]) -> None:
    strings = L.map_strings()
    skin = L._parse_objects(L._extract(L.MAP_PATH, "war3mapSkin.w3t"))

    def tip(code: str) -> str:
        mods = skin.get(code, {})
        return clean(L._resolve(mods["utub"][0], strings)) if "utub" in mods else ""

    talents: dict[str, str] = {}
    glyphs: dict[str, str] = {}
    codes: set[str] = set()
    for spec in specs:
        space, _ = load(hero=hero, spec=spec, pool="mixed", top=150)
        for c in space.talents:
            talents.setdefault(space.talent_names[c], tip(c))
        for c in space.glyphs:
            glyphs.setdefault(space.glyph_names[c], tip(c))
        data = json.loads((SRC / f"{hero}-{spec}-enriched.json").read_text(encoding="utf-8"))
        codes |= {it["code"] for rs in data["runs"].values() for r in rs for it in r["items"]}
    consts = {
        "TALENTS": "const TALENTS: TipTable = [\n" + "".join(
            f"  {json.dumps([n, t, True], ensure_ascii=False)},\n" for n, t in talents.items()) + "];",
        "GLYPHS": "const GLYPHS: TipTable = [\n" + "".join(
            f"  {json.dumps([n, t, True], ensure_ascii=False)},\n" for n, t in sorted(glyphs.items())) + "];",
        "ITEM_TIPS": "const ITEM_TIPS: Record<string, string> = "
                     + json.dumps({c: tip(c) for c in sorted(codes)}, ensure_ascii=False) + ";",
        "NAME_TIPS": "const NAME_TIPS: Record<string, [string, string]> = {};",
    }
    path = SRC / f"{hero}.tsx"
    text = path.read_text(encoding="utf-8")
    for name, block in consts.items():
        text, n = re.subn(r"^const " + name + r":[^\n]*(?:\n(?!const |export )[^\n]*)*", lambda m: block, text, count=1, flags=re.M)
        if n != 1:
            raise SystemExit(f"{path.name}: no const {name}")
    path.write_text(text, encoding="utf-8")
    print("updated", path.name, len(talents), "talents", len(glyphs), "glyphs", len(codes), "items")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
