import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script, map_strings

script = map_script()
strings = map_strings()
lines = []
for match in re.finditer(r".{0,80}udg_Hero_Paladin=.{0,120}", script):
    lines.append(match.group(0).replace("\n", " "))
    if len(lines) > 15:
        break
lines.append("--- create ---")
for match in re.finditer(r"CreateNUnitsAtLoc.{0,40}udg_Hero_Paladin|udg_Hero_Paladin=CreateUnit.{0,80}", script):
    lines.append(match.group(0).replace("\n", " "))

# crusader function
i = script.find("udg_CrusaderStrike_Damage=(((")
lines.append("--- crusader context ---")
lines.append(script[max(0, i - 800) : i + 900])

# string 2274 and nearby long crusader tooltips
for number in (2274, 8113, 3079, 3505, 4000, 261, 1188, 307):
    text = strings.get(number, "")
    plain = re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", text)
    lines.append(f"\n--- str {number} ---\n{plain[:800]}")

Path(__file__).with_name("paladin-unit.txt").write_text("\n".join(lines), encoding="utf-8")
print("ok", len(lines))
