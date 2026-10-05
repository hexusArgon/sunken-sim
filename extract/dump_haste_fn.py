from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("function Trig_Haste_Gain_Func010C ")
print(script[i : i + 1500])
print("--- codes in haste gain region ---")
start = script.find("function Trig_Haste_Gain_Func003Func")
end = script.find("function Trig_Haste_Gain_Actions")
region = script[start:end]
print("region", start, end, "len", len(region))
codes = re.findall(r"'([A-Za-z0-9]{4})'", region)
print("unique", len(set(codes)))
print(codes[:40])
