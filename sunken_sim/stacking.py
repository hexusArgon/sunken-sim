"""Which item bonuses apply again on a second copy.

Pickup counters and per-slot white damage stack. Item abilities and
"the hero has this item" effects do not. A second legendary or a second
Elemental Orb is removed by the map.
"""

from __future__ import annotations

import re
from functools import lru_cache

ORBS = frozenset({"I07O", "I0NS", "I0NT"})
LEGENDARIES = frozenset({"I052", "I048", "I053", "I04A", "I0HU", "I09E", "I044", "I0BR"})

_FIELD_BY_VARIABLE = {
    "Haste_Items": "haste",
    "Mastery_Stat": "mastery",
    "CriticalStrike_ChanceFlat": "crit",
    "CriticalStrike_RatingFlat": "crit_rating",
    "PA_Items": "primary",
    "AttackSpeed_Items": "attack_speed",
    "Potency_Items": "potency",
    "Potency_Stat": "potency",
    "Luck_Items": "luck",
    "Luck_Stat": "luck",
}


def _script() -> str:
    from sunken_sim.library import map_script

    return map_script()


def _bodies(script: str) -> dict[str, str]:
    bodies = {}
    for match in re.finditer(r"function (Trig_\w+) takes nothing returns", script):
        end = script.find("endfunction", match.end())
        bodies[match.group(1)] = script[match.end() : end]
    return bodies


def _codes_of(name: str, bodies: dict[str, str], seen: set[str] | None = None) -> set[str]:
    if seen is None:
        seen = set()
    if name in seen or name not in bodies:
        return set()
    seen.add(name)
    body = bodies[name]
    found = set(re.findall(r"GetItemTypeId\(GetManipulatedItem\(\)\)=='([A-Za-z0-9]{4})'", body))
    for child in re.findall(r"(Trig_\w+)\(\)", body):
        found |= _codes_of(child, bodies, seen)
    return found


@lru_cache(maxsize=1)
def stack_profiles() -> dict[str, dict[str, float]]:
    script = _script()
    bodies = _bodies(script)
    profiles: dict[str, dict[str, float]] = {}

    def add(code: str, field: str, amount: float) -> None:
        profile = profiles.setdefault(code, {})
        profile[field] = profile.get(field, 0.0) + amount

    for name, body in bodies.items():
        if not name.endswith("_Gain_Actions"):
            continue
        for func, var, amount in re.findall(
            r"if\((Trig_\w+)\(\)\)then\nset udg_(\w+)\[[^\n]*\+(\d+(?:\.\d+)?)\)",
            body,
        ):
            field = _FIELD_BY_VARIABLE.get(var)
            if field is None:
                continue
            value = float(amount)
            if field == "attack_speed" and value < 1:
                value *= 100
            for code in _codes_of(func, bodies):
                add(code, field, value)

    for code, amount in re.findall(
        r"set udg_DCS_ItemInt='([A-Za-z0-9]{4})'\nset udg_DCS_ItemDamageBonus=(\d+)",
        script,
    ):
        if int(amount):
            add(code, "damage", float(amount))
    return profiles


def stack_fields(rawcode: str) -> dict[str, float]:
    return stack_profiles().get(rawcode, {})


def allows_copies(rawcode: str) -> bool:
    if rawcode in LEGENDARIES or rawcode in ORBS:
        return False
    return item_verdict(rawcode) == "Стакается"


def _has_item_codes(script: str) -> set[str]:
    return set(re.findall(r"UnitHasItemOfTypeBJ\([^,]+,'([A-Za-z0-9]{4})'", script))


def _ability_stat_codes() -> set[str]:
    import struct

    from sunken_sim.library import _extract, _parse_objects, MAP_PATH

    fields = {"Iint", "Istr", "Iagi", "Idam", "Iarp", "Ilif", "Impg", "Isx1"}
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

    stat_abilities = set()
    pos = 0
    version, pos = u32(blob, pos)
    for _table in range(2):
        count, pos = u32(blob, pos)
        for _ in range(count):
            base, pos = raw4(blob, pos)
            new, pos = raw4(blob, pos)
            sets = 1
            if version >= 3:
                sets, pos = u32(blob, pos)
            code = new if new.strip("\x00") else base
            has_stat = False
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
                        _value, pos = cstr(blob, pos)
                        value = 0
                    else:
                        raise RuntimeError(value_type)
                    if version > 0:
                        pos += 4
                    if level == 1 and mod_id in fields and value:
                        has_stat = True
            if has_stat:
                stat_abilities.add(code)
    objects = _parse_objects(_extract(MAP_PATH, "war3map.w3t"))
    owners = set()
    for code, mods in objects.items():
        abi = str(mods.get("iabi", [""])[0])
        if any(part in stat_abilities for part in abi.split(",")):
            owners.add(code)
    return owners


@lru_cache(maxsize=1)
def _blocked_codes() -> set[str]:
    blocked = _has_item_codes(_script()) | _ability_stat_codes()
    return blocked


def item_verdict(rawcode: str) -> str:
    stacks = bool(stack_fields(rawcode))
    blocked = rawcode in _blocked_codes()
    if stacks and blocked:
        return "Частично"
    if stacks:
        return "Стакается"
    if blocked:
        return "Не стакается"
    return "Нет данных"
