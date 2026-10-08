import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items

codes = ["I0OT", "I09Y", "I09R", "I069", "I064", "I04C", "I09L", "I01J", "I0NG", "I0I1", "I09Z", "I0OR", "I0OQ", "I0G8", "I0OU", "I0OS", "I0NC", "I0ND"]
by = {item.rawcode: item for item in load_items()}
lines = []
for code in codes:
    item = by[code]
    lines.append(f"\n==== {code} {item.name} ====\n{item.tip[:500]}")
Path(__file__).with_name("paladin-talent-tips.txt").write_text("\n".join(lines), encoding="utf-8")
print("ok")
