"""Write the item self-stack canvas from map triggers and item abilities."""

import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import MAP_PATH, WTS_PATH, _extract, _load_strings, _parse_objects, load_items
from sunken_sim.search import LEGENDARIES

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

bodies = {}
for match in re.finditer(r"function (Trig_\w+) takes nothing returns", script):
    name = match.group(1)
    end = script.find("endfunction", match.end())
    bodies[name] = script[match.end() : end]


def codes_of(name, seen=None):
    if seen is None:
        seen = set()
    if name in seen or name not in bodies:
        return set()
    seen.add(name)
    body = bodies[name]
    found = set(re.findall(r"GetItemTypeId\(GetManipulatedItem\(\)\)=='([A-Za-z0-9]{4})'", body))
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
    "Potency_Stat": "Potency",
    "Potency_Items": "Potency",
    "Luck_Stat": "Luck",
    "Luck_Items": "Luck",
    "HealingPower_Items": "сила лечения",
    "MagicFind_Items": "Magic Find",
    "PetDamage_Items": "урон питомца",
    "Taunt_Items": "Taunt",
}

stack_stats: dict[str, list[str]] = {}
for fname, body in bodies.items():
    if not fname.endswith("_Gain_Actions"):
        continue
    for func, var, amount in re.findall(
        r"if\((Trig_\w+)\(\)\)then\nset udg_(\w+)\[[^\n]*\+(\d+(?:\.\d+)?)\)",
        body,
    ):
        value = float(amount) if "." in amount else int(amount)
        if var.startswith("AttackSpeed") and isinstance(value, float) and value < 1:
            text = f"скорость атаки +{round(value * 100):g}%"
        else:
            label = STAT.get(var, var)
            shown = int(value) if float(value).is_integer() else value
            text = f"{label} +{shown}"
        for code in codes_of(func):
            stack_stats.setdefault(code, [])
            if text not in stack_stats[code]:
                stack_stats[code].append(text)

damage = {}
for code, amount in re.findall(
    r"set udg_DCS_ItemInt='([A-Za-z0-9]{4})'\nset udg_DCS_ItemDamageBonus=(\d+)",
    script,
):
    if int(amount):
        damage[code] = int(amount)

has_item = set(re.findall(r"UnitHasItemOfTypeBJ\([^,]+,'([A-Za-z0-9]{4})'", script))

# ability stat fields
blob = _extract(MAP_PATH, "war3map.w3a")

def u32(data, i):
    return struct.unpack_from("<I", data, i)[0], i + 4

def i32(data, i):
    return struct.unpack_from("<i", data, i)[0], i + 4

def f32(data, i):
    return struct.unpack_from("<f", data, i)[0], i + 4

def raw4(data, i):
    return data[i : i + 4].decode("latin1"), i + 4

def cstr(data, i):
    end = data.index(b"\x00", i)
    return data[i:end], end + 1

ABILITY_STAT = {
    "Iint": "интеллект",
    "Istr": "сила",
    "Iagi": "ловкость",
    "Idam": "урон",
    "Iarp": "броня",
    "Ilif": "здоровье",
    "Impg": "мана",
    "Isx1": "скорость атаки",
}
ability_stats: dict[str, list[str]] = {}
pos = 0
version, pos = u32(blob, pos)
unknown = set()
for _table in range(2):
    count, pos = u32(blob, pos)
    for _ in range(count):
        base, pos = raw4(blob, pos)
        new, pos = raw4(blob, pos)
        sets = 1
        if version >= 3:
            sets, pos = u32(blob, pos)
        code = new if new.strip("\x00") else base
        stats = []
        for _s in range(sets):
            if version >= 3:
                pos += 4
            mod_count, pos = u32(blob, pos)
            for _m in range(mod_count):
                mod_id, pos = raw4(blob, pos)
                value_type, pos = u32(blob, pos)
                level, pos = i32(blob, pos)
                _dataptr, pos = i32(blob, pos)
                if value_type == 0:
                    value, pos = i32(blob, pos)
                elif value_type in (1, 2):
                    value, pos = f32(blob, pos)
                elif value_type == 3:
                    value, pos = cstr(blob, pos)
                else:
                    raise RuntimeError(value_type)
                if version > 0:
                    pos += 4
                if level == 1 and mod_id in ABILITY_STAT and isinstance(value, (int, float)) and value:
                    label = ABILITY_STAT[mod_id]
                    number = float(value)
                    if mod_id == "Isx1" and number <= 5:
                        stats.append(f"{label} +{round(number * 100):g}%")
                    else:
                        shown = int(number) if number.is_integer() else round(number, 2)
                        stats.append(f"{label} +{shown}")
        if stats:
            ability_stats[code] = stats

objects = _parse_objects(_extract(MAP_PATH, "war3map.w3t"))
ORBS = {"I07O", "I0NS", "I0NT"}
rows = []
for item in load_items():
    code = item.rawcode
    stacks = list(stack_stats.get(code, []))
    if code in damage:
        stacks.append(f"белый урон +{damage[code]}")
    blocked = []
    abi = objects.get(code, {}).get("iabi", [""])[0]
    for part in abi.split(","):
        for stat in ability_stats.get(part, []):
            if stat not in blocked:
                blocked.append(f"способность: {stat}")
    if code in has_item:
        blocked.append("эффект «вещь надета» один раз")
    if code in LEGENDARIES:
        blocked.append("вторая легендарка удаляется")
    if code in ORBS:
        blocked.append("второй Elemental Orb удаляется")
    if code == "I00D":
        blocked.append("одна привязка заклинания, −30% кулдауна один раз")
    if not stacks and not blocked:
        continue
    if stacks and blocked:
        verdict = "Частично"
    elif stacks:
        verdict = "Стакается"
    else:
        verdict = "Не стакается"
    rows.append(
        {
            "name": item.name,
            "code": code,
            "verdict": verdict,
            "stacks": ", ".join(stacks),
            "blocked": ", ".join(blocked),
        }
    )

rows.sort(key=lambda row: (row["verdict"], row["name"]))
counts = {key: sum(1 for row in rows if row["verdict"] == key) for key in ("Стакается", "Не стакается", "Частично")}
print("rows", len(rows), counts)
print("unknown ability fields", sorted(unknown))
print("ring", next(row for row in rows if row["code"] == "I00D"))

out = Path(r"C:\Users\eseid\sunken-sim\extract\stack-rows.json")
out.write_text(json.dumps({"counts": counts, "rows": rows}, ensure_ascii=False), encoding="utf-8")
print("wrote", out)
