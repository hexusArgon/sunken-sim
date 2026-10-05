from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = script.find("if(Trig_PreDamage_Items_Glyphs_Func002Func005C())then")
call = script.find("if(Trig_PreDamage_Items_Glyphs_Func002Func005Func012C())then")
chunk = script[start:call]
# crude: each line if( ... then depth+1, endif depth-1
depth = 0
for line in chunk.split("\n"):
    s = line.strip()
    if s.startswith("if(") and s.endswith("then"):
        depth += 1
    elif s == "endif":
        depth -= 1
print("depth just before orb block", depth)
print("lines", chunk.count("\n"))
