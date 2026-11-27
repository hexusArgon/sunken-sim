"""One-slot screen on the exact OpenCL kernels (no Python fight model).

    python3.11 tools/one_slot_gpu.py berserker

Each talent, each item of the class pools, each glyph alone on the bare hero, 5 targets,
for every spec -> extract/<hero>-one-slot.json (same layout as the old extract/one_slot_<hero>.py).
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

HEROES = {
    "berserker": dict(class_name="Berserker", module="farm.hybrid.berserker_cl", engine="BerserkerCL",
                      specs=(("Headhunter", "headhunter"), ("Poison", "poison"), ("Fury", "fury"))),
    "death_knight": dict(class_name="DeathKnight", module="farm.hybrid.death_knight_cl", engine="DeathKnightCL",
                         specs=(("Frost", "frost"), ("Blood", "blood"), ("Unholy", "unholy"))),
}
TARGETS = 5


def main() -> None:
    from farm import runner as R
    from farm.hybrid import class_cl as C
    from sunken_sim.esc import ESC_ATTRS
    from sunken_sim.search import GLYPHS, LEGENDARIES, pools_for
    from sunken_sim.library import load_items
    from sunken_sim.shadow import ORB_MODE

    hero = sys.argv[1]
    cfg = HEROES[hero]
    mod = importlib.import_module(cfg["module"])
    space, items = C.full_space(hero, cfg["class_name"], mod.TALENT_NAMES)
    sources = R.source_map(items)
    shop, drop, legs = pools_for(load_items(), cfg["class_name"])
    shop_ids = {i.rawcode for i in shop}
    pool = {}
    for item in shop + drop + legs:
        label = f"{item.name} ({ORB_MODE[item.rawcode]})" if item.rawcode in ORB_MODE else item.name
        src = "Legendary" if item.rawcode in LEGENDARIES else "Shop" if item.rawcode in shop_ids else "Drop"
        pool[item.rawcode] = (label, src)
    talents = sorted(((c, n) for c, n in mod.TALENT_NAMES.items() if c not in mod.IGNORED_TALENTS), key=lambda p: p[1])
    glyphs = sorted(GLYPHS.items(), key=lambda p: p[1])
    titles = [t for t, _ in cfg["specs"]]
    zero = [0] * len(ESC_ATTRS)

    cases = [((), (), ())] + [((), (c,), ()) for c, _ in talents] + [((code,), (), ()) for code in pool] + \
            [((), (), (c,)) for c, _ in glyphs]
    value = {}
    for title, spec in cfg["specs"]:
        engine = getattr(mod, cfg["engine"])(space, items, sources, TARGETS, None, spec)
        dps, _g, status = engine.pick([engine.picks_of(i) for i, _t, _gl in cases],
                                      [engine.talent_mask(t) for _i, t, _gl in cases],
                                      [engine.glyph_mask(gl) for _i, _t, gl in cases], [zero] * len(cases))
        if status.any():
            raise SystemExit(f"{spec}: kernel declined {int((status != 0).sum())} rows")
        value[title] = {case: round(float(d), 1) for case, d in zip(cases, dps)}
    bare = {t: value[t][((), (), ())] for t in titles}
    if not all(v > 0 for v in bare.values()):
        raise SystemExit(f"bare DPS is not positive: {bare}")

    talent_rows = [["Талант", "Код"] + [f"{t} DPS" for t in titles], ["Без таланта", ""] + [bare[t] for t in titles]]
    talent_rows += [[n, c] + [value[t][((), (c,), ())] for t in titles] for c, n in talents]
    item_rows = [["Предмет", "Код", "Источник"] + [f"{t} DPS" for t in titles] + [f"Привязка {t}" for t in titles],
                 ["Без предмета", "", ""] + [bare[t] for t in titles] + [""] * len(titles)]
    body = [[label, code, src] + [value[t][((code,), (), ())] for t in titles] + [""] * len(titles)
            for code, (label, src) in pool.items()]
    body.sort(key=lambda row: (-max(row[3:3 + len(titles)]), row[0]))
    item_rows += body
    glyph_rows = [["Глиф", "Код"] + [f"{t} DPS" for t in titles], ["Без глифа", ""] + [bare[t] for t in titles]]
    glyph_rows += [[n, c] + [value[t][((), (), (c,))] for t in titles] for c, n in glyphs]
    out = Path("extract") / f"{hero}-one-slot.json"
    out.write_text(json.dumps({"specs": titles, "talents": talent_rows, "items": item_rows, "glyphs": glyph_rows},
                              ensure_ascii=False), encoding="utf-8")
    print("wrote", out, "items", len(pool), "talents", len(talents), "glyphs", len(glyphs), "bare", bare)


if __name__ == "__main__":
    main()
