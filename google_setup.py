"""Run this once to authorize Google OAuth: python3 google_setup.py"""
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
TOKEN_PATH = Path("token.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}

from google_auth_oauthlib.flow import InstalledAppFlow

print("Abriendo navegador para autorizar...")
flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=8085)

TOKEN_PATH.write_text(creds.to_json())
print(f"\nToken guardado en {TOKEN_PATH}")
print("Listo! Ya puedes correr docker-compose up")
