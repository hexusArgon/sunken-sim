"""Save the top 89 Retribution items plus Mind Amplifier."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

SPREADSHEET = "1Cnn9KJfwdI9pKEZMR_6T-xKCO674TsqYP5Bb4bsCj6w"
ROOT = Path(__file__).resolve().parents[1]
TOKEN = json.loads(Path(r"C:\Users\eseid\Documents\keys\google-sheets-token.json").read_text(encoding="utf-8"))["token"]
AMPLIFIER = "I0IC"
TALENTS = ["I064", "I09Y", "I04C", "I0NC", "I09R", "I0NG", "I01J", "I0G8"]


def main() -> None:
    sheet = "Паладин предметы"
    target = urllib.parse.quote(f"'{sheet}'!A1:G")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET}/values/{target}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        values = json.loads(response.read().decode())["values"]
    header = values[0]
    retri = header.index("Retribution DPS")
    code_col = header.index("Код")
    name_col = header.index("Предмет")
    rows = []
    for row in values[1:]:
        if len(row) <= retri or not row[code_col].strip():
            continue
        rows.append((float(row[retri]), row[code_col].strip(), row[name_col]))
    rows.sort(key=lambda item: (-item[0], item[2]))
    chosen = rows[:89]
    codes = [code for _dps, code, _name in chosen]
    if AMPLIFIER not in codes:
        codes.append(AMPLIFIER)
    payload = {
        "hero": "paladin",
        "spec": "retribution",
        "pool": "mixed",
        "talents": TALENTS,
        "items": codes,
        "note": "Топ-89 по Retribution DPS с листа Паладин предметы плюс Mind Amplifier X-8000. Таланты — тройки из этого списка, четвёрка если надет усилитель.",
    }
    path = ROOT / "extract" / "paladin-retribution-top89.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("items", len(codes), "amplifier", AMPLIFIER in codes, "top", chosen[0][2], chosen[0][1])


if __name__ == "__main__":
    main()
