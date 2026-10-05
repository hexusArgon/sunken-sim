from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

# find functions that mention the flat amounts' parent item checks near Func034
start = script.find("function Trig_CDR_Cast_And_Spell_Types_Func034Func004")
end = script.find("function Trig_CDR_Cast_And_Spell_Types_Func034C ")
chunk = script[start:end]
print("chunk", len(chunk))
# print item codes with nearby flat numbers by scanning function names
codes = re.findall(r"'([A-Za-z0-9]{4})'", chunk)
print("codes", codes)

# Hand of magi haste aura
for needle in ["I06M", "Arcane Aura", "B071"]:
    print(needle, script.count(f"'{needle}'" if len(needle)==4 else needle))
