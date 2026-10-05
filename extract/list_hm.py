import re
from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
names = sorted(set(re.findall(r"function (Trig_\w*(?:Haste|Mastery)\w*)", script)))
for name in names:
    if "Tooltip" in name or name.endswith("_Actions"):
        print(name)
