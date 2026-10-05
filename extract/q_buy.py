from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
names = re.findall(r"function (TasItem\w+) takes", script)
print("\n".join(names[:60]))
print("count", len(names))
