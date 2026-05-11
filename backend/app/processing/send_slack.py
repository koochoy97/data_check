"""Envía un mensaje a Slack con los links de descarga de los CSVs consolidados."""
import time
from pathlib import Path

import httpx

from app.config import PUBLIC_BASE_URL, SLACK_BOT_TOKEN, SLACK_CHANNEL

SLACK_API = "https://slack.com/api/chat.postMessage"


def send_consolidated_slack(consolidated: dict[str, Path]) -> None:
    if not consolidated:
        return
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL:
        print("[slack] SLACK_BOT_TOKEN o SLACK_CHANNEL no configurados, omitiendo envío")
        return

    date_str = _date_from_consolidated(consolidated)

    lines = [
        f"*Reportes consolidados de Reply.io del {date_str}*",
        "",
        "Links de descarga (válidos por 24h):",
    ]
    for path in consolidated.values():
        size_mb = path.stat().st_size / 1024 / 1024
        url = f"{PUBLIC_BASE_URL}/api/consolidated/{path.name}"
        lines.append(f"• <{url}|{path.name}> ({size_mb:.1f} MB)")

    payload = {
        "channel": SLACK_CHANNEL,
        "text": "\n".join(lines),
        "unfurl_links": False,
        "unfurl_media": False,
    }
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }

    print(f"[slack] Enviando a {SLACK_CHANNEL}")
    for attempt in range(3):
        try:
            r = httpx.post(SLACK_API, json=payload, headers=headers, timeout=30)
            data = r.json()
            if data.get("ok"):
                print("[slack] Enviado correctamente")
                return
            err = data.get("error", "unknown")
            print(f"[slack] Intento {attempt+1}/3 falló: {err}")
            if err in ("ratelimited", "service_unavailable") and attempt < 2:
                wait = 30 * (attempt + 1)
                time.sleep(wait)
                continue
            raise RuntimeError(f"Slack API error: {err}")
        except httpx.HTTPError as e:
            print(f"[slack] Intento {attempt+1}/3 error HTTP: {e}")
            if attempt < 2:
                time.sleep(30 * (attempt + 1))
                continue
            raise


def _date_from_consolidated(consolidated: dict[str, Path]) -> str:
    for path in consolidated.values():
        parts = path.stem.split("_")
        if parts:
            return parts[-1]
    return ""
