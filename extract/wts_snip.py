import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_wts_text
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
wts = map_wts_text()
print(wts[101400:102200])
print("\n\n==== CDR ====")
print(wts[114300:115200])
print("\n\n==== ignore armor strings ====")
idx = 0
low = wts.lower()
n = 0
while n < 8:
    i = low.find("ignore armor", idx)
    if i < 0:
        break
    print(wts[max(0,i-250):i+200].replace("\r",""))
    print("---")
    idx = i + 10
    n += 1
