from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("function Trig_PreDamage_Increase_Func001Func013Func011Func002Func002C ")
print(script[i : i + 450])
print("--- parent attack ---")
i = script.find("function Trig_PreDamage_Increase_Func001Func013Func011Func002C ")
print(script[i : i + 400])
# is parent inside attack gate? find call depth later if needed
print("--- 011C ---")
i = script.find("function Trig_PreDamage_Increase_Func001Func013Func011C ")
print(script[i : i + 350])
