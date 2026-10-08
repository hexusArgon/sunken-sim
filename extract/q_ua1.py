import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import MAP_PATH, _Reader, _extract

blob = _extract(MAP_PATH, "war3map.w3u")
reader = _Reader(blob)
version = reader.u32()
want = {"O009", "H000", "Hpal"}
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
                    raise RuntimeError(mid)
                if version > 0:
                    reader.raw4()
                mods.setdefault(mid, []).append(val)
        if new in want or base in want and new.strip("\x00") in want:
            print(new, "base", base, {k: mods[k] for k in mods if k.startswith("ua1")})
