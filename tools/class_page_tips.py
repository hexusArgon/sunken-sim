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
ALIASES = {"Surge of Toxins": "Venomous Axes",
           # Monk: Xuen stance and Windwalker attacks are described in Power Strike, Wrath of Xuen in Celestial Wrath
           "Celestial Attack (Xuen)": "Power Strike", "White Tiger": "Power Strike", "Wrath of Xuen": "Celestial Wrath",
           # Necromancer: skeletons come from Tombstone / Raise Dead, the Lords from the Lord of the Dead talent
           "Скелеты (Raise Dead/Tombstone)": "Tombstone", "Executor (Lord)": "Lord of the Dead",
           "Mage (Lord)": "Lord of the Dead", "Executor (эхо)": "Lord of the Dead"}
# Hero abilities by rawcode where the name is ambiguous in war3mapSkin.w3a (A06B "Steel Trap" carries another
# hero's learn tooltip there): the level-1 tooltip (aub1) of that ability.
# Hero unit types per page: their hero abilities (uhab) and unit abilities (uabi) in war3map.w3u give the ability
# codes of this class, so a name shared with another hero's ability (Metamorphosis, Cleansing Fire, Steel Trap)
# resolves to this hero's own tooltip (level-1 aub1, else the learn tooltip).
HERO_UNITS = {
    "hunter": ("H001",),
    "death_knight": ("U002",),
    "demon_hunter": ("E00A", "E00B"),
    "dragon_sentinel": ("O00P", "O007", "O015", "O01Q"),
    "feral_druid": ("O00R", "O00J", "O01B"),
    "monk": ("N04R",),
    "necromancer": ("O00H",),
}
BY_CODE = {
    "hunter": {"Steel Trap": "A06B", "Serpent Sting": "A0E3", "Serpent Sting (тики)": "A0E3", "Multi-Shot": "A01V",
               "Split Shot": "A01V", "Bestial Wrath": "A03X"},
    # spec-swapped abilities that are not in the hero unit's lists
    "dragon_sentinel": {"Cleansing Fire": "A0OO", "Cleansing Fire (от лечения)": "A0OO"},
    "demon_hunter": {"Demon Spikes": "A0RH"},
}


def _ability_tips(strings, by_code: dict | None = None, file: str = "war3mapSkin.w3a") -> dict[str, str]:
    """Hero ability name -> learn tooltip (arut, all levels) from war3mapSkin.w3a, raw with colors."""
    blob = L._extract(L.MAP_PATH, file)
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
            orig = blob[pos:pos + 4].decode("latin1")
            new = blob[pos + 4:pos + 8].decode("latin1")
            code = orig if new == "\0\0\0\0" else new
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
                text = L._resolve(tip, strings).replace("|n", "\n").strip()
                out.setdefault(name, text)
                if by_code is not None:
                    ub = mods.get(("aub1", 1)) or mods.get(("aub1", 0))
                    ub = L._resolve(ub, strings).replace("|n", "\n").strip() if isinstance(ub, str) else ""
                    by_code[code] = (name, text, ub)
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
    codes_tips: dict = {}
    abilities = _ability_tips(strings, codes_tips)
    shared = _page_name_tips()
    name_tips: dict[str, list] = {}
    by_code = BY_CODE.get(hero, {})
    own: dict[str, list] = {}
    if hero in HERO_UNITS:
        units = L._parse_objects(L._extract(L.MAP_PATH, "war3map.w3u"))
        for unit in HERO_UNITS[hero]:
            mods = units.get(unit, {})
            for field in ("uhab", "uabi"):
                for code in str((mods.get(field) or [""])[0] or "").split(","):
                    if code in codes_tips:
                        name, learn, level1 = codes_tips[code]
                        own.setdefault(name, [name, level1 or learn])
    for n in sorted(names):
        src = ALIASES.get(n, n)
        if src not in abilities and src not in talents and " (" in src:
            src = src.split(" (")[0]  # "Burnout (пассив)" -> "Burnout"
        if n in by_code and by_code[n] in codes_tips:
            name, learn, level1 = codes_tips[by_code[n]]
            name_tips[n] = [name, level1 or learn]
        elif src in own:
            name_tips[n] = own[src]
        elif src in abilities:
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
