from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
for name in (
    "Trig_PreDamage_Increase_Func001Func020C",
    "Trig_PreDamage_Increase_Func001Func024C",
    "Trig_PreDamage_Increase_Func001C",
):
    i = script.find(f"function {name} ")
    print("\n====", name)
    print(script[i : i + 450])
