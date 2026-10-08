"""Dump paladin damage and heal trigger bodies."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sunken_sim.library import map_script

script = map_script()
funcs = [
    "Trig_Blessed_Hammer_Damage_Actions",
    "Trig_Blessed_Hammer_Cast_Actions",
    "Trig_Holy_Light_Actions",
    "Trig_Divine_Toll_Actions",
    "Trig_Beacon_of_Light_Actions",
    "Trig_Hammer_of_Justice_Actions",
    "Trig_Divine_Protection_Actions",
    "Trig_Ardent_Defender_Activate_Actions",
]
chunks = []
for name in funcs:
    start = script.find(f"function {name}")
    if start < 0:
        chunks.append(f"\nMISSING {name}\n")
        continue
    end = script.find("\nendfunction", start)
    body = script[start : end + 12]
    chunks.append(f"\n===== {name} {len(body)} =====\n")
    chunks.append(body[:6000])

# any function with Crusader in the name
idx = 0
while True:
    i = script.find("Crusader", idx)
    if i < 0:
        break
    line_start = script.rfind("\n", 0, i) + 1
    line_end = script.find("\n", i)
    chunks.append("\nLINE " + script[line_start:line_end][:240])
    idx = i + 8
    if idx > 0 and script[:i].count("Crusader") > 40:
        break

path = Path(__file__).with_name("paladin-triggers.txt")
path.write_text("".join(chunks), encoding="utf-8")
print(path.stat().st_size)
