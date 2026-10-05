from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = script.find("set udg_MagicalType_Bonus=1.00")
end = script.find("set udg_PhysicalType_Bonus=1.00", start)
chunk = script[start:end]
for m in re.finditer(r"set udg_MagicalType_(Bonus|Dynamic)=\(udg_MagicalType_\1([+\*])", chunk):
    line = chunk[m.start() : m.start() + 140].replace("\n", " ")
    print(f"{m.start():5} {line}")
