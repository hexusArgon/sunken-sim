from pathlib import Path

from sunken_sim.search import GLYPHS, TALENTS, search_one_target
from sunken_sim.shadow import format_report, simulate


def main() -> None:
    build, dps = search_one_target()
    report = simulate(build, 1)
    text = format_report(report)
    names = [
        "Таланты: " + ", ".join(TALENTS[raw] for raw in sorted(build.talents)),
        "Глифы: " + ", ".join(GLYPHS[raw] for raw in sorted(build.glyphs)),
        f"Очки: крит {build.crit_points}, Potency {build.potency_points}, Luck {build.luck_points}, Mastery {build.mastery_points}",
        f"Поиск дал {dps:.1f} DPS, полный прогон {report.dps:.1f} DPS",
        "",
        text,
    ]
    path = Path(__file__).resolve().parents[1] / "extract" / "shadow-full.txt"
    path.write_text("\n".join(names), encoding="utf-8")
    print("\n".join(names))


if __name__ == "__main__":
    main()
