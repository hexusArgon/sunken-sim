import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
for code in ("B03T", "B03O", "B03R", "A0AU", "A0AO", "A0AT"):
    print("\n====", code, script.count(f"'{code}'"))
    start = 0
    n = 0
    while n < 6:
        i = script.find(f"'{code}'", start)
        if i < 0:
            break
        print(script[max(0,i-160):i+80].replace("\n"," | "))
        print("---")
        start = i + 6
        n += 1
