"""Pull Paladin specialization blocks out of the map script."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import map_script, map_strings

script = map_script()
out = Path(__file__).with_name("paladin-spec.txt")
chunks = []
start = script.find("function Trig_Specialization_Change_Actions")
end = script.find("function InitTrig_Specialization_Change")
body = script[start:end]
chunks.append(f"spec change body {len(body)} Hero_Paladin {body.count('Hero_Paladin')}\n")
idx = 0
n = 0
while n < 12:
    i = body.find("Hero_Paladin", idx)
    if i < 0:
        break
    chunks.append(f"\n==== {n} {i} ====\n")
    chunks.append(body[max(0, i - 400) : i + 2200])
    idx = i + 12
    n += 1

# talent book names that mention paladin
strings = map_strings()
hits = []
for number, text in strings.items():
    low = text.lower()
    if "paladin" in low:
        hits.append(f"{number}: {text[:240].replace(chr(10), ' | ')}")
chunks.append("\n\n==== strings ====\n")
chunks.append("\n".join(hits[:80]))
chunks.append(f"\nstring hits {len(hits)}\n")

out.write_text("".join(chunks), encoding="utf-8")
print("wrote", out, "blocks", n, "strings", len(hits))
