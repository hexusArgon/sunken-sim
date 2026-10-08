"""One Discord bot, one slash command per computer.

Discord allows a single gateway connection for a token. Every computer runs
this process. One of them holds the connection and receives slash commands.
The computer named by the command does the arithmetic.
"""

from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime, timezone

import discord

from farm.catalog import load
from farm.identity import env_required, load_env, worker_name
from farm.paths import atomic_write, data_dir
from farm.protocol import (
    command_body,
    format_control,
    format_job,
    format_stop,
    grouped,
    parse_control,
    parse_int,
    parse_job,
    parse_progress,
    parse_stop,
    presence_text,
    resolve_hero_spec,
    resolve_pool,
    resolve_targets,
    size_text,
    status_text,
)
from farm.rest import Rest, RestError
from farm.runner import run_job

PERMISSIONS = 125952
STALE_SECONDS = 30


def invite_url(app_id: str) -> str:
    return (
        "https://discord.com/api/oauth2/authorize"
        f"?client_id={app_id}&scope=bot%20applications.commands&permissions={PERMISSIONS}"
    )


def message_age(message: dict) -> float:
    stamp = message.get("edited_timestamp") or message.get("timestamp")
    when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - when).total_seconds()


class Farm:
    def __init__(self, name: str, token: str, guild: str, channel: str) -> None:
        self.name = name
        self.token = token
        self.guild = guild
        self.channel = channel
        self.rest = Rest(token)
        self.app_id = ""
        self.control_id = ""
        self.control_channel = channel
        self.lock = asyncio.Lock()
        self.client: discord.Client | None = None
        self.gateway_task: asyncio.Task | None = None
        self.closing = False
        self.cooldown_until = 0.0
        self.presence = ""
        self.mirrors: dict[str, str] = {}
        self.mirror_sent: dict[str, str] = {}
        self.status_texts: dict[str, str] = {}
        self.running = False
        self.box = {"stop": False, "job_id": ""}
        self.current_job: dict | None = None
        self.tasks: set[asyncio.Task] = set()

    def active_path(self):
        return data_dir() / "active.json"

    def read_active(self) -> dict | None:
        path = self.active_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def write_active(self, payload: dict) -> None:
        atomic_write(self.active_path(), json.dumps(payload, ensure_ascii=False))

    def clear_active(self) -> None:
        path = self.active_path()
        if path.exists():
            path.unlink()

    def log(self, text: str) -> None:
        print(text, flush=True)
        try:
            path = data_dir() / "bot.log"
            with path.open("a", encoding="utf-8") as handle:
                stamp = datetime.now().isoformat(timespec="seconds")
                handle.write(f"{stamp} {text}\n")
        except OSError:
            pass

    async def run(self) -> None:
        while True:
            try:
                await self.start()
                break
            except RestError as exc:
                print(exc, flush=True)
                if exc.status == 401:
                    raise SystemExit("Ключ бота не подошёл. Проверь DISCORD_TOKEN.") from exc
                print("повтор через 15 с", flush=True)
                await asyncio.sleep(15)
        await asyncio.gather(self.leader_forever(), self.worker_forever())

    async def start(self) -> None:
        self.app_id = await asyncio.to_thread(self.rest.application_id)
        print(f"Приглашение бота:\n{invite_url(self.app_id)}", flush=True)
        await asyncio.to_thread(self.rest.upsert_command, self.app_id, self.guild, command_body(self.name))
        self.control_id = await self.ensure_control()
        await asyncio.to_thread(
            self.rest.send,
            self.channel,
            f"Компьютер {self.name} запущен. Команда: /{self.name}",
        )
        print(f"Компьютер {self.name}. Команда /{self.name}", flush=True)

    async def channel_messages(self, channel: str | None = None) -> list[dict]:
        channel = channel or self.channel
        recent = await asyncio.to_thread(self.rest.recent, channel)
        pins: list = []
        try:
            pins = await asyncio.to_thread(self.rest.pins, channel)
        except RestError as exc:
            self.log(f"закрепления недоступны: {exc}")
        found: dict[str, dict] = {}
        for message in list(pins) + list(recent):
            found[str(message["id"])] = message
        return list(found.values())

    async def ensure_control(self) -> str:
        controls = await self._controls_all()
        if not controls:
            created = await asyncio.to_thread(self.rest.send, self.channel, format_control("", []))
            controls = [created]
        controls.sort(key=lambda message: int(message["id"]))
        keep = controls[0]
        self.control_channel = str(keep.get("channel_id") or self.channel)
        keep_id = str(keep["id"])
        for extra in controls[1:]:
            try:
                await asyncio.to_thread(self.rest.delete, str(extra.get("channel_id") or self.control_channel), extra["id"])
            except RestError:
                pass
        try:
            await asyncio.to_thread(self.rest.pin, self.control_channel, keep_id)
        except RestError as exc:
            self.log(
                "Не закрепил служебное сообщение. Боту нужно право Manage Messages, "
                f"иначе команда пропадёт из истории канала. {exc}"
            )
        return keep_id

    async def _controls_all(self) -> list[dict]:
        try:
            channels = await asyncio.to_thread(self.rest.guild_channels, self.guild)
        except RestError as exc:
            self.log(f"список каналов: {exc}")
            channels = [{"id": self.channel, "type": 0}]
        found = []
        for row in channels:
            if row.get("type") not in (0, None):
                continue
            try:
                messages = await asyncio.to_thread(self.rest.recent, str(row["id"]))
            except RestError:
                continue
            found.extend(message for message in messages if parse_control(message.get("content") or ""))
        return found

    async def leader_forever(self) -> None:
        while True:
            try:
                await self.leader_once()
            except RestError as exc:
                if exc.status == 404:
                    self.control_id = await self.ensure_control()
                else:
                    traceback.print_exc()
            except Exception:
                traceback.print_exc()
            await asyncio.sleep(5)

    async def leader_once(self) -> None:
        async with self.lock:
            message = await asyncio.to_thread(self.rest.get_message, self.control_channel, self.control_id)
            state = parse_control(message.get("content") or "") or {"leader": "", "watch": []}
            foreign = state["leader"] not in ("", self.name) and message_age(message) <= STALE_SECONDS
            rows: list[tuple[str, int, int]] = []
            if not foreign:
                watch, rows = await self._collect_watch(state["watch"])
                await asyncio.to_thread(
                    self.rest.edit,
                    self.control_channel,
                    self.control_id,
                    format_control(self.name, watch),
                )
                confirm = await asyncio.to_thread(self.rest.get_message, self.control_channel, self.control_id)
                confirmed = parse_control(confirm.get("content") or "") or {"leader": ""}
                foreign = confirmed["leader"] != self.name
        if foreign:
            await self.drop_gateway()
            return
        await self.ensure_gateway()
        await self.apply_presence(rows)
        await self.mirror_statuses()

    async def _collect_watch(self, watch: list[dict]) -> tuple[list[dict], list[tuple[str, int, int]]]:
        kept = []
        rows = []
        texts: dict[str, str] = {}
        for item in watch:
            try:
                message = await asyncio.to_thread(self.rest.get_message, item["channel"], item["message"])
            except RestError as exc:
                if exc.status != 404:
                    kept.append(item)
                continue
            content = message.get("content") or ""
            parsed = parse_progress(content)
            if parsed is None:
                continue
            texts[str(item["message"])] = content
            kept.append(item)
            rows.append((item["worker"], parsed[0], parsed[1]))
        self.status_texts = texts
        return kept, rows

    async def apply_presence(self, rows: list[tuple[str, int, int]]) -> None:
        client = self.client
        if client is None or not client.is_ready():
            return
        text = presence_text(rows)
        if text == self.presence:
            return
        try:
            await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=text))
            self.presence = text
        except Exception as exc:
            print(f"статус бота: {exc}", flush=True)

    async def mirror_statuses(self) -> None:
        dead = []
        for status_id, token in list(self.mirrors.items()):
            content = self.status_texts.get(status_id)
            if not content or self.mirror_sent.get(status_id) == content:
                continue
            try:
                await asyncio.to_thread(self.rest.edit_original, self.app_id, token, content)
                self.mirror_sent[status_id] = content
            except RestError:
                dead.append(status_id)
        for status_id in dead:
            self.mirrors.pop(status_id, None)
            self.mirror_sent.pop(status_id, None)

    async def ensure_gateway(self) -> None:
        if time_now() < self.cooldown_until:
            return
        if self.gateway_task and not self.gateway_task.done():
            return
        self.closing = False
        self.gateway_task = asyncio.create_task(self._run_gateway())

    async def _run_gateway(self) -> None:
        client = discord.Client(intents=discord.Intents.default())
        self.client = client

        @client.event
        async def on_ready() -> None:
            print(f"шлюз Discord: {client.user}", flush=True)

        @client.event
        async def on_interaction(interaction: discord.Interaction) -> None:
            try:
                await self.on_interaction(interaction)
            except Exception:
                traceback.print_exc()

        try:
            await client.start(self.token, reconnect=False)
        except Exception:
            traceback.print_exc()
        finally:
            if self.client is client:
                self.client = None
            if not self.closing:
                self.cooldown_until = time_now() + 20
                print("шлюз закрылся, пауза 20 с", flush=True)
            self.closing = False

    async def drop_gateway(self) -> None:
        client = self.client
        task = self.gateway_task
        if client is None or task is None or task.done():
            return
        self.closing = True
        await client.close()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=10)
        except (asyncio.TimeoutError, Exception):
            pass

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type is not discord.InteractionType.application_command:
            return
        if interaction.response.is_done():
            return
        await interaction.response.defer()
        self._track(self.dispatch(interaction))

    async def show(self, interaction: discord.Interaction, text: str) -> None:
        text = text[:1900]
        try:
            await asyncio.wait_for(interaction.edit_original_response(content=text), timeout=15)
            return
        except Exception as exc:
            self.log(f"ответ команды: {exc}")
        try:
            await asyncio.to_thread(self.rest.edit_original, self.app_id, interaction.token, text)
        except RestError as exc:
            self.log(f"webhook ответа: {exc}")

    async def dispatch(self, interaction: discord.Interaction) -> None:
        data = interaction.data or {}
        name = str(data.get("name") or "")
        options = {opt["name"]: opt.get("value") for opt in data.get("options") or []}
        self.log(f"команда /{name}")
        try:
            if options.get("stop"):
                await self.stop_worker(interaction, name)
                return
            hero, spec = resolve_hero_spec(options.get("hero"), options.get("spec"))
            pool = resolve_pool(options.get("pool"))
            targets = resolve_targets(options.get("targets"))
            preset = options.get("preset") or None
            share = options.get("share")
            if share is not None:
                share = int(share)
                if share < 1 or share > 100:
                    raise ValueError("доля от 1 до 100")

            def space_of():
                return load(hero, spec, pool, preset)

            if "start" not in options and "end" not in options and share is None:
                space, _items = await asyncio.to_thread(space_of)
                await self.show(
                    interaction,
                    size_text(worker=name, hero=hero, spec=spec, pool=pool, targets=targets, total=space.total),
                )
                return
            await self.show(interaction, "Считаю размер пространства…")
            space, _items = await asyncio.to_thread(space_of)
            if space.total <= 0:
                raise ValueError("в этом пространстве нет чанков")
            if share is not None and "start" not in options and "end" not in options:
                count = max(1, space.total * share // 100)
                start, end = 0, min(space.total, count) - 1
            else:
                if "start" not in options or "end" not in options:
                    raise ValueError("нужны оба края диапазона: start и end")
                start = parse_int(str(options["start"]))
                end = parse_int(str(options["end"]))
                if end < start:
                    raise ValueError("end меньше start")
                if start >= space.total or end >= space.total:
                    raise ValueError(f"последний чанк {grouped(space.total - 1)}")
            left = end - start + 1
            await self.show(
                interaction,
                status_text(
                    worker=name,
                    hero=hero,
                    spec=spec,
                    pool=pool,
                    targets=targets,
                    start=start,
                    end=end,
                    done=0,
                    left=left,
                    best=None,
                    elapsed=0,
                ),
            )
            await self.enqueue(interaction, name, hero, spec, pool, targets, start, end, preset)
        except (ValueError, RuntimeError) as exc:
            await self.show(interaction, str(exc))
        except Exception as exc:
            traceback.print_exc()
            self.log(f"команда /{name}: {exc}")
            await self.show(interaction, f"ошибка: {exc}")

    async def enqueue(
        self,
        interaction: discord.Interaction,
        name: str,
        hero: str,
        spec: str,
        pool: str,
        targets: int,
        start: int,
        end: int,
        preset: str | None = None,
    ) -> None:
        channel = str(interaction.channel_id or self.channel)
        for message in await self.channel_messages(channel):
            job = parse_job(message.get("content") or "")
            if job and job["worker"] == name:
                await self.show(interaction, f"{name} уже считает. Остановка: команда /{name} с галкой stop")
                return
        import secrets

        left = end - start + 1
        text = status_text(
            worker=name,
            hero=hero,
            spec=spec,
            pool=pool,
            targets=targets,
            start=start,
            end=end,
            done=0,
            left=left,
            best=None,
            elapsed=0,
        )
        status = await asyncio.to_thread(self.rest.send, channel, text)
        job = {
            "id": secrets.token_hex(4),
            "worker": name,
            "start": start,
            "end": end,
            "hero": hero,
            "spec": spec,
            "pool": pool,
            "targets": targets,
            "channel": channel,
            "status": str(status["id"]),
            "preset": preset or "",
        }
        posted = await asyncio.to_thread(self.rest.send, channel, format_job(job))
        job["job_message"] = str(posted["id"])
        try:
            await asyncio.to_thread(self.rest.pin, channel, job["job_message"])
        except RestError as exc:
            self.log(f"не закрепил задачу: {exc}")
        self.mirrors[job["status"]] = interaction.token
        self.status_texts[job["status"]] = text
        async with self.lock:
            message = await asyncio.to_thread(self.rest.get_message, self.control_channel, self.control_id)
            state = parse_control(message.get("content") or "") or {"leader": self.name, "watch": []}
            state["watch"].append({"channel": channel, "message": job["status"], "worker": name})
            await asyncio.to_thread(
                self.rest.edit,
                self.control_channel,
                self.control_id,
                format_control(self.name, state["watch"]),
            )
        self.log(f"задача {job['id']} для {name}: {start}–{end}")

    async def stop_worker(self, interaction: discord.Interaction, name: str) -> None:
        found = None
        channel = str(interaction.channel_id or self.channel)
        messages = await self.channel_messages(channel)
        for message in messages:
            job = parse_job(message.get("content") or "")
            if job and job["worker"] == name:
                found = job
                found["job_message"] = str(message["id"])
                break
        if found is None and self.current_job and self.current_job.get("worker") == name:
            found = self.current_job
        if found is None:
            await self.show(interaction, f"{name} сейчас не считает")
            return
        for message in messages:
            if parse_stop(message.get("content") or "") == found["id"]:
                await self.show(interaction, f"{name} уже останавливается")
                return
        job_channel = str(found.get("channel") or channel)
        posted = await asyncio.to_thread(self.rest.send, job_channel, format_stop(found["id"]))
        try:
            await asyncio.to_thread(self.rest.pin, job_channel, posted["id"])
        except RestError as exc:
            self.log(f"не закрепил остановку: {exc}")
        if self.box.get("job_id") == found["id"]:
            self.box["stop"] = True
        await self.show(interaction, f"Останавливаю {name}. Топ на момент остановки придёт файлом.")

    async def worker_forever(self) -> None:
        while True:
            try:
                await self.worker_once()
            except Exception:
                traceback.print_exc()
            await asyncio.sleep(5)

    async def worker_once(self) -> None:
        messages = await self.channel_messages()
        stops = {parse_stop(message.get("content") or "") for message in messages}
        stops.discard(None)
        if self.running:
            if self.box.get("job_id") in stops:
                self.box["stop"] = True
            return
        active = self.read_active()
        if active and active.get("done") and not active.get("uploaded"):
            await self.upload_and_clear(active)
            return
        if active and not active.get("done"):
            job = active["job"]
            if job["id"] in stops:
                self.box["stop"] = True
            else:
                self.box["stop"] = False
            self.box["job_id"] = job["id"]
            self.launch(job)
            return
        for message in messages:
            job = parse_job(message.get("content") or "")
            if not job or job["worker"] != self.name:
                continue
            job["job_message"] = str(message["id"])
            if job["id"] in stops:
                await self.abort(job)
                return
            self.box["stop"] = False
            self.box["job_id"] = job["id"]
            self.write_active({"done": False, "uploaded": False, "job": job})
            self.launch(job)
            return

    def launch(self, job: dict) -> None:
        self.running = True
        self.current_job = job
        self.box["job_id"] = job["id"]
        self._track(self.execute(job))

    def sync_tick(self, text: str) -> None:
        job = self.current_job
        if not job:
            return
        try:
            self.rest.edit(str(job["channel"]), str(job["status"]), text)
        except RestError as exc:
            print(f"статус не обновился: {exc}", flush=True)

    async def execute(self, job: dict) -> None:
        try:
            result = await asyncio.to_thread(run_job, job, self.box, self.sync_tick)
            if result.get("stopped") and not result.get("done"):
                await self.abort(job)
                return
            path = result.get("path") or ""
            if path and result.get("done"):
                uploaded = await self.send_file(job, path)
            else:
                uploaded = True
            if uploaded:
                self.clear_active()
                await self.delete_marks(job)
            else:
                self.write_active({"done": True, "uploaded": False, "job": job, "path": path})
        except Exception as exc:
            traceback.print_exc()
            try:
                self.rest.edit(str(job["channel"]), str(job["status"]), f"{job['worker']}: ошибка\n{exc}"[:1900])
            except RestError:
                pass
            await asyncio.sleep(30)
        finally:
            self.running = False
            self.current_job = None

    async def send_file(self, job: dict, path: str) -> bool:
        from pathlib import Path

        file_path = Path(path)
        if not file_path.exists():
            return False
        text = (
            f"{job['worker']}: топ-10 Shop+Random, Shop only и Random only, чанки {grouped(int(job['start']))}–{grouped(int(job['end']))}, "
            f"{job['spec']}, {job['pool']}, {job['targets']} целей"
        )
        try:
            await asyncio.to_thread(
                self.rest.upload,
                str(job["channel"]),
                text,
                file_path.name,
                file_path.read_bytes(),
            )
            return True
        except RestError as exc:
            print(f"файл не ушёл: {path}\n{exc}", flush=True)
            return False

    async def upload_and_clear(self, active: dict) -> None:
        job = active["job"]
        if await self.send_file(job, active.get("path") or ""):
            self.clear_active()
            await self.delete_marks(job)

    async def abort(self, job: dict) -> None:
        left = int(job["end"]) - int(job["start"]) + 1
        text = status_text(
            worker=job["worker"],
            hero=job["hero"],
            spec=job["spec"],
            pool=job["pool"],
            targets=int(job["targets"]),
            start=int(job["start"]),
            end=int(job["end"]),
            done=0,
            left=left,
            best=None,
            final=True,
            stopped=True,
        )
        try:
            await asyncio.to_thread(self.rest.edit, str(job["channel"]), str(job["status"]), text)
        except RestError as exc:
            print(exc, flush=True)
        self.clear_active()
        await self.delete_marks(job)

    async def delete_marks(self, job: dict) -> None:
        channel = str(job.get("channel") or self.channel)
        messages = await self.channel_messages(channel)
        doomed = []
        if job.get("job_message"):
            doomed.append(str(job["job_message"]))
        for message in messages:
            content = message.get("content") or ""
            parsed = parse_job(content)
            if parsed and parsed["id"] == job["id"]:
                doomed.append(str(message["id"]))
            if parse_stop(content) == job["id"]:
                doomed.append(str(message["id"]))
        for message_id in dict.fromkeys(doomed):
            try:
                await asyncio.to_thread(self.rest.delete, channel, message_id)
            except RestError:
                pass

    def _track(self, coro) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


def time_now() -> float:
    return datetime.now(timezone.utc).timestamp()


def main() -> None:
    import multiprocessing
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    multiprocessing.freeze_support()
    load_env()
    name = worker_name()
    token = env_required("DISCORD_TOKEN")
    guild = env_required("DISCORD_GUILD_ID")
    channel = env_required("DISCORD_CHANNEL_ID")
    if not guild.isdigit() or not channel.isdigit():
        raise SystemExit("DISCORD_GUILD_ID и DISCORD_CHANNEL_ID — числовые id. Включи режим разработчика в Discord и скопируй id.")
    asyncio.run(Farm(name, token, guild, channel).run())
