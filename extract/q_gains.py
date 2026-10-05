from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
names = sorted(set(re.findall(r"function (Trig_\w+_Gain_Actions)", script)))
print("\n".join(names))
print("count", len(names))
