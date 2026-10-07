import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import MAP_PATH, _extract, _load_strings, _resolve, map_script, map_strings

strings = map_strings()
blob = _extract(MAP_PATH, "war3mapSkin.w3a")

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

want = {"A0NC", "A0F6", "A0MH"}
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
        texts = []
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
                if code in want and value_type == 3 and mod_id in ("anam", "atp1") and level in (0, 1, 2, 3):
                    text = _resolve(value, strings)
                    texts.append((mod_id, level, text[:80].replace("\n", " | ")))
        if code in want:
            print(code)
            for row in texts:
                print(" ", row)

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("function DivineImageIcon")
print("\n==== DivineImageIcon ====")
print(script[i : i + 900])
