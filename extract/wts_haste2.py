from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
wts = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.wts").read_text(encoding="utf-8", errors="replace")
for key in ["Haste", "Mastery", "Shadow Word", "ignore armor", "Elemental Orb"]:
    print(key, wts.lower().count(key.lower()))
# haste description likely "reduces the cooldown"
idx = wts.find("reduces the cooldown of your abilities")
print("\nreduces idx", idx)
idx = wts.lower().find("cooldown reduction")
print("cdr idx", idx)
# print a window around first "Haste" that looks like a stat explanation
import re
for m in re.finditer(r".{80}Haste.{120}", wts):
    s = m.group(0).replace("\n"," ")
    if "abil" in s.lower() or "cooldown" in s.lower() or "cast" in s.lower() or "%" in s:
        print(s[:220])
        print("---")
