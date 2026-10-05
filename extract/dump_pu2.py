from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
needle = "Func001Func020Func008Func005C())then"
i = script.find(needle)
print(script[i : i + 600])
print("--- cond ---")
i = script.find("function Trig_PreDamage_Increase_Func001Func020Func008Func005C ")
print(script[i : i + 400])
