"""Reconciliación de clientes Siete <-> Reply.io.

No persiste estado local. Las correcciones se hacen via PATCH a Siete API.
Reply.io se scrapea live cuando la UI lo pide.
"""
import os
from typing import Iterable

from app.scraper.reply_io import fetch_workspaces
from app.siete_api import _is_excluded
from app.utils.slug import slug


async def fetch_reply_workspaces_live() -> list[dict] | None:
    """Scrape Reply.io en tiempo real. Retorna None si el scrape falla.

    Estructura: [{"name": str, "team_id": int}]
    """
    from app.config import REPLY_IO_EMAIL, REPLY_IO_PASSWORD

    headless = os.getenv("HEADLESS", "true").lower() != "false"
    workspaces = await fetch_workspaces(
        email=REPLY_IO_EMAIL,
        password=REPLY_IO_PASSWORD,
        headless=headless,
    )
    if not workspaces:
        return None
    return [{"name": w["name"], "team_id": w["team_id"]} for w in workspaces]


def suggest_match(siete_slug: str, reply_workspaces: Iterable[dict]) -> dict | None:
    """Encuentra el mejor match Reply.io para un slug de Siete.

    Estrategia:
    - Exacto: slug(reply.name) == siete_slug → confidence "exact"
    - Substring (siete_slug en slug(reply.name) o viceversa) → confidence "partial"

    Retorna {"name", "team_id", "confidence"} o None si no hay match.
    """
    exact = []
    partial = []
    for ws in reply_workspaces:
        rs = slug(ws["name"])
        if rs == siete_slug:
            exact.append(ws)
        elif siete_slug in rs or rs in siete_slug:
            partial.append(ws)

    if exact:
        ws = exact[0]
        return {"name": ws["name"], "team_id": ws["team_id"], "confidence": "exact"}
    if partial:
        ws = partial[0]
        return {"name": ws["name"], "team_id": ws["team_id"], "confidence": "partial"}
    return None


def build_pending_payload(siete_pending: list[dict],
                          reply_workspaces: list[dict] | None) -> dict:
    """Arma el payload del endpoint GET /api/reconciliation/pending.

    Cada item: {siete_id, siete_name, siete_slug, suggested, reply_options}
    """
    reply_options = reply_workspaces or []
    pending = []
    for p in siete_pending:
        suggested = suggest_match(p["siete_slug"], reply_options) if reply_options else None
        pending.append({
            "siete_id": p["siete_id"],
            "siete_name": p["siete_name"],
            "siete_slug": p["siete_slug"],
            "status": p.get("status"),
            "suggested": suggested,
        })
    return {
        "pending": pending,
        "reply_options": reply_options,
        "scrape_error": None if reply_workspaces is not None else "Reply.io scrape failed",
    }


def build_mapping_payload(siete_clients: list[dict],
                          reply_workspaces: list[dict] | None) -> dict:
    """Arma el payload del endpoint GET /api/clients/mapping.

    Cada item: {siete_id, siete_name, siete_slug, status, team_id, reply_match}.
    `reply_match` es {name, team_id} cuando el team_id del cliente matchea
    un workspace conocido, o None en otro caso.
    """
    by_team_id: dict[int, dict] = {}
    if reply_workspaces:
        for ws in reply_workspaces:
            try:
                by_team_id[int(ws["team_id"])] = ws
            except (TypeError, ValueError, KeyError):
                continue

    out = []
    for c in siete_clients:
        if _is_excluded(c.get("cliente", "") or ""):
            continue
        team_id = c.get("team_id")
        match = by_team_id.get(int(team_id)) if team_id else None
        out.append({
            "siete_id": c["id"],
            "siete_name": c.get("cliente"),
            "siete_slug": slug(c.get("cliente") or ""),
            "status": c.get("status"),
            "team_id": team_id,
            "reply_match": {"name": match["name"], "team_id": match["team_id"]} if match else None,
        })
    return {
        "clients": out,
        "scrape_error": None if reply_workspaces is not None else "Reply.io scrape failed",
    }
