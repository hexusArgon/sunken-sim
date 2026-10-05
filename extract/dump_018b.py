from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
name = "Trig_PreDamage_Increase_Func001Func020Func002Func002C"
i = script.find(f"function {name} ")
print(script[i : i + 700])
print("---- parent")
name = "Trig_PreDamage_Increase_Func001Func020Func002C"
i = script.find(f"function {name} ")
print(script[i : i + 400])
