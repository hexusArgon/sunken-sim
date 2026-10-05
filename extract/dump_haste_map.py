from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
# action amounts
start = script.find("function Trig_Haste_Gain_Actions")
end = script.find("function InitTrig_Haste_Gain")
body = script[start:end]
adds = re.findall(r"Trig_Haste_Gain_(Func\d+C)\(\)\)then\nset udg_Haste_Items\[udg_PlayerNumber\]=\(udg_Haste_Items\[udg_PlayerNumber\]\+(\d+)\)", body)
print("adds", adds)
for func, amount in adds:
    i = script.find(f"function Trig_Haste_Gain_{func} ")
    chunk = script[i : i + 2500]
    # stop at next function after this one... the condition function may call subfunctions
    codes = re.findall(r"'([A-Za-z0-9]{4})'", chunk.split("endfunction")[0])
    print(amount, func, codes)
