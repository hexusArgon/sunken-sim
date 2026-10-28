"""Build per-spec top-80 farm presets from one-slot DPS (plus Mind Amplifier)."""

from __future__ import annotations

import json
from pathlib import Path

from sunken_sim.mage import TALENTS as MAGE_TALENTS
from sunken_sim.paladin import TALENTS as PALADIN_TALENTS
from sunken_sim.search import TALENTS as PRIEST_TALENTS
from sunken_sim.shadow import MIND_AMPLIFIER
from sunken_sim.shaman import TALENTS as SHAMAN_TALENTS

ROOT = Path(__file__).resolve().parent
RUNEMASTERY = "I0Q8"
NOTE = (
    "Топ-80 по DPS соло-предмета этой специализации плюс Mind Amplifier X-8000. "
    "Таланты — те, что соло выше голого героя."
)


def _name_to_code(talents: dict[str, str]) -> dict[str, str]:
    return {name: code for code, name in talents.items()}


def _pick_talents(rows: list[dict], bare: list[float], spec_i: int, name_map: dict[str, str], exclude: set[str] | None = None) -> list[str]:
    exclude = exclude or set()
    bare_dps = float(bare[spec_i])
    codes = []
    for row in rows:
        name = row["name"]
        code = name_map.get(name)
        if code is None or code in exclude:
            continue
        if float(row["dps"][spec_i]) > bare_dps:
            codes.append(code)
    return sorted(codes)


def _top_items(rows: list[dict], spec_i: int, n: int = 80) -> list[str]:
    ranked = sorted(rows, key=lambda row: (-float(row["dps"][spec_i]), row["code"]))
    codes = []
    seen = set()
    for row in ranked:
        code = row["code"]
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
        if len(codes) >= n:
            break
    if MIND_AMPLIFIER not in seen:
        codes.append(MIND_AMPLIFIER)
    return codes


def from_classes() -> list[tuple[str, dict]]:
    data = json.loads((ROOT / "one-slot-classes.json").read_text(encoding="utf-8"))
    plans = [
        ("Priest", "priest", PRIEST_TALENTS, set(), {
            "Shadow": "shadow",
            "Discipline": "discipline",
            "Holy": "holy",
        }),
        ("Mage", "mage", MAGE_TALENTS, {RUNEMASTERY}, {
            "Frost": "frost",
            "Arcane": "arcane",
            "Fire": "fire",
        }),
        ("Paladin", "paladin", PALADIN_TALENTS, set(), {
            "Retribution": "retribution",
            "Protection": "protection",
            "Holy": "holy",
        }),
    ]
    out = []
    for class_key, hero, talent_map, exclude, specs in plans:
        block = data[class_key]
        name_map = _name_to_code(talent_map)
        bare = block["bare"]
        items = block["items"]
        talent_rows = block["talents"]
        for i, (label, spec) in enumerate(specs.items()):
            payload = {
                "hero": hero,
                "spec": spec,
                "pool": "mixed",
                "talents": _pick_talents(talent_rows, bare, i, name_map, exclude),
                "items": _top_items(items, i),
                "note": NOTE,
            }
            filename = f"{hero}-{spec}-top80.json"
            out.append((filename, payload))
    return out


def from_shaman() -> list[tuple[str, dict]]:
    raw = json.loads((ROOT / "shaman-one-slot.json").read_text(encoding="utf-8"))
    name_map = _name_to_code(SHAMAN_TALENTS)
    bare = raw["talents"][1]
    bare_dps = [float(bare[1]), float(bare[2]), float(bare[3])]
    talent_rows = []
    for row in raw["talents"][2:]:
        talent_rows.append({"name": row[0], "dps": [float(row[1]), float(row[2]), float(row[3])]})
    item_rows = []
    for row in raw["items"][1:]:
        code = row[1]
        if not code:
            continue
        item_rows.append({
            "code": code,
            "name": row[0],
            "dps": [float(row[3]), float(row[4]), float(row[5])],
        })
    specs = [("restoration", 0), ("enhancement", 1), ("elemental", 2)]
    out = []
    for spec, i in specs:
        payload = {
            "hero": "shaman",
            "spec": spec,
            "pool": "mixed",
            "talents": _pick_talents(talent_rows, bare_dps, i, name_map),
            "items": _top_items(item_rows, i),
            "note": NOTE,
        }
        out.append((f"shaman-{spec}-top80.json", payload))
    return out


def main() -> None:
    written = []
    for filename, payload in from_classes() + from_shaman():
        path = ROOT / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append((filename, payload["hero"], payload["spec"], len(payload["items"]), len(payload["talents"]), MIND_AMPLIFIER in payload["items"]))
    for row in written:
        print("%s %s/%s items=%d talents=%d amp=%s" % row)


if __name__ == "__main__":
    main()
