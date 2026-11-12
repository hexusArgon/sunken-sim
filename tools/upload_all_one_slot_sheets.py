"""Build (and optionally upload) every one-slot tab of the Sunken City spreadsheet from extract/*.json.

Layout per tab mirrors the existing Tables on the sheet:
    items    A.. (Предмет, Описание, Код, Источник, <spec> DPS...)  "Без предмета" pinned first
    talents  at TALENT_COL (Талант, Описание, [Код], <spec> DPS...), sorted by first spec, "Без таланта" last
    blank row, then glyphs in the same columns (Глиф, Описание, [Код], <spec> DPS...), "Без глифа" last
Priest/Paladin/Mage come from extract/one-slot-classes.json; their glyphs are measured here
(cached in extract/one-slot-classes-glyphs.json, use --remeasure to redo).

    python tools/upload_all_one_slot_sheets.py --html logs/sheets_html   # write HTML blocks + manifest (paste via pasteData)
    python tools/upload_all_one_slot_sheets.py                           # upload with ~/Documents/keys/google-sheets-token.json
    python tools/upload_all_one_slot_sheets.py --tabs "Priest,Mage"      # upload only these tabs
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "extract"))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import load_items

SPREADSHEET = "1Cnn9KJfwdI9pKEZMR_6T-xKCO674TsqYP5Bb4bsCj6w"
EXTRACT = ROOT / "extract"

# tab: (json file or None for one-slot-classes, talents column index, talents have Код, glyphs have Код)
TABS = {
    "Berserker": ("berserker-one-slot.json", 8, False, False),
    "Death Knight": ("death_knight-one-slot.json", 8, False, False),
    "Demon Hunter": ("demon_hunter-one-slot.json", 8, False, False),
    "Dragon Sentinel": ("dragon_sentinel-one-slot.json", 8, False, False),
    "Druid": ("druid-one-slot.json", 7, False, True),
    "Feral Druid": ("feral-druid-one-slot.json", 8, False, True),
    "Hunter": ("hunter-one-slot.json", 8, False, False),
    "Mage": (None, 8, False, False),
    "Monk": ("monk-one-slot.json", 8, False, False),
    "Necromancer": ("necromancer-one-slot.json", 8, False, False),
    "Paladin": (None, 8, False, False),
    "Priest": (None, 8, False, False),
    "Rogue": ("rogue-one-slot.json", 8, False, False),
    "Shaman": ("shaman-one-slot.json", 8, False, True),
    "Siren": ("siren-one-slot.json", 8, False, False),
    "Tidewarrior": ("tidewarrior-one-slot.json", 7, False, False),
    "Tinker": ("tinker-one-slot.json", 8, False, False),
    "Warlock": ("warlock-one-slot.json", 8, False, False),
    "Warrior": ("warrior-one-slot.json", 8, False, False),
    "Windmaster": ("windmaster-one-slot.json", 8, False, False),
    "Witch Doctor": ("witch_doctor-one-slot.json", 8, False, False),
}
TALENT_MODULE = {"Shaman": "shaman", "Druid": "druid", "Feral Druid": "feral_druid"}
BARE_ITEM, BARE_TALENT, BARE_GLYPH = "Без предмета", "Без таланта", "Без глифа"

ITEMS = load_items()
BY_CODE = {item.rawcode: item for item in ITEMS}
BY_NAME = {}
for _item in ITEMS:
    BY_NAME.setdefault(_item.name, _item)


def plain(text: str) -> str:
    cleaned = re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", text or "")
    return cleaned.replace("|n", "\n").replace("\r\n", "\n").replace("\r", "\n").strip()


def tip(code: str = "", name: str = "") -> str:
    item = BY_CODE.get(code) if code else None
    if item is None and name:
        item = BY_NAME.get(name)
    return plain(item.tip) if item else ""


def _cols(header: list) -> dict:
    return {
        "code": header.index("Код") if "Код" in header else None,
        "source": header.index("Источник") if "Источник" in header else None,
        "dps": [i for i, h in enumerate(header) if str(h).endswith(" DPS")],
        "bind": [i for i, h in enumerate(header) if str(h).startswith("Привязка")],
    }


def _first(row) -> float:
    return float(row[0]) if row and row[0] != "" else -1e9


def generic_blocks(tab: str, file: str, talent_code: bool, glyph_code: bool):
    saved = json.loads((EXTRACT / file).read_text(encoding="utf-8"))
    head = saved["items"][0]
    c = _cols(head)
    specs = [head[i][: -len(" DPS")] for i in c["dps"]]
    items, bare = [], None
    for row in saved["items"][1:]:
        name = row[0]
        code = row[c["code"]] if c["code"] is not None else ""
        source = row[c["source"]] if c["source"] is not None else ""
        dps = [row[i] for i in c["dps"]]
        if name == BARE_ITEM:
            bare = [name, "", "", "", *dps]
            continue
        binds = [row[i] for i in c["bind"] if i < len(row) and row[i]]
        if binds and len(set(binds)) == 1:
            name = f"{name} ({binds[0]})"
        elif binds:
            name = f"{name} ({' / '.join(binds)})"
        items.append([name, tip(code, row[0]), code, source, *dps])
    items.sort(key=lambda r: (-_first(r[4:]), r[0]))
    item_rows = [["Предмет", "Описание", "Код", "Источник", *[f"{s} DPS" for s in specs]]]
    if bare:
        item_rows.append(bare)
    item_rows += items

    talents_map = {}
    if tab in TALENT_MODULE:
        mod = __import__(f"sunken_sim.{TALENT_MODULE[tab]}", fromlist=["TALENTS"])
        talents_map = {title: code for code, title in mod.TALENTS.items()}

    def small(block: str, bare_name: str, with_code: bool, first_title: str):
        rows = saved[block]
        h = rows[0]
        cc = _cols(h)
        names = [r[0] for r in rows[1:]]
        dup = {n for n in names if names.count(n) > 1}
        body, tail = [], None
        for r in rows[1:]:
            name = r[0]
            code = r[cc["code"]] if cc["code"] is not None else talents_map.get(name, "")
            dps = [r[i] for i in cc["dps"]]
            if name == bare_name:
                tail = [name, "", *([""] if with_code else []), *dps]
                continue
            label = f"{name} ({code})" if name in dup and code else name
            body.append([label, tip(code, name), *([code] if with_code else []), *dps])
        off = 3 if with_code else 2
        body.sort(key=lambda r: (-_first(r[off:]), r[0]))
        out = [[first_title, "Описание", *(["Код"] if with_code else []), *[f"{s} DPS" for s in specs]], *body]
        if tail:
            out.append(tail)
        return out

    talent_rows = small("talents", BARE_TALENT, talent_code, "Талант")
    glyph_rows = small("glyphs", BARE_GLYPH, glyph_code, "Глиф") if "glyphs" in saved else None
    return specs, item_rows, talent_rows, glyph_rows


CLASS_FIGHTS = {"Priest": "fight_priest", "Paladin": "fight_paladin", "Mage": "fight_mage"}


def class_glyphs(remeasure: bool) -> dict:
    cache = EXTRACT / "one-slot-classes-glyphs.json"
    classes = json.loads((EXTRACT / "one-slot-classes.json").read_text(encoding="utf-8"))
    if cache.exists() and not remeasure and cache.stat().st_mtime >= (EXTRACT / "one-slot-classes.json").stat().st_mtime:
        return json.loads(cache.read_text(encoding="utf-8"))
    import one_slot_classes as osc
    from sunken_sim.search import GLYPHS
    from sunken_sim.shadow import Build

    spec_sets = {"Priest": osc.PRIEST_SPECS, "Paladin": osc.PALADIN_SPECS, "Mage": osc.MAGE_SPECS}
    found = {}
    for hero, fname in CLASS_FIGHTS.items():
        fight = getattr(osc, fname)
        specs = spec_sets[hero]
        rows = {BARE_GLYPH: [round(fight(Build(frozenset(), frozenset(), (), 0, 0, 0, 0), s), 1) for _t, s in specs]}
        for code, name in GLYPHS.items():
            rows[name] = [round(fight(Build(frozenset(), frozenset({code}), (), 0, 0, 0, 0), s), 1) for _t, s in specs]
            print(hero, "glyph", name, rows[name], flush=True)
        found[hero] = {"specs": [t for t, _s in specs], "codes": {n: c for c, n in GLYPHS.items()}, "rows": rows}
    with open(cache, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(found, fh, ensure_ascii=False, indent=1)
    return found


def class_blocks(tab: str, glyphs: dict):
    block = json.loads((EXTRACT / "one-slot-classes.json").read_text(encoding="utf-8"))[tab]
    specs = block["specs"]
    dps_head = [f"{s} DPS" for s in specs]
    items = [["Предмет", "Описание", "Код", "Источник", *dps_head]]
    for row in block["items"]:
        items.append([row["name"], row["tip"], row["code"], row["source"], *row["dps"]])
    body = [[r["name"], r["tip"], *r["dps"]] for r in block["talents"]]
    body.sort(key=lambda r: (-_first(r[2:]), r[0]))
    talents = [["Талант", "Описание", *dps_head], *body, [BARE_TALENT, "", *block["bare"]]]
    g = glyphs[tab]
    gbody = [[n, tip(g["codes"][n], n), *v] for n, v in g["rows"].items() if n != BARE_GLYPH]
    gbody.sort(key=lambda r: (-_first(r[2:]), r[0]))
    glyph_rows = [["Глиф", "Описание", *dps_head], *gbody, [BARE_GLYPH, "", *g["rows"][BARE_GLYPH]]]
    return specs, items, talents, glyph_rows


def all_tabs(remeasure: bool = False) -> dict:
    glyphs = class_glyphs(remeasure)
    out = {}
    for tab, (file, tcol, tcode, gcode) in TABS.items():
        if file is None:
            specs, items, talents, glyph_rows = class_blocks(tab, glyphs)
        else:
            specs, items, talents, glyph_rows = generic_blocks(tab, file, tcode, gcode)
        out[tab] = {
            "specs": specs,
            "items": items,
            "talents": talents,
            "glyphs": glyph_rows,
            "talent_col": tcol,
            "glyph_row": len(talents) + 1,
        }
    return out


def to_html(rows: list[list]) -> str:
    def cell(v):
        if v is None or v == "":
            return "<td></td>"
        if isinstance(v, (int, float)):
            return f"<td>{v}</td>"
        return "<td>" + html.escape(str(v)).replace("\n", "<br>") + "</td>"

    return "<table>" + "".join("<tr>" + "".join(cell(v) for v in r) + "</tr>" for r in rows) + "</table>"


def col_letter(index: int) -> str:
    s = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        s = chr(65 + rem) + s
    return s


def write_html(outdir: Path, data: dict) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for tab, d in data.items():
        slug = tab.replace(" ", "_")
        entry = {"talent_col": d["talent_col"], "glyph_row": d["glyph_row"], "specs": d["specs"]}
        for key in ("items", "talents", "glyphs"):
            rows = d[key]
            if rows is None:
                continue
            (outdir / f"{slug}__{key}.html").write_text(to_html(rows), encoding="utf-8")
            entry[key] = {"rows": len(rows), "cols": len(rows[0])}
        manifest[tab] = entry
    with open(outdir / "manifest.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    print("html ->", outdir, len(manifest), "tabs")


def upload(data: dict) -> None:
    from upload_one_slot import service

    values = service().spreadsheets().values()
    for tab, d in data.items():
        tcol = d["talent_col"]
        blocks = [(0, 0, d["items"]), (0, tcol, d["talents"])]
        if d["glyphs"]:
            blocks.append((d["glyph_row"], tcol, d["glyphs"]))
        values.batchClear(spreadsheetId=SPREADSHEET, body={"ranges": [f"'{tab}'!A2:{col_letter(tcol - 2)}600", f"'{tab}'!{col_letter(tcol)}1:{col_letter(tcol + 6)}80"]}).execute()
        payload = []
        for r0, c0, rows in blocks:
            width = len(rows[0])
            payload.append({"range": f"'{tab}'!{col_letter(c0)}{r0 + 1}:{col_letter(c0 + width - 1)}{r0 + len(rows)}", "values": rows})
        values.batchUpdate(spreadsheetId=SPREADSHEET, body={"valueInputOption": "RAW", "data": payload}).execute()
        print("wrote", tab, {k: len(d[k]) for k in ("items", "talents") }, flush=True)


def main() -> None:
    args = sys.argv[1:]
    data = all_tabs(remeasure="--remeasure" in args)
    if "--tabs" in args:
        # e.g. --tabs "Priest,Mage,Paladin": upload only these tabs
        want = [t.strip() for t in args[args.index("--tabs") + 1].split(",") if t.strip()]
        missing = [t for t in want if t not in data]
        if missing:
            raise SystemExit(f"unknown tabs: {missing}")
        data = {t: data[t] for t in want}
    if "--html" in args:
        write_html(ROOT / args[args.index("--html") + 1], data)
    else:
        upload(data)


if __name__ == "__main__":
    main()
