"""Match the Paladin tabs to the Priest sheet layout."""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sunken_sim.library import load_items
from sunken_sim.paladin import TALENTS

SPREADSHEET = "1Cnn9KJfwdI9pKEZMR_6T-xKCO674TsqYP5Bb4bsCj6w"
ROOT = Path(__file__).resolve().parents[1]
TOKEN = json.loads(Path(r"C:\Users\eseid\Documents\keys\google-sheets-token.json").read_text(encoding="utf-8"))["token"]
HEADER = {
    "backgroundColor": {"red": 0.11764706, "green": 0.15686275, "blue": 0.21960784},
    "horizontalAlignment": "CENTER",
    "verticalAlignment": "MIDDLE",
    "textFormat": {
        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
        "fontSize": 11,
        "bold": True,
    },
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
    cleaned = re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", text or "")
    return cleaned.replace("|n", "\n").replace("\r\n", "\n").replace("\r", "\n").strip()


def rows() -> tuple[list[list], list[list]]:
    saved = json.loads((ROOT / "extract" / "paladin-one-slot.json").read_text(encoding="utf-8"))
    by_code = {item.rawcode: item for item in load_items()}
    by_name = {item.name: item for item in by_code.values()}
    talents = [["Талант", "Описание", "Retribution DPS", "Protection DPS", "Holy DPS"]]
    for row in saved["talents"][1:]:
        name, retri, prot, holy = row
        tip = ""
        if name != "Без таланта":
            code = next(code for code, title in TALENTS.items() if title == name)
            tip = plain(by_code[code].tip)
        talents.append([name, tip, retri, prot, holy])
    items = [["Предмет", "Описание", "Код", "Источник", "Retribution DPS", "Protection DPS", "Holy DPS"]]
    for row in saved["items"][1:]:
        name, code, source, retri, prot, holy = row
        tip = ""
        if code:
            item = by_code.get(code) or by_name.get(name.split(" (")[0])
            if item is not None:
                tip = plain(item.tip)
        items.append([name, tip, code, source, retri, prot, holy])
    return talents, items


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


def style(sheet_id: int, rows_n: int, columns: int, dps_start: int, widths: list[int]) -> dict:
    requests = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {
                        "frozenRowCount": 1,
                        "rowCount": max(rows_n, 1),
                        "columnCount": columns,
                    },
                },
                "fields": "gridProperties.frozenRowCount,gridProperties.rowCount,gridProperties.columnCount",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": columns,
                },
                "cell": {"userEnteredFormat": HEADER},
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": rows_n,
                    "startColumnIndex": 1,
                    "endColumnIndex": 2,
                },
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
                    "endColumnIndex": columns,
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
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": index,
                        "endIndex": index + 1,
                    },
                    "properties": {"pixelSize": size},
                    "fields": "pixelSize",
                }
            }
        )
    return {"requests": requests}


def main() -> None:
    talents, items = rows()
    write("Паладин таланты", talents)
    write("Паладин предметы", items)
    book = request("GET", f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}?fields=sheets.properties")
    ids = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in book["sheets"]}
    request(
        "POST",
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}:batchUpdate",
        style(ids["Паладин таланты"], len(talents), 5, 2, [120, 520, 150, 140, 110]),
    )
    request(
        "POST",
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}:batchUpdate",
        style(ids["Паладин предметы"], len(items), 7, 4, [205, 522, 70, 110, 150, 140, 110]),
    )
    print("talents", len(talents), "items", len(items))


if __name__ == "__main__":
    main()
