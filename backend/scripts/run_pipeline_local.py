"""Ejecuta el bulk pipeline completo (igual que el cron diario) desde local.

Diferencia vs el cron:
  - DESACTIVA el envío del reporte consolidado a Slack (`send_consolidated_slack`
    queda como no-op) para no spamear al equipo con un reporte fuera de horario.
  - MANTIENE las alertas de workspace inaccesible (`send_workspace_unavailable_alert`)
    para validar el fix end-to-end.

Outputs:
  - CSVs consolidados en /tmp/reports/consolidated/
  - Log con prefijo [pipeline] a stdout (redirigir a archivo si se ejecuta en bg)
  - Resumen final con clientes OK, failures, archivos generados
"""
import asyncio
import sys
from pathlib import Path

# Permitir importar app.* desde la raíz del repo
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

# Cargar .env ANTES de importar config
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.main import _run_bulk_pipeline  # noqa: E402
from app.siete_api import fetch_active_clients  # noqa: E402
import app.processing.send_slack as slack_mod  # noqa: E402


def _noop_consolidated(*args, **kwargs):
    print("[pipeline] (skip) send_consolidated_slack desactivado para test local")


# Monkeypatch ANTES de correr el pipeline
slack_mod.send_consolidated_slack = _noop_consolidated
# Reimport en main.py (que ya importó la función directamente)
import app.main as main_mod  # noqa: E402
main_mod.send_consolidated_slack = _noop_consolidated


async def main() -> None:
    print("[pipeline] Fetching active clients from Siete API...")
    clients = await fetch_active_clients()
    print(f"[pipeline] Procesando {len(clients)} clientes activos")
    print(f"[pipeline] Lista: {[c['client_id'] for c in clients]}\n")

    def emit(msg):
        if msg.get("type") == "progress":
            print(f"[pipeline] {msg['message']}")
        elif msg.get("type") == "file":
            print(f"[pipeline] FILE {msg['name']} ({msg['size']:,} bytes)")

    per_client_files, failures, consolidated = await _run_bulk_pipeline(emit, clients)

    print("\n" + "=" * 70)
    print(f"[pipeline] RESUMEN")
    print("=" * 70)
    print(f"  Clientes OK:    {len(per_client_files)}/{len(clients)}")
    print(f"  Failures:       {len(failures)}")
    print(f"  Consolidados:   {len(consolidated)} archivo(s)")
    for k, p in consolidated.items():
        print(f"     - {k}: {p} ({p.stat().st_size:,} bytes)")
    if failures:
        print(f"\n[pipeline] FAILURES:")
        for f in failures:
            print(f"  - {f}")


if __name__ == "__main__":
    asyncio.run(main())
