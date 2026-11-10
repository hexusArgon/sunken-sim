"""Re-sim Priest farm top runs for docs/sim-html/priest.html (Shadow, Discipline, Holy).

    PRIEST_SPEC=discipline python tools/priest_html_enrich.py
    PRIEST_SPEC=shadow PRIEST_FARM=<results json> python tools/priest_html_enrich.py 10

Reads a finished top-80 farm result (level 15, ESC 30 greedy; by default the
GPU run in sunken-sim-runs/priest-<spec>-opencl-top80-gpu), re-sims every
displayed run ("Shop + drop" = top, top_shop, top_random per
.cursor/rules/sim-canvas.mdc; top_shop_random is not shown; 5 targets, the
run's ESC points) with sunken_sim.shadow.simulate and writes Report fields
(sources, actions, stats, mana_left, bound_spell) plus in-context talent /
glyph scans to docs/sim-html/sources/priest-<spec>-enriched.json.

Talent scan: every 3-talent combo (4 with Mind Amplifier) of the spec's farm
talents, with the run's items, glyphs and ESC points. Talent DPS = best combo
that contains it. Glyph scan: every 3-glyph combo, with the run's items,
talents and ESC points. The scans use the exact OpenCL Priest kernel
(farm/hybrid/priest_cl.py, bit-identical to simulate) when an OpenCL float64
device is present; PRIEST_ENRICH_CL=0 forces Python.
"""

from __future__ import annotations

import glob
import itertools
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SPEC = os.environ.get("PRIEST_SPEC", "shadow")
os.environ.setdefault("FARM_DATA", str(ROOT.parent / "sunken-sim-runs" / f"priest-{SPEC}-opencl-top80-gpu"))

from farm.catalog import load  # noqa: E402
from sunken_sim.esc import ESC_ATTRS, apply_points  # noqa: E402
from sunken_sim.library import load_items  # noqa: E402
from sunken_sim.shadow import FIGHT, LEVEL, MIND_AMPLIFIER, Build, simulate  # noqa: E402


def _default_farm() -> Path:
    found = sorted(glob.glob(str(ROOT.parent / "sunken-sim-runs" / f"priest-{SPEC}-opencl-top80-gpu" / "results" / "*.json")))
    if not found:
        raise SystemExit(f"no farm result for priest {SPEC}; set PRIEST_FARM")
    return Path(found[-1])


FARM = Path(os.environ["PRIEST_FARM"]) if os.environ.get("PRIEST_FARM") else _default_farm()
OUT = ROOT / "docs" / "sim-html" / "sources" / f"priest-{SPEC}-enriched.json"
TARGETS = 5
GROUPS = {"mixed": "top", "shop": "top_shop", "drop": "top_random"}

SPACE, _ = load(hero="priest", spec=SPEC, pool="mixed", top=80)
FARM_TALENTS = list(SPACE.talents)
FARM_GLYPHS = list(SPACE.glyphs)
TALENT_NAME = dict(SPACE.talent_names)
GLYPH_NAME = dict(SPACE.glyph_names)
TALENT_CODE = {name: code for code, name in TALENT_NAME.items()}
GLYPH_CODE = {name: code for code, name in GLYPH_NAME.items()}
BY_CODE = {item.rawcode: item for item in load_items()}

_CL = None


def _engine():
    """Exact OpenCL kernel for the talent/glyph scans, or None (Python scans)."""
    global _CL
    if _CL is None:
        _CL = False
        if os.environ.get("PRIEST_ENRICH_CL", "1") != "0":
            try:
                from farm.hybrid.priest_cl import PriestCL
                from farm.runner import source_map

                space, items = load(hero="priest", spec=SPEC, pool="mixed", top=80)
                _CL = PriestCL(space, items, source_map(items), TARGETS, spec=SPEC)
                print("talent/glyph scans on", _CL.name, flush=True)
            except Exception as exc:
                print(f"OpenCL unavailable ({type(exc).__name__}: {exc}); Python scans", flush=True)
    return _CL or None


def build_of(items, talents, glyphs, points) -> Build:
    bare = Build(frozenset(talents), frozenset(glyphs), tuple(items), 0, 0)
    return apply_points(bare, points)


def scan(entry, items, combos) -> list[float]:
    """simulate().dps of (talents, glyphs, points) builds with the run's items."""
    engine = _engine()
    chunk = entry.get("chunk")
    if engine is not None and chunk is not None and 0 <= int(chunk) < SPACE.total \
            and list(SPACE.decode(int(chunk))[0]) == [it.rawcode for it in items]:
        return engine.scores(int(chunk), combos, mode=0)
    return [simulate(build_of(items, t, g, p), TARGETS, spec=SPEC, use_history=False).dps for t, g, p in combos]


def stats_rows(report, points) -> list[list[str]]:
    s = report.stats
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
    if SPEC != "holy":  # Holy has no Shadow Word: Pain
        rows.append(["Тик Shadow Word: Pain", f"{s['swp_period']:.2f} с"])
    rows += [
        ["Множитель КД (предметы)", f"×{s['cd_temp']:.3f}"],
        ["Плоское снижение КД", f"{s['flat_cdr']:.2f} с"],
        ["Пробитие брони", f"{s['armor_pen']:.0f}"],
    ]
    if report.orb_mode:
        rows.append(["Elemental Orb", report.orb_mode])
    if report.bound_spell:
        rows.append(["Diamond Ring привязан к", report.bound_spell])
    return rows


def enrich(entry: dict) -> dict:
    items = [BY_CODE[it["code"]] for it in entry["items"]]
    talents = [TALENT_CODE[n] for n in entry["talents"]]
    glyphs = [GLYPH_CODE[n] for n in entry["glyphs"]]
    points = {k: int(entry["points"].get(k, 0)) for k in ESC_ATTRS}
    report = simulate(build_of(items, talents, glyphs, points), TARGETS, spec=SPEC, use_history=False)
    sources = sorted(((name, round(total / FIGHT, 1)) for name, total in report.sources.items()), key=lambda r: -r[1])
    actions = []
    if report.orb_mode:
        actions.append(["до боя", f"Elemental Orb → {report.orb_mode}"])
    if report.bound_spell:
        actions.append(["до боя", f"Diamond Ring → привязка {report.bound_spell}"])
    actions += [[f"{t:.2f}", name] for t, name in report.actions]

    picks = SPACE.picks_with if any(it.rawcode == MIND_AMPLIFIER for it in items) else SPACE.picks_without
    talent_dps: dict[str, float] = {}
    combos = list(itertools.combinations(sorted(FARM_TALENTS), picks))
    for combo, dps in zip(combos, scan(entry, items, [(c, glyphs, points) for c in combos])):
        for code in combo:
            name = TALENT_NAME[code]
            talent_dps[name] = max(talent_dps.get(name, -1.0), dps)
    glyph_dps: dict[str, float] = {}
    combos = list(itertools.combinations(sorted(FARM_GLYPHS), SPACE.glyph_picks))
    for combo, dps in zip(combos, scan(entry, items, [(talents, c, points) for c in combos])):
        for code in combo:
            name = GLYPH_NAME[code]
            glyph_dps[name] = max(glyph_dps.get(name, -1.0), dps)

    return {
        "farm_dps": round(entry["dps"], 1),
        "dps": round(report.dps, 1),
        "total": round(report.total),
        "manaLeft": round(report.mana_left, 1),
        "bound_spell": report.bound_spell,
        "orb_mode": report.orb_mode,
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
        "spec": SPEC,
        "farm_file": os.path.relpath(FARM, ROOT).replace("\\", "/"),
        "done": farm["done"],
        "end": farm.get("end"),
        "errors": farm["errors"],
        "stopped": farm["stopped"],
        "spec_talents": [TALENT_NAME[c] for c in sorted(FARM_TALENTS)],
        "glyphs": [GLYPH_NAME[c] for c in sorted(FARM_GLYPHS)],
        "runs": {},
    }
    if SPEC == "shadow":
        out["shadow_talents"] = out["spec_talents"]
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    for mode, key in GROUPS.items():
        rows = []
        for i, entry in enumerate(farm[key][:limit]):
            t0 = time.time()
            row = enrich(entry)
            rows.append(row)
            print(f"{SPEC} {mode} {i + 1}: farm {row['farm_dps']} resim {row['dps']} mana {row['manaLeft']}% "
                  f"bind {row['bound_spell']} ({time.time() - t0:.1f}s)", flush=True)
        out["runs"][mode] = rows
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
