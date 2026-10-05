import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
wts = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.wts").read_text(encoding="utf-8", errors="replace")
for key in ("Shadow Specialization", "Holy Specialization", "Discipline Specialization", "Priest:"):
    print(key, wts.find(key))
# spec button text near priest
idx = wts.lower().find("shadow specialization")
print("---")
print(wts[idx:idx+400] if idx>=0 else "no shadow spec phrase")
idx = wts.lower().find("discipline")
print("discipline idx", idx)
print(wts[idx:idx+200] if idx>=0 else "")
