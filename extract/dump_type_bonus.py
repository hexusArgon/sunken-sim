from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("udg_MagicalType_Bonus")
print("first", script[i-100:i+150].replace("\n"," | "))
# application: damage * (1+bonus)
idx = 0
n = 0
while n < 6:
    i = script.find("1.00+udg_MagicalType_Bonus", idx)
    if i < 0:
        i = script.find("1+udg_MagicalType_Bonus", idx)
    if i < 0:
        break
    print("\n", script[i-80:i+80].replace("\n"," | "))
    idx = i + 10
    n += 1
print("hits", n)
