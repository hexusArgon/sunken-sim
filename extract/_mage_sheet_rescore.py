"""Recalculate Mage one-slot DPS and sort each block by Frost DPS."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extract.upload_one_slot import service
from sunken_sim.library import load_items
from sunken_sim.mage import TALENTS
from sunken_sim.search import GLYPHS
from sunken_sim.shadow import Build

SPREADSHEET = "1Cnn9KJfwdI9pKEZMR_6T-xKCO674TsqYP5Bb4bsCj6w"
SPECS = ("frost", "arcane", "fire")
ROOT = Path(__file__).resolve().parents[1]


def _numbers(build: Build) -> list[float]:
    from sunken_sim.mage import simulate

    return [round(simulate(build, 5, spec=spec, use_history=False).dps, 1) for spec in SPECS]


def score(job: tuple[str, str]) -> tuple[str, str, list[float]]:
    kind, code = job
    by_code = {item.rawcode: item for item in load_items()}
    if kind == "bare":
        build = Build(frozenset(), frozenset(), (), 0, 0, 0, 0)
    elif kind == "item":
        build = Build(frozenset(), frozenset(), (by_code[code],), 0, 0, 0, 0)
    elif kind == "talent":
        build = Build(frozenset({code}), frozenset(), (), 0, 0, 0, 0)
    else:
        build = Build(frozenset(), frozenset({code}), (), 0, 0, 0, 0)
    return kind, code, _numbers(build)


def main() -> None:
    sheets = service().spreadsheets()
    values = sheets.values()
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    snap_dir = ROOT / "_snapshots"
    snap_dir.mkdir(exist_ok=True)
    current = values.get(spreadsheetId=SPREADSHEET, range="Mage!A1:M400").execute().get("values", [])
    formulas = values.get(
        spreadsheetId=SPREADSHEET, range="Mage!A1:M400", valueRenderOption="FORMULA"
    ).execute().get("values", [])
    (snap_dir / f"Mage_{stamp}_values.json").write_text(
        json.dumps(current, ensure_ascii=False), encoding="utf-8"
    )
    (snap_dir / f"Mage_{stamp}_formulas.json").write_text(
        json.dumps(formulas, ensure_ascii=False), encoding="utf-8"
    )
    print("snapshot", stamp, "rows", len(current), flush=True)

    by_code = {item.rawcode: item for item in load_items()}
    jobs: list[tuple[str, str]] = [("bare", "")]
    item_rows = []
    for row in current[1:]:
        if len(row) < 3 or not row[2]:
            break
        code = row[2]
        if code not in by_code:
            raise SystemExit(f"unknown item {code}")
        item_rows.append(row[:4])
        jobs.append(("item", code))
    talent_names = {name: code for code, name in TALENTS.items()}
    glyph_names = {name: code for code, name in GLYPHS.items()}
    talent_block = []
    glyph_block = []
    mode = "talent"
    for row in current:
        name = row[8] if len(row) > 8 else ""
        if name == "Глиф":
            mode = "glyph"
            continue
        if name in ("", "Талант"):
            continue
        tip = row[9] if len(row) > 9 else ""
        if mode == "talent":
            talent_block.append((name, tip))
            if name != "Без таланта":
                jobs.append(("talent", talent_names[name]))
        else:
            glyph_block.append((name, tip))
            if name != "Без глифа":
                jobs.append(("glyph", glyph_names[name]))

    found: dict[tuple[str, str], list[float]] = {}
    with ProcessPoolExecutor(max_workers=8) as pool:
        done = 0
        for kind, code, numbers in pool.map(score, jobs, chunksize=4):
            found[(kind, code)] = numbers
            done += 1
            if done % 40 == 0 or done == len(jobs):
                print("scored", done, "/", len(jobs), flush=True)

    ranked = []
    for name, tip, code, source in item_rows:
        numbers = found[("item", code)]
        ranked.append((name, tip, code, source, *numbers))
    ranked.sort(key=lambda row: (-row[4], row[0]))
    item_out = [["Предмет", "Описание", "Код", "Источник", "Frost DPS", "Arcane DPS", "Fire DPS"]]
    item_out.extend([list(row) for row in ranked])

    talents = []
    for name, tip in talent_block:
        code = "" if name == "Без таланта" else talent_names[name]
        kind = "bare" if name == "Без таланта" else "talent"
        talents.append((name, tip, *found[(kind, code)]))
    talents.sort(key=lambda row: (-row[2], row[0]))
    talent_out = [["Талант", "Описание", "Frost DPS", "Arcane DPS", "Fire DPS"]]
    talent_out.extend([list(row) for row in talents])

    glyphs = []
    bare_glyph = None
    for name, tip in glyph_block:
        if name == "Без глифа":
            bare_glyph = ["Без глифа", "", *found[("bare", "")]]
            continue
        glyphs.append((name, tip, *found[("glyph", glyph_names[name])]))
    glyphs.sort(key=lambda row: (-row[2], row[0]))
    glyph_out = [["Глиф", "Описание", "Frost DPS", "Arcane DPS", "Fire DPS"]]
    glyph_out.extend([list(row) for row in glyphs])
    glyph_out.append(bare_glyph)

    result = ROOT / "extract" / "_mage_sheet_rows.json"
    result.write_text(
        json.dumps({"items": item_out, "talents": talent_out, "glyphs": glyph_out}, ensure_ascii=False),
        encoding="utf-8",
    )
    print("top", ranked[0][0], ranked[0][4:], flush=True)
    print("items", len(ranked), "talents", len(talents), "glyphs", len(glyphs), flush=True)


if __name__ == "__main__":
    main()
