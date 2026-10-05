from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

def dump(name: str, size: int = 1800) -> None:
    index = script.find(f"function {name} ")
    print("\n====", name, index)
    print(script[index : index + size])

dump("Trig_Haste_Gain_Actions", 2200)
