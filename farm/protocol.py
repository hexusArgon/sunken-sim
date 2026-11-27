"""Text of Discord messages. The first line of a live status is machine-readable."""

from __future__ import annotations

import json
import re

PRIEST_SPECS = ("shadow", "discipline", "holy")
MAGE_SPECS = ("frost", "arcane", "fire")
PALADIN_SPECS = ("retribution", "protection", "holy")
SHAMAN_SPECS = ("restoration", "enhancement", "elemental")
POOLS = ("mixed", "shop", "drop")
TOPS = tuple(range(10, 251, 10))

POOL_LABEL = {
    "mixed": "Shop + drop",
    "shop": "только Shop",
    "drop": "только Random drop",
}
# Classes whose Python fight model was removed: only the exact OpenCL kernel (farm/hybrid/<hero>_cl.py) fights,
# names and constants live there, checks replay farm/hybrid/fixtures/<hero>.json.
GPU_ONLY = frozenset({"berserker", "death_knight"})
# hero key == module name in sunken_sim; order of specs == SPECS of that module.
SPECS = {
    "priest": PRIEST_SPECS,
    "mage": MAGE_SPECS,
    "paladin": PALADIN_SPECS,
    "shaman": SHAMAN_SPECS,
    "berserker": ("headhunter", "poison", "fury"),
    "death_knight": ("frost", "blood", "unholy"),
    "demon_hunter": ("havoc", "vengeance", "devourer"),
    "dragon_sentinel": ("ruby", "obsidian", "emerald"),
    "druid": ("restoration", "balance"),
    "feral_druid": ("primal", "guardian", "savage"),
    "hunter": ("marksmanship", "beast_mastery", "survival"),
    "monk": ("windwalker", "brewmaster", "mistweaver"),
    "necromancer": ("bone", "blood", "essence"),
    "rogue": ("subtlety", "combat"),
    "siren": ("sharpshooter", "watershaper", "seagrace"),
    "tidewarrior": ("myrmidon", "guardian"),
    "tinker": ("engineering", "demolitions", "nanotech"),
    "warlock": ("demonology", "destruction", "affliction"),
    "warrior": ("protection", "arms", "fury"),
    "windmaster": ("upheaval", "storm", "combat"),
    "witch_doctor": ("voodoo", "poison"),
}
HERO_LABEL = {
    "priest": "жрец",
    "mage": "маг",
    "paladin": "паладин",
    "shaman": "шаман",
    "berserker": "берсерк",
    "death_knight": "рыцарь смерти",
    "demon_hunter": "охотник на демонов",
    "dragon_sentinel": "драконий страж",
    "druid": "друид",
    "feral_druid": "друид-зверь",
    "hunter": "охотник",
    "monk": "монах",
    "necromancer": "некромант",
    "rogue": "разбойник",
    "siren": "сирена",
    "tidewarrior": "воин прилива",
    "tinker": "механик",
    "warlock": "чернокнижник",
    "warrior": "воин",
    "windmaster": "мастер ветра",
    "witch_doctor": "знахарь",
}
HERO_NAME = {
    "priest": "Priest",
    "mage": "Mage",
    "paladin": "Paladin",
    "shaman": "Shaman",
    "berserker": "Berserker",
    "death_knight": "Death Knight",
    "demon_hunter": "Demon Hunter",
    "dragon_sentinel": "Dragon Sentinel",
    "druid": "Druid",
    "feral_druid": "Feral Druid",
    "hunter": "Hunter",
    "monk": "Monk",
    "necromancer": "Necromancer",
    "rogue": "Rogue",
    "siren": "Siren",
    "tidewarrior": "Tidewarrior",
    "tinker": "Tinker",
    "warlock": "Warlock",
    "warrior": "Warrior",
    "windmaster": "Windmaster",
    "witch_doctor": "Witch Doctor",
}
# Heroes whose old whole-pool flow (no top) still works.
LEGACY_POOL_HEROES = ("priest", "mage", "paladin", "shaman")

# Legacy preset files (old jobs / local runs). Not offered in Discord.
PRESET_HERO_SPEC = {
    "shadow-top80": ("priest", "shadow"),
    "discipline-top80": ("priest", "discipline"),
    "priest-holy-top80": ("priest", "holy"),
    "frost-top80": ("mage", "frost"),
    "arcane-top80": ("mage", "arcane"),
    "fire-top80": ("mage", "fire"),
    "retribution-top80": ("paladin", "retribution"),
    "protection-top80": ("paladin", "protection"),
    "paladin-holy-top80": ("paladin", "holy"),
    "restoration-top80": ("shaman", "restoration"),
    "enhancement-top80": ("shaman", "enhancement"),
    "elemental-top80": ("shaman", "elemental"),
    "retribution-top79": ("paladin", "retribution"),
    "retribution-top89": ("paladin", "retribution"),
    "protection-top89": ("paladin", "protection"),
}


NOTIFY_USER_ID = "229350465668775936"  # hexus_argon


def mention(text: str) -> str:
    return f"<@{NOTIFY_USER_ID}> {text}"[:2000]


def allowed_mentions() -> dict:
    return {"parse": [], "users": [NOTIFY_USER_ID]}


CONTROL = "sunken-farm-control "
JOB = "sunken-farm-job "
STOP = "sunken-farm-stop "


def grouped(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def clock(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    whole = max(0, int(seconds))
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def rate_text(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 10:
        return str(int(round(value)))
    return f"{value:.1f}"


def parse_int(text: str) -> int:
    cleaned = str(text).replace(" ", "").replace("_", "").replace("\u00a0", "")
    if not cleaned.isdigit():
        raise ValueError(f"не число: {text}")
    return int(cleaned)


def _norm(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = str(text).strip().lower().replace(" ", "_").replace("-", "_")
    return cleaned or None


def heroes_with(spec: str) -> list[str]:
    return [hero for hero, specs in SPECS.items() if spec in specs]


def resolve_hero_spec(hero: str | None, spec: str | None, preset: str | None = None) -> tuple[str, str]:
    preset = (preset or "").strip() or None
    if preset in PRESET_HERO_SPEC:
        preset_hero, preset_spec = PRESET_HERO_SPEC[preset]
        if hero and _norm(hero) != preset_hero:
            raise ValueError(f"набор {preset} для {preset_hero}, не {hero}")
        if spec and _norm(spec) != preset_spec:
            raise ValueError(f"набор {preset} для {preset_spec}, не {spec}")
        return preset_hero, preset_spec
    hero = _norm(hero)
    spec = _norm(spec)
    if spec and "/" in spec:
        spec_hero, spec = spec.split("/", 1)
        spec_hero = spec_hero.strip("_")
        spec = spec.strip("_")
        if hero and hero != spec_hero:
            raise ValueError(f"специализация {spec} выбрана для {spec_hero}, а класс {hero}")
        hero = spec_hero
    if hero is not None and hero not in SPECS:
        raise ValueError(f"нет класса {hero}")
    if spec is None:
        if hero is None:
            return "priest", "shadow"
        raise ValueError(f"укажи spec для {hero}: {', '.join(SPECS[hero])}")
    if hero is None:
        found = heroes_with(spec)
        if not found:
            raise ValueError(f"нет специализации {spec}")
        if len(found) > 1:
            raise ValueError(f"{spec} есть у нескольких классов, укажи hero: {', '.join(found)}")
        hero = found[0]
    if spec not in SPECS[hero]:
        raise ValueError(f"у класса {hero} ({HERO_LABEL[hero]}) нет специализации {spec}; есть {', '.join(SPECS[hero])}")
    return hero, spec


def resolve_top(value) -> int | None:
    if value is None or value == "":
        return None
    number = int(value)
    if number not in TOPS:
        raise ValueError("top: 10, 20, … 250")
    return number


def spec_suggestions(hero: str | None, typed: str | None) -> list[tuple[str, str]]:
    """Autocomplete rows (name, value) for the spec option, at most 25."""
    hero = _norm(hero)
    needle = (_norm(typed) or "").replace("/", "_")
    rows = []
    heroes = [hero] if hero in SPECS else list(SPECS)
    for key in heroes:
        for spec in SPECS[key]:
            label = f"{HERO_NAME[key]} · {spec.replace('_', ' ')}"
            hay = f"{key}_{spec}_{_norm(label)}"
            if needle and needle not in hay:
                continue
            value = spec if hero in SPECS else f"{key}/{spec}"
            rows.append((label, value))
    return rows[:25]


def resolve_pool(pool: str | None) -> str:
    pool = (pool or "mixed").strip().lower()
    if pool not in POOLS:
        raise ValueError(f"нет пула {pool}")
    return pool


def resolve_targets(value) -> int:
    if value is None or value == "":
        return 5
    number = int(value)
    if number < 1 or number > 5:
        raise ValueError("целей от 1 до 5")
    return number


def _dump(prefix: str, payload: dict) -> str:
    return prefix + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _load(prefix: str, content: str) -> dict | None:
    if not content or prefix not in content:
        return None
    raw = content.split(prefix, 1)[1].strip().splitlines()[0]
    return json.loads(raw)


def format_control(leader: str, watch: list[dict]) -> str:
    return "ферма\n" + _dump(CONTROL, {"leader": leader, "watch": watch})


def parse_control(content: str) -> dict | None:
    payload = _load(CONTROL, content)
    if payload is None:
        return None
    payload["watch"] = list(payload.get("watch") or [])
    payload["leader"] = str(payload.get("leader") or "")
    return payload


def format_job(job: dict) -> str:
    payload = {
        "id": job["id"],
        "worker": job["worker"],
        "start": str(job["start"]),
        "end": str(job["end"]),
        "hero": job["hero"],
        "spec": job["spec"],
        "pool": job["pool"],
        "targets": int(job["targets"]),
        "channel": str(job["channel"]),
        "status": str(job["status"]),
    }
    if job.get("preset"):
        payload["preset"] = job["preset"]
    if job.get("top"):
        payload["top"] = int(job["top"])
    body = _dump(JOB, payload)
    return f"{job['worker']}: чанки {payload['start']}–{payload['end']}\n{body}"


def parse_job(content: str) -> dict | None:
    payload = _load(JOB, content)
    if payload is None:
        return None
    payload["start"] = int(payload["start"])
    payload["end"] = int(payload["end"])
    payload["targets"] = int(payload["targets"])
    payload["top"] = int(payload["top"]) if payload.get("top") else None
    return payload


def format_stop(job_id: str) -> str:
    return f"остановка {job_id}\n" + _dump(STOP, {"id": job_id})


def parse_stop(content: str) -> str | None:
    payload = _load(STOP, content)
    if payload is None:
        return None
    return str(payload["id"])


def parse_progress(content: str) -> tuple[int, int] | None:
    if not content:
        return None
    match = re.search(r"посчитано\s+([\d ]+?)\s+·\s+осталось\s+([\d ]+)", content)
    if not match:
        return None
    return int(match.group(1).replace(" ", "")), int(match.group(2).replace(" ", ""))


def status_text(
    *,
    worker: str,
    hero: str,
    spec: str,
    pool: str,
    targets: int,
    start: int,
    end: int,
    done: int,
    left: int,
    best: float | None,
    errors: int = 0,
    final: bool = False,
    stopped: bool = False,
    elapsed: float | None = None,
    remaining: float | None = None,
    rate: float | None = None,
    rate_max: float | None = None,
    rate_min: float | None = None,
    cpu: float | None = None,
    top: int | None = None,
    admission_policy: str | None = None,
) -> str:
    lines = []
    if final and stopped:
        lines.append(f"{worker} остановлен")
    elif final:
        lines.append(f"{worker} готово")
    lines.append(
        f"{worker} · {HERO_LABEL[hero]} · {spec}{top_label(top)} · {POOL_LABEL[pool]} · {targets} целей"
    )
    lines.append(f"чанки {grouped(start)}–{grouped(end)}")
    if final:
        lines.append(f"сделано {grouped(done)} из {grouped(done + left)}")
    else:
        lines.append(f"посчитано {grouped(done)} · осталось {grouped(left)}")
    if best is None:
        lines.append("лучший DPS ещё нет")
    else:
        lines.append(f"лучший DPS {best:.1f}")
    if elapsed is not None or rate is not None or cpu is not None:
        lines.append(f"прошло {clock(elapsed)} · осталось {clock(remaining)}")
        lines.append(f"бои/с {rate_text(rate)} · макс {rate_text(rate_max)} · мин {rate_text(rate_min)}")
        lines.append(f"ЦП {rate_text(cpu)}%")
    if admission_policy is not None:
        lines.append('Bare top-10 heuristic; no global optimum guarantee' if admission_policy in ('bare-top10', 'unsafe-bare-top10')
                     else 'Bare top-50 gate, top-20 written; no global optimum guarantee' if admission_policy == 'bare-top50'
                     else 'Legacy admission policy: ' + str(admission_policy) + ' (not a production mode)')
    if errors:
        lines.append(f"ошибок {grouped(errors)}")
    if final and done:
        lines.append("файл с топ-20 ниже" if admission_policy == "bare-top50" else "файл с топ-10 ниже")
    return "\n".join(lines)


def top_label(top: int | None) -> str:
    return f" · топ {int(top)} + Mind Amplifier" if top else ""


def size_text(*, worker: str, hero: str, spec: str, pool: str, targets: int, total: int, top: int | None = None) -> str:
    last = max(0, total - 1)
    return "\n".join(
        (
            f"{worker}: {HERO_LABEL[hero]} · {spec}{top_label(top)} · {POOL_LABEL[pool]} · {targets} целей",
            f"всего чанков {grouped(total)} (номера 0–{grouped(last)})",
            "One chunk is one legal six-item loadout. Default bare top-10 gate refines talents/glyphs/ESC only for admitted loadouts. Heuristic; no global optimum guarantee.",
            f"запуск всех чанков: /{worker} без start и end (или start:0 end:{last})",
        )
    )


def chunk_range(total: int, start=None, end=None, share: int | None = None) -> tuple[int, int]:
    """Inclusive chunk range. No start/end: share% from 0, or all chunks."""
    if total <= 0:
        raise ValueError("в этом пространстве нет чанков")
    if start is None and end is None:
        if share is not None:
            count = max(1, total * share // 100)
            return 0, min(total, count) - 1
        return 0, total - 1
    if start is None or end is None:
        raise ValueError("нужны оба края диапазона: start и end (или ни одного — тогда все чанки)")
    start = parse_int(str(start))
    end = parse_int(str(end))
    if end < start:
        raise ValueError("end меньше start")
    if start >= total or end >= total:
        raise ValueError(f"последний чанк {grouped(total - 1)}")
    return start, end

def presence_text(rows: list[tuple[str, int, int]]) -> str:
    if not rows:
        return "ждёт команду"
    parts = [f"{name}: {grouped(done)}, осталось {grouped(left)}" for name, done, left in rows]
    return " · ".join(parts)[:128]


def command_body(name: str) -> dict:
    return {
        "name": name,
        "type": 1,
        "description": "Считать чанки на этом компьютере",
        "dm_permission": False,
        "options": [
            {"type": 3, "name": "start", "description": "Первый чанк, включительно", "required": False},
            {"type": 3, "name": "end", "description": "Последний чанк, включительно", "required": False},
            {
                "type": 3,
                "name": "hero",
                "description": "Класс",
                "required": False,
                "choices": [
                    {"name": f"{HERO_NAME[hero]} · {HERO_LABEL[hero]}", "value": hero} for hero in SPECS
                ],
            },
            {
                "type": 3,
                "name": "spec",
                "description": "Специализация (подсказки по выбранному классу)",
                "required": False,
                "autocomplete": True,
            },
            {
                "type": 4,
                "name": "top",
                "description": "Топ-N предметов по DPS спека из one-slot (+ Mind Amplifier всегда)",
                "required": False,
                "choices": [{"name": f"топ {number}", "value": number} for number in TOPS],
            },
            {
                "type": 4,
                "name": "share",
                "description": "Доля чанков в процентах",
                "required": False,
                "min_value": 1,
                "max_value": 100,
            },
            {
                "type": 3,
                "name": "pool",
                "description": "Пул предметов",
                "required": False,
                "choices": [
                    {"name": "Shop + drop", "value": "mixed"},
                    {"name": "только Shop", "value": "shop"},
                    {"name": "только Random drop", "value": "drop"},
                ],
            },
            {
                "type": 4,
                "name": "targets",
                "description": "Число целей",
                "required": False,
                "choices": [{"name": str(number), "value": number} for number in range(1, 6)],
            },
            {"type": 5, "name": "stop", "description": "Остановить текущий прогон", "required": False},
        ],
    }
