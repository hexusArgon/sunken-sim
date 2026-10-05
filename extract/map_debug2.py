from pathlib import Path
import re
script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = script.find("set udg_MagicalType_Bonus=1.00")
end = script.find("set udg_PhysicalType_Bonus=1.00", start + 10)
chunk = script[start:end]
print("len", len(chunk), "sets", chunk.count("set udg_MagicalType_"))
pat = re.compile(r"if\((Trig_PreDamage_Increase_Func\w+)\)\)then\s*set udg_")
print("matches", len(pat.findall(chunk)))
print(pat.findall(chunk)[:8])
