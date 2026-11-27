"""Build the Druid tab matrix from extract/druid-one-slot.json (Druid E009 only).

Layout matches the Priest tab, two specs (Restoration, Balance):
    A–F  items: Предмет, Описание, Код, Источник, Restoration DPS, Balance DPS
    G    spacer
    H–K  talents: Талант, Описание, Restoration DPS, Balance DPS
         one blank row, then glyphs under talents in H–K: Глиф, Описание, Restoration DPS, Balance DPS
Feral Druid is a separate class and is not on this tab.

    python extract/_build_druid_sheet_matrix.py   # writes extract/_druid_sheet_matrix.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from farm.hybrid.druid_cl import TALENT_NAMES as TALENTS
from sunken_sim.library import load_items

SPEC_TITLES = ("Restoration", "Balance")
SPEC_DPS = [f"{title} DPS" for title in SPEC_TITLES]
N = len(SPEC_TITLES)
ITEM_COL = 0  # A
ITEM_WIDTH = 4 + N  # A–F
SPACER_COL = ITEM_COL + ITEM_WIDTH  # G
TALENT_COL = SPACER_COL + 1  # H
TALENT_WIDTH = 2 + N  # H–K
WIDTH = TALENT_COL + TALENT_WIDTH


def plain(text: str) -> str:
    cleaned = re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", text or "")
    return cleaned.replace("|n", "\n").replace("\r\n", "\n").replace("\r", "\n").strip()


def _num(value):
    return "" if value == "" or value is None else float(value)


def _best(row: list, start: int) -> float:
    values = [v for v in row[start : start + N] if isinstance(v, float)]
    return max(values) if values else -1e9


def tables() -> dict:
    saved = json.loads((ROOT / "extract" / "druid-one-slot.json").read_text(encoding="utf-8"))
    if saved.get("specs") != list(SPEC_TITLES):
        raise SystemExit("druid-one-slot.json is not the Druid-only 2-spec run; rerun tools/one_slot_gpu.py druid")
    by_code = {item.rawcode: item for item in load_items()}

    items = []
    for row in saved["items"][2:]:  # skip header and "Без предмета"
        name, code, source = row[0], row[1], row[2]
        binds = [v for v in row[3 + N : 3 + 2 * N] if v]
        if binds and len(set(binds)) == 1:
            name = f"{name} ({binds[0]})"
        elif binds:
            name = f"{name} ({' / '.join(binds)})"
        tip = plain(by_code[code].tip) if code in by_code else ""
        items.append([name, tip, code, source, *[_num(v) for v in row[3 : 3 + N]]])
    items.sort(key=lambda r: (-_best(r, 4), r[0]))

    talents = []
    for row in saved["talents"][1:]:
        name, code = row[0], row[1]
        tip = plain(by_code[code].tip) if code and code in by_code else ""
        if not tip and code in TALENTS and code in by_code:
            tip = plain(by_code[code].tip)
        talents.append([name, tip, *[_num(v) for v in row[2 : 2 + N]]])
    talents.sort(key=lambda r: (-_best(r, 2), r[0]))

    glyphs = []
    for row in saved["glyphs"][1:]:
        name, code = row[0], row[1]
        tip = plain(by_code[code].tip) if code and code in by_code else ""
        glyphs.append([name, tip, *[_num(v) for v in row[2 : 2 + N]]])
    glyphs.sort(key=lambda r: (-_best(r, 2), r[0]))

    talent_block = 1 + len(talents)
    glyph_header = talent_block + 1  # one blank row between talents and glyphs (0-based row index)
    height = max(1 + len(items), glyph_header + 1 + len(glyphs))
    sheet = [[""] * WIDTH for _ in range(height)]
    sheet[0][ITEM_COL : ITEM_COL + ITEM_WIDTH] = ["Предмет", "Описание", "Код", "Источник", *SPEC_DPS]
    sheet[0][TALENT_COL : TALENT_COL + TALENT_WIDTH] = ["Талант", "Описание", *SPEC_DPS]
    for i, row in enumerate(items, start=1):
        sheet[i][ITEM_COL : ITEM_COL + ITEM_WIDTH] = row
    for i, row in enumerate(talents, start=1):
        sheet[i][TALENT_COL : TALENT_COL + TALENT_WIDTH] = row
    sheet[glyph_header][TALENT_COL : TALENT_COL + TALENT_WIDTH] = ["Глиф", "Описание", *SPEC_DPS]
    for i, row in enumerate(glyphs, start=glyph_header + 1):
        sheet[i][TALENT_COL : TALENT_COL + TALENT_WIDTH] = row
    return {
        "rows": sheet,
        "nrows": len(sheet),
        "ncols": WIDTH,
        "items": len(items),
        "talents": len(talents),
        "glyphs": len(glyphs),
        "glyph_header_row": glyph_header,  # 0-based
        "items_range": f"A1:F{1 + len(items)}",
        "talents_range": f"H1:K{talent_block}",
        "glyphs_range": f"H{glyph_header + 1}:K{glyph_header + 1 + len(glyphs)}",
    }


def main() -> None:
    matrix = tables()
    out = ROOT / "extract" / "_druid_sheet_matrix.json"
    out.write_text(json.dumps(matrix, ensure_ascii=False), encoding="utf-8")
    print(
        "wrote", out, "rows", matrix["nrows"], "cols", matrix["ncols"],
        "items", matrix["items"], matrix["items_range"],
        "talents", matrix["talents"], matrix["talents_range"],
        "glyphs", matrix["glyphs"], matrix["glyphs_range"],
    )


if __name__ == "__main__":
    main()
