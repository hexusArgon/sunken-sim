from pathlib import Path
import sys
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import _extract, _parse_objects, MAP_PATH

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
print("I03L contexts")
start = 0
n = 0
while n < 8:
    i = script.find("'I03L'", start)
    if i < 0:
        break
    print(script[max(0, i - 100) : i + 90].replace("\n", " | ")[:240])
    print("---")
    start = i + 6
    n += 1

# skin order of orbs
skin_blob = _extract(MAP_PATH, "war3mapSkin.w3t")
text = skin_blob.decode("latin1", "replace")
for code in ("I07O", "I0NS", "I0NT"):
    print(code, "pos", text.find(code))
