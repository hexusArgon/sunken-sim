import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import Item, load_items, map_script, map_strings

strings = map_strings()
script = map_script()
codes = ["I0OT", "I09Y", "I09R", "I069", "I064", "I04C", "I09L", "I01J", "I0NG", "I0MD", "I0I1", "I09Z", "I0OR", "I0OQ", "I0G8", "I0OU", "I0OS", "I0NC", "I0ND", "I0MC"]
by = {item.rawcode: item for item in load_items()}
lines = []
for code in codes:
    item = by.get(code)
    lines.append(f"{code} {item.name if item else 'MISSING'}")

# hammer spawn duration
start = script.find("function Trig_Blessed_Hammer_Spawn_Actions")
end = script.find("\nendfunction", start)
lines.append("\nSPAWN\n" + script[start:end][:2500])

# long tooltips
lines.append("\nTIPS")
for number, text in strings.items():
    plain = re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", text)
    if "Crusader Strike" in plain and ("Cooldown" in plain or "cooldown" in plain or len(plain) > 180):
        if plain.strip() in {"Crusader Strike", "Crusader Strike now causes Divine Storm which unleashes a whirl of holy hammers, dealing 20 Magical damage (+100% of Strength) (+100% of Intelligence) (+100% of Mastery) to all nearby enemies.\n\nWhile in Protection or Holy Specialziations, the damage dealt will be reduced by 50%, but Righteous Fury will be applied on enemies hit.\n\nThe Paladin needs to have the Righteous Fury ability for its debuff to be applied."}:
            continue
        lines.append(f"\n#{number}\n{plain[:700]}")

Path(__file__).with_name("paladin-talents.txt").write_text("\n".join(lines), encoding="utf-8")
print("items", sum(1 for c in codes if c in by))
