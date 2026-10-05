from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("set udg_MagicalType_Bonus=(udg_MagicalType_Bonus+0.18)")
print("at", i)
# walk back to the if(
back = script.rfind("if(Trig_", 0, i)
print(script[back : i + 40])
name = script[back + 3 : script.find("(", back)]
print("NAME", name)
fn = script.find(f"function {name} ")
print(script[fn : fn + 600])
