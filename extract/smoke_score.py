import sys
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
from sunken_sim.library import load_items
from sunken_sim.search import _best_points
from sunken_sim.shadow import Build, simulate

by = {item.rawcode: item for item in load_items()}
codes = ("I0NT", "I07P", "I0QT", "I048", "tlum", "I044")
build = Build(
    frozenset({"I0PS", "I0PU", "I0SA"}),
    frozenset({"I0AV", "I0JA", "I0OF"}),
    tuple(by[c] for c in codes),
    1,
    2,
    2,
    0,
)
counter = {}
report = simulate(build, 3, counter)
dps, points = _best_points(counter, build)
print("simulate", round(report.dps, 2))
print("search points", points, "dps", round(dps, 2))
# resim at those points: crit, potency, luck, mastery stored as points tuple (crit, pot, luck, mast)
final = Build(build.talents, build.glyphs, build.items, points[1], points[3], points[0], points[2])
again = simulate(final, 3)
print("resim", round(again.dps, 2), "delta", round(again.dps - dps, 2))
