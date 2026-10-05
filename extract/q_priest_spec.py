from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = script.find("function Trig_Specialization_Change_Actions")
end = script.find("function InitTrig_Specialization_Change")
body = script[start:end]
print("body", len(body))
idx = 0
n = 0
while n < 8:
    i = body.find("Hero_Priest", idx)
    if i < 0:
        break
    print("\n====", n, i)
    print(body[max(0, i - 200) : i + 1800])
    idx = i + 11
    n += 1
print("hits", n)
