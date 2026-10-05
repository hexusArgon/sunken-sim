"""Classify whether a second copy of each item stacks."""

import re
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import _extract, _load_strings, _parse_objects, _resolve, MAP_PATH, WTS_PATH, load_items

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
strings = _load_strings(WTS_PATH)

bodies = {}
for match in re.finditer(r"function (Trig_\w+) takes nothing returns", script):
    name = match.group(1)
    start = match.end()
    end = script.find("endfunction", start)
    bodies[name] = script[start:end]

def codes_of(name, seen=None):
    if seen is None:
        seen = set()
    if name in seen or name not in bodies:
        return set()
    seen.add(name)
    body = bodies[name]
    found = set(re.findall(r"GetItemTypeId\(GetManipulatedItem\(\)\)=='([A-Za-z0-9]{4})'", body))
    found |= set(re.findall(r"UnitHasItemOfTypeBJ\([^,]+,'([A-Za-z0-9]{4})'", body))
    for child in re.findall(r"(Trig_\w+)\(\)", body):
        found |= codes_of(child, seen)
    return found

STAT = {
    "Haste_Items": "Haste",
    "Mastery_Stat": "Mastery",
    "CriticalStrike_ChanceFlat": "крит",
    "CriticalStrike_RatingFlat": "рейтинг крита",
    "PA_Items": "основной атрибут",
    "AttackSpeed_Items": "скорость атаки",
    "Potency_Items": "Potency",
    "Luck_Items": "Luck",
    "HealingPower_Items": "сила лечения",
    "MagicFind_Items": "Magic Find",
    "PetDamage_Items": "урон питомца",
    "Taunt_Items": "Taunt",
}

stack_stats = {}  # code -> list of "Haste +10"
for fname, body in bodies.items():
    if not fname.endswith("_Gain_Actions"):
        continue
    for func, var, amount in re.findall(
        r"if\((Trig_\w+)\(\)\)then\nset udg_(\w+)\[[^\n]*\+(\d+(?:\.\d+)?)\)",
        body,
    ):
        label = STAT.get(var, var)
        for code in codes_of(func):
            stack_stats.setdefault(code, []).append(f"{label} +{amount.rstrip('0').rstrip('.') if '.' in amount else amount}")

# DCS white damage, stacks per slot
damage = {}
for code, amount in re.findall(
    r"set udg_DCS_ItemInt='([A-Za-z0-9]{4})'\nset udg_DCS_ItemDamageBonus=(\d+)",
    script,
):
    damage[code] = int(amount)

# boolean has-item effects: count UnitHasItem checks
has_item = {}
for code in re.findall(r"UnitHasItemOfTypeBJ\([^,]+,'([A-Za-z0-9]{4})'", script):
    has_item[code] = has_item.get(code, 0) + 1

items = load_items()
print("gain actions", [name for name in bodies if name.endswith("_Gain_Actions")])
sample = bodies.get("Trig_Mastery_Gain_Actions", "")
print("sample len", len(sample))
print(repr(sample[:400]))
matches = re.findall(
    r"if\((Trig_\w+)\(\)\)then\nset udg_(\w+)\[[^\n]*\+(\d+(?:\.\d+)?)\)",
    sample,
)
print("matches", matches[:5], "n", len(matches))
print("stack stat codes", len(stack_stats), "damage", len(damage), "has-item", len(has_item))
print("I00D haste/stats", stack_stats.get("I00D"), "dmg", damage.get("I00D"), "has", has_item.get("I00D"))
print("sample haste", list(stack_stats.items())[:3])
