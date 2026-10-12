"""Text of Discord messages. The first line of a live status is machine-readable."""

from __future__ import annotations

import json
import re

PRIEST_SPECS = ("shadow", "discipline", "holy")
MAGE_SPECS = ("frost", "arcane", "fire")
PALADIN_SPECS = ("retribution", "protection", "holy")
POOLS = ("mixed", "shop", "drop")

POOL_LABEL = {
    "mixed": "Shop + drop",
    "shop": "только Shop",
    "drop": "только Random drop",
}
HERO_LABEL = {"priest": "жрец", "mage": "маг", "paladin": "паладин"}

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


def resolve_hero_spec(hero: str | None, spec: str | None) -> tuple[str, str]:
    spec = (spec or "shadow").strip().lower()
    hero = hero.strip().lower() if hero else None
    if hero is None:
        if spec in ("retribution", "protection"):
            hero = "paladin"
        elif spec in MAGE_SPECS:
            hero = "mage"
        elif spec in PRIEST_SPECS:
            hero = "priest"
        else:
            raise ValueError(f"нет специализации {spec}")
    if hero == "priest" and spec not in PRIEST_SPECS:
        raise ValueError(f"у жреца нет специализации {spec}")
    if hero == "mage" and spec not in MAGE_SPECS:
        raise ValueError(f"у мага нет специализации {spec}")
    if hero == "paladin" and spec not in PALADIN_SPECS:
        raise ValueError(f"у паладина нет специализации {spec}")
    if hero not in HERO_LABEL:
        raise ValueError(f"нет класса {hero}")
    return hero, spec


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
    body = _dump(JOB, payload)
    return f"{job['worker']}: чанки {payload['start']}–{payload['end']}\n{body}"


def parse_job(content: str) -> dict | None:
    payload = _load(JOB, content)
    if payload is None:
        return None
    payload["start"] = int(payload["start"])
    payload["end"] = int(payload["end"])
    payload["targets"] = int(payload["targets"])
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
) -> str:
    lines = []
    if final and stopped:
        lines.append(f"{worker} остановлен")
    elif final:
        lines.append(f"{worker} готово")
    lines.append(
        f"{worker} · {HERO_LABEL[hero]} · {spec} · {POOL_LABEL[pool]} · {targets} целей"
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
    if errors:
        lines.append(f"ошибок {grouped(errors)}")
    if final and done:
        lines.append("файл с топ-10 ниже")
    return "\n".join(lines)


def size_text(*, worker: str, hero: str, spec: str, pool: str, targets: int, total: int) -> str:
    last = max(0, total - 1)
    return "\n".join(
        (
            f"{worker}: {HERO_LABEL[hero]} · {spec} · {POOL_LABEL[pool]} · {targets} целей",
            f"всего чанков {grouped(total)} (номера 0–{grouped(last)})",
            "один чанк — шестёрка предметов. Таланты, глифы и очки навыков считаются, только если её DPS без талантов выше 10-го места по DPS без талантов",
            f"запуск: /{worker} start:0 end:{last}",
        )
    )


def presence_text(rows: list[tuple[str, int, int]]) -> str:
    if not rows:
        return "ждёт команду"
    parts = [f"{name}: {grouped(done)}, осталось {grouped(left)}" for name, done, left in rows]
    return " · ".join(parts)[:128]


def command_body(name: str) -> dict:
    specs = ["shadow", "discipline", "holy", "frost", "arcane", "fire", "retribution", "protection"]
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
                "name": "preset",
                "description": "Готовый набор вещей и талантов",
                "required": False,
                "choices": [
                    {"name": "Paladin Retribution top 80", "value": "retribution-top80"},
                    {"name": "Paladin Retribution top 79", "value": "retribution-top79"},
                    {"name": "Paladin Retribution top 89", "value": "retribution-top89"},
                    {"name": "Paladin Protection top 89", "value": "protection-top89"},
                ],
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
                "name": "hero",
                "description": "Класс",
                "required": False,
                "choices": [
                    {"name": "Жрец", "value": "priest"},
                    {"name": "Маг", "value": "mage"},
                    {"name": "Паладин", "value": "paladin"},
                ],
            },
            {
                "type": 3,
                "name": "spec",
                "description": "Специализация",
                "required": False,
                "choices": [{"name": spec, "value": spec} for spec in specs],
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
