"""Re-score saved builds with real orb modes and the Diamond Ring bind."""

import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import load_items
from sunken_sim.search import GLYPHS, TALENTS
from sunken_sim.shadow import ORB_MODE, Build, simulate

PATH = Path(r"C:\Users\eseid\sunken-sim\extract\target-sims.json")
data = json.loads(PATH.read_text(encoding="utf-8"))
talent_code = {name: code for code, name in TALENTS.items()}
glyph_code = {name: code for code, name in GLYPHS.items()}
by_name: dict[str, list] = {}
by_code = {}
for item in load_items():
    by_name.setdefault(item.name, []).append(item)
    by_code[item.rawcode] = item

for key, run in data.items():
    talents = frozenset(talent_code[name] for name in run["talents"])
    glyphs = frozenset(glyph_code[name] for name in run["glyphs"])
    points = run["points"]
    base = []
    has_orb = False
    for entry in run["items"]:
        if entry["name"] == "Elemental Orb":
            has_orb = True
            continue
        choices = [item for item in by_name[entry["name"]] if item.rawcode not in ORB_MODE]
        if len(choices) != 1:
            raise SystemExit(f"{key} {entry['name']} matches {len(choices)}")
        base.append(choices[0])
    best = None
    for code in ORB_MODE if has_orb else (None,):
        gear = list(base)
        if code is not None:
            gear.append(by_code[code])
        build = Build(
            talents,
            glyphs,
            tuple(gear),
            points["potency"],
            points["mastery"],
            points["crit"],
            points["luck"],
        )
        report = simulate(build, run["targets"])
        if best is None or report.dps > best.dps:
            best = report
    assert best is not None
    run["dps"] = round(best.dps, 1)
    run["total"] = round(best.total)
    run["orb_mode"] = best.orb_mode
    run["bound_spell"] = best.bound_spell
    run["sources"] = [
        {"name": name, "amount": round(amount, 1)}
        for name, amount in sorted(best.sources.items(), key=lambda row: -row[1])
    ]
    run["actions"] = [{"time": round(moment, 2), "spell": spell} for moment, spell in best.actions]
    stats = best.stats
    run["stats"] = {
        "int": stats["int"],
        "ad": stats["ad"],
        "potency": stats["potency"],
        "mastery": stats["mastery"],
        "crit": stats["crit"],
        "rating": stats["rating"],
        "haste": stats["haste"],
        "attack_speed": stats["attack_speed"],
        "mana_max": stats["mana_max"],
        "swing": stats["swing"],
        "swp_period": stats["swp_period"],
    }
    print(
        f"{key:8} {run['dps']:7} orb {run['orb_mode']} ring {run['bound_spell']}"
    )

PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", PATH)
