"""Re-sim class farm top runs (Shaman, Paladin, Druid, Berserker, Hunter, Death Knight, Demon Hunter, Dragon Sentinel, Feral Druid) for docs/sim-html/<hero>.html.

    HERO=shaman SPEC=elemental TOP=150 python tools/class_html_enrich.py
    HERO=paladin SPEC=holy FARM=<results json> python tools/class_html_enrich.py 10

Reads a finished farm result (level 15, ESC 30 greedy; by default the GPU run in
sunken-sim-runs/<hero>-<spec>-opencl-top<TOP>-gpu), re-sims every displayed run
("Shop + drop" = top, top_shop, top_random per .cursor/rules/sim-canvas.mdc;
top_shop_random is not shown; 5 targets, the run's ESC points) with
sunken_sim.<hero>.simulate on an empty timeline cache, and writes Report fields
(sources, actions, stats, mana_left, bound_spell) plus in-context talent / glyph
scans to docs/sim-html/sources/<hero>-<spec>-enriched.json, in the same shape as
tools/priest_html_enrich.py.

Talent scan: every combo of the spec's farm talents (picks, or picks with Mind
Amplifier) with the run's items, glyphs and ESC points; talent DPS = best combo
that contains it. Glyph scan: every glyph combo with the run's items, talents and
ESC points. The scans use the exact OpenCL kernels (farm/hybrid/shaman_cl.py,
paladin_cl.py, bit-identical to simulate) when an OpenCL float64 device is
present; ENRICH_CL=0 forces Python.
"""

from __future__ import annotations

import glob
import importlib
import itertools
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HERO = os.environ.get("HERO", "shaman")
SPEC = os.environ.get("SPEC", "enhancement" if HERO == "shaman" else "retribution")
TOP = int(os.environ.get("TOP", "150"))
RUN_DIR = ROOT.parent / "sunken-sim-runs" / f"{HERO}-{SPEC}-opencl-top{TOP}-gpu"
os.environ.setdefault("FARM_DATA", str(RUN_DIR))

from farm.catalog import load  # noqa: E402
from sunken_sim.esc import ESC_ATTRS, apply_points  # noqa: E402
from sunken_sim.library import load_items  # noqa: E402
from sunken_sim.shadow import FIGHT, LEVEL, MIND_AMPLIFIER, Build  # noqa: E402

# Classes whose Python fight model was removed: reports come from the exact kernel's report mode.
GPU_ONLY = frozenset({"berserker", "death_knight", "demon_hunter", "dragon_sentinel", "druid", "feral_druid", "hunter"})
MOD = importlib.import_module(f"farm.hybrid.{HERO}_cl" if HERO in GPU_ONLY else f"sunken_sim.{HERO}")


def _default_farm() -> Path:
    found = sorted(glob.glob(str(RUN_DIR / "results" / "*.json")))
    if not found:
        raise SystemExit(f"no farm result for {HERO} {SPEC}; set FARM")
    return Path(found[-1])


FARM = Path(os.environ["FARM"]) if os.environ.get("FARM") else _default_farm()
OUT = ROOT / "docs" / "sim-html" / "sources" / f"{HERO}-{SPEC}-enriched.json"
TARGETS = 5
GROUPS = {"mixed": "top", "shop": "top_shop", "drop": "top_random"}

SPACE, _ = load(hero=HERO, spec=SPEC, pool="mixed", top=TOP)
FARM_TALENTS = list(SPACE.talents)
FARM_GLYPHS = list(SPACE.glyphs)
TALENT_NAME = dict(SPACE.talent_names)
GLYPH_NAME = dict(SPACE.glyph_names)
TALENT_CODE = {name: code for code, name in TALENT_NAME.items()}
GLYPH_CODE = {name: code for code, name in GLYPH_NAME.items()}
BY_CODE = {item.rawcode: item for item in load_items()}

_CL = None


def _engine():
    global _CL
    if _CL is None:
        _CL = False
        if os.environ.get("ENRICH_CL", "1") != "0":
            try:
                from farm.hybrid.mage_cl import make_engine
                from farm.runner import source_map

                space, items = load(hero=HERO, spec=SPEC, pool="mixed", top=TOP)
                _CL = make_engine(HERO, space, items, source_map(items), TARGETS, SPEC)
                print("talent/glyph scans on", _CL.name, flush=True)
            except Exception as exc:
                print(f"OpenCL unavailable ({type(exc).__name__}: {exc}); Python scans", flush=True)
    return _CL or None


def build_of(items, talents, glyphs, points) -> Build:
    return apply_points(Build(frozenset(talents), frozenset(glyphs), tuple(items), 0, 0, 0, 0), points)


def fresh_sim(build):
    """simulate() on an empty timeline cache (the value the farm and the kernel report)."""
    if HERO in GPU_ONLY:
        from types import SimpleNamespace

        from sunken_sim.esc import points_from_build

        engine = _engine()
        if engine is None:
            raise SystemExit(f"{HERO}: no Python model, the report needs an OpenCL float64 device")
        rep = engine.report([it.rawcode for it in build.items], build.talents, build.glyphs, points_from_build(build))
        return SimpleNamespace(**{"orb_mode": None, "bound_spell": None, **rep})
    if not hasattr(MOD, "_TIMELINE"):  # berserker: no fight cache
        return MOD.simulate(build, TARGETS, SPEC)
    old = MOD._TIMELINE
    MOD._TIMELINE = {}
    try:
        return MOD.simulate(build, TARGETS, SPEC)
    finally:
        MOD._TIMELINE = old


def scan(entry, items, combos) -> list[float]:
    engine = _engine()
    chunk = entry.get("chunk")
    if engine is not None and chunk is not None and 0 <= int(chunk) < SPACE.total \
            and list(SPACE.decode(int(chunk))[0]) == [it.rawcode for it in items]:
        return engine.scores(int(chunk), combos)
    if HERO in GPU_ONLY and engine is not None:
        from sunken_sim.esc import ESC_ATTRS as _A

        codes = [it.rawcode for it in items]
        dps, _g, status = engine.pick([engine.picks_of(codes)] * len(combos), [engine.talent_mask(t) for t, _g2, _p in combos],
                                      [engine.glyph_mask(g) for _t, g, _p in combos],
                                      [[int(p.get(a, 0)) for a in _A] for _t, _g2, p in combos])
        if status.any():
            raise SystemExit(f"{HERO}: kernel declined {int((status != 0).sum())} scan rows")
        return [float(d) for d in dps]
    return [fresh_sim(build_of(items, t, g, p)).dps for t, g, p in combos]


def stats_rows(report, points) -> list[list[str]]:
    s = report.stats
    if HERO == "berserker":
        swing = 1.6 * (1.20 if s["galactic"] else 1.0) / (1.0 + s["attack_speed"])
        rows = [
            ["Ловкость", f"{s['agi']:.0f}"],
            ["Сила", f"{s['str']:.0f}"],
            ["Интеллект", f"{s['int']:.0f}"],
            ["Урон автоатаки", f"{30.0 + 0.75 * s['agi'] + s['damage']:.1f}"],
            ["Potency", f"{s['potency']:.1f}"],
            ["Mastery", f"{s['mastery']:.0f}"],
            ["Шанс крита", f"{min(100.0, s['crit']):.0f}%"],
            ["Рейтинг крита", f"{s['rating']:.2f}"],
            ["Спешка", f"{s['haste'] * 100:.1f}%"],
            ["Скорость атаки", f"{s['attack_speed'] * 100:.1f}%"],
            ["Удача", f"{s['luck'] * 100:.0f}%"],
            ["Магический бонус", f"+{s['magic_add'] * 100:.0f}%"],
            ["Физический бонус", f"+{s['phys_add'] * 100:.0f}%"],
            ["Здоровье", f"{s['hp']:.0f}"],
            ["Мана макс.", f"{s['mana_max']:.0f}"],
            ["Реген маны", f"{s['mana_regen']:.2f}/с"],
            ["Мана в конце", f"{report.mana_left:.0f}%"],
            ["Интервал атаки (без Berserk)", f"{swing:.2f} с"],
        ]
    elif HERO == "hunter":
        swing = 1.60 * (1.20 if s["galactic"] else 1.0) * (0.90 if SPEC == "marksmanship" else 1.0)
        swing /= 1.0 + max(-0.8, min(4.0, s["attack_speed"]))
        rows = [
            ["Ловкость", f"{s['agi']:.0f}"],
            ["Сила", f"{s['str']:.0f}"],
            ["Интеллект", f"{s['int']:.0f}"],
            ["Урон автоатаки", f"{30.0 + 0.75 * s['agi'] + s['damage']:.1f}"],
            ["Potency", f"{s['potency']:.1f}"],
            ["Mastery", f"{s['mastery']:.0f}"],
            ["Шанс крита", f"{min(100.0, s['crit']):.0f}%"],
            ["Рейтинг крита", f"{s['rating']:.2f}"],
            ["Спешка", f"{s['haste'] * 100:.1f}%"],
            ["Скорость атаки", f"{s['attack_speed'] * 100:.1f}%"],
            ["Удача", f"{s['luck'] * 100:.0f}%"],
            ["Магический бонус", f"+{s['magic_add'] * 100:.0f}%"],
            ["Физический бонус", f"+{s['phys_add'] * 100:.0f}%"],
            ["Урон питомцев", f"+{s['pet_damage'] * 100:.1f}%"],
            ["Крит питомцев", f"{s['summon_crit']:.0f}%"],
            ["Здоровье", f"{s['hp']:.0f}"],
            ["Мана макс.", f"{s['mana_max']:.0f}"],
            ["Реген маны", f"{s['mana_regen']:.2f}/с"],
            ["Мана в конце", f"{report.mana_left:.0f}%"],
            ["Интервал атаки (без баффов)", f"{swing:.2f} с"],
        ]
    elif HERO in ("death_knight", "demon_hunter", "dragon_sentinel", "monk", "necromancer"):
        primary = {"demon_hunter": "agi", "necromancer": "int"}.get(HERO, "str")
        swing = MOD.SWING * (1.20 if s["galactic"] else 1.0) / (1.0 + max(-0.8, min(4.0, s["attack_speed"])))
        attrs = [["Сила", f"{s['str']:.0f}"], ["Ловкость", f"{s['agi']:.0f}"], ["Интеллект", f"{s['int']:.0f}"]]
        if primary == "agi":
            attrs = [attrs[1], attrs[0], attrs[2]]
        elif primary == "int":
            attrs = [attrs[2], attrs[0], attrs[1]]
        rows = attrs + [
            ["Урон автоатаки", f"{MOD.WHITE_BASE + 0.75 * s[primary] + s['damage']:.1f}"],
            ["Potency", f"{s['potency']:.1f}"],
            ["Mastery", f"{s['mastery']:.0f}"],
            ["Шанс крита", f"{min(100.0, s['crit']):.0f}%"],
            ["Рейтинг крита", f"{s['rating']:.2f}"],
            ["Спешка", f"{s['haste'] * 100:.1f}%"],
            ["Скорость атаки", f"{s['attack_speed'] * 100:.1f}%"],
            ["Удача", f"{s['luck'] * 100:.0f}%"],
            ["Магический бонус", f"+{s['magic_add'] * 100:.0f}%"],
            ["Физический бонус", f"+{s['phys_add'] * 100:.0f}%"],
        ]
        if HERO == "necromancer":
            rows += [
                ["Урон питомцев", f"+{s['pet_damage'] * 100:.1f}%"],
                ["Крит питомцев", f"{s['summon_crit']:.0f}%"],
            ]
        rows.append(["Здоровье", f"{s['hp']:.0f}"])
        if "armor" in s:
            rows.append(["Броня", f"{s['armor']:.1f}"])
        rows += [
            ["Мана макс.", f"{s['mana_max']:.0f}"],
            ["Реген маны", f"{s['mana_regen']:.2f}/с"],
            ["Мана в конце", f"{report.mana_left:.0f}%"],
            ["Интервал атаки (без баффов)", f"{swing:.2f} с"],
        ]
    elif HERO == "feral_druid":
        rows = [
            ["Ловкость", f"{s['agi']:.0f}"],
            ["Сила", f"{s['str']:.0f}"],
            ["Интеллект", f"{s['int']:.0f}"],
            ["Сила атаки", f"{s['ad']:.1f}"],
            ["Potency", f"{s['potency']:.1f}"],
            ["Mastery", f"{s['mastery']:.0f}"],
            ["Шанс крита", f"{s['crit']:.0f}%"],
            ["Рейтинг крита", f"{s['rating']:.2f}"],
            ["Спешка", f"{s['haste'] * 100:.1f}%"],
            ["Скорость атаки", f"{s['attack_speed'] * 100:.1f}%"],
            ["Удача", f"{s['luck'] * 100:.0f}%"],
            ["Здоровье", f"{s['max_hp']:.0f}"],
            ["Броня", f"{s['armor']:.1f}"],
            ["Мана макс.", f"{s['mana_max']:.0f}"],
            ["Реген маны", f"{s['mana_regen']:.2f}/с"],
            ["Мана в конце", f"{report.mana_left:.0f}%"],
            ["Интервал атаки (без баффов)", f"{s['swing']:.2f} с"],
        ]
    elif HERO == "paladin":
        swing = 1.85 * (1.20 if s["galactic"] else 1.0) / (1.0 + s["attack_speed"])
        rows = [
            ["Сила", f"{s['str']:.0f}"],
            ["Ловкость", f"{s['agi']:.0f}"],
            ["Интеллект", f"{s['int']:.0f}"],
            ["Урон автоатаки", f"{13.0 + 0.75 * s['str'] + s['damage']:.1f}"],
            ["Potency", f"{s['potency']:.1f}"],
            ["Mastery", f"{s['mastery']:.0f}"],
            ["Шанс крита", f"{min(100.0, s['crit']):.0f}%"],
            ["Рейтинг крита", f"{s['rating']:.2f}"],
            ["Спешка", f"{s['haste'] * 100:.1f}%"],
            ["Скорость атаки", f"{s['attack_speed'] * 100:.1f}%"],
            ["Удача", f"{s['luck'] * 100:.0f}%"],
            ["Магический бонус", f"+{s['magic_add'] * 100:.0f}%"],
            ["Физический бонус", f"+{s['phys_add'] * 100:.0f}%"],
            ["Здоровье от ESC", f"+{30 * int(points.get('health', 0))}"],
            ["Мана макс.", f"{s['mana_max']:.0f}"],
            ["Реген маны", f"{s['mana_regen']:.2f}/с"],
            ["Мана в конце", f"{report.mana_left:.0f}%"],
            ["Интервал атаки", f"{swing:.2f} с"],
        ]
    else:
        rows = [
            ["Интеллект", f"{s['int']:.0f}"],
            ["Сила", f"{s['str']:.0f}"],
            ["Ловкость", f"{s['agi']:.0f}"],
            ["Сила атаки", f"{s['ad']:.1f}"],
            ["Potency", f"{s['potency']:.1f}"],
            ["Mastery", f"{s['mastery']:.0f}"],
            ["Шанс крита", f"{s['crit']:.0f}%"],
            ["Рейтинг крита", f"{s['rating']:.2f}"],
            ["Спешка", f"{s['haste'] * 100:.1f}%"],
            ["Скорость атаки", f"{s['attack_speed'] * 100:.1f}%"],
            ["Удача", f"{s['luck'] * 100:.0f}%"],
            ["Healing Power", f"{s['healing_power']:.0f}"],
            ["Pet Damage", f"{s['pet_damage'] * 100:.1f}%"],
            ["Здоровье от ESC", f"+{30 * int(points.get('health', 0))}"],
            ["Мана макс.", f"{s['mana_max']:.0f}"],
            ["Реген маны", f"{s['mana_regen']:.2f}/с"],
            ["Мана в конце", f"{report.mana_left:.0f}%"],
            ["Интервал атаки", f"{s['swing']:.2f} с"],
        ]
    rows += [
        ["Множитель КД (предметы)", f"×{s['cd_temp']:.3f}"],
        ["Плоское снижение КД", f"{s['flat_cdr']:.2f} с"],
        ["Пробитие брони", f"{s['armor_pen']:.0f}"],
    ]
    if getattr(report, "orb_mode", None):
        rows.append(["Elemental Orb", report.orb_mode])
    if getattr(report, "bound_spell", None):
        rows.append(["Diamond Ring привязан к", report.bound_spell])
    return rows


def enrich(entry: dict) -> dict:
    items = [BY_CODE[it["code"]] for it in entry["items"]]
    talents = [TALENT_CODE[n] for n in entry["talents"]]
    glyphs = [GLYPH_CODE[n] for n in entry["glyphs"]]
    points = {k: int(entry["points"].get(k, 0)) for k in ESC_ATTRS}
    report = fresh_sim(build_of(items, talents, glyphs, points))
    orb = getattr(report, "orb_mode", None)
    bound = getattr(report, "bound_spell", None)
    sources = sorted(((name, round(total / FIGHT, 1)) for name, total in report.sources.items() if total), key=lambda r: -r[1])
    actions = []
    if orb:
        actions.append(["до боя", f"Elemental Orb → {orb}"])
    if bound:
        actions.append(["до боя", f"Diamond Ring → привязка {bound}"])
    actions += [[f"{t:.2f}", name] for t, name in report.actions]

    picks = SPACE.picks_with if any(it.rawcode == MIND_AMPLIFIER for it in items) else SPACE.picks_without
    talent_dps: dict[str, float] = {}
    combos = list(itertools.combinations(sorted(FARM_TALENTS), picks))
    for combo, dps in zip(combos, scan(entry, items, [(c, glyphs, points) for c in combos])):
        for code in combo:
            talent_dps[TALENT_NAME[code]] = max(talent_dps.get(TALENT_NAME[code], -1.0), dps)
    glyph_dps: dict[str, float] = {}
    combos = list(itertools.combinations(sorted(FARM_GLYPHS), SPACE.glyph_picks))
    for combo, dps in zip(combos, scan(entry, items, [(talents, c, points) for c in combos])):
        for code in combo:
            glyph_dps[GLYPH_NAME[code]] = max(glyph_dps.get(GLYPH_NAME[code], -1.0), dps)

    return {
        "farm_dps": round(entry["dps"], 1),
        "dps": round(report.dps, 1),
        "total": round(report.total),
        "manaLeft": round(report.mana_left, 1),
        "bound_spell": bound,
        "orb_mode": orb,
        "items": entry["items"],
        "talents": entry["talents"],
        "glyphs": entry["glyphs"],
        "points": points,
        "chunk": entry["chunk"],
        "sources": sources,
        "actions": actions,
        "stats": stats_rows(report, points),
        "talentDps": {k: round(v, 1) for k, v in talent_dps.items()},
        "glyphDps": {k: round(v, 1) for k, v in glyph_dps.items()},
    }


def main() -> None:
    farm = json.loads(FARM.read_text(encoding="utf-8"))
    out = {
        "level": LEVEL,
        "targets": TARGETS,
        "hero": HERO,
        "spec": SPEC,
        "top": TOP,
        "farm_file": os.path.relpath(FARM, ROOT).replace("\\", "/"),
        "done": farm["done"],
        "end": farm.get("end"),
        "errors": farm["errors"],
        "stopped": farm["stopped"],
        "spec_talents": [TALENT_NAME[c] for c in sorted(FARM_TALENTS)],
        "glyphs": [GLYPH_NAME[c] for c in sorted(FARM_GLYPHS)],
        "runs": {},
    }
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    for mode, key in GROUPS.items():
        rows = []
        for i, entry in enumerate(farm[key][:limit]):
            t0 = time.time()
            row = enrich(entry)
            rows.append(row)
            print(f"{HERO} {SPEC} {mode} {i + 1}: farm {row['farm_dps']} resim {row['dps']} mana {row['manaLeft']}% "
                  f"bind {row['bound_spell']} ({time.time() - t0:.1f}s)", flush=True)
        out["runs"][mode] = rows
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
