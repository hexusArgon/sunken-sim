"""Top-N items by one-slot DPS of one spec, plus Mind Amplifier, from extract/*one-slot*.json.

Tables are not sorted by DPS: rows are ranked here by the spec's DPS column.
Talents kept: those whose solo DPS beats the bare hero for that spec.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from farm.protocol import HERO_NAME, SPECS

EXTRACT = Path(__file__).resolve().parents[1] / "extract"
MIND_AMPLIFIER = "I0IC"
RUNEMASTERY = "I0Q8"
# one-slot-classes.json holds these three.
CLASSES_BLOCK = {"priest": "Priest", "mage": "Mage", "paladin": "Paladin"}
SHEET_FILE = {"feral_druid": "feral-druid-one-slot.json"}
TALENT_EXCLUDE = {"mage": {RUNEMASTERY}}
# Talents that only gain together with items (a lone-talent screen never shows them): always in the pool.
# Death Knight Blood Feast heals on every damage instance: damage through Bloodlord's Regalia and the
# health-dependent items (user decision 2026-11-27).
TALENT_INCLUDE = {"death_knight": {"I0CU"}}
# Items always added to the top-N pool (after it, like Mind Amplifier) so such talents meet their partners:
# Bloodlord's Regalia, Mask of the Blood Hungerer (Blood Feast as an item) and the items whose damage depends
# on the hero's health (Crimson Fury, Immortal Gladiator's Mask, The Furnace, Belt of Living Strength,
# Bloodhowl, Dark Iron Ale, Icecrown Ring).
ITEM_INCLUDE = {"death_knight": ("I05V", "I0NJ", "I024", "arsc", "I079", "fgun", "I05N", "I06J", "I015")}
SOURCE_POOL = {"Shop": "shop", "Drop": "drop", "Legendary": "legendary"}


def _key(text: str) -> str:
    return str(text).strip().lower().replace(" ", "_").replace("-", "_")


def _talent_names(hero: str) -> dict[str, str]:
    from farm.protocol import GPU_ONLY

    if hero in GPU_ONLY:
        import importlib

        return dict(importlib.import_module(f"farm.hybrid.{hero}_cl").TALENT_NAMES)
    if hero == "priest":
        from sunken_sim.search import TALENTS
    else:
        import importlib

        TALENTS = importlib.import_module(f"sunken_sim.{hero}").TALENTS
    return dict(TALENTS)


@lru_cache(maxsize=None)
def table(hero: str) -> dict:
    """Normalised table: specs, bare[spec], items[{code,name,source,dps[]}], talents[{code,name,dps[]}]."""
    specs = list(SPECS[hero])
    names = _talent_names(hero)
    by_name = {name: code for code, name in names.items()}
    if hero in CLASSES_BLOCK:
        block = json.loads((EXTRACT / "one-slot-classes.json").read_text(encoding="utf-8"))[CLASSES_BLOCK[hero]]
        if [_key(s) for s in block["specs"]] != specs:
            raise RuntimeError(f"порядок спеков {hero} в one-slot-classes.json: {block['specs']}")
        items = [
            {"code": row["code"], "name": row["name"], "source": row.get("source") or "", "dps": [float(v) for v in row["dps"]]}
            for row in block["items"]
        ]
        talents = [
            {"code": by_name.get(row["name"]), "name": row["name"], "dps": [float(v) for v in row["dps"]]}
            for row in block["talents"]
        ]
        return {"specs": specs, "bare": [float(v) for v in block["bare"]], "items": items, "talents": talents, "file": "one-slot-classes.json"}
    filename = SHEET_FILE.get(hero, f"{hero}-one-slot.json")
    raw = json.loads((EXTRACT / filename).read_text(encoding="utf-8"))
    head = raw["items"][0]
    cols = []
    for spec in specs:
        label = None
        for i, cell in enumerate(head):
            text = str(cell)
            if text.endswith(" DPS") and _key(text[: -len(" DPS")]) == spec:
                label = i
        if label is None:
            raise RuntimeError(f"{filename}: нет колонки DPS для {spec}")
        cols.append(label)
    items = []
    bare = None
    for row in raw["items"][1:]:
        if not row[1]:
            if bare is None:
                bare = [float(row[c]) for c in cols]
            continue
        items.append({"code": row[1], "name": row[0], "source": row[2], "dps": [float(row[c]) for c in cols]})
    t_head = raw["talents"][0]
    t_cols = []
    for spec in specs:
        for i, cell in enumerate(t_head):
            text = str(cell)
            if text.endswith(" DPS") and _key(text[: -len(" DPS")]) == spec:
                t_cols.append(i)
                break
        else:
            raise RuntimeError(f"{filename}: нет колонки DPS талантов для {spec}")
    has_code = len(t_head) > 1 and str(t_head[1]) == "Код"
    talents = []
    t_bare = None
    for row in raw["talents"][1:]:
        if str(row[0]).startswith("Без "):
            t_bare = [float(row[c]) for c in t_cols]
            continue
        code = row[1] if has_code and row[1] else by_name.get(row[0])
        talents.append({"code": code, "name": row[0], "dps": [float(row[c]) for c in t_cols]})
    return {"specs": specs, "bare": t_bare or bare, "items": items, "talents": talents, "file": filename}


def top_items(hero: str, spec: str, top: int, pool: str = "mixed", known: set[str] | None = None) -> list[str]:
    """Codes of the top-N items by DPS for this spec, then Mind Amplifier if it is not among them."""
    data = table(hero)
    i = data["specs"].index(spec)
    allowed = {"mixed": {"shop", "drop", "legendary"}, "shop": {"shop", "legendary"}, "drop": {"drop", "legendary"}}[pool]
    rows = [
        row
        for row in data["items"]
        if row["code"]
        and row["code"] != MIND_AMPLIFIER
        and SOURCE_POOL.get(row["source"], "drop") in allowed
        and (known is None or row["code"] in known)
    ]
    rows.sort(key=lambda row: (-row["dps"][i], row["code"]))
    codes: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row["code"] in seen:
            continue
        seen.add(row["code"])
        codes.append(row["code"])
        if len(codes) >= top:
            break
    by_code = {row["code"]: row for row in rows}
    for code in ITEM_INCLUDE.get(hero, ()):
        if code in by_code and code not in seen:
            seen.add(code)
            codes.append(code)
    codes.append(MIND_AMPLIFIER)
    return codes


def top_talents(hero: str, spec: str) -> list[str]:
    data = table(hero)
    i = data["specs"].index(spec)
    bare = float(data["bare"][i])
    names = _talent_names(hero)
    exclude = TALENT_EXCLUDE.get(hero, set())
    out = set()
    for row in data["talents"]:
        code = row["code"]
        if not code or code in exclude or code not in names:
            continue
        if row["dps"][i] > bare:
            out.add(code)
    out |= {code for code in TALENT_INCLUDE.get(hero, set()) if code in names and code not in exclude}
    return sorted(out)


def describe(hero: str) -> str:
    return f"{HERO_NAME[hero]}: {table(hero)['file']}"
