from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
index = script.find("I2R(udg_Haste_Items[GetConvertedPlayerId")
print(script[index : index + 3500])
