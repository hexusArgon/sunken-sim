from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("function Trig_Primary_Gain_Actions")
print(script[i : i + 1100])
print("\n==== stack split head ====")
i = script.find("function Trig_EasyItemStacknSplitGUI_Actions")
print("idx", i)
print(script[i : i + 600] if i >= 0 else "none")
