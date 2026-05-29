"""Sonda manual para validar acceso a un workspace de Reply.io.

Uso:
    cd backend
    python -m scripts.probe_workspace <team_id>            # validar un team
    python -m scripts.probe_workspace <t1> <t2> ...        # validar varios

Lo que hace:
    1. Login en Reply.io con REPLY_IO_EMAIL / REPLY_IO_PASSWORD del .env.
    2. Para cada team_id, llama a `_switch_workspace` exactamente igual que el
       scraper en producción.
    3. Reporta éxito o muestra el mensaje de `WorkspaceUnavailable`.

Sirve para reproducir el bug 28-05 (probar team_id=463109 de 7Graus) y para
auditar manualmente nuevos workspaces antes de incorporarlos al cron.

No emite alertas a Slack (alert_context=None).
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Permitir ejecutar desde la raíz del repo (`python backend/scripts/probe_workspace.py`)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.scraper.reply_io import (  # noqa: E402
    CHROMIUM_ARGS,
    WorkspaceUnavailable,
    _login_reply_io,
    _switch_workspace,
)


async def probe(team_ids: list[int]) -> None:
    load_dotenv(ROOT / ".env")
    email = os.getenv("REPLY_IO_EMAIL")
    password = os.getenv("REPLY_IO_PASSWORD")
    if not email or not password:
        raise SystemExit("Falta REPLY_IO_EMAIL o REPLY_IO_PASSWORD en .env")

    print(f"Probando {len(team_ids)} workspace(s) como {email}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        await _login_reply_io(page, email, password, emit=print)

        for team_id in team_ids:
            print(f"\n--- teamId={team_id} ---")
            try:
                await _switch_workspace(page, team_id, emit=print, alert_context=None)
                print(f"OK: workspace {team_id} accesible y activo")
            except WorkspaceUnavailable as e:
                print(f"FAIL: {e}")

        await browser.close()


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    try:
        team_ids = [int(arg) for arg in sys.argv[1:]]
    except ValueError as e:
        raise SystemExit(f"team_id debe ser entero: {e}")
    asyncio.run(probe(team_ids))


if __name__ == "__main__":
    main()
