"""Re-search Priest Shadow with one legendary and no single-copy uniques."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import Item, load_items
from sunken_sim.search import GLYPHS, LEGENDARIES, TALENTS, pools_for, search_pool
from sunken_sim.shadow import Build, _ignored_lines, simulate

OUT = Path(__file__).with_name("hp-sims.json")


def source_of(item: Item, shop_ids: set[str]) -> str:
    if item.rawcode in LEGENDARIES:
        return "Mysterious Wanderer"
    if item.rawcode in shop_ids or item.tip.startswith("Shop Item"):
        return "Shop Item"
    return "Random drop"


def payload(label: str, build: Build, shop_ids: set[str], targets: int) -> dict:
    report = simulate(build, targets)
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
        "actions": [{"time": round(moment, 2), "spell": spell} for moment, spell in report.actions],
        "items": [
            {
                "name": item.name,
                "source": source_of(item, shop_ids),
                "tip": item.tip,
            }
            for item in build.items
        ],
        "ignored": ignored,
    }


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
    seed = Build(
        frozenset({"I0PS", "I0PU", "I0SA"}),
        frozenset({"I0AV", "I0HC", "I0JA"}),
        (),
        0,
        0,
        5,
        0,
    )
    results = {}
    out = OUT.with_name("target-sims.json")
    if out.exists():
        results = json.loads(out.read_text(encoding="utf-8"))
    for targets in (1, 2, 3, 4, 5):
        for label, pool in pools:
            key = f"{targets}-{label}"
            if key in results:
                print(f"уже есть {key}", flush=True)
                continue
            print(f"старт {key} {len(pool)}", flush=True)
            build, dps = search_pool(pool, seed, targets)
            legend = [item.name for item in build.items if item.rawcode in LEGENDARIES]
            print(f"{key} {dps:.1f} legendary {legend} " + ", ".join(item.name for item in build.items), flush=True)
            results[key] = payload(label, build, shop_ids, targets)
            out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("готово", flush=True)


if __name__ == "__main__":
    main()
