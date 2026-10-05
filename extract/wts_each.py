from pathlib import Path
import re, sys
sys.stdout.reconfigure(encoding="utf-8")
wts = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.wts").read_text(encoding="utf-8", errors="replace")
for m in re.finditer(r"Each point of Mastery.{0,220}", wts):
    print(m.group(0).replace("\n", " ")[:240])
    print("---")
print("\n==== Haste stat button ====")
idx = wts.find("The Haste stat")
print("idx", idx)
if idx < 0:
    idx = wts.find("Haste |c")
print(wts[idx:idx+900] if idx>=0 else "no haste intro")
