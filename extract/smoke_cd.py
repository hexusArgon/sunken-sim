import sys
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items
from sunken_sim.shadow import Build, _ability_cd, character, simulate

by = {item.rawcode: item for item in load_items()}

def stats_of(*codes, glyphs=()):
    build = Build(frozenset(), frozenset(glyphs), tuple(by[c] for c in codes), 0, 0, 0, 0)
    return character(build)

base = stats_of()
print("no haste mind", round(_ability_cd(8, base), 4))
orb = stats_of("I0NT")
print("orb haste", orb["haste"], "mind", round(_ability_cd(8, orb), 4), "tick", round(orb["swp_period"], 4))
harness = stats_of("I07P", "I0NT")
print("harness+orb temp", harness["cd_temp"], "mind", round(_ability_cd(8, harness), 4))
mind = stats_of(glyphs=("I0OF",))
print("mindhaste haste", mind["haste"], "flat", mind["flat_cdr"], "mind", round(_ability_cd(8, mind), 4))
magi = stats_of("I06M")
print("magi haste", magi["haste"])
core = stats_of("I0FW")
print("core temp", core["cd_temp"], "mind", round(_ability_cd(8, core), 4))
pipe = stats_of("I00L")
print("pipe flat", pipe["flat_cdr"], "mind", round(_ability_cd(8, pipe), 4))
ring = stats_of("I00D")
print("ring unbound", round(_ability_cd(8, ring), 4), "bound", round(_ability_cd(8, ring, True), 4))

# one short fight so the diamond branch and scoring don't crash
build = Build(frozenset({"I0PS", "I0PU", "I0SA"}), frozenset({"I0AV", "I0HC", "I0JA"}), tuple(by[c] for c in ("I0NT", "I07P")), 0, 0, 5, 0)
report = simulate(build, 1)
print("sample dps", round(report.dps, 1), "haste", report.stats["haste"], "tick", round(report.stats["swp_period"], 3))
print("cds", {name: round(_ability_cd({"Shadow Word: Pain": 6, "Mind Spike": 8, "Void Rift": 10, "Divine Image": 16}[name], report.stats), 3) for name in ("Shadow Word: Pain", "Mind Spike", "Void Rift", "Divine Image")})
