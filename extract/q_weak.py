import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path
import re, sys
sys.stdout.reconfigure(encoding="utf-8")

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

print("shop", len(re.findall(r"TasItemShop_Item='I0JU'", script)))
print("drops", script.count("Drops_") and "search")
# any assignment of item I0JU besides talents and crit gain
for label, needle in (
    ("create", "CreateItem"),
    ("add", "UnitAddItem"),
    ("shop", "TasItemShop_Item='I0JU'"),
    ("drop set", "='I0JU'"),
):
    print(label, script.count(needle if "I0JU" in needle else needle))

print("assignments of I0JU")
start = 0
while True:
    i = script.find("'I0JU'", start)
    if i < 0:
        break
    line = script[max(0, i - 80) : i + 20].replace("\n", " | ")
    print(line)
    start = i + 6

# crit gain amount near Func004
i = script.find("function Trig_Critical_Gain_Actions")
print("\nCRIT GAIN head")
print(script[i : i + 900])
