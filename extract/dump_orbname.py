from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
for pat in ["ElementalOrb", "Elemental_Orb", "Orb_Power", "OrbPower", "I0NT"]:
    print(pat, script.count(pat))

# fusion mats
i = script.find("set udg_TasItemShop_Item='I07O'")
print("\nFUSION")
print(script[i:i+500])

# buff string usage - search B codes near ignore
# Find ability that mentions TRIGSTR_2632
# w3a is binary. Search extracted objects.
print("\nTRIGSTR_2632 in j", script.count("TRIGSTR_2632"))
