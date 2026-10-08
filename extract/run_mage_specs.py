"""Search Frost, Arcane and Fire with the same item rules as the priest."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.mage import TALENTS as MAGE_TALENTS
from sunken_sim.mage import simulate
from sunken_sim.library import Item, load_items
from sunken_sim.search import GLYPHS, LEGENDARIES, pools_for, search_pool
from sunken_sim.shadow import Build, _ignored_lines

from build_mage_canvas import write_all


def source_of(item, shop_ids: set[str]) -> str:
    if item.rawcode in LEGENDARIES:
        return "Mysterious Wanderer"
    if item.rawcode in shop_ids or item.tip.startswith("Shop Item"):
        return "Shop Item"
    return "Random drop"


def payload(label: str, build: Build, shop_ids: set[str], targets: int, spec: str) -> dict:
    report = simulate(build, targets, spec=spec)
    ignored = []
    for item in build.items:
        extra = _ignored_lines(item)
        if extra:
            ignored.append({"item": item.name, "lines": extra})
    return {
        "label": label,
        "targets": targets,
        "dps": round(report.dps, 1),
        "total": round(report.total),
        "talents": [MAGE_TALENTS[code] for code in sorted(build.talents)],
        "glyphs": [GLYPHS[code] for code in sorted(build.glyphs)],
        "points": {
            "crit": build.crit_points,
            "potency": build.potency_points,
            "luck": build.luck_points,
            "mastery": build.mastery_points,
        },
        "stats": {
            "int": report.stats["int"],
            "ad": report.stats["ad"],
            "potency": report.stats["potency"],
            "mastery": report.stats["mastery"],
            "crit": report.stats["crit"],
            "rating": report.stats["rating"],
            "haste": report.stats["haste"],
            "attack_speed": report.stats["attack_speed"],
            "mana_max": report.stats["mana_max"],
            "swing": report.stats["swing"],
            "bomb_period": report.stats["bomb_period"],
            "hydra_swing": report.stats.get("hydra_swing", 0.0),
        },
        "mana_left": round(report.mana_left, 1),
        "sources": [
            {"name": name, "amount": round(amount, 1)}
            for name, amount in sorted(report.sources.items(), key=lambda row: -row[1])
        ],
        "orb_mode": report.orb_mode,
        "bound_spell": report.bound_spell,
        "actions": [{"time": round(moment, 2), "spell": spell} for moment, spell in report.actions],
        "items": [
            {"name": item.name, "source": source_of(item, shop_ids), "tip": item.tip}
            for item in build.items
        ],
        "ignored": ignored,
    }


def saved_build(run: dict, by_name: dict[str, list[Item]]) -> Build:
    talents = frozenset(code for code, name in MAGE_TALENTS.items() if name in run["talents"])
    glyphs = frozenset(code for code, name in GLYPHS.items() if name in run["glyphs"])
    if len(talents) != len(run["talents"]) or len(glyphs) != len(run["glyphs"]):
        raise KeyError(run["talents"] + run["glyphs"])
    chosen = []
    for row in run["items"]:
        found = by_name[row["name"]]
        chosen.append(next((item for item in found if item.tip == row["tip"]), found[0]))
    points = run["points"]
    return Build(
        talents,
        glyphs,
        tuple(chosen),
        points["potency"],
        points["mastery"],
        points["crit"],
        points["luck"],
    )


def fill_mana(spec: str, results: dict, by_name: dict[str, list[Item]]) -> None:
    for key, run in results.items():
        if "mana_left" in run:
            continue
        targets = int(key.split("-", 1)[0])
        report = simulate(saved_build(run, by_name), targets, spec=spec)
        run["mana_left"] = round(report.mana_left, 1)
        print(f"мана {spec} {key} {run['mana_left']}", flush=True)


def run_spec(spec: str, pools: tuple[tuple[str, list], ...], shop_ids: set[str], by_name: dict[str, list[Item]]) -> None:
    seeds = {
        "frost": frozenset({"I0KU", "I0UO", "I0Q7"}),
        "arcane": frozenset({"I0KU", "I0KV", "I0O0"}),
        "fire": frozenset({"I0KU", "I0NZ", "I0KQ"}),
    }
    seed = Build(
        seeds[spec],
        frozenset({"I0AV", "I0JA", "I0OF"}),
        (),
        5,
        0,
        0,
        0,
    )
    out = Path(__file__).with_name(f"{spec}-sims.json")
    results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    fill_mana(spec, results, by_name)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    write_all()
    for targets in (5,):
        for label, pool in pools:
            key = f"{targets}-{label}"
            if key in results:
                print(f"уже есть {spec} {key}", flush=True)
                continue
            print(f"старт {spec} {key} {len(pool)}", flush=True)
            found = search_pool(pool, seed, targets, spec, MAGE_TALENTS, "mage")
            tops = []
            for place, (build, dps) in enumerate(found, start=1):
                names = ", ".join(item.name for item in build.items)
                print(f"{spec} {key} #{place} {dps:.1f} {names}", flush=True)
                row = payload(label, build, shop_ids, targets, spec)
                row["place"] = place
                tops.append(row)
            best = dict(tops[0])
            best["top"] = tops
            results[key] = best
            out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            write_all()
    print(f"{spec} готово", flush=True)
    write_all()


def main() -> None:
    catalog = load_items()
    by_name: dict[str, list[Item]] = {}
    for item in catalog:
        by_name.setdefault(item.name, []).append(item)
    shop, drop, legendaries = pools_for(catalog, "Mage")
    print(f"shop {len(shop)} drop {len(drop)} legendaries {len(legendaries)}", flush=True)
    shop_ids = {item.rawcode for item in shop}
    pools = (
        ("mixed", shop + drop + legendaries),
        ("shop", shop + legendaries),
        ("drop", drop + legendaries),
    )
    for spec in ("frost", "arcane", "fire"):
        run_spec(spec, pools, shop_ids, by_name)
    print("готово", flush=True)


if __name__ == "__main__":
    main()
