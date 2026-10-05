from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
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
