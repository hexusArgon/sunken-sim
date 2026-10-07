import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
for needle in ("TasItemStock", "StockMax", "stockMax", "AddItemToStock", "RemoveItemFromStock"):
    print(needle, script.count(needle))
i = script.find("function TasItemShop")
print("fn", i)
# purchase function
i = script.find("function BuyTasItem")
print("buy", i)
idx = script.find("UndoStackGainer")
print(script[idx - 200 : idx + 500][:800])
