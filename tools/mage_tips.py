"""Dump in-game tooltips for mage.html (Fire): talents, glyphs, items used in runs.

Modeled on tools/druid_tips.py. Writes logs/mage_fire_tips.json (plain text;
colors are restored later by docs/sim-html/build/wc3col/apply.py).
"""
import json, os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FARM_DATA", str(ROOT / "farm-data-mage-fire"))
from farm.catalog import load
from sunken_sim import library as L

def clean(t):
    t = re.sub(r"\|c[0-9a-fA-F]{8}", "", t).replace("|r", "").replace("|R", "").replace("|n", "\n")
    return t.strip()

space, _ = load(hero="mage", spec="fire", pool="mixed", top=80)
strings = L.map_strings()
skin = L._parse_objects(L._extract(L.MAP_PATH, "war3mapSkin.w3t"))
def tip(code):
    mods = skin.get(code, {})
    if "utub" not in mods:
        return None
    return clean(L._resolve(mods["utub"][0], strings))
enr = json.loads((ROOT / "docs/sim-html/sources/mage-fire-enriched.json").read_text(encoding="utf-8"))
codes = sorted({it["code"] for runs in enr["runs"].values() for r in runs for it in r["items"]})
out = {
    "talents": {space.talent_names[c]: tip(c) for c in space.talents},
    "glyphs": {space.glyph_names[c]: tip(c) for c in space.glyphs},
    "items": {c: tip(c) for c in codes},
}
(ROOT / "logs").mkdir(exist_ok=True)
(ROOT / "logs" / "mage_fire_tips.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok", len(out["items"]), [k for k, v in {**out["talents"], **out["glyphs"], **out["items"]}.items() if not v])