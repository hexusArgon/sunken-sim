from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
print("SetPlayerAbilityAvailable priest-ish")
idx = 0
n = 0
while n < 15:
    i = script.find("SetPlayerAbilityAvailable", idx)
    if i < 0:
        break
    window = script[i : i + 120]
    if any(code in window for code in ("A0GB", "A0NC", "A0JK", "A0GC", "A0GK", "A0MC", "A0MI")):
        print(window.replace("\n", " | ")[:200])
        n += 1
    idx = i + 20
print("shown", n)

# full shadow form tooltip from skin already partially known
# search ability available false for priest
print("\ncount available", script.count("SetPlayerAbilityAvailableBJ"))
