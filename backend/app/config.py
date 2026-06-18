import json
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

REPLY_IO_EMAIL = os.getenv("REPLY_IO_EMAIL")
REPLY_IO_PASSWORD = os.getenv("REPLY_IO_PASSWORD")
SIETE_API_ENDPOINT = os.getenv("SIETE_API_ENDPOINT", os.getenv("SIETE-API-ENDPOINT", "https://apirest.wearesiete.com"))
SIETE_API_KEY = os.getenv("SIETE_API_KEY", os.getenv("X_HEADER_SIETE_API", os.getenv("X-HEADER-SIETE-API")))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://data-check.wearesiete.com")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
GOOGLE_TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "/tmp/google_token.json")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")
SLACK_DESTINATIONS = os.getenv("SLACK_DESTINATIONS")

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
            "https://www.googleapis.com/auth/gmail.send",
        ],
        "universe_domain": "googleapis.com",
        "account": "",
    }
    Path(GOOGLE_TOKEN_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(GOOGLE_TOKEN_PATH).write_text(json.dumps(token_data))
    print("[config] Token reconstruido desde env vars individuales")
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/reports"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

TFLX_PATH = os.getenv("TFLX_PATH")
TABLEAU_SERVER_URL = os.getenv("TABLEAU_SERVER_URL")
TABLEAU_SITE_ID = os.getenv("TABLEAU_SITE_ID", "")
TABLEAU_PAT_NAME = os.getenv("TABLEAU_PAT_NAME")
TABLEAU_PAT_SECRET = os.getenv("TABLEAU_PAT_SECRET")
