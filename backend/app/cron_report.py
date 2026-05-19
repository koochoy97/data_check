"""Persistencia del último run del cron diario para observabilidad.

Best-effort: si la escritura falla, se logea pero no se propaga.
"""
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from app.config import DOWNLOAD_DIR

_REPORT_PATH = DOWNLOAD_DIR / "last_cron_run.json"


@dataclass
class CronRunReport:
    started_at: str = ""
    finished_at: str | None = None
    clients_total: int = 0
    clients_processed: int = 0
    failures: list[dict] = field(default_factory=list)        # [{"slug", "error"}]
    reconciliation: dict = field(default_factory=dict)         # {"missing_team_id": [{"slug", ...}]}
    slack_delivery: dict = field(default_factory=dict)         # {"sent_to": [...], "failed": [...]}
    error: str | None = None                                   # error fatal (ej. siete_api_down)

    @classmethod
    def start(cls) -> "CronRunReport":
        return cls(started_at=datetime.utcnow().isoformat() + "Z")

    def finish(self, error: str | None = None) -> None:
        self.finished_at = datetime.utcnow().isoformat() + "Z"
        if error:
            self.error = error

    def save(self) -> None:
        try:
            _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            _REPORT_PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"[cron-report] No se pudo escribir {_REPORT_PATH}: {e}")


def load_last_cron_run() -> dict | None:
    """Lee el último cron run report. Retorna None si no existe."""
    if not _REPORT_PATH.exists():
        return None
    try:
        return json.loads(_REPORT_PATH.read_text())
    except Exception as e:
        print(f"[cron-report] Error leyendo {_REPORT_PATH}: {e}")
        return None
