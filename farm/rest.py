"""Discord REST. Several computers share one bot token; only the gateway is single."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_API = "https://discord.com/api/v10"


class RestError(Exception):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Discord {status}: {body[:400]}")


class Rest:
    def __init__(self, token: str) -> None:
        self.token = token
        self._lock = threading.Lock()

    def _request(self, method: str, path: str, payload: dict | None = None, *, raw: bytes | None = None, content_type: str | None = None, auth: bool = True):
        headers = {"User-Agent": "DiscordBot (sunken-sim, 1.0)"}
        if auth:
            headers["Authorization"] = f"Bot {self.token}"
        body = raw
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        elif content_type:
            headers["Content-Type"] = content_type
        url = _API + path
        for attempt in range(6):
            request = urllib.request.Request(url, data=body, headers=headers, method=method)
            try:
                with self._lock:
                    with urllib.request.urlopen(request, timeout=60) as response:
                        data = response.read()
                if not data:
                    return None
                return json.loads(data.decode())
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")
                if exc.code == 429 and attempt < 5:
                    delay = 1.0
                    try:
                        delay = float(json.loads(detail).get("retry_after", 1))
                    except (ValueError, TypeError, json.JSONDecodeError):
                        pass
                    time.sleep(min(delay, 30) + 0.05)
                    continue
                raise RestError(exc.code, detail) from None
            except urllib.error.URLError as exc:
                raise RestError(0, str(exc.reason)) from None
        raise RestError(429, "rate limit")

    def application_id(self) -> str:
        return str(self._request("GET", "/oauth2/applications/@me")["id"])

    def upsert_command(self, app_id: str, guild_id: str, body: dict) -> None:
        route = f"/applications/{app_id}/guilds/{guild_id}/commands"
        existing = self._request("GET", route)
        current = next((row for row in existing if row["name"] == body["name"]), None)
        if current:
            self._request("PATCH", f"{route}/{current['id']}", body)
        else:
            self._request("POST", route, body)

    def send(self, channel: str, content: str) -> dict:
        return self._request("POST", f"/channels/{channel}/messages", {"content": content})

    def edit(self, channel: str, message: str, content: str) -> dict:
        return self._request("PATCH", f"/channels/{channel}/messages/{message}", {"content": content})

    def delete(self, channel: str, message: str) -> None:
        self._request("DELETE", f"/channels/{channel}/messages/{message}")

    def pin(self, channel: str, message: str) -> None:
        self._request("PUT", f"/channels/{channel}/pins/{message}")

    def pins(self, channel: str) -> list:
        return self._request("GET", f"/channels/{channel}/pins") or []

    def recent(self, channel: str) -> list:
        return self._request("GET", f"/channels/{channel}/messages?limit=100") or []

    def get_message(self, channel: str, message: str) -> dict:
        return self._request("GET", f"/channels/{channel}/messages/{message}")

    def edit_original(self, app_id: str, token: str, content: str) -> None:
        safe = urllib.parse.quote(token, safe="")
        self._request(
            "PATCH",
            f"/webhooks/{app_id}/{safe}/messages/@original",
            {"content": content},
            auth=False,
        )

    def upload(self, channel: str, content: str, filename: str, data: bytes) -> dict:
        boundary = "----sunkenfarm" + str(time.time_ns())
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="payload_json"\r\n'
            f"Content-Type: application/json\r\n\r\n"
            f"{json.dumps({'content': content}, ensure_ascii=False)}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'
            f"Content-Type: application/json\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        return self._request(
            "POST",
            f"/channels/{channel}/messages",
            raw=head + data + tail,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
