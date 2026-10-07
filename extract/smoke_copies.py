from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items
from sunken_sim.shadow import Build, character
from sunken_sim.stacking import allows_copies, stack_fields

by = {item.rawcode: item for item in load_items()}
ring = by["I00D"]
print("ring", allows_copies("I00D"), stack_fields("I00D"))
one = character(Build(frozenset(), frozenset(), (ring,), 0, 0))
two = character(Build(frozenset(), frozenset(), (ring, ring), 0, 0))
print("haste", one["haste"], two["haste"])
print("mastery", one["mastery"], two["mastery"])
print("int", one["int"], two["int"])
print("orb copies", allows_copies("I0NT"), "legendary", allows_copies("I052"))
