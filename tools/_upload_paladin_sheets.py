"""Create Paladin tabs in the one-slot spreadsheet and fill them from the sim JSON."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SPREADSHEET = "1Cnn9KJfwdI9pKEZMR_6T-xKCO674TsqYP5Bb4bsCj6w"
TOKEN = json.loads(Path(r"C:\Users\eseid\Documents\keys\google-sheets-token.json").read_text(encoding="utf-8"))["token"]
ROWS = json.loads(Path(__file__).resolve().parents[1].joinpath("extract", "paladin-one-slot.json").read_text(encoding="utf-8"))
TABS = (
    ("Паладин таланты", ROWS["talents"]),
    ("Паладин предметы", ROWS["items"]),
)


def request(method: str, url: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read()
            return json.loads(body.decode()) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{exc.code} {detail[:500]}") from None


def main() -> None:
    book = request("GET", f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}")
    existing = {sheet["properties"]["title"] for sheet in book["sheets"]}
    requests = []
    for title, _rows in TABS:
        if title not in existing:
            requests.append({"addSheet": {"properties": {"title": title}}})
    if requests:
        request("POST", f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}:batchUpdate", {"requests": requests})
    for title, rows in TABS:
        encoded = urllib.parse.quote(f"'{title}'!A1")
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        request(
            "PUT",
            f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}/values/{encoded}?valueInputOption=RAW",
            {"range": f"'{title}'!A1", "majorDimension": "ROWS", "values": padded},
        )
        print(title, len(rows))


if __name__ == "__main__":
    main()
