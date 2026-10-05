import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
from sunken_sim.library import _extract, _parse_objects, MAP_PATH

items = _parse_objects(_extract(MAP_PATH, "war3map.w3t"))
print("I00D", items.get("I00D"))
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
    return data[i:end].decode("utf-8", "replace"), end + 1

want = set()
for code in ("I00D",):
    abi = items[code].get("iabi", [""])[0]
    want.update(part for part in abi.split(",") if part)

pos = 0
version, pos = u32(blob, pos)
found = {}
for table in range(2):
    count, pos = u32(blob, pos)
    for _ in range(count):
        base, pos = raw4(blob, pos)
        new, pos = raw4(blob, pos)
        sets = 1
        if version >= 3:
            sets, pos = u32(blob, pos)
        code = new if new.strip("\x00") else base
        mods = []
        for _s in range(sets):
            if version >= 3:
                pos += 4
            mod_count, pos = u32(blob, pos)
            for _m in range(mod_count):
                mod_id, pos = raw4(blob, pos)
                value_type, pos = u32(blob, pos)
                level, pos = i32(blob, pos)
                dataptr, pos = i32(blob, pos)
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
                mods.append((mod_id, level, value))
        if code in want:
            found[code] = (base, mods)
print("want", want)
for code, (base, mods) in found.items():
    print(code, "base", base)
    for mod in mods:
        if mod[0] in ("Iint", "Istr", "Iagi", "Iatt", "Idef", "Ihp ", "Iman", "Ihpx", "Inm1") or mod[1] == 1:
            print(" ", mod)
