"""Cliente del API de Siete (apirest.wearesiete.com) para obtener clientes activos."""
import re

import httpx

from app.config import SIETE_API_ENDPOINT, SIETE_API_KEY


# Clientes a excluir del run diario (case-insensitive sobre el nombre exacto)
EXCLUDED_CLIENT_NAMES = {"siete"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


async def fetch_active_clients() -> list[dict]:
    """
    Devuelve los clientes con status='Active' y team_id no nulo,
    excluyendo los nombres en EXCLUDED_CLIENT_NAMES.
    Estructura: [{"client_id": str, "client_name": str, "team_id": int}, ...]
    """
    if not SIETE_API_KEY:
        raise RuntimeError("Falta env var X-HEADER-SIETE-API")

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(
            f"{SIETE_API_ENDPOINT}/core/clientes/",
            params={"limit": 500},
            headers={"x-api-key": SIETE_API_KEY},
        )
        r.raise_for_status()
        data = r.json()

    return [
        {
            "client_id": _slug(c["cliente"]),
            "client_name": c["cliente"],
            "team_id": c["team_id"],
        }
        for c in data
        if c.get("status") == "Active"
        and c.get("team_id")
        and c.get("cliente", "").strip().lower() not in EXCLUDED_CLIENT_NAMES
    ]
