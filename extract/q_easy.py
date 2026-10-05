from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("function Trig_EasyItemStacknSplitGUI_Func019C ")
print(script[i : i + 500])
print("--- 004 ---")
i = script.find("function Trig_EasyItemStacknSplitGUI_Func019Func004C ")
print(script[i : i + 400])
