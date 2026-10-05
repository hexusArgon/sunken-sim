from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

def dump(name: str, size: int = 500) -> None:
    index = script.find(f"function {name} ")
    print("\n", name)
    print(script[index : index + size])

dump("Trig_ArmorDamage_Increase_Func001Func006Func027C", 400)
index = script.find("UnitHasItemOfTypeBJ(udg_DamageEventSource,'ram1')")
print("\nRAM CONTEXT")
print(script[index - 600 : index + 900])
