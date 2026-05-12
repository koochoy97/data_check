"""Envía un mensaje a Slack con los links de descarga de los CSVs consolidados.

Soporta múltiples destinos vía SLACK_DESTINATIONS (lista separada por comas).
Cada destino puede ser:
  - email (ej. jaime@wearesiete.com)         → DM al usuario (lookup por email)
  - canal con # (ej. #automations)           → canal por nombre
  - ID de canal/DM/usuario (C.../D.../U...)  → tal cual

Fallback: si SLACK_DESTINATIONS está vacío, usa SLACK_CHANNEL.
"""
import time
from pathlib import Path

import httpx

from app.config import (
    PUBLIC_BASE_URL,
    SLACK_BOT_TOKEN,
    SLACK_CHANNEL,
    SLACK_DESTINATIONS,
)

SLACK_API = "https://slack.com/api/chat.postMessage"
SLACK_LOOKUP = "https://slack.com/api/users.lookupByEmail"


def send_consolidated_slack(consolidated: dict[str, Path]) -> None:
    if not consolidated:
        return
    if not SLACK_BOT_TOKEN:
        print("[slack] SLACK_BOT_TOKEN no configurado, omitiendo envío")
        return

    destinations = _parse_destinations()
    if not destinations:
        print("[slack] No hay destinos (SLACK_DESTINATIONS/SLACK_CHANNEL vacíos), omitiendo envío")
        return

    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }
    text = _build_message(consolidated)

    failures = []
    for raw in destinations:
        channel = _resolve_destination(raw, headers)
        if not channel:
            failures.append(raw)
            continue
        try:
            _post_with_retry(channel, text, headers, label=raw)
        except Exception as e:
            print(f"[slack] Falló envío a {raw}: {e}")
            failures.append(raw)

    if failures:
        raise RuntimeError(f"Slack: falló envío a {failures}")


def _parse_destinations() -> list[str]:
    raw = SLACK_DESTINATIONS or SLACK_CHANNEL or ""
    return [d.strip() for d in raw.replace(";", ",").split(",") if d.strip()]


def _resolve_destination(dest: str, headers: dict) -> str | None:
    """Convierte email → user_id; deja IDs y #canales tal cual."""
    if "@" in dest:
        try:
            r = httpx.get(SLACK_LOOKUP, params={"email": dest}, headers=headers, timeout=15)
            data = r.json()
            if data.get("ok"):
                return data["user"]["id"]
            print(f"[slack] lookupByEmail falló para {dest}: {data.get('error')}")
            return None
        except httpx.HTTPError as e:
            print(f"[slack] lookupByEmail HTTP error para {dest}: {e}")
            return None
    return dest


def _post_with_retry(channel: str, text: str, headers: dict, label: str) -> None:
    payload = {
        "channel": channel,
        "text": text,
        "unfurl_links": False,
        "unfurl_media": False,
    }
    print(f"[slack] Enviando a {label} (channel={channel})")
    for attempt in range(3):
        try:
            r = httpx.post(SLACK_API, json=payload, headers=headers, timeout=30)
            data = r.json()
            if data.get("ok"):
                print(f"[slack] Enviado a {label}")
                return
            err = data.get("error", "unknown")
            print(f"[slack] {label} intento {attempt+1}/3 falló: {err}")
            if err in ("ratelimited", "service_unavailable") and attempt < 2:
                time.sleep(30 * (attempt + 1))
                continue
            raise RuntimeError(f"Slack API error: {err}")
        except httpx.HTTPError as e:
            print(f"[slack] {label} intento {attempt+1}/3 error HTTP: {e}")
            if attempt < 2:
                time.sleep(30 * (attempt + 1))
                continue
            raise


def _build_message(consolidated: dict[str, Path]) -> str:
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
    return "\n".join(lines)


def _date_from_consolidated(consolidated: dict[str, Path]) -> str:
    for path in consolidated.values():
        parts = path.stem.split("_")
        if parts:
            return parts[-1]
    return ""
