"""Create the Shaman tabs on the one-slot spreadsheet and fill them."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sunken_sim.library import load_items
from sunken_sim.search import GLYPHS
from sunken_sim.shaman import TALENTS

SPREADSHEET = "1Cnn9KJfwdI9pKEZMR_6T-xKCO674TsqYP5Bb4bsCj6w"
ROOT = Path(__file__).resolve().parents[1]
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
        with urllib.request.urlopen(req, timeout=120) as response:
            body = response.read()
            return json.loads(body.decode()) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{exc.code} {detail[:800]}") from None


def plain(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def tables() -> tuple[list[list], list[list], list[list]]:
    saved = json.loads((ROOT / "extract" / "shaman-one-slot.json").read_text(encoding="utf-8"))
    by_code = {item.rawcode: item for item in load_items()}
    talents = [["Талант", "Описание", "Restoration DPS", "Enhancement DPS", "Elemental DPS"]]
    for row in saved["talents"][1:]:
        name = row[0]
        tip = ""
        if name != "Без таланта":
            code = next(code for code, title in TALENTS.items() if title == name)
            tip = plain(by_code[code].tip)
        talents.append([name, tip, *row[1:]])
    items = [[
        "Предмет",
        "Описание",
        "Код",
        "Источник",
        "Restoration DPS",
        "Enhancement DPS",
        "Elemental DPS",
        "Привязка Restoration",
        "Привязка Enhancement",
        "Привязка Elemental",
    ]]
    for row in saved["items"][1:]:
        name, code, source = row[0], row[1], row[2]
        tip = plain(by_code[code].tip) if code and code in by_code else ""
        items.append([name, tip, code, source, *row[3:]])
    glyphs = [["Глиф", "Описание", "Код", "Restoration DPS", "Enhancement DPS", "Elemental DPS"]]
    for row in saved["glyphs"][1:]:
        name, code = row[0], row[1]
        tip = ""
        if code:
            tip = plain(by_code[code].tip) if code in by_code else GLYPHS.get(code, "")
        glyphs.append([name, tip, code, *row[2:]])
    return talents, items, glyphs


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


def style(sheet_id: int, rows_n: int, columns: int, dps_start: int, dps_end: int, widths: list[int]) -> dict:
    requests = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1, "rowCount": max(rows_n, 1), "columnCount": columns},
                },
                "fields": "gridProperties.frozenRowCount,gridProperties.rowCount,gridProperties.columnCount",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": columns},
                "cell": {"userEnteredFormat": HEADER},
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": rows_n, "startColumnIndex": 1, "endColumnIndex": 2},
                "cell": {"userEnteredFormat": WRAP},
                "fields": "userEnteredFormat(verticalAlignment,wrapStrategy)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": rows_n,
                    "startColumnIndex": dps_start,
                    "endColumnIndex": dps_end,
                },
                "cell": {"userEnteredFormat": NUMBER},
                "fields": "userEnteredFormat.numberFormat",
            }
        },
    ]
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
    talents, items, glyphs = tables()
    titles = ["Шаман таланты", "Шаман предметы", "Шаман глифы"]
    ensure(titles)
    write(titles[0], talents)
    write(titles[1], items)
    write(titles[2], glyphs)
    book = request("GET", f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}?fields=sheets.properties")
    ids = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in book["sheets"]}
    endpoint = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}:batchUpdate"
    request("POST", endpoint, style(ids[titles[0]], len(talents), 5, 2, 5, [180, 520, 150, 160, 140]))
    request("POST", endpoint, style(ids[titles[1]], len(items), 10, 4, 7, [220, 520, 70, 110, 150, 160, 140, 180, 190, 170]))
    request("POST", endpoint, style(ids[titles[2]], len(glyphs), 6, 3, 6, [160, 520, 70, 150, 160, 140]))
    print("talents", len(talents), "items", len(items), "glyphs", len(glyphs))


if __name__ == "__main__":
    main()
