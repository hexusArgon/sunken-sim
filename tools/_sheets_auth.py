"""Refresh the Google Sheets token with a browser login. Does not print secrets."""

from __future__ import annotations

import json
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SECRET = Path(
    r"C:\Users\eseid\Documents\keys\client_secret_384742056673-lfd5m9762jvnoimg99dtcm6ifov2ot2c.apps.googleusercontent.com.json"
)
TOKEN = Path(r"C:\Users\eseid\Documents\keys\google-sheets-token.json")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file(str(SECRET), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    payload = json.loads(TOKEN.read_text(encoding="utf-8"))
    payload["token"] = creds.token
    payload["refresh_token"] = creds.refresh_token or payload.get("refresh_token")
    payload["scopes"] = list(creds.scopes or SCOPES)
    if creds.expiry:
        payload["expiry"] = creds.expiry.isoformat() + "Z"
    TOKEN.write_text(json.dumps(payload), encoding="utf-8")
    print("auth_ok", payload["expiry"])


if __name__ == "__main__":
    main()
