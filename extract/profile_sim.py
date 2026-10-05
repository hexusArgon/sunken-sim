import cProfile
import pstats
import sys
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
from sunken_sim.library import load_items
from sunken_sim.search import _best_points
from sunken_sim.shadow import Build, simulate

by = {item.rawcode: item for item in load_items()}
items = tuple(by[c] for c in ("I0NT", "I07P", "I052", "I0QN", "I04F", "I0BB"))
build = Build(frozenset({"I0PS", "I0PU", "I0SA"}), frozenset({"I0AV", "I0HC", "I0JA"}), items, 0, 0, 5, 0)
profiler = cProfile.Profile()
profiler.enable()
for _ in range(30):
    counter = {}
    simulate(build, 1, counter)
    _best_points(counter, build)
profiler.disable()
stats = pstats.Stats(profiler).sort_stats("cumulative")
stats.print_stats(25)
