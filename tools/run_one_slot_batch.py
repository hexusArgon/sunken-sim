import subprocess, sys, time
from pathlib import Path
scripts = Path("extract").glob("one_slot_*.py")
skip = {"one_slot_classes.py","one_slot_sim.py"}
order = [
 "one_slot_shaman.py",
 "one_slot_monk.py","one_slot_necromancer.py","one_slot_rogue.py","one_slot_siren.py","one_slot_tidewarrior.py",
 "one_slot_tinker.py","one_slot_warlock.py","one_slot_warrior.py","one_slot_windmaster.py","one_slot_witch_doctor.py",
 "one_slot_paladin.py"
]
log = Path("logs/one_slot_batch.log")
err = Path("logs/one_slot_batch.err")
with log.open("w", encoding="utf-8") as out, err.open("w", encoding="utf-8") as er:
    for name in order:
        path = Path("extract")/name
        if not path.exists():
            out.write(f"SKIP missing {name}\n"); out.flush(); continue
        out.write(f"\n=== {name} ===\n"); out.flush()
        p = subprocess.run([sys.executable, "-u", str(path)], stdout=out, stderr=er)
        out.write(f"exit {p.returncode}\n"); out.flush()
        if p.returncode != 0:
            er.write(f"{name} failed {p.returncode}\n"); er.flush()
print("batch done")
