import json
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

REPLY_IO_EMAIL = os.getenv("REPLY_IO_EMAIL")
REPLY_IO_PASSWORD = os.getenv("REPLY_IO_PASSWORD")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
GOOGLE_TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "/tmp/google_token.json")

# Reconstruir token.json desde env vars individuales (evita problemas de JSON en env vars)
if GOOGLE_REFRESH_TOKEN and GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    token_data = {
        "token": "",
        "refresh_token": GOOGLE_REFRESH_TOKEN,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "scopes": [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
        "universe_domain": "googleapis.com",
        "account": "",
    }
    Path(GOOGLE_TOKEN_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(GOOGLE_TOKEN_PATH).write_text(json.dumps(token_data))
    print("[config] Token reconstruido desde env vars individuales")
CLIENTS_CONFIG_PATH = os.getenv("CLIENTS_CONFIG_PATH", "clients.json")
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/reports"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def load_clients() -> dict:
    path = Path(CLIENTS_CONFIG_PATH)
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)
