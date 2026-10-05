from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("Trig_Critical_Gain_Func004C())then")
print(script[i : i + 400])
print("--- cond ---")
i = script.find("function Trig_Critical_Gain_Func004C ")
print(script[i : i + 350])
