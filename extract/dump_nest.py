from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = script.find("set udg_MagicalType_Bonus=1.00")
end = script.find("set udg_PhysicalType_Bonus=1.00", start)
chunk = script[start:end]
depth = 0
for line in chunk.split("\n"):
    s = line.strip()
    if s.startswith("if(") and s.endswith("then"):
        depth += 1
    elif s == "endif":
        depth -= 1
print("depth at physical reset", depth)
# show last 15 lines
print("\n".join(chunk.split("\n")[-12:]))
