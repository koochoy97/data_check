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

def send_consolidated_slack(
    consolidated: dict[str, Path],
    pending_count: int = 0,
) -> None:
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
    text = _build_message(consolidated, pending_count=pending_count)

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


def _post_with_retry(channel: str, text: str, headers: dict, label: str) -> str:
    """Returns the actual channel ID from the Slack API response (needed for file uploads to DMs)."""
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
                actual_channel = data.get("channel", channel)
                print(f"[slack] Enviado a {label} (actual_channel={actual_channel})")
                return actual_channel
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



def _build_message(consolidated: dict[str, Path], pending_count: int = 0) -> str:
    date_str = _date_from_consolidated(consolidated)
    lines = [
        f"*Reportes consolidados de Reply.io del {date_str}*",
        "",
        "Links de descarga (válidos por 48h):",
    ]
    for path in consolidated.values():
        size_mb = path.stat().st_size / 1024 / 1024
        url = f"{PUBLIC_BASE_URL}/api/consolidated/{path.name}"
        lines.append(f"• <{url}|{path.name}> ({size_mb:.1f} MB)")

    logs_url = f"{PUBLIC_BASE_URL.rstrip('/')}/download-logs"
    lines.append("")
    lines.append(f"<{logs_url}|Logs de descarga>")

    if pending_count > 0:
        plural = "s" if pending_count != 1 else ""
        recon_url = f"{PUBLIC_BASE_URL.rstrip('/')}/reconciliation"
        lines.append("")
        lines.append(
            f"⚠️ Hay {pending_count} cliente{plural} pendiente{plural} de reconciliar: "
            f"<{recon_url}|abrir reconciliación>"
        )
    return "\n".join(lines)


def _date_from_consolidated(consolidated: dict[str, Path]) -> str:
    for path in consolidated.values():
        parts = path.stem.split("_")
        if parts:
            return parts[-1]
    return ""


# ── Alertas operativas (canal #automations_notifications) ─────────────────────

# Canal #automations_notifications. Override-able via env var por si cambia.
import os
_ALERTS_CHANNEL = os.getenv("SLACK_ALERTS_CHANNEL", "C093XM2UV9C")


def _post_to_alerts(text: str) -> None:
    """Manda un mensaje al canal de alertas. Best-effort, no levanta si falla."""
    if not SLACK_BOT_TOKEN:
        print(f"[slack-alert] SLACK_BOT_TOKEN no configurado, skip: {text[:80]}")
        return
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }
    try:
        _post_with_retry(_ALERTS_CHANNEL, text, headers, label=f"alerts/{_ALERTS_CHANNEL}")
    except Exception as e:
        # No relanzar: la alerta es best-effort y el caller no debería abortar por esto.
        print(f"[slack-alert] No se pudo enviar alerta: {e}")


def send_reconciliation_alert(pending_count: int, base_url: str) -> None:
    """Avisa al canal de alertas que hay clientes pendientes de reconciliación.

    No envía nada si pending_count == 0.
    """
    if pending_count <= 0:
        return
    url = f"{base_url.rstrip('/')}/reconciliation"
    text = (
        f"*⚠️ Reconciliación pendiente*\n"
        f"{pending_count} cliente{'s' if pending_count != 1 else ''} Active en Siete sin `team_id`.\n"
        f"Resolvé en {url}"
    )
    _post_to_alerts(text)


def send_siete_down_alert(error: str, endpoint: str) -> None:
    """Avisa al canal de alertas que el cron diario abortó por fallo de Siete API."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    text = (
        f"*🚨 Cron diario abortado — Siete API caída*\n"
        f"`endpoint:` {endpoint}\n"
        f"`error:` {error}\n"
        f"`timestamp:` {ts}"
    )
    _post_to_alerts(text)


def send_workspace_unavailable_alert(
    client_name: str,
    siete_id: int | None,
    team_id: int | None,
    reason: str,
) -> None:
    """Avisa al canal de alertas que un workspace de Reply.io no es accesible.

    Se dispara cuando el SwitchTeam devuelve no-2xx o la verificación post-switch
    detecta que el workspace activo no coincide con el esperado. El cron sigue
    procesando los demás clientes; este aviso es para que el operador resuelva
    el acceso (churn del cliente o re-invitación del bot al workspace).
    """
    text = (
        f"*⚠️ Workspace de Reply.io inaccesible*\n"
        f"*Cliente:* {client_name}\n"
        f"`siete_id:` {siete_id}\n"
        f"`team_id:` {team_id}\n"
        f"`motivo:` {reason}\n"
        f"_Revisar si el cliente fue dado de baja o si hay que re-invitar al bot al workspace en Reply.io._"
    )
    _post_to_alerts(text)
