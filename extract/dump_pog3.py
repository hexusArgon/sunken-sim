from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
for m in re.finditer(r"set udg_PoG_Haste_Value\[", script):
    print(script[m.start()-120:m.start()+180].replace("\n"," | "))
    print("---")
print("COUNT", len(re.findall(r"set udg_PoG_Haste_Value\[", script)))
print("SUM sets", len(re.findall(r"set udg_PoG_Haste_Sum\[", script)))
