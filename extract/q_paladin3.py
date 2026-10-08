"""Find paladin ability triggers and tooltip bodies."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import map_script, map_strings

script = map_script()
strings = map_strings()
names = (
    "Crusader_Strike",
    "Blessed_Hammer",
    "Holy_Light",
    "Divine_Storm",
    "Judgement",
    "Judgment",
    "Consecration",
    "Divine_Protection",
    "Ardent_Defender",
    "Avenging",
    "Hammer_of",
    "Shield_of_the_Righteous",
    "Word_of_Glory",
    "Holy_Shock",
    "Beacon",
    "Righteous_Fury",
    "Divine_Toll",
)
funcs = re.findall(r"(?m)^function (Trig_\w+)", script)
picked = [name for name in funcs if any(bit.lower() in name.lower() for bit in names)]
lines = ["functions " + str(len(picked))]
lines.extend(picked)

# tooltip bodies for short exact names
want = {
    "Crusader Strike",
    "Blessed Hammer",
    "Holy Light",
    "Divine Storm",
    "Judgement",
    "Consecration",
    "Divine Protection",
    "Ardent Defender",
    "Holy Shock",
    "Beacon of Light",
    "Righteous Fury",
    "Divine Toll",
    "Hammer of Wrath",
    "Avenging Wrath",
    "Shield of the Righteous",
    "Word of Glory",
    "Blade of Justice",
    "Final Verdict",
    "Templar's Verdict",
    "Wake of Ashes",
}
lines.append("\n==== tooltips ====")
for number, text in strings.items():
    plain = re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", text)
    first = plain.strip().split("\n", 1)[0].strip()
    if first in want or any(first.startswith(name + " ") for name in want):
        if len(plain) < 40:
            continue
        lines.append(f"\n--- {number} {first[:80]} ---")
        lines.append(plain[:1200])

Path(__file__).with_name("paladin-abilities.txt").write_text("\n".join(lines), encoding="utf-8")
print("funcs", len(picked), "file", Path(__file__).with_name("paladin-abilities.txt").stat().st_size)
