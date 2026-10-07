import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
idx = 0
while True:
    i = script.find("'I0PU'", idx)
    if i < 0:
        break
    fn = script.rfind("function ", 0, i)
    header = script[fn : script.find("\n", fn)]
    print(header)
    idx = i + 6
