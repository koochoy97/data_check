"""Cliente del API de Siete (apirest.wearesiete.com).

Source of truth de clientes. Lecturas via GET, escrituras via PATCH.
"""
import httpx

from app.config import SIETE_API_ENDPOINT, SIETE_API_KEY
from app.utils.slug import slug


# Clientes a excluir del run diario (case-insensitive sobre el nombre exacto)
EXCLUDED_CLIENT_NAMES = {"siete"}


async def _fetch_all_clientes() -> list[dict]:
    """Trae el listado crudo de clientes desde Siete API."""
    if not SIETE_API_KEY:
        raise RuntimeError("Falta env var X-HEADER-SIETE-API")

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(
            f"{SIETE_API_ENDPOINT}/core/clientes/",
            params={"limit": 500},
            headers={"x-api-key": SIETE_API_KEY},
        )
        r.raise_for_status()
        return r.json()


def _is_excluded(name: str) -> bool:
    return name.strip().lower() in EXCLUDED_CLIENT_NAMES


async def fetch_active_clients() -> list[dict]:
    """Devuelve los clientes con status='Active' y team_id no nulo.

    Estructura: [{"client_id": slug, "client_name": str, "team_id": int, "siete_id": int}]
    """
    data = await _fetch_all_clientes()
    return [
        {
            "client_id": slug(c["cliente"]),
            "client_name": c["cliente"],
            "team_id": c["team_id"],
            "siete_id": c["id"],
        }
        for c in data
        if c.get("status") == "Active"
        and c.get("team_id")
        and not _is_excluded(c.get("cliente", ""))
    ]


async def fetch_active_missing_team_id() -> list[dict]:
    """Devuelve los clientes Active sin team_id (candidatos a reconciliación).

    Estructura: [{"siete_id": int, "siete_name": str, "siete_slug": str, "status": str}]
    """
    data = await _fetch_all_clientes()
    return [
        {
            "siete_id": c["id"],
            "siete_name": c["cliente"],
            "siete_slug": slug(c["cliente"]),
            "status": c.get("status"),
        }
        for c in data
        if c.get("status") == "Active"
        and not c.get("team_id")
        and not _is_excluded(c.get("cliente", ""))
    ]


async def patch_team_id(siete_id: int, team_id: int) -> dict:
    """Actualiza el team_id de un cliente en Siete API.

    Retorna el registro actualizado. Levanta httpx.HTTPStatusError si falla.
    """
    if not SIETE_API_KEY:
        raise RuntimeError("Falta env var X-HEADER-SIETE-API")
    if not isinstance(team_id, int) or team_id <= 0:
        raise ValueError(f"team_id inválido: {team_id!r}")

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.patch(
            f"{SIETE_API_ENDPOINT}/core/clientes/{siete_id}/",
            json={"team_id": team_id},
            headers={
                "x-api-key": SIETE_API_KEY,
                "Content-Type": "application/json",
            },
        )
        r.raise_for_status()
        return r.json()
