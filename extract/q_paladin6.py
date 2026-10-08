import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script

script = map_script()
lines = []
for code in ("A0GE", "A07L", "A01G", "A0JM"):
    count = script.count(f"'{code}'")
    lines.append(f"{code} {count}")
    idx = 0
    shown = 0
    while shown < 6:
        i = script.find(f"'{code}'", idx)
        if i < 0:
            break
        lines.append(script[max(0, i - 90) : i + 70].replace("\n", " | "))
        idx = i + 6
        shown += 1
    lines.append("---")

# cooldown calls near these abilities
for match in re.finditer(r"BlzSetUnitAbilityCooldown\('A0GE'[^)]{0,80}\)|BlzSetAbilityRealLevelField\([^)]{0,40}'A0GE'", script):
    lines.append(match.group(0)[:200])

Path(__file__).with_name("paladin-ids.txt").write_text("\n".join(lines), encoding="utf-8")
print("lines", len(lines))
