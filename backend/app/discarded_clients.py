"""Lista persistente local de clientes Siete descartados.

NO toca Siete API. Solo excluye `siete_id`s del listado de pendientes de
reconciliación. El operador puede descartar un cliente que aparece como
Active sin team_id pero que no quiere procesar (ej. cliente ya inactivo cuyo
status no fue actualizado en Siete), sin necesidad de cambiar nada en el CRM.

Persistencia: `DOWNLOAD_DIR / "discarded_clients.json"` con
`{"siete_ids": [int], "updated_at": iso8601}`. Mismo patrón best-effort que
`last_cron_run.json`.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import DOWNLOAD_DIR

_PATH = DOWNLOAD_DIR / "discarded_clients.json"


def path() -> Path:
    return _PATH


def load() -> set[int]:
    """Devuelve el set de siete_ids descartados. Set vacío si no existe el archivo."""
    if not _PATH.exists():
        return set()
    try:
        data = json.loads(_PATH.read_text())
        ids = data.get("siete_ids", [])
        return {int(x) for x in ids}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        print(f"[discarded] WARN: archivo corrupto en {_PATH} ({e}); tratando como vacío")
        return set()


def add(siete_id: int) -> None:
    """Agrega un siete_id a la lista. Idempotente."""
    current = load()
    current.add(int(siete_id))
    _save(current)


def remove(siete_id: int) -> None:
    """Quita un siete_id de la lista. Idempotente."""
    current = load()
    current.discard(int(siete_id))
    _save(current)


def _save(ids: set[int]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "siete_ids": sorted(ids),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
