from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("set udg_MagicalType_Dynamic=(udg_MagicalType_Dynamic+0.15)")
print(script[i - 200 : i + 80])
# condition of the 0.15
back = script.rfind("if(Trig_PreDamage_Increase_", 0, i)
name = script[back + 3 : script.find("()", back)]
print("COND", name)
fn = script.find(f"function {name} ")
print(script[fn : fn + 500])
