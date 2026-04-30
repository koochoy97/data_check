"""Envía los CSVs consolidados por Gmail API."""
import base64
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from googleapiclient.discovery import build

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
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def _date_from_consolidated(consolidated: dict[str, Path]) -> str:
    """Extract the date suffix from the first filename, e.g. '2026-04-30'."""
    for path in consolidated.values():
        parts = path.stem.split("_")
        if parts:
            return parts[-1]
    return ""
