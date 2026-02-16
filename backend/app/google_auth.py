"""Google OAuth2 authentication for Sheets and Drive APIs."""
from pathlib import Path

import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_TOKEN_PATH

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _client_config() -> dict:
    """Build OAuth client config dict from env vars."""
    return {
        "installed": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def get_credentials() -> Credentials:
    """Load or refresh OAuth2 credentials. Raises if not authorized yet."""
    token_path = Path(GOOGLE_TOKEN_PATH)
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())

    if not creds or not creds.valid:
        raise RuntimeError(
            "Google OAuth no autorizado. Corre 'python -m app.google_setup' primero."
        )

    return creds


def authorize_interactive():
    """One-time interactive OAuth flow. Opens browser for user consent."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise ValueError(
            "Falta GOOGLE_CLIENT_ID o GOOGLE_CLIENT_SECRET en el .env"
        )

    flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path = Path(GOOGLE_TOKEN_PATH)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    print(f"Token guardado en {token_path}")
    return creds


def get_gspread_client():
    creds = get_credentials()
    return gspread.authorize(creds)


def get_sheets_service():
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds)


def get_drive_service():
    creds = get_credentials()
    return build("drive", "v3", credentials=creds)
