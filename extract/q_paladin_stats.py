import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import MAP_PATH, _extract, _parse_objects, _resolve, map_strings

# reparse keeping base id
from sunken_sim.library import _Reader

blob = _extract(MAP_PATH, "war3map.w3u")
reader = _Reader(blob)
version = reader.u32()
strings = map_strings()
found = None
for _table in range(2):
    count = reader.u32()
    for _ in range(count):
        base = reader.raw4().decode("latin1")
        new = reader.raw4().decode("latin1")
        sets = reader.u32() if version >= 3 else 1
        mods = {}
        for _set in range(sets):
            if version >= 3:
                reader.u32()
            nmod = reader.u32()
            for __ in range(nmod):
                mid = reader.raw4().decode("latin1")
                vtype = reader.u32()
                if vtype == 0:
                    val = reader.i32()
                elif vtype in (1, 2):
                    val = reader.f32()
                elif vtype == 3:
                    val = reader.cstr()
                else:
                    raise RuntimeError(vtype)
                if version > 0:
                    reader.raw4()
                mods.setdefault(mid, []).append(val)
        blob_s = " ".join(str(v) for vals in mods.values() for v in vals)
        if new == "H000" or "A0GE" in blob_s:
            found = (base, new, mods)

base, new, mods = found
print("base", base, "new", new)
for key in sorted(mods):
    vals = mods[key]
    shown = []
    for val in vals:
        if isinstance(val, str) and val.startswith("TRIGSTR_"):
            shown.append(_resolve(val, strings)[:80])
        else:
            shown.append(val)
    print(key, shown)
