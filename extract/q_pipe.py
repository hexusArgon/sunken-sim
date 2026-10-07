from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items, map_script
by = {i.rawcode: i for i in load_items()}
item = by["I00L"]
print(item.name)
print(item.tip)
print("parsed stun", item.stun_chance, item.stun_duration, "flat", item.cooldown_add)

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
print("mentions", script.count("'I00L'"))
start = 0
n = 0
while n < 8:
    i = script.find("'I00L'", start)
    if i < 0:
        break
    print(n, script[max(0, i-120):i+100].replace("\n", " | ")[:260])
    print("---")
    start = i + 6
    n += 1
