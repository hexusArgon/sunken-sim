from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("set udg_TasItemShop_Item='I07O'\nset udg_TasItemShop_Mats")
print("idx", i)
print(script[i-200:i+700])
