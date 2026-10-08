import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_strings

strings = map_strings()
keys = ("Blessed Hammer", "Holy Light", "Crusader Strike", "Divine Protection", "Judgement", "Divine Toll")
lines = []
for number, text in strings.items():
    plain = re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", text)
    if "Cooldown" not in plain and "cooldown" not in plain:
        continue
    if any(key in plain for key in keys) and len(plain) < 900:
        lines.append(f"#{number}\n{plain}\n")
Path(__file__).with_name("paladin-cd.txt").write_text("\n".join(lines), encoding="utf-8")
print("blocks", len(lines))
