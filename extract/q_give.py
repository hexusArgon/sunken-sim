from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

def show(name, n=1800):
    i = script.find(f"function {name} ")
    print("\n====", name, "at", i)
    print(script[i : i + n] if i >= 0 else "missing")

show("TasItemShop_CanBuyItem", 900)
show("TasItemShop_GiveItem", 2200)
