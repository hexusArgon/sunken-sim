"""Shadow sextuples that include Mind Amplifier X-8000. Does not edit the top-100 list."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.amplifier_run import search_with_amplifier
from sunken_sim.library import load_items
from sunken_sim.search import LEGENDARIES, pools_for
from sunken_sim.shadow import MIND_AMPLIFIER

from run_hp import SHADOW_TALENTS, payload

TOP100 = Path(__file__).with_name("shadow-top100.json")
OUT = Path(__file__).with_name("amplifier-sims.json")
RECORD_DIR = Path(__file__).with_name("exhaustive")


def main() -> None:
    catalog = load_items()
    by_code = {item.rawcode: item for item in catalog}
    amplifier = by_code[MIND_AMPLIFIER]
    allowed = {row["rawcode"] for row in json.loads(TOP100.read_text(encoding="utf-8"))}
    if amplifier.rawcode in allowed:
        raise SystemExit("усилитель уже в топ-100, отдельный прогон не нужен")
    shop, drop, legendaries = pools_for(catalog)
    shop = [item for item in shop if item.rawcode in allowed]
    drop = [item for item in drop if item.rawcode in allowed]
    legendaries = [item for item in legendaries if item.rawcode in allowed]
    if amplifier.rawcode not in {item.rawcode for item in pools_for(catalog)[1]}:
        raise SystemExit("Mind Amplifier X-8000 нет в пуле дропа")
    shop_ids = {item.rawcode for item in shop}
    pools = (
        ("mixed", [amplifier] + shop + drop + legendaries),
        ("drop", [amplifier] + drop + legendaries),
    )
    print(
        f"{amplifier.name} дроп, к топ-100 не дописан, "
        f"таланты {len(SHADOW_TALENTS)}, shop нет",
        flush=True,
    )
    talents = tuple(sorted(SHADOW_TALENTS))
    results = {}
    if OUT.exists():
        results = json.loads(OUT.read_text(encoding="utf-8"))
    for targets in (5,):
        for label, pool in pools:
            key = f"{targets}-{label}"
            if key in results:
                print(f"уже есть {key}", flush=True)
                continue
            print(f"старт {key} {len(pool)}", flush=True)
            record = RECORD_DIR / f"shadow-{targets}-amplifier-{label}.json"
            build, dps = search_with_amplifier(pool, targets, talents, record)
            legend = [item.name for item in build.items if item.rawcode in LEGENDARIES]
            print(
                f"{key} {dps:.1f} legendary {legend} " + ", ".join(item.name for item in build.items),
                flush=True,
            )
            results[key] = payload(label, build, shop_ids, targets)
            OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("готово", flush=True)


if __name__ == "__main__":
    main()
