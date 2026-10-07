import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import load_items, map_script

wanted = ("Cursed Skull", "Sinister Deathblade", "Silent Messenger")
items = {item.name: item for item in load_items()}
for name in wanted:
    item = items[name]
    print(item.rawcode, name)
    print(item.tip)
    print()

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
for code in (items["Silent Messenger"].rawcode, items["Sinister Deathblade"].rawcode, items["Cursed Skull"].rawcode):
    print("====", code, script.count(f"'{code}'"))
    index = 0
    shown = 0
    needle = f"'{code}'"
    while shown < 4:
        index = script.find(needle, index)
        if index < 0:
            break
        print(script[max(0, index - 250) : index + 500].replace("\n", " | ")[:700])
        print()
        shown += 1
        index += len(needle)
