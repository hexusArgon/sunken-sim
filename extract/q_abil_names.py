import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import MAP_PATH, _extract, _load_strings, _parse_objects, _resolve, map_strings

strings = map_strings()
units = _parse_objects(_extract(MAP_PATH, "war3map.w3u"))
priest = units.get("O009") or units.get("H00I")
print("priest keys", "O009" in units, "sample unit ids", [c for c in units if c.startswith("O") or "priest" in c.lower()][:20])
# find priest by name
for code, mods in units.items():
    if "unam" not in mods:
        continue
    name = _resolve(str(mods["unam"][0]), strings)
    if "Priest" in name or "priest" in name:
        print("UNIT", code, name)
        print(" uabi", mods.get("uabi"))

# ability names
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

want = {"A0GK", "A0MC", "A0CP", "A0KI", "A0GC", "A0MI", "A0GS", "A0GB", "A0JK", "A0MH", "A0J8"}
pos = 0
version, pos = u32(blob, pos)
names = {}
for _table in range(2):
    count, pos = u32(blob, pos)
    for _ in range(count):
        base, pos = raw4(blob, pos)
        new, pos = raw4(blob, pos)
        sets = 1
        if version >= 3:
            sets, pos = u32(blob, pos)
        code = new if new.strip("\x00") else base
        anam = None
        atp1 = None
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
                if code in want and mod_id in ("anam", "atp1", "aub1", "ahky"):
                    if mod_id == "anam":
                        anam = _resolve(value, strings) if isinstance(value, str) else value
                    if mod_id == "atp1" and level == 1:
                        atp1 = _resolve(value, strings)[:120] if isinstance(value, str) else value
        if code in want:
            names[code] = (anam, atp1)
for code in want:
    print(code, names.get(code))
