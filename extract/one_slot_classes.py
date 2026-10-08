"""One-slot item and talent DPS for Priest, Paladin and Mage. Five targets, no skill points."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import load_items
from sunken_sim.search import LEGENDARIES, TALENTS as PRIEST_TALENTS, ignored_item_names, pools_for
from sunken_sim.shadow import ORB_MODE, Build

PRIEST_SPECS = (("Shadow", "shadow"), ("Discipline", "discipline"), ("Holy", "holy"))
PALADIN_SPECS = (("Retribution", "retribution"), ("Protection", "protection"), ("Holy", "holy"))
MAGE_SPECS = (("Frost", "frost"), ("Arcane", "arcane"), ("Fire", "fire"))


def catalog_items(hero: str) -> list[tuple[str, str, str, object]]:
    ban = ignored_item_names(hero)
    shop, drop, legs = pools_for(load_items(), hero)
    shop_ids = {item.rawcode for item in shop}
    rows = []
    seen = set()
    for item in shop + drop + legs:
        if item.rawcode in seen or item.name in ban:
            continue
        seen.add(item.rawcode)
        label = item.name
        if item.rawcode in ORB_MODE:
            label = f"{item.name} ({ORB_MODE[item.rawcode]})"
        if item.rawcode in LEGENDARIES:
            source = "Legendary"
        elif item.rawcode in shop_ids:
            source = "Shop"
        else:
            source = "Drop"
        rows.append((label, item.rawcode, source, item))
    return rows


def tip_of(code: str, items: dict) -> str:
    item = items.get(code)
    return item.tip if item is not None else ""


def fight_priest(build: Build, spec: str) -> float:
    from sunken_sim.shadow import simulate

    return simulate(build, 5, spec=spec, use_history=False).dps


def fight_paladin(build: Build, spec: str) -> float:
    from sunken_sim.paladin import simulate

    return simulate(build, 5, spec=spec).dps


def fight_mage(build: Build, spec: str) -> float:
    from sunken_sim.mage import simulate

    return simulate(build, 5, spec=spec, use_history=False).dps


def measure(hero: str, specs, talents: dict, fight) -> dict:
    by_code = {item.rawcode: item for item in load_items()}
    bare = [round(fight(Build(frozenset(), frozenset(), (), 0, 0, 0, 0), spec), 1) for _title, spec in specs]
    print(hero, "bare", bare, flush=True)
    item_rows = []
    for label, rawcode, source, item in catalog_items(hero):
        numbers = [round(fight(Build(frozenset(), frozenset(), (item,), 0, 0, 0, 0), spec), 1) for _t, spec in specs]
        item_rows.append({"name": label, "tip": item.tip, "code": rawcode, "source": source, "dps": numbers})
        print(hero, "item", label, numbers, flush=True)
    item_rows.sort(key=lambda row: (-row["dps"][0], row["name"]))
    talent_rows = []
    for code, name in sorted(talents.items(), key=lambda pair: pair[1]):
        numbers = [round(fight(Build(frozenset({code}), frozenset(), (), 0, 0, 0, 0), spec), 1) for _t, spec in specs]
        talent_rows.append({"name": name, "tip": tip_of(code, by_code), "dps": numbers})
        print(hero, "talent", name, numbers, flush=True)
    talent_rows.sort(key=lambda row: (-row["dps"][0], row["name"]))
    return {
        "specs": [title for title, _spec in specs],
        "bare": bare,
        "items": item_rows,
        "talents": talent_rows,
    }


def main() -> None:
    from sunken_sim.mage import TALENTS as MAGE_TALENTS
    from sunken_sim.paladin import TALENTS as PALADIN_TALENTS

    out = Path(__file__).with_name("one-slot-classes.json")
    payload = {
        "Priest": measure("Priest", PRIEST_SPECS, PRIEST_TALENTS, fight_priest),
        "Paladin": measure("Paladin", PALADIN_SPECS, PALADIN_TALENTS, fight_paladin),
        "Mage": measure("Mage", MAGE_SPECS, MAGE_TALENTS, fight_mage),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print("wrote", out, flush=True)


if __name__ == "__main__":
    main()
