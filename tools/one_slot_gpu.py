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
    "demon_hunter": dict(class_name="DemonHunter", module="farm.hybrid.demon_hunter_cl", engine="DemonHunterCL",
                         specs=(("Havoc", "havoc"), ("Vengeance", "vengeance"), ("Devourer", "devourer"))),
    "dragon_sentinel": dict(class_name="DragonSentinel", module="farm.hybrid.dragon_sentinel_cl",
                            engine="DragonSentinelCL",
                            specs=(("Ruby", "ruby"), ("Obsidian", "obsidian"), ("Emerald", "emerald"))),
    # the caster Druid (E009); Feral Druid is another class. Every talent row is kept (the old screen did),
    # Diamond Ring rows name the binding the fight chose.
    "druid": dict(class_name="Druid", module="farm.hybrid.druid_cl", engine="DruidCL",
                  specs=(("Restoration", "restoration"), ("Balance", "balance")), all_talents=True, bind=("I00D",)),
    # Feral Druid O00R (not the caster Druid); its sheet file keeps the old name
    "feral_druid": dict(class_name="FeralDruid", module="farm.hybrid.feral_druid_cl", engine="FeralDruidCL",
                        specs=(("Primal", "primal"), ("Guardian", "guardian"), ("Savage", "savage")),
                        all_talents=True, bind=("I00D",), out="feral-druid-one-slot.json"),
    "hunter": dict(class_name="Hunter", module="farm.hybrid.hunter_cl", engine="HunterCL",
                   specs=(("Marksmanship", "marksmanship"), ("Beast Mastery", "beast_mastery"), ("Survival", "survival"))),
    "death_knight": dict(class_name="DeathKnight", module="farm.hybrid.death_knight_cl", engine="DeathKnightCL",
                         specs=(("Frost", "frost"), ("Blood", "blood"), ("Unholy", "unholy")),
                         # Blood Feast gains only with its partners (farm.top.TALENT_INCLUDE / ITEM_INCLUDE)
                         combos=[("I0CU", code) for code in ("I05V", "I024", "arsc", "I079", "fgun", "I05N", "I06J",
                                                             "I015")]),
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
        if item.rawcode in pool:
            continue
        label = f"{item.name} ({ORB_MODE[item.rawcode]})" if item.rawcode in ORB_MODE else item.name
        src = "Legendary" if item.rawcode in LEGENDARIES else "Shop" if item.rawcode in shop_ids else "Drop"
        pool[item.rawcode] = (label, src)
    talents = sorted(((c, n) for c, n in mod.TALENT_NAMES.items()
                      if cfg.get("all_talents") or c not in mod.IGNORED_TALENTS), key=lambda p: p[1])
    glyphs = sorted(GLYPHS.items(), key=lambda p: p[1])
    titles = [t for t, _ in cfg["specs"]]
    zero = [0] * len(ESC_ATTRS)

    cases = [((), (), ())] + [((), (c,), ()) for c, _ in talents] + [((code,), (), ()) for code in pool] + \
            [((), (), (c,)) for c, _ in glyphs]
    combos = [((item,), (talent,), ()) for talent, item in cfg.get("combos", ())]
    cases += combos
    value = {}
    bound = {}
    for title, spec in cfg["specs"]:
        engine = getattr(mod, cfg["engine"])(space, items, sources, TARGETS, None, spec)
        dps, _g, status = engine.pick([engine.picks_of(i) for i, _t, _gl in cases],
                                      [engine.talent_mask(t) for _i, t, _gl in cases],
                                      [engine.glyph_mask(gl) for _i, _t, gl in cases], [zero] * len(cases))
        if status.any():
            raise SystemExit(f"{spec}: kernel declined {int((status != 0).sum())} rows")
        value[title] = {case: round(float(d), 1) for case, d in zip(cases, dps)}
        for code in cfg.get("bind", ()):
            if code in pool:
                bound[(title, code)] = engine.report([code])["bound_spell"] or ""
    bare = {t: value[t][((), (), ())] for t in titles}
    if not all(v > 0 for v in bare.values()):
        raise SystemExit(f"bare DPS is not positive: {bare}")

    talent_rows = [["Талант", "Код"] + [f"{t} DPS" for t in titles], ["Без таланта", ""] + [bare[t] for t in titles]]
    talent_rows += [[n, c] + [value[t][((), (c,), ())] for t in titles] for c, n in talents]
    item_rows = [["Предмет", "Код", "Источник"] + [f"{t} DPS" for t in titles] + [f"Привязка {t}" for t in titles],
                 ["Без предмета", "", ""] + [bare[t] for t in titles] + [""] * len(titles)]
    body = [[label, code, src] + [value[t][((code,), (), ())] for t in titles] + [bound.get((t, code), "") for t in titles]
            for code, (label, src) in pool.items()]
    body.sort(key=lambda row: (-max(row[3:3 + len(titles)]), row[0]))
    item_rows += body
    glyph_rows = [["Глиф", "Код"] + [f"{t} DPS" for t in titles], ["Без глифа", ""] + [bare[t] for t in titles]]
    glyph_rows += [[n, c] + [value[t][((), (), (c,))] for t in titles] for c, n in glyphs]
    payload = {"specs": titles, "talents": talent_rows, "items": item_rows, "glyphs": glyph_rows}
    if combos:
        # talent + item together: DPS, and the talent's gain over the item alone
        tname = dict(talents)
        combo_rows = [["Талант + предмет", "Коды"] + [f"{t} DPS" for t in titles] + [f"Прирост таланта {t}" for t in titles]]
        for case in combos:
            (item,), (talent,), _ = case
            label = f"{tname.get(talent, talent)} + {pool[item][0] if item in pool else item}"
            alone = ((item,), (), ())
            combo_rows.append([label, f"{talent}+{item}"] + [value[t][case] for t in titles]
                              + [round(value[t][case] - value[t][alone], 1) for t in titles])
        payload["combos"] = combo_rows
    out = Path("extract") / cfg.get("out", f"{hero}-one-slot.json")
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print("wrote", out, "items", len(pool), "talents", len(talents), "glyphs", len(glyphs), "bare", bare)


if __name__ == "__main__":
    main()
