"""Envía un email con los links de descarga de los CSVs consolidados (Gmail API)."""
import base64
import time
from email.mime.text import MIMEText
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import PUBLIC_BASE_URL
from app.google_auth import get_credentials

RECIPIENTS = [
    "jaime@wearesiete.com",
    "nicolas@wearesiete.com",
]


def send_consolidated_report(consolidated: dict[str, Path]) -> None:
    """Envía un email con los links de descarga (no los archivos como adjuntos)."""
    if not consolidated:
        return

    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    date_str = _date_from_consolidated(consolidated)

    lines = [
        f"Reportes consolidados de Reply.io del {date_str}.",
        "",
        "Links de descarga (válidos por 24h):",
    ]
    for path in consolidated.values():
        size_mb = path.stat().st_size / 1024 / 1024
        url = f"{PUBLIC_BASE_URL}/api/consolidated/{path.name}"
        lines.append(f"  • {path.name} ({size_mb:.1f} MB): {url}")

    msg = MIMEText("\n".join(lines))
    msg["To"] = ", ".join(RECIPIENTS)
    msg["Subject"] = f"Reporte diario Reply.io — {date_str}"

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    print(f"[email] Enviando a {RECIPIENTS} ({len(raw)} bytes)")

    for attempt in range(3):
        try:
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            print("[email] Enviado correctamente")
            return
        except HttpError as e:
            print(f"[email] Intento {attempt+1}/3 falló: status={e.resp.status} reason={e.reason}")
            if e.resp.status in (500, 503, 429) and attempt < 2:
                wait = 30 * (attempt + 1)
                print(f"[email] Esperando {wait}s antes de reintentar...")
                time.sleep(wait)
                continue
            raise


def _date_from_consolidated(consolidated: dict[str, Path]) -> str:
    for path in consolidated.values():
        parts = path.stem.split("_")
        if parts:
            return parts[-1]
    return ""
