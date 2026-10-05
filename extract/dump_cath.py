from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("Func001Func020Func004Func002C())then")
print(script[i : i + 450])
print("---- unsealed leaf")
i = script.find("function Trig_PreDamage_Increase_Func001Func020Func002Func002Func001C ")
print(script[i : i + 350])
