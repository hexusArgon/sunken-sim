"""Search Discipline and Holy Priest with the same item rules as Shadow."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import Item, load_items
from sunken_sim.search import GLYPHS, LEGENDARIES, TALENTS, pools_for, search_pool
from sunken_sim.shadow import Build, _ignored_lines, simulate

from build_spec_canvas import write_all


def source_of(item: Item, shop_ids: set[str]) -> str:
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
        "talents": [TALENTS[code] for code in sorted(build.talents)],
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
            "swp_period": report.stats["swp_period"],
        },
        "sources": [
            {"name": name, "amount": round(amount, 1)}
            for name, amount in sorted(report.sources.items(), key=lambda row: -row[1])
        ],
        "orb_mode": report.orb_mode,
        "mana_left": round(report.mana_left, 1),
        "bound_spell": report.bound_spell,
        "actions": [{"time": round(moment, 2), "spell": spell} for moment, spell in report.actions],
        "items": [
            {"name": item.name, "source": source_of(item, shop_ids), "tip": item.tip}
            for item in build.items
        ],
        "ignored": ignored,
    }


def run_spec(spec: str, pools: tuple[tuple[str, list], ...], shop_ids: set[str]) -> None:
    seed = Build(
        frozenset({"I0PS", "I0PU", "I0SA"}),
        frozenset({"I0AV", "I0HC", "I0JA"}),
        (),
        0,
        0,
        5,
        0,
    )
    out = Path(__file__).with_name(f"{spec}-sims.json")
    results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    for targets in (5,):
        for label, pool in pools:
            key = f"{targets}-{label}"
            if key in results:
                print(f"уже есть {spec} {key}", flush=True)
                continue
            print(f"старт {spec} {key} {len(pool)}", flush=True)
            found = search_pool(pool, seed, targets, spec)
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
    shop, drop, legendaries = pools_for(catalog)
    print(f"shop {len(shop)} drop {len(drop)} legendaries {len(legendaries)}", flush=True)
    shop_ids = {item.rawcode for item in shop}
    pools = (
        ("mixed", shop + drop + legendaries),
        ("shop", shop + legendaries),
        ("drop", drop + legendaries),
    )
    for spec in ("discipline", "holy"):
        run_spec(spec, pools, shop_ids)
    print("готово", flush=True)


if __name__ == "__main__":
    main()
