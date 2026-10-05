from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

def dump_call(needle: str, before: int = 200, after: int = 500) -> None:
    index = script.find(needle)
    print("\n====", needle, index)
    print(script[max(0, index - before) : index + after])

dump_call("UnitHasItemOfTypeBJ(udg_DamageEventSource,'I07O')")
dump_call("UnitHasItemOfTypeBJ(udg_DamageEventSource,'I0NT')", 100, 400)
# party count?
print("\ncount players with orb", script.count("I07O"))
