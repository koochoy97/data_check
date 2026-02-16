import json
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

REPLY_IO_EMAIL = os.getenv("REPLY_IO_EMAIL")
REPLY_IO_PASSWORD = os.getenv("REPLY_IO_PASSWORD")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "/tmp/google_token.json")

# Si el token viene como env var, escribirlo a disco
_token_json = os.getenv("GOOGLE_TOKEN_JSON")
if _token_json:
    Path(GOOGLE_TOKEN_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(GOOGLE_TOKEN_PATH).write_text(_token_json)
CLIENTS_CONFIG_PATH = os.getenv("CLIENTS_CONFIG_PATH", "clients.json")
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/reports"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def load_clients() -> dict:
    path = Path(CLIENTS_CONFIG_PATH)
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)
