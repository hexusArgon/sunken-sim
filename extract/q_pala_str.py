import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script

script = map_script()
idx = 0
n = 0
lines = []
while n < 25:
    i = script.find("udg_Hero_Paladin", idx)
    if i < 0:
        break
    window = script[max(0, i - 100) : i + 40].replace("\n", " | ")
    if "Damage" in window or "STR" in window or "0." in window:
        lines.append(window)
        n += 1
    idx = i + 16
Path(__file__).with_name("pala-str.txt").write_text("\n\n".join(lines), encoding="utf-8")
print(n)
