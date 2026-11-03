"""Load item names and stat lines from the Sunken City map."""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

MAP_PATH = Path(__file__).resolve().parents[1] / "maps" / "Sunken City v2.5.2a.w3x"

OTHER_HEROES = (
    "Death Knight",
    "Demon Hunter",
    "Witch Doctor",
    "Windmaster",
    "Tidewarrior",
    "Necromancer",
    "Berserker",
    "Warlock",
    "Warrior",
    "Paladin",
    "Shaman",
    "Hunter",
    "Rogue",
    "Druid",
    "Mage",
    "Monk",
    "Siren",
    "Tinker",
    "Dragon Sentinel",
)


def _crypt_table():
    seed = 0x00100001
    table = [0] * 0x500
    for index1 in range(0x100):
        index2 = index1
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp1 = (seed & 0xFFFF) << 0x10
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp2 = seed & 0xFFFF
            table[index2] = (temp1 | temp2) & 0xFFFFFFFF
            index2 += 0x100
    return table


CT = _crypt_table()


def _hash_string(text: str, hash_type: int) -> int:
    seed1 = 0x7FED7FED
    seed2 = 0xEEEEEEEE
    for ch in text.replace("/", "\\").upper():
        code = ord(ch)
        seed1 = (CT[(hash_type << 8) + code] ^ ((seed1 + seed2) & 0xFFFFFFFF)) & 0xFFFFFFFF
        seed2 = (code + seed1 + seed2 + ((seed2 << 5) & 0xFFFFFFFF) + 3) & 0xFFFFFFFF
    return seed1


def _decrypt(raw: bytes, key: int) -> bytes:
    seed = 0xEEEEEEEE
    key &= 0xFFFFFFFF
    size = len(raw) & ~3
    out = bytearray()
    for offset in range(0, size, 4):
        seed = (seed + CT[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        value = struct.unpack_from("<I", raw, offset)[0]
        value = (value ^ ((key + seed) & 0xFFFFFFFF)) & 0xFFFFFFFF
        key = ((((~key) << 0x15) & 0xFFFFFFFF) + 0x11111111) | (key >> 0x0B)
        key &= 0xFFFFFFFF
        seed = (value + seed + ((seed << 5) & 0xFFFFFFFF) + 3) & 0xFFFFFFFF
        out += struct.pack("<I", value)
    out += raw[size:]
    return bytes(out)


class _Reader:
    def __init__(self, blob: bytes):
        self.blob = blob
        self.offset = 0

    def u32(self) -> int:
        value = struct.unpack_from("<I", self.blob, self.offset)[0]
        self.offset += 4
        return value

    def i32(self) -> int:
        value = struct.unpack_from("<i", self.blob, self.offset)[0]
        self.offset += 4
        return value

    def f32(self) -> float:
        value = struct.unpack_from("<f", self.blob, self.offset)[0]
        self.offset += 4
        return value

    def raw4(self) -> bytes:
        value = self.blob[self.offset : self.offset + 4]
        self.offset += 4
        return value

    def cstr(self) -> str:
        end = self.blob.index(0, self.offset)
        raw = self.blob[self.offset : end]
        self.offset = end + 1
        return raw.decode("utf-8", "replace")


@lru_cache(maxsize=2)
def _map_bytes(path: str) -> bytes:
    return Path(path).read_bytes()


def _archive_tables(data: bytes):
    _version, shift = struct.unpack_from("<HH", data, 12)
    hash_off, block_off, hash_n, block_n = struct.unpack_from("<IIII", data, 16)
    sector_size = 512 << shift
    hashes = _decrypt(data[hash_off : hash_off + hash_n * 16], _hash_string("(hash table)", 3))
    blocks = _decrypt(data[block_off : block_off + block_n * 16], _hash_string("(block table)", 3))
    entries = [struct.unpack_from("<IIHHI", hashes, index * 16) for index in range(hash_n)]
    return sector_size, entries, blocks


def _table_key(encrypted: int, plain: int) -> int | None:
    """File key minus one, from the known first sector offset."""
    for low in range(256):
        seed = (0xEEEEEEEE + CT[0x400 + low]) & 0xFFFFFFFF
        key = ((encrypted ^ plain) - seed) & 0xFFFFFFFF
        if (key & 0xFF) == low:
            return key
    return None


def _decode_block(
    data: bytes,
    sector_size: int,
    file_pos: int,
    comp_size: int,
    file_size: int,
    flags: int,
    key: int,
    limit: int | None = None,
) -> bytes:
    raw = data[file_pos : file_pos + comp_size]
    encrypted = bool(flags & 0x00010000)
    compressed = bool(flags & 0x00000200)
    if not compressed:
        blob = _decrypt(raw, key) if encrypted else raw
        return blob[: file_size if limit is None else min(file_size, limit)]
    sectors = (file_size + sector_size - 1) // sector_size
    table_bytes = (sectors + 1) * 4
    table = _decrypt(raw[:table_bytes], (key - 1) & 0xFFFFFFFF) if encrypted else raw[:table_bytes]
    offsets = list(struct.unpack("<" + "I" * (sectors + 1), table[:table_bytes]))
    out = bytearray()
    last = sectors if limit is None else min(sectors, (limit + sector_size - 1) // sector_size)
    for index in range(last):
        chunk = raw[offsets[index] : offsets[index + 1]]
        remain = file_size - len(out)
        if encrypted:
            chunk = _decrypt(chunk, (key + index) & 0xFFFFFFFF)
        if len(chunk) == min(sector_size, remain):
            out += chunk
        else:
            out += zlib.decompress(chunk[1:])
        if limit is not None and len(out) >= limit:
            break
    if limit is not None:
        return bytes(out[:limit])
    return bytes(out[:file_size])


def _extract(path: Path, name: str) -> bytes:
    data = _map_bytes(str(path))
    sector_size, entries, blocks = _archive_tables(data)
    hash_n = len(entries)
    slot = _hash_string(name, 0) % hash_n
    name_a, name_b = _hash_string(name, 1), _hash_string(name, 2)
    found = None
    for _ in range(hash_n):
        hash_a, hash_b, _loc, _plat, block_index = entries[slot]
        if block_index == 0xFFFFFFFF:
            break
        if hash_a == name_a and hash_b == name_b and block_index != 0xFFFFFFFE:
            found = block_index
            break
        slot = (slot + 1) % hash_n
    if found is None:
        raise FileNotFoundError(name)
    file_pos, comp_size, file_size, flags = struct.unpack_from("<IIII", blocks, found * 16)
    return _decode_block(data, sector_size, file_pos, comp_size, file_size, flags, _hash_string(name, 3))


def _extract_script(path: Path) -> bytes:
    """The map script is stored without the usual war3map.j name."""
    data = _map_bytes(str(path))
    sector_size, entries, blocks = _archive_tables(data)
    seen: set[int] = set()
    candidates: list[tuple[int, int, int, int, int]] = []
    for _hash_a, _hash_b, _loc, _plat, block_index in entries:
        if block_index in (0xFFFFFFFF, 0xFFFFFFFE) or block_index in seen:
            continue
        seen.add(block_index)
        file_pos, comp_size, file_size, flags = struct.unpack_from("<IIII", blocks, block_index * 16)
        if file_size < 1000 or not (flags & 0x00000200):
            continue
        candidates.append((file_size, file_pos, comp_size, flags, block_index))
    candidates.sort(reverse=True)
    for file_size, file_pos, comp_size, flags, _block_index in candidates:
        sectors = (file_size + sector_size - 1) // sector_size
        table_bytes = (sectors + 1) * 4
        encrypted_first = struct.unpack_from("<I", data, file_pos)[0]
        table_key = _table_key(encrypted_first, table_bytes)
        if table_key is None:
            continue
        file_key = (table_key + 1) & 0xFFFFFFFF
        try:
            head = _decode_block(data, sector_size, file_pos, comp_size, file_size, flags, file_key, 32)
        except Exception:
            continue
        head = head.lstrip(b"\xef\xbb\xbf")
        if head.startswith((b"globals", b"function", b"//")):
            return _decode_block(data, sector_size, file_pos, comp_size, file_size, flags, file_key)
    raise FileNotFoundError("war3map.j")


def _map_text(name: str) -> str:
    try:
        blob = _extract(MAP_PATH, name)
    except FileNotFoundError:
        if name != "war3map.j":
            raise
        blob = _extract_script(MAP_PATH)
    return blob.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")


@lru_cache(maxsize=1)
def map_script() -> str:
    return _map_text("war3map.j")


@lru_cache(maxsize=1)
def map_wts_text() -> str:
    return _map_text("war3map.wts")


def _parse_strings(text: str) -> dict[int, str]:
    strings = {}
    for match in re.finditer(r"STRING\s+(\d+)\s*\r?\n\{\r?\n(.*?)\r?\n\}", text, re.S):
        strings[int(match.group(1))] = match.group(2)
    return strings


@lru_cache(maxsize=1)
def map_strings() -> dict[int, str]:
    return _parse_strings(_map_text("war3map.wts"))


def _parse_objects(blob: bytes) -> dict[str, dict]:
    reader = _Reader(blob)
    version = reader.u32()
    objects: dict[str, dict] = {}
    for _table in range(2):
        count = reader.u32()
        for _ in range(count):
            base = reader.raw4().decode("latin1")
            new = reader.raw4().decode("latin1")
            sets = reader.u32() if version >= 3 else 1
            mods: dict[str, list] = {}
            for _set in range(sets):
                if version >= 3:
                    reader.u32()
                mod_count = reader.u32()
                for _mod in range(mod_count):
                    mod_id = reader.raw4().decode("latin1")
                    value_type = reader.u32()
                    if value_type == 0:
                        value = reader.i32()
                    elif value_type in (1, 2):
                        value = reader.f32()
                    elif value_type == 3:
                        value = reader.cstr()
                    else:
                        raise RuntimeError(f"bad object type {value_type}")
                    if version > 0:
                        reader.raw4()
                    mods.setdefault(mod_id, []).append(value)
            rawcode = new if new.strip("\x00") else base
            if rawcode.strip("\x00"):
                objects[rawcode] = mods
    return objects


def _load_strings(path: Path) -> dict[int, str]:
    return _parse_strings(path.read_text(encoding="utf-8", errors="replace"))


def _resolve(value: str, strings: dict[int, str]) -> str:
    match = re.fullmatch(r"TRIGSTR_(\d+)", value or "")
    if not match:
        return value or ""
    text = strings.get(int(match.group(1)), "")
    text = re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", text)
    text = text.replace("|n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    return text


def _sum_ints(pattern: str, text: str) -> int:
    return sum(int(float(match)) for match in re.findall(pattern, text, flags=re.I | re.M))


def _outgoing_parts(tip: str) -> tuple[int, int]:
    """Always-on outgoing percents: (all sources, magical and physical).

    Skips damage taken, timed procs, a primary-stat branch, a multiplicative
    line, and a bonus that only applies to stunned or frozen enemies.
    """
    sources = 0
    both = 0
    for line in tip.split("\n"):
        low = line.lower()
        if "damage taken" in low or "damage you take" in low:
            continue
        if re.search(r"for \d+(?:[.,]\d+)? seconds", low):
            continue
        if re.search(r"\b(?:strength|agility|intelligence)\s*:", low):
            continue
        if "multiplicatively" in low or "stunned" in low or "frozen" in low:
            continue
        sources += _sum_ints(r"all sources by (\d+)%", line)
        both += _sum_ints(r"Magical and Physical Type effects by (\d+)%", line)
    return sources, both


def _sum_floats(pattern: str, text: str) -> float:
    return sum(float(match.replace(",", ".")) for match in re.findall(pattern, text, flags=re.I | re.M))


def _first_float(pattern: str, text: str) -> float:
    match = re.search(pattern, text, flags=re.I)
    if not match:
        return 0.0
    return float(match.group(1).replace(",", "."))


def _execute(tip: str) -> tuple[float, float]:
    matches = re.findall(
        r"(\d+)% more damage to enemies below (\d+(?:[.,]\d+)?)% of maximum health",
        tip,
        flags=re.I,
    )
    if not matches:
        return 0.0, 0.0
    percent = sum(int(amount) for amount, _threshold in matches) / 100
    threshold = float(matches[0][1].replace(",", ".")) / 100
    return percent, threshold


def _signed_pct(line_pattern: str, text: str) -> int:
    total = 0
    for sign, number in re.findall(line_pattern, text, flags=re.I | re.M):
        total += int(number) if sign == "+" else -int(number)
    return total


@dataclass
class Item:
    rawcode: str
    name: str
    tip: str
    intel: int = 0
    strength: int = 0
    agility: int = 0
    all_stats: int = 0
    potency: int = 0
    mastery: int = 0
    damage: int = 0
    mana: int = 0
    crit: float = 0.0
    crit_rating: float = 0.0
    haste: float = 0.0
    attack_speed: float = 0.0
    damage_pct: float = 0.0
    source_pct: float = 0.0
    cooldown_add: float = 0.0
    cdr_pct: float = 0.0
    stun_chance: float = 0.0
    stun_duration: float = 0.0
    cast_stun_chance: float = 0.0
    cast_stun_duration: float = 0.0
    spell_crit: bool = False
    double_attack_potency: bool = False
    auto_pct: float = 0.0
    execute_pct: float = 0.0
    execute_below: float = 0.0
    armor_pen: float = 0.0
    crit_as: float = 0.0
    crit_as_duration: float = 0.0
    stab_chance: float = 0.0
    stab_ratio: float = 0.0
    armor: int = 0

    @property
    def offense(self) -> int:
        return (
            self.intel
            + self.all_stats
            + self.potency
            + self.mastery
            + self.damage
            + self.mana // 20
            + int(self.crit)
            + int(self.haste)
            + int(self.attack_speed)
            + int(self.damage_pct)
        )


def _parse_tip(tip: str) -> dict:
    lines = tip.split("\n")
    stat_text = "\n".join(line for line in lines if line.startswith("+") or "Equip:" in line or "Increases" in line)
    sources, both = _outgoing_parts(tip)
    return {
        "intel": _sum_ints(r"^\+(\d+) Intelligence\b", "\n".join(lines)),
        "strength": _sum_ints(r"^\+(\d+) Strength\b", "\n".join(lines)),
        "agility": _sum_ints(r"^\+(\d+) Agility\b", "\n".join(lines)),
        "all_stats": _sum_ints(r"^\+(\d+) (?:to )?All Stats\b", "\n".join(lines)),
        "potency": _sum_ints(r"^\+(\d+) Potency\b", "\n".join(lines)),
        "mastery": _sum_ints(r"^\+(\d+) Mastery\b", "\n".join(lines)),
        "damage": _sum_ints(r"^\+(\d+) (?:Attack )?Damage\b", "\n".join(lines)),
        # Flat "+N Mana" only; "+N Mana per 5 seconds" is regen, not max mana.
        "mana": _sum_ints(r"^\+(\d+) Mana\b(?! per\b)", "\n".join(lines)),
        "crit": _sum_ints(r"^\+(\d+)% Critical Strike\b", "\n".join(lines))
        + _sum_ints(r"Critical Strike by (\d+)%", stat_text),
        "crit_rating": _sum_ints(r"Critical Strike bonus damage is increased by additional (\d+)%", tip) / 100,
        "haste": _sum_ints(r"^\+(\d+)% Haste\b", "\n".join(lines))
        + _sum_ints(r"Haste by (\d+)%", stat_text),
        "attack_speed": _signed_pct(r"^([+-])(\d+)% Attack Speed\b", "\n".join(lines)),
        "damage_pct": sources + both,
        "source_pct": sources,
        "cooldown_add": _sum_floats(r"cooldowns of all abilities by (\d+(?:[.,]\d+)?) second", tip),
        "cdr_pct": _sum_ints(r"abilities have their base cooldown reduced by (\d+)%", tip) / 100,
        "stun_chance": _sum_ints(r"(\d+)% chance to Stun you", "\n".join(line for line in lines if "spellcasts have" not in line.lower())) / 100,
        "stun_duration": _first_float(r"Stun you for (\d+(?:[.,]\d+)?)", "\n".join(line for line in lines if "spellcasts have" not in line.lower())),
        "cast_stun_chance": _sum_ints(r"spellcasts have (\d+)% chance to stun you", tip) / 100,
        "cast_stun_duration": _first_float(r"spellcasts have \d+% chance to stun you for (\d+(?:[.,]\d+)?)", tip),
        "spell_crit": "Magical Type effects benefit from Critical Strike" in tip,
        "double_attack_potency": "Potency at double effectiveness" in tip,
        "auto_pct": _sum_ints(r"auto-attacks by (\d+)%", tip) / 100,
        "execute_pct": _execute(tip)[0],
        "execute_below": _execute(tip)[1],
        "armor_pen": _sum_ints(r"ignore (\d+) of the target's Armor", tip),
        "crit_as": _sum_ints(r"Critical Strikes grant you (\d+)% Attack Speed for", tip) / 100,
        "crit_as_duration": _first_float(r"Attack Speed for (\d+(?:[.,]\d+)?) second", tip),
        "stab_chance": _sum_ints(r"(\d+)% chance to stab", tip) / 100,
        "stab_ratio": _sum_ints(r"stab the target with darkness, dealing Attrition damage equal to (\d+)%", tip) / 100,
        "armor": _signed_pct(r"^([+-])(\d+) Armor\b", "\n".join(lines)),
    }


# Soul Lantern (I06D): tip "+150 Mana" plus Soul Shards "+4 Mana, up to a
# maximum of 200". Sims take the shard cap as reached (user rule): 150 + 200.
SOUL_LANTERN = "I06D"
SOUL_LANTERN_MANA = 150 + 200
MANA_OVERRIDES = {SOUL_LANTERN: SOUL_LANTERN_MANA}


def _blocked_for_priest(name: str, tip: str) -> bool:
    blob = f"{name}\n{tip}"
    if "Priest" in blob:
        return False
    return any(hero in blob for hero in OTHER_HEROES)


def load_items() -> list[Item]:
    strings = map_strings()
    skin = _parse_objects(_extract(MAP_PATH, "war3mapSkin.w3t"))
    items: list[Item] = []
    for rawcode, mods in skin.items():
        if "unam" not in mods or "utub" not in mods:
            continue
        name = _resolve(mods["unam"][0], strings).strip()
        tip = _resolve(mods["utub"][0], strings).strip()
        if not name:
            continue
        stats = _parse_tip(tip)
        item = Item(
            rawcode=rawcode,
            name=name,
            tip=tip,
            **{key: value for key, value in stats.items() if key != "spell_crit"},
            spell_crit=stats["spell_crit"],
        )
        if rawcode in MANA_OVERRIDES:
            item.mana = MANA_OVERRIDES[rawcode]
        items.append(item)
    items.sort(key=lambda item: item.name)
    return items
