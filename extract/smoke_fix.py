import sys

sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items
from sunken_sim.shadow import Build, simulate

items = {item.name: item for item in load_items()}
for name in ("Silent Messenger", "Sinister Deathblade", "Cursed Skull"):
    item = items[name]
    print(name, "pen", item.armor_pen, "crit_as", item.crit_as, item.crit_as_duration, "stab", item.stab_chance, item.stab_ratio)

# messenger build-ish: just messenger + nightfall + ardite to see swing
build = Build(frozenset({"I0PS", "I0PU", "I0SA"}), frozenset({"I0AV", "I0HC", "I0JA"}), (items["Silent Messenger"], items["Nightfall"], items["Ardite Impaler"], items["Celestial Crown"], items["Predaplant Thorn"], items["Aruzal, Fang of Neltharion"]), 0, 0, 4, 0)
report = simulate(build)
print("messenger dps", round(report.dps, 1), "as", round(report.stats["attack_speed"], 3), "pen", report.stats["armor_pen"])

blade = Build(frozenset({"I0PS", "I0PU", "I0SC"}), frozenset({"I0AV", "I0HC", "I0JA"}), (items["Sinister Deathblade"], items["Harness of Beyond"], items["Cursed Skull"], items["Netherspike"], items["Decapitator"], items["Aruzal, Fang of Neltharion"]), 0, 0, 5, 0)
report = simulate(blade)
print("blade", round(report.dps, 1))
for name, amount in sorted(report.sources.items(), key=lambda row: -row[1]):
    print(f"  {amount/30:.1f} {name}")
