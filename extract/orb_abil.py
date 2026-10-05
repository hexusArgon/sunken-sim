from pathlib import Path
import struct, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
from sunken_sim.library import _extract, _load_strings, _resolve

MAP = Path(r"c:\Users\eseid\Documents\Warcraft III\Maps\Download\Sunken City v2.5.2a.w3x")
strings = _load_strings(Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.wts"))
blob = _extract(MAP, "war3map.w3a")
want = {"A0AM", "A0AO", "A0AT", "A0AU", "A06G", "A07F"}

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

pos = 0
version, pos = u32(blob, pos)
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
            print("\n====", code, "base", base)
            for mod_id, level, value in mods:
                if isinstance(value, str) and value.startswith("TRIGSTR_"):
                    value = _resolve(value, strings)[:300].replace("\n", " | ")
                if mod_id in ("anam", "aub1", "arhk", "ahky", "aret", "alev", "Eme1", "Eme2", "Oae1", "Oae2", "Uau1", "Uau2", "DataA", "DataB", "DataC", "abuf", "aare", "atat", "Htb1", "Iob1"):
                    print(f"  {mod_id} L{level}: {value}")
print("done", pos, len(blob))
