from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

def action_pairs(name):
    start = script.find(f"function {name}")
    end = script.find("function InitTrig_", start)
    body = script[start:end]
    adds = re.findall(
        r"(Func\d+C)\)\)then\nset udg_\w+\[udg_PlayerNumber\]=\(udg_\w+\[udg_PlayerNumber\]\+([0-9.]+)\)",
        body,
    )
    print(name, "adds", adds[:8], "n", len(adds))

for name in (
    "Trig_Mastery_Gain_Actions",
    "Trig_Attack_Speed_Gain_Actions",
    "Trig_Potency_Gain_Actions",
    "Trig_Luck_Gain_Actions",
):
    action_pairs(name)

# sample mastery func body
i = script.find("function Trig_Mastery_Gain_Func006Func")
print("\nSAMPLE")
print(script[i : i + 400])
