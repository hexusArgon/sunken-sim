from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

def around(needle: str, before: int = 100, after: int = 700, n: int = 2) -> None:
    print("\n####", needle)
    index = 0
    shown = 0
    while shown < n:
        index = script.find(needle, index)
        if index < 0:
            break
        print(script[max(0, index - before) : index + after].replace("\n", " | ")[:900])
        print()
        shown += 1
        index += len(needle)

around("function Trig_ArmorDamage_Increase_Func001Func006Func013C", 0, 200, 1)
around("ArmorPenetration", 80, 200, 6)
around("150.00", 200, 250, 3)
around("udg_CursedSkull_Stacks", 150, 400, 3)
