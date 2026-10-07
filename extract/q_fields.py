from pathlib import Path
import struct
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import MAP_PATH, _extract, _parse_objects, load_items

items = {item.rawcode: item.name for item in load_items()}
objects = _parse_objects(_extract(MAP_PATH, "war3map.w3t"))
blob = _extract(MAP_PATH, "war3map.w3a")

def u32(data, i):
    return struct.unpack_from("<I", data, i)[0], i + 4
def i32(data, i):
    return struct.unpack_from("<i", data, i)[0], i + 4
def f32(data, i):
    return struct.unpack_from("<f", data, i)[0], i + 4
def raw4(data, i):
    return data[i:i+4].decode("latin1"), i + 4
def cstr(data, i):
    end = data.index(b"\x00", i)
    return data[i:end], end + 1

watch = {"Idam", "Isx1", "Iarp", "Ihps", "Impg", "Imrp", "Ihpr", "Ilif", "Ivam", "Ispi"}
found = {key: [] for key in watch}
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
        got = []
        for _s in range(sets):
            if version >= 3:
                pos += 4
            mod_count, pos = u32(blob, pos)
            for _m in range(mod_count):
                mod_id, pos = raw4(blob, pos)
                value_type, pos = u32(blob, pos)
                level, pos = i32(blob, pos)
                _d, pos = i32(blob, pos)
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
                if level == 1 and mod_id in watch and value:
                    got.append((mod_id, value))
        if got:
            found.setdefault(code, []).extend(got)

# reverse: ability -> items
abil_items = {}
for code, mods in objects.items():
    abi = mods.get("iabi", [""])[0]
    for part in str(abi).split(","):
        if part:
            abil_items.setdefault(part, []).append(code)

for field in watch:
    print("\n==", field)
    n = 0
    for abil, mods in found.items():
        for mod_id, value in mods:
            if mod_id != field:
                continue
            names = [items.get(c, c) for c in abil_items.get(abil, [])[:2]]
            if names:
                print(f"  {value} {abil} {names}")
                n += 1
            if n >= 4:
                break
        if n >= 4:
            break
