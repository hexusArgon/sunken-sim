"""Re-sim Fire Mage farm top runs for docs/sim-html/mage.html.

Reads the ESC top-80 farm result (level 15, ESC 30 greedy), re-sims every
displayed run (top_shop_random, top_shop, top_random; 5 targets, the run's ESC
points) with sunken_sim.mage.simulate(spec="fire") and writes Report fields
(sources, actions, stats, mana_left, bound_spell) plus in-context talent / glyph
scans to docs/sim-html/sources/mage-fire-enriched.json.

Modeled on tools/druid_html_enrich.py. Diamond Ring binding: simulate() tries
every button and keeps the best one; that choice is reported as bound_spell.
Talent scan: every combo of the farm's Fire talents (3, or 4 with Mind
Amplifier) with the run's items, glyphs and ESC. Talent DPS = best combo that
contains it. Glyph scan: every 3-glyph combo with the run's items/talents/ESC.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FARM_DATA", str(ROOT / "farm-data-mage-fire"))

from farm.catalog import load  # noqa: E402
from sunken_sim.mage import FIGHT, LEVEL, simulate  # noqa: E402
from sunken_sim.esc import ESC_ATTRS, apply_points  # noqa: E402
from sunken_sim.library import load_items  # noqa: E402
from sunken_sim.shadow import MIND_AMPLIFIER, Build  # noqa: E402

FARM = Path(os.environ["MAGE_FARM"]) if os.environ.get("MAGE_FARM") else ROOT / "farm-data-mage-fire" / "results" / "local-esc-mage-fire-mixed-top80-5-0-312052229.json"
OUT = ROOT / "docs" / "sim-html" / "sources" / "mage-fire-enriched.json"
TARGETS = 5
SPEC = "fire"
GROUPS = {"mixed": "top_shop_random", "shop": "top_shop", "drop": "top_random"}

SPACE, _ = load(hero="mage", spec=SPEC, pool="mixed", top=80)
FARM_TALENTS = list(SPACE.talents)
FARM_GLYPHS = list(SPACE.glyphs)
TALENT_NAME = dict(SPACE.talent_names)
GLYPH_NAME = dict(SPACE.glyph_names)
TALENT_CODE = {name: code for code, name in TALENT_NAME.items()}
GLYPH_CODE = {name: code for code, name in GLYPH_NAME.items()}
BY_CODE = {item.rawcode: item for item in load_items()}


def build_of(items, talents, glyphs, points) -> Build:
    bare = Build(frozenset(talents), frozenset(glyphs), tuple(items), 0, 0)
    return apply_points(bare, points)


def stats_rows(report, points) -> list[list[str]]:
    s = report.stats
    spec = [
        ("Интеллект", "int", "{:.0f}", 1),
        ("Сила", "str", "{:.0f}", 1),
        ("Ловкость", "agi", "{:.0f}", 1),
        ("Сила атаки", "ad", "{:.1f}", 1),
        ("Potency", "potency", "{:.1f}", 1),
        ("Mastery", "mastery", "{:.0f}", 1),
        ("Шанс крита", "crit", "{:.0f}%", 1),
        ("Рейтинг крита", "rating", "{:.2f}", 1),
        ("Скорость (Haste)", "haste", "{:.1f}%", 100),
        ("Скорость атаки", "attack_speed", "{:.1f}%", 100),
        ("Удача", "luck", "{:.0f}%", 100),
        ("Healing Power", "healing_power", "{:.0f}", 1),
        ("Pet Damage", "pet_damage", "{:.1f}%", 100),
    ]
    rows = []
    for label, key, fmt, mul in spec:
        if key in s:
            rows.append([label, fmt.format(s[key] * mul)])
    rows.append(["Здоровье от ESC", f"+{30 * int(points.get('health', 0))}"])
    for label, key, fmt in [
        ("Мана макс.", "mana_max", "{:.0f}"),
        ("Реген маны", "mana_regen", "{:.2f}/с"),
    ]:
        if key in s:
            rows.append([label, fmt.format(s[key])])
    rows.append(["Мана в конце", f"{report.mana_left:.0f}%"])
    for label, key, fmt in [
        ("Интервал атаки", "swing", "{:.2f} с"),
        ("Интервал атаки Hydra", "hydra_swing", "{:.2f} с"),
        ("Тик Living Bomb", "bomb_period", "{:.2f} с"),
        ("Множитель КД (предметы)", "cd_temp", "×{:.3f}"),
        ("Плоское снижение КД", "flat_cdr", "{:.2f} с"),
        ("Пробитие брони", "armor_pen", "{:.0f}"),
    ]:
        if key in s and s[key]:
            rows.append([label, fmt.format(s[key])])
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
    report = simulate(build_of(items, talents, glyphs, points), TARGETS, spec=SPEC)
    sources = sorted(((name, round(total / FIGHT, 1)) for name, total in report.sources.items() if total > 0), key=lambda r: -r[1])
    actions = []
    if report.orb_mode:
        actions.append(["до боя", f"Elemental Orb → {report.orb_mode}"])
    if report.bound_spell:
        actions.append(["до боя", f"Diamond Ring → привязка {report.bound_spell}"])
    actions += [[f"{t:.2f}", name] for t, name in report.actions]

    picks = SPACE.picks_with if any(it.rawcode == MIND_AMPLIFIER for it in items) else SPACE.picks_without
    talent_dps: dict[str, float] = {}
    for combo in itertools.combinations(sorted(FARM_TALENTS), picks):
        dps = simulate(build_of(items, combo, glyphs, points), TARGETS, spec=SPEC).dps
        for code in combo:
            name = TALENT_NAME[code]
            talent_dps[name] = max(talent_dps.get(name, -1.0), dps)
    glyph_dps: dict[str, float] = {}
    for combo in itertools.combinations(sorted(FARM_GLYPHS), SPACE.glyph_picks):
        dps = simulate(build_of(items, talents, combo, points), TARGETS, spec=SPEC).dps
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
        "farm_file": str(FARM.relative_to(ROOT)).replace("\\", "/"),
        "done": farm["done"],
        "errors": farm["errors"],
        "stopped": farm["stopped"],
        "fire_talents": [TALENT_NAME[c] for c in sorted(FARM_TALENTS)],
        "glyphs": [GLYPH_NAME[c] for c in sorted(FARM_GLYPHS)],
        "runs": {},
    }
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    for mode, key in GROUPS.items():
        rows = []
        for i, entry in enumerate(farm[key][:limit]):
            t0 = time.time()
            row = enrich(entry)
            rows.append(row)
            print(f"{mode} {i + 1}: farm {row['farm_dps']} resim {row['dps']} mana {row['manaLeft']}% bind {row['bound_spell']} ({time.time() - t0:.1f}s)", flush=True)
        out["runs"][mode] = rows
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()