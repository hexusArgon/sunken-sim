from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
wts = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.wts").read_text(encoding="utf-8", errors="replace")
idx = 0
n = 0
low = wts.lower()
while n < 8:
    i = low.find("elemental orb", idx)
    if i < 0:
        break
    print(wts[max(0,i-200):i+600].replace("\r","")[:800])
    print("========")
    idx = i + 12
    n += 1
print("hits", n)
