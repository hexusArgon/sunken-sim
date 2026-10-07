import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
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
