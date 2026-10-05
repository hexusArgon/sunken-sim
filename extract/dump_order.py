from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = script.find("set udg_MagicalType_Bonus=1.00")
end = script.find("set udg_PhysicalType_Bonus=1.00", start)
chunk = script[start:end]
needles = [
    "MagicalType_Bonus+0.18",
    "MagicalType_Bonus*1.15",
    "MagicalType_Bonus*1.30",
    "MagicalType_Dynamic+(0.30",
    "MagicalType_Bonus+0.14",
    "I0QT",
    "MagicalType_Bonus+",
    "MagicalType_Bonus*",
]
print("section", len(chunk))
for n in needles:
    print(n, chunk.find(n))
