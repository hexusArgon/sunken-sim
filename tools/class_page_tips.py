"""Write TALENTS, GLYPHS, ITEM_TIPS, NAME_TIPS for a sim-html page from the map tooltips.

    python tools/class_page_tips.py berserker headhunter poison fury

NAME_TIPS (damage sources and buttons): the hero ability's learn tooltip from war3mapSkin.w3a, else the
talent of that name, else the same name on another page (item procs such as Sulfuras, Elemental Orb).
Talents: every farm talent of the listed specs (labels = farm.catalog talent names, as in the runs).
Glyphs: the farm glyphs. Items: every item shown in docs/sim-html/sources/<hero>-<spec>-enriched.json.
Tips are plain text from war3mapSkin.w3t (utub); colors are put back afterwards by
docs/sim-html/build/wc3col (python corpus.py && python apply.py ../../sources/<hero>.tsx).
Replaces the four constants in docs/sim-html/sources/<hero>.tsx in place.
"""
from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from farm.catalog import load  # noqa: E402
from sunken_sim import library as L  # noqa: E402

SRC = ROOT / "docs" / "sim-html" / "sources"


def clean(t: str) -> str:
    return re.sub(r"\|c[0-9a-fA-F]{8}", "", t).replace("|r", "").replace("|R", "").replace("|n", "\n").strip()


# A damage source named after a mechanic that the map describes inside another ability's tooltip.
ALIASES = {"Surge of Toxins": "Venomous Axes"}


def _ability_tips(strings) -> dict[str, str]:
    """Hero ability name -> learn tooltip (arut, all levels) from war3mapSkin.w3a, raw with colors."""
    blob = L._extract(L.MAP_PATH, "war3mapSkin.w3a")
    pos = 0

    def i32():
        nonlocal pos
        v = struct.unpack_from("<i", blob, pos)[0]
        pos += 4
        return v

    ver = i32()
    out: dict[str, str] = {}
    for _table in range(2):
        for _ in range(i32()):
            pos += 8
            mods: dict[tuple[str, int], object] = {}
            for _set in range(i32() if ver >= 3 else 1):
                if ver >= 3:
                    i32()
                for _m in range(i32()):
                    mid = blob[pos:pos + 4].decode("latin1")
                    pos += 4
                    kind = i32()
                    level = i32()
                    i32()
                    if kind == 0:
                        val = i32()
                    elif kind in (1, 2):
                        val = struct.unpack_from("<f", blob, pos)[0]
                        pos += 4
                    else:
                        end = blob.index(b"\0", pos)
                        val = blob[pos:end].decode("utf-8", "replace")
                        pos = end + 1
                    pos += 4
                    mods[(mid, level)] = val
            name = L._resolve(str(mods.get(("anam", 0), "")), strings)
            tip = mods.get(("arut", 0))
            if name and isinstance(tip, str):
                out.setdefault(name, L._resolve(tip, strings).replace("|n", "\n").strip())
    return out


def _page_name_tips() -> dict[str, list]:
    """NAME_TIPS of the other pages (shared item procs: Sulfuras, Elemental Orb, ...)."""
    out: dict[str, list] = {}
    for f in sorted(SRC.glob("*.tsx")):
        m = re.search(r"^const NAME_TIPS: [^=]*=\s*(.*?);\s*$", f.read_text(encoding="utf-8"), re.M)
        if m:
            for k, v in json.loads(m.group(1)).items():
                out.setdefault(k, v)
    return out


def main(hero: str, specs: list[str]) -> None:
    strings = L.map_strings()
    skin = L._parse_objects(L._extract(L.MAP_PATH, "war3mapSkin.w3t"))

    def tip(code: str) -> str:
        mods = skin.get(code, {})
        return clean(L._resolve(mods["utub"][0], strings)) if "utub" in mods else ""

    talents: dict[str, str] = {}
    glyphs: dict[str, str] = {}
    codes: set[str] = set()
    names: set[str] = set()
    for spec in specs:
        space, _ = load(hero=hero, spec=spec, pool="mixed", top=150)
        for c in space.talents:
            talents.setdefault(space.talent_names[c], tip(c))
        for c in space.glyphs:
            glyphs.setdefault(space.glyph_names[c], tip(c))
        data = json.loads((SRC / f"{hero}-{spec}-enriched.json").read_text(encoding="utf-8"))
        codes |= {it["code"] for rs in data["runs"].values() for r in rs for it in r["items"]}
        names |= {n for rs in data["runs"].values() for r in rs for n, _ in r["sources"]}
        names |= {a for rs in data["runs"].values() for r in rs for _, a in r["actions"]}
    abilities = _ability_tips(strings)
    shared = _page_name_tips()
    name_tips: dict[str, list] = {}
    for n in sorted(names):
        src = ALIASES.get(n, n)
        if src in abilities:
            name_tips[n] = [src, abilities[src]]
        elif src in talents:
            name_tips[n] = [src, talents[src]]
        elif n in shared:
            name_tips[n] = shared[n]
    missing = sorted(names - set(name_tips))
    if missing:
        print("no tooltip for", missing)
    consts = {
        "TALENTS": "const TALENTS: TipTable = [\n" + "".join(
            f"  {json.dumps([n, t, True], ensure_ascii=False)},\n" for n, t in talents.items()) + "];",
        "GLYPHS": "const GLYPHS: TipTable = [\n" + "".join(
            f"  {json.dumps([n, t, True], ensure_ascii=False)},\n" for n, t in sorted(glyphs.items())) + "];",
        "ITEM_TIPS": "const ITEM_TIPS: Record<string, string> = "
                     + json.dumps({c: tip(c) for c in sorted(codes)}, ensure_ascii=False) + ";",
        "NAME_TIPS": "const NAME_TIPS: Record<string, [string, string]> = "
                     + json.dumps(name_tips, ensure_ascii=False) + ";",
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
