import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path
import re

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

# Find Weakness item vs talent
print("I0JU count", script.count("'I0JU'"))
start = 0
n = 0
while n < 12:
    i = script.find("'I0JU'", start)
    if i < 0:
        break
    window = script[max(0, i - 140) : i + 80].replace("\n", " | ")
    print(n, window[:260])
    print("---")
    start = i + 6
    n += 1

print("\n==== duplicate / already carrying phrases ====")
for needle in (
    "already have",
    "already owns",
    "only have one",
    "cannot carry more",
    "ItemCount",
    "CountItems",
):
    print(needle, script.lower().count(needle.lower()) if needle != "ItemCount" else script.count(needle))
