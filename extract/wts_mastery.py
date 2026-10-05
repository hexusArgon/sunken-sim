from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
wts = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.wts").read_text(encoding="utf-8", errors="replace")
# priest mastery button
idx = wts.find("Priest:")
print("Priest: count", wts.count("Priest:"))
# find mastery class list
idx = wts.find("Necromancer:")
print(wts[idx:idx+2500][:2000])
