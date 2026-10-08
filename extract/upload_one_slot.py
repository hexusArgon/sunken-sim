"""Upload one-slot tables. Priest glyphs are the already measured allowed set."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from sunken_sim.library import load_items
from sunken_sim.search import GLYPHS
from sunken_sim.shadow import Build

SPREADSHEET = "1Cnn9KJfwdI9pKEZMR_6T-xKCO674TsqYP5Bb4bsCj6w"
ROOT = Path(__file__).resolve().parents[1]

PRIEST_GLYPHS = [
    ("Fortitude", 159.9, 93.6, 38.1),
    ("Hellfire", 158.2, 103.8, 55.9),
    ("Thunder", 157.8, 103.4, 38.3),
    ("Unsealed Power", 155.7, 91.5, 35.0),
    ("Glass Cannon", 151.8, 89.2, 34.1),
    ("Mindhaste", 136.9, 84.3, 29.7),
    ("Blood Violence", 135.7, 81.3, 30.7),
    ("Supremacy", 134.7, 79.8, 29.7),
    ("Animosity", 133.7, 79.3, 31.5),
    ("Battle Frenzy", 133.6, 82.0, 30.5),
    ("Arc Striking", 132.0, 77.6, 29.7),
    ("Fortune", 132.0, 77.6, 29.7),
]


def service():
    raw = json.loads((Path.home() / "Documents/keys/google-sheets-token.json").read_text(encoding="utf-8"))
    creds = Credentials(
        token=raw.get("token"),
        refresh_token=raw["refresh_token"],
        token_uri=raw["token_uri"],
        client_id=raw["client_id"],
        client_secret=raw["client_secret"],
        scopes=raw["scopes"],
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def item_rows(block):
    header = ["Предмет", "Описание", "Код", "Источник"] + [f"{name} DPS" for name in block["specs"]]
    rows = [header]
    for row in block["items"]:
        rows.append([row["name"], row["tip"], row["code"], row["source"], *row["dps"]])
    return rows


def talent_rows(block):
    header = ["Талант", "Описание"] + [f"{name} DPS" for name in block["specs"]]
    body = list(block["talents"])
    body.append({"name": "Без таланта", "tip": "", "dps": block["bare"]})
    body.sort(key=lambda row: (-row["dps"][0], row["name"]))
    rows = [header]
    for row in body:
        rows.append([row["name"], row["tip"], *row["dps"]])
    return rows


def glyph_rows(specs, measured):
    header = ["Глиф", "Описание"] + [f"{name} DPS" for name in specs]
    tips = {item.rawcode: item.tip for item in load_items()}
    body = []
    for code, name in GLYPHS.items():
        body.append((name, tips.get(code, ""), measured[name]))
    body.sort(key=lambda row: (-row[2][0], row[0]))
    rows = [header]
    for name, tip, numbers in body:
        rows.append([name, tip, *numbers])
    rows.append(["Без глифа", "", *measured["Без глифа"]])
    return rows


def priest_glyph_rows():
    tips = {item.name: item.tip for item in load_items() if item.name in GLYPHS.values() or True}
    by_name = {}
    for code, name in GLYPHS.items():
        item = next(piece for piece in load_items() if piece.rawcode == code)
        by_name[name] = item.tip
    rows = [["Глиф", "Описание", "Shadow DPS", "Discipline DPS", "Holy DPS"]]
    for name, shadow, discipline, holy in PRIEST_GLYPHS:
        rows.append([name, by_name[name], shadow, discipline, holy])
    rows.append(["Без глифа", "", 132.0, 77.6, 29.7])
    return rows


def measure_glyphs(fight, specs):
    bare = [round(fight(Build(frozenset(), frozenset(), (), 0, 0, 0, 0), spec), 1) for _title, spec in specs]
    found = {"Без глифа": bare}
    for code, name in GLYPHS.items():
        found[name] = [round(fight(Build(frozenset(), frozenset({code}), (), 0, 0, 0, 0), spec), 1) for _t, spec in specs]
        print(name, found[name], flush=True)
    return found


def put(sheets, title, range_name, rows):
    sheets.values().update(
        spreadsheetId=SPREADSHEET,
        range=f"'{title}'!{range_name}",
        valueInputOption="RAW",
        body={"values": rows},
    ).execute()
    print("wrote", title, range_name, len(rows), flush=True)


def clear(sheets, title, range_name):
    try:
        sheets.values().clear(spreadsheetId=SPREADSHEET, range=f"'{title}'!{range_name}").execute()
    except Exception as error:
        if "exceeds grid limits" not in str(error):
            raise


def main() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    data = json.loads((Path(__file__).with_name("one-slot-classes.json")).read_text(encoding="utf-8"))
    sheets = service().spreadsheets()
    meta = sheets.get(spreadsheetId=SPREADSHEET).execute()
    titles = {sheet["properties"]["title"] for sheet in meta["sheets"]}
    if "Mage" not in titles:
        sheets.batchUpdate(
            spreadsheetId=SPREADSHEET,
            body={"requests": [{"addSheet": {"properties": {"title": "Mage"}}}]},
        ).execute()
        print("created Mage", flush=True)

    from one_slot_classes import fight_mage, fight_paladin

    paladin_glyphs = measure_glyphs(fight_paladin, (("Retribution", "retribution"), ("Protection", "protection"), ("Holy", "holy")))
    mage_glyphs = measure_glyphs(fight_mage, (("Frost", "frost"), ("Arcane", "arcane"), ("Fire", "fire")))

    jobs = {
        "Priest": (data["Priest"], priest_glyph_rows()),
        "Paladin": (data["Paladin"], glyph_rows(data["Paladin"]["specs"], paladin_glyphs)),
        "Mage": (data["Mage"], glyph_rows(data["Mage"]["specs"], mage_glyphs)),
    }
    for title, (block, glyphs) in jobs.items():
        items = item_rows_of(block)
        talents = talent_rows_of(block)
        put(sheets, title, f"A1:G{len(items)}", items)
        clear(sheets, title, f"A{len(items) + 1}:G500")
        put(sheets, title, f"I1:M{len(talents)}", talents)
        glyph_start = len(talents) + 2
        put(sheets, title, f"I{glyph_start}:M{glyph_start + len(glyphs) - 1}", glyphs)
        clear(sheets, title, f"I{len(talents) + 1}:M{len(talents) + 1}")
        clear(sheets, title, f"I{glyph_start + len(glyphs)}:M80")
        print(title, "items", len(items), "talents", len(talents), "glyphs", len(glyphs), flush=True)


def item_rows_of(block):
    header = ["Предмет", "Описание", "Код", "Источник"] + [f"{name} DPS" for name in block["specs"]]
    rows = [header]
    for row in block["items"]:
        rows.append([row["name"], row["tip"], row["code"], row["source"], *row["dps"]])
    return rows


def talent_rows_of(block):
    header = ["Талант", "Описание"] + [f"{name} DPS" for name in block["specs"]]
    body = list(block["talents"])
    body.append({"name": "Без таланта", "tip": "", "dps": block["bare"]})
    body.sort(key=lambda row: (-row["dps"][0], row["name"]))
    rows = [header]
    for row in body:
        rows.append([row["name"], row["tip"], *row["dps"]])
    return rows


if __name__ == "__main__":
    main()
