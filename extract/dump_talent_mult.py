import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
for code in ("I0AV", "I0PU", "I0PS"):
    print("\n####", code, script.count(f"'{code}'"))
    start = 0
    n = 0
    while n < 4:
        i = script.find(f"'{code}'", start)
        if i < 0:
            break
        window = script[max(0, i - 60) : i + 40].replace("\n", " | ")
        if "PreDamage" in window or "Damage" in window or "Type_Bonus" in window or "Glyph" in window or "Talent" in window:
            print(n, window[:200])
            n += 1
        start = i + 6
