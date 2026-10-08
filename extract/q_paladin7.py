import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script, map_strings, _extract, MAP_PATH
import re

script = map_script()
strings = map_strings()
i = script.find("set udg_Ability_Str[3]='A0GE'")
chunk = script[i - 2500 : i + 800]
# talent names
codes = re.findall(r"udg_Talents_Str\[\d+\]='(....)'", script)
# only the run that contains A0GE nearby: take unique in the chunk
local = re.findall(r"udg_Talents_Str\[\d+\]='(....)'", chunk)
lines = ["LOCAL TALENTS " + " ".join(local), "CHUNK:\n" + chunk]

# resolve ability names from extended tooltips is hard; print string if code appears as text
path = Path(__file__).with_name("paladin-bar.txt")
path.write_text("\n".join(lines), encoding="utf-8")
print("local", local, "all talents_str", len(codes))
