"""Re-search Priest Shadow with one legendary and no single-copy uniques."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import Item, load_items
from sunken_sim.search import GLYPHS, LEGENDARIES, TALENTS, pools_for, search_pool
from sunken_sim.shadow import Build, _ignored_lines, simulate

from build_spec_canvas import write_all

OUT = Path(__file__).with_name("hp-sims.json")
TOP100 = Path(__file__).with_name("shadow-top100.json")

# The eight talents for this Shadow run. Smite, Empyreal Blaze, Blinding Light
# and Dark Evangelism stay out.
SHADOW_TALENTS = {
    "I0KF": "Dark Torment",
    "I0PU": "Insanity",
    "I0PS": "Catharsis",
    "I0HL": "Psychic Link",
    "I0SB": "Answered Prayers",
    "I0SC": "Touch of the Naaru",
    "I0HP": "Cosmic Horrors",
    "I0SA": "Clairvoyance",
}


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
        "orb_mode": report.orb_mode,
        "mana_left": round(report.mana_left, 1),
        "bound_spell": report.bound_spell,
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


def _write_merged(out, results: dict) -> None:
    """Keep the higher DPS already stored for a pool. A parallel part must not erase it."""
    current = {}
    if out.exists():
        current = json.loads(out.read_text(encoding="utf-8"))
    for key, row in results.items():
        old = current.get(key)
        if old is None or row["dps"] > old["dps"]:
            current[key] = row
    out.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def _top_codes() -> set[str]:
    rows = json.loads(TOP100.read_text(encoding="utf-8"))
    return {row["rawcode"] for row in rows}


def main() -> None:
    catalog = load_items()
    shop, drop, legendaries = pools_for(catalog)
    allowed = _top_codes()
    shop = [item for item in shop if item.rawcode in allowed]
    drop = [item for item in drop if item.rawcode in allowed]
    legendaries = [item for item in legendaries if item.rawcode in allowed]
    kept = {item.rawcode for item in shop + drop + legendaries}
    missing = sorted(allowed - kept)
    if missing:
        raise SystemExit(f"топ-100 нет в пуле: {', '.join(missing)}")
    print(
        f"shop {len(shop)} drop {len(drop)} legendaries {len(legendaries)} "
        f"топ {len(kept)} таланты {len(SHADOW_TALENTS)}",
        flush=True,
    )
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
    for targets in (5,):
        for label, pool in pools:
            key = f"{targets}-{label}"
            print(f"старт {key} {len(pool)}", flush=True)
            build, dps = search_pool(pool, seed, targets, talents=SHADOW_TALENTS)
            legend = [item.name for item in build.items if item.rawcode in LEGENDARIES]
            print(f"{key} {dps:.1f} legendary {legend} " + ", ".join(item.name for item in build.items), flush=True)
            results[key] = payload(label, build, shop_ids, targets)
            _write_merged(out, results)
            write_all()
    print("готово", flush=True)


if __name__ == "__main__":
    main()
