"""Envía los CSVs consolidados por Gmail API."""
import base64
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.google_auth import get_credentials

RECIPIENTS = [
    "jaime@wearesiete.com",
    "nicolas@wearesiete.com",
]


def send_consolidated_report(consolidated: dict[str, Path]) -> None:
    """
    Envía los archivos consolidados como adjuntos por email.
    `consolidated` es el dict devuelto por consolidate(): {"people": Path, "email_activity": Path}
    """
    if not consolidated:
        return

    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    msg = MIMEMultipart()
    msg["To"] = ", ".join(RECIPIENTS)
    msg["Subject"] = f"Reporte diario Reply.io — {_date_from_consolidated(consolidated)}"

    body_lines = ["Adjunto los reportes consolidados de Reply.io de hoy:\n"]
    for kind, path in consolidated.items():
        size_kb = path.stat().st_size / 1024
        body_lines.append(f"  • {path.name} ({size_kb:.1f} KB)")

    msg.attach(MIMEText("\n".join(body_lines), "plain"))

    for path in consolidated.values():
        with open(path, "rb") as f:
            attachment = MIMEApplication(f.read(), Name=path.name)
        attachment["Content-Disposition"] = f'attachment; filename="{path.name}"'
        msg.attach(attachment)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    print(f"[email] Tamaño del mensaje: {len(raw) / 1024 / 1024:.1f} MB")
    for attempt in range(3):
        try:
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            return
        except HttpError as e:
            print(f"[email] Intento {attempt+1}/3 falló: status={e.resp.status} reason={e.reason} details={e.error_details}")
            if e.resp.status in (500, 503, 429) and attempt < 2:
                wait = 30 * (attempt + 1)
                print(f"[email] Esperando {wait}s antes de reintentar...")
                time.sleep(wait)
                continue
            raise


def _date_from_consolidated(consolidated: dict[str, Path]) -> str:
    """Extract the date suffix from the first filename, e.g. '2026-04-30'."""
    for path in consolidated.values():
        parts = path.stem.split("_")
        if parts:
            return parts[-1]
    return ""
