from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
print("0.006", script.count("0.006"))
print("Haste_Stat", script.count("Haste_Stat"))
print("Haste_Items", script.count("Haste_Items"))
index = script.find("function Trig_CDR_Setup_Actions")
print("\nCDR SETUP")
print(script[index : index + 1600])
