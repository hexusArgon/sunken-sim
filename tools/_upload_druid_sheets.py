"""Fill the Druid tab on the one-slot spreadsheet (Druid E009 only: Restoration, Balance).

Layout matches Priest: items A–F, spacer G, talents H–K, one blank row, glyphs under talents in H–K.
Feral Druid is a separate class with its own future tab/script.
Matrix comes from extract/_build_druid_sheet_matrix.py.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "extract"))

from _build_druid_sheet_matrix import ITEM_COL, ITEM_WIDTH, N, SPACER_COL, TALENT_COL, TALENT_WIDTH, WIDTH, tables

SPREADSHEET = "1Cnn9KJfwdI9pKEZMR_6T-xKCO674TsqYP5Bb4bsCj6w"
TOKEN = json.loads(Path(r"C:\Users\eseid\Documents\keys\google-sheets-token.json").read_text(encoding="utf-8"))["token"]
HEADER = {
    "backgroundColor": {"red": 0.11764706, "green": 0.15686275, "blue": 0.21960784},
    "horizontalAlignment": "CENTER",
    "verticalAlignment": "MIDDLE",
    "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "fontSize": 11, "bold": True},
}
NUMBER = {"numberFormat": {"type": "NUMBER", "pattern": "0.0"}}
WRAP = {"verticalAlignment": "TOP", "wrapStrategy": "WRAP"}


def request(method: str, url: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            body = response.read()
            return json.loads(body.decode()) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{exc.code} {detail[:800]}") from None


def ensure(titles: list[str]) -> None:
    book = request("GET", f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}?fields=sheets.properties")
    existing = {sheet["properties"]["title"] for sheet in book["sheets"]}
    requests = [{"addSheet": {"properties": {"title": title}}} for title in titles if title not in existing]
    if requests:
        request("POST", f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}:batchUpdate", {"requests": requests})


def write(title: str, values: list[list]) -> None:
    encoded = urllib.parse.quote(f"'{title}'!A1")
    request("POST", f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}/values/{encoded}:clear", {})
    width = max(len(row) for row in values)
    padded = [row + [""] * (width - len(row)) for row in values]
    request(
        "PUT",
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}/values/{encoded}?valueInputOption=RAW",
        {"range": f"'{title}'!A1", "majorDimension": "ROWS", "values": padded},
    )


def _cells(sheet_id: int, row0: int, row1: int, col0: int, col1: int, fmt: dict, fields: str) -> dict:
    return {
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": row0, "endRowIndex": row1, "startColumnIndex": col0, "endColumnIndex": col1},
            "cell": {"userEnteredFormat": fmt},
            "fields": fields,
        }
    }


def style(sheet_id: int, matrix: dict) -> dict:
    rows_n = matrix["nrows"]
    glyph_row = matrix["glyph_header_row"]
    header_fields = "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)"
    wrap_fields = "userEnteredFormat(verticalAlignment,wrapStrategy)"
    widths = [220, 520, 70, 110] + [140] * N + [24] + [180, 520] + [140] * N
    requests = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1, "rowCount": max(rows_n, 1), "columnCount": WIDTH},
                },
                "fields": "gridProperties.frozenRowCount,gridProperties.rowCount,gridProperties.columnCount",
            }
        },
        _cells(sheet_id, 0, 1, ITEM_COL, ITEM_COL + ITEM_WIDTH, HEADER, header_fields),
        _cells(sheet_id, 0, 1, TALENT_COL, TALENT_COL + TALENT_WIDTH, HEADER, header_fields),
        _cells(sheet_id, glyph_row, glyph_row + 1, TALENT_COL, TALENT_COL + TALENT_WIDTH, HEADER, header_fields),
        _cells(sheet_id, 1, rows_n, ITEM_COL + 1, ITEM_COL + 2, WRAP, wrap_fields),
        _cells(sheet_id, 1, rows_n, TALENT_COL + 1, TALENT_COL + 2, WRAP, wrap_fields),
        _cells(sheet_id, 1, rows_n, ITEM_COL + 4, ITEM_COL + 4 + N, NUMBER, "userEnteredFormat.numberFormat"),
        _cells(sheet_id, 1, glyph_row, TALENT_COL + 2, TALENT_COL + 2 + N, NUMBER, "userEnteredFormat.numberFormat"),
        _cells(sheet_id, glyph_row + 1, rows_n, TALENT_COL + 2, TALENT_COL + 2 + N, NUMBER, "userEnteredFormat.numberFormat"),
    ]
    assert len(widths) == WIDTH and widths[SPACER_COL] == 24
    for index, size in enumerate(widths):
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": index, "endIndex": index + 1},
                    "properties": {"pixelSize": size},
                    "fields": "pixelSize",
                }
            }
        )
    return {"requests": requests}


def main() -> None:
    matrix = tables()
    values = matrix["rows"]
    title = "Druid"
    ensure([title])
    write(title, values)
    book = request("GET", f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}?fields=sheets.properties")
    ids = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in book["sheets"]}
    endpoint = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}:batchUpdate"
    request("POST", endpoint, style(ids[title], matrix))
    print("rows", len(values), "sheetId", ids[title], matrix["items_range"], matrix["talents_range"], matrix["glyphs_range"])


if __name__ == "__main__":
    main()
