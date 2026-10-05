from pathlib import Path
script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = script.find("set udg_MagicalType_Bonus=1.00")
print(repr(script[start:start+400]))
