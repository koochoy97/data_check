import base64
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

# Si el token viene como env var (base64 o JSON crudo), escribirlo a disco
_token_raw = os.getenv("GOOGLE_TOKEN_JSON")
if _token_raw:
    print(f"[config] GOOGLE_TOKEN_JSON encontrado ({len(_token_raw)} chars)")
    print(f"[config] Primeros 30 chars: {repr(_token_raw[:30])}")
    # Intentar decodificar base64 primero
    try:
        _token_json = base64.b64decode(_token_raw).decode("utf-8")
        json.loads(_token_json)  # validar que es JSON válido
        print("[config] Token decodificado desde base64 OK")
    except Exception as e:
        print(f"[config] Base64 decode falló ({e}), usando valor crudo")
        _token_json = _token_raw
    # Validar JSON antes de escribir
    try:
        json.loads(_token_json)
        print("[config] JSON válido, escribiendo a disco")
    except json.JSONDecodeError as e:
        print(f"[config] ERROR: JSON inválido: {e}")
        print(f"[config] Primeros 80 chars del valor: {repr(_token_json[:80])}")
    Path(GOOGLE_TOKEN_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(GOOGLE_TOKEN_PATH).write_text(_token_json)
else:
    print("[config] GOOGLE_TOKEN_JSON no encontrado en env vars")
CLIENTS_CONFIG_PATH = os.getenv("CLIENTS_CONFIG_PATH", "clients.json")
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/reports"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def load_clients() -> dict:
    path = Path(CLIENTS_CONFIG_PATH)
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)
