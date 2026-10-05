from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("function Trig_DCS_")
print("first", script[i : i + 80] if i >= 0 else "none")
# how damage bonus is applied from items in slots
idx = script.find("DCS_ItemDamageBonus")
print("mentions", script.count("DCS_ItemDamageBonus"))
# find a slot loop adding damage
key = "UnitItemInSlotBJ"
print("slots", script.count(key))
# search function names with DCS
import re
names = sorted(set(re.findall(r"function (Trig_DCS_\w+|DCS_\w+)", script)))
print("names", names[:30])
