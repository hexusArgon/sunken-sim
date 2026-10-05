from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = script.find("function Trig_Haste_Gain_Actions")
end = script.find("function InitTrig_Haste_Gain")
body = script[start:end]
# pairs of +N and nearby item codes in conditions are separate functions
# dump each Func00N condition that adds haste
for m in re.finditer(r"function (Trig_Haste_Gain_Func\d+C) takes nothing returns boolean\n(.*?)\nendfunction", script):
    name, bodyf = m.group(1), m.group(2)
    if "Haste_Gain_Func" not in name:
        continue
    codes = re.findall(r"'([A-Za-z0-9]{4})'", bodyf)
    if codes:
        print(name, codes)
