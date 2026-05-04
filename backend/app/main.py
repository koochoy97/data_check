"""FastAPI backend with SSE for Reply.io report validation"""
import asyncio
import json
import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app.config import load_clients, REPLY_IO_EMAIL, REPLY_IO_PASSWORD, DOWNLOAD_DIR, CLIENTS_CONFIG_PATH
from app.processing.consolidator import consolidate
from app.processing.send_email import send_consolidated_report
from app.scraper.reply_io import download_all_reports, download_reports, fetch_workspaces


MAX_FILE_AGE_HOURS = 24
# Peru is UTC-5, no DST
PERU_UTC_OFFSET = timezone(timedelta(hours=-5))


def load_active_clients() -> dict:
    """Return clients that don't have excluded=true."""
    return {k: v for k, v in load_clients().items() if not v.get("excluded")}


# ── Cleanup ──────────────────────────────────────────────────────────────────

def _cleanup_old_files(root: Path, max_age_hours: int = MAX_FILE_AGE_HOURS) -> int:
    """Delete files under `root` older than `max_age_hours`. Returns count deleted."""
    if not root.exists():
        return 0
    cutoff = datetime.now().timestamp() - max_age_hours * 3600
    deleted = 0
    for path in root.rglob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            try:
                path.unlink()
                deleted += 1
            except OSError as e:
                print(f"[cleanup] No se pudo borrar {path}: {e}")
    return deleted


async def _cleanup_cron():
    """Delete files older than MAX_FILE_AGE_HOURS, checked every hour."""
    while True:
        try:
            deleted = _cleanup_old_files(DOWNLOAD_DIR)
            if deleted:
                print(f"[cleanup] Borrados {deleted} archivos > {MAX_FILE_AGE_HOURS}h")
        except Exception as e:
            print(f"[cleanup] Error: {e}")
        await asyncio.sleep(3600)


# ── Workspace sync ────────────────────────────────────────────────────────────

async def _sync_workspaces():
    """Scrape Reply.io workspaces and update clients.json. Returns updated dict or None."""
    headless = os.getenv("HEADLESS", "true").lower() != "false"
    workspaces = await fetch_workspaces(
        email=REPLY_IO_EMAIL,
        password=REPLY_IO_PASSWORD,
        headless=headless,
    )
    if not workspaces:
        return None

    clients = load_clients()
    for ws in workspaces:
        key = ws["name"].lower().replace(" ", "_")
        if key not in clients:
            clients[key] = {"display_name": ws["name"], "team_id": ws["team_id"]}
        else:
            clients[key]["team_id"] = ws["team_id"]
            clients[key]["display_name"] = ws["name"]

    with open(CLIENTS_CONFIG_PATH, "w") as f:
        json.dump(clients, f, indent=2, ensure_ascii=False)

    return clients


async def _daily_sync_cron():
    """Sync workspaces every day at 00:00 local time."""
    while True:
        now = datetime.now()
        midnight = datetime.combine(now.date(), time(0, 0)) + timedelta(days=1)
        wait_seconds = (midnight - now).total_seconds()
        print(f"[sync-cron] Próximo sync en {wait_seconds:.0f}s ({midnight})")
        await asyncio.sleep(wait_seconds)
        try:
            print("[sync-cron] Ejecutando sync de workspaces...")
            result = await _sync_workspaces()
            print(f"[sync-cron] {'Sync exitoso: ' + str(len(result)) + ' clientes' if result else 'Sync falló: no se encontraron workspaces'}")
        except Exception as e:
            print(f"[sync-cron] Error: {e}")


# ── Bulk pipeline ─────────────────────────────────────────────────────────────

async def _run_bulk_pipeline(emit, client_ids: list[str], clients: dict):
    """
    Download + consolidate reports for the given client_ids.
    Uses a single browser session (one login) for all clients.
    `emit` is a callable that receives dicts with keys: type, message, [name, size, path].
    Returns (per_client_files, failures, consolidated).
    """
    headless = os.getenv("HEADLESS", "true").lower() != "false"
    per_client_files: list[dict] = []
    failures: list[str] = []

    # Build client list for the single-session scraper
    scraper_clients = [
        {
            "client_id": cid,
            "team_id": clients[cid]["team_id"],
            "download_dir": DOWNLOAD_DIR / cid,
        }
        for cid in client_ids
    ]

    def on_progress(msg):
        emit({"type": "progress", "message": msg})

    results = await download_all_reports(
        email=REPLY_IO_EMAIL,
        password=REPLY_IO_PASSWORD,
        clients=scraper_clients,
        on_progress=on_progress,
        headless=headless,
    )

    for cid in client_ids:
        display_name = clients[cid].get("display_name", cid)
        result = results.get(cid, {"error": "sin resultado"})
        if "error" in result:
            failures.append(f"{display_name}: {result['error']}")
        else:
            per_client_files.append({
                "client_id": cid,
                "client_name": display_name,
                "people_csv": result.get("personas"),
                "email_csv": result.get("correos"),
            })

    consolidated = {}
    if per_client_files:
        emit({"type": "progress", "message": "Consolidando CSVs..."})
        consolidated = consolidate(
            per_client_files=per_client_files,
            output_dir=DOWNLOAD_DIR / "consolidated",
        )
        for path in consolidated.values():
            emit({"type": "file", "name": path.name, "size": path.stat().st_size,
                  "path": f"/api/consolidated/{path.name}"})

        emit({"type": "progress", "message": "Enviando por email..."})
        try:
            send_consolidated_report(consolidated)
            emit({"type": "progress", "message": "Email enviado a jaime@wearesiete.com, nicolas@wearesiete.com"})
            print("[email] Enviado correctamente")
        except Exception as e:
            traceback.print_exc()
            print(f"[email] ERROR: {e}")
            emit({"type": "progress", "message": f"Error enviando email: {e}"})

    return per_client_files, failures, consolidated


async def _daily_bulk_cron():
    """Download all active clients and consolidate every day at 00:00 Peru (05:00 UTC)."""
    BULK_HOUR_UTC = 5  # 00:00 Peru = 05:00 UTC
    while True:
        now_utc = datetime.now(timezone.utc)
        next_run = now_utc.replace(hour=BULK_HOUR_UTC, minute=0, second=0, microsecond=0)
        if next_run <= now_utc:
            next_run += timedelta(days=1)
        wait_seconds = (next_run - now_utc).total_seconds()
        print(f"[bulk-cron] Próxima descarga masiva en {wait_seconds:.0f}s ({next_run.astimezone(PERU_UTC_OFFSET)} hora Perú)")
        await asyncio.sleep(wait_seconds)

        try:
            clients = load_active_clients()
            client_ids = list(clients.keys())
            print(f"[bulk-cron] Iniciando descarga de {len(client_ids)} clientes activos")

            messages = []

            def emit(msg):
                messages.append(msg)
                if msg.get("type") == "progress":
                    print(f"[bulk-cron] {msg['message']}")

            per_client_files, failures, consolidated = await _run_bulk_pipeline(emit, client_ids, clients)

            print(f"[bulk-cron] Completado: {len(per_client_files)}/{len(client_ids)} clientes OK, "
                  f"{len(failures)} fallidos, {len(consolidated)} archivos consolidados")
            if failures:
                print(f"[bulk-cron] Fallidos: {failures}")
        except Exception as e:
            traceback.print_exc()
            print(f"[bulk-cron] Error fatal: {e}")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    tasks = [
        asyncio.create_task(_daily_sync_cron()),
        asyncio.create_task(_cleanup_cron()),
        asyncio.create_task(_daily_bulk_cron()),
    ]
    yield
    for t in tasks:
        t.cancel()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Reply.io Report Validator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/clients")
def list_clients():
    clients = load_clients()
    return [
        {"id": k, "name": v.get("display_name", k), "team_id": v["team_id"],
         "excluded": v.get("excluded", False)}
        for k, v in clients.items()
    ]


@app.get("/api/generate/{client_id}")
async def generate_report(client_id: str):
    """SSE: download reports for a single client."""
    queue: asyncio.Queue = asyncio.Queue()

    async def run_pipeline():
        try:
            clients = load_clients()
            if client_id not in clients:
                await queue.put({"type": "error", "message": f"Cliente '{client_id}' no encontrado"})
                return

            client = clients[client_id]
            team_id = client["team_id"]
            display_name = client.get("display_name", client_id)
            email = client.get("reply_io_email", REPLY_IO_EMAIL)
            password = client.get("reply_io_password", REPLY_IO_PASSWORD)

            def on_progress(msg):
                queue.put_nowait({"type": "progress", "message": msg})

            on_progress("Conectando a Reply.io...")
            download_dir = DOWNLOAD_DIR / client_id
            headless = os.getenv("HEADLESS", "true").lower() != "false"
            reports = await download_reports(
                email=email, password=password, team_id=team_id,
                download_dir=download_dir, on_progress=on_progress, headless=headless,
            )

            people_size = reports["personas"].stat().st_size
            on_progress(f"people.csv descargado ({people_size:,} bytes)")
            queue.put_nowait({"type": "file", "name": "people.csv", "size": people_size,
                              "path": f"/api/files/{client_id}/people.csv"})

            email_size = reports["correos"].stat().st_size
            on_progress(f"email_activity.csv descargado ({email_size:,} bytes)")
            queue.put_nowait({"type": "file", "name": "email_activity.csv", "size": email_size,
                              "path": f"/api/files/{client_id}/email_activity.csv"})

            await queue.put({"type": "done", "message": f"Listo! Reportes descargados para {display_name}"})

        except Exception as e:
            traceback.print_exc()
            await queue.put({"type": "error", "message": str(e)})

    async def event_generator():
        task = asyncio.create_task(run_pipeline())
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield {"event": "message", "data": json.dumps(msg)}
                if msg["type"] in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                yield {"comment": "keepalive"}
        await task

    return EventSourceResponse(event_generator())


@app.get("/api/files/{client_id}/{filename}")
def download_file(client_id: str, filename: str):
    allowed = {"people.csv", "email_activity.csv"}
    if filename not in allowed:
        return {"error": "File not found"}
    path = DOWNLOAD_DIR / client_id / filename
    if not path.exists():
        return {"error": "File not found"}
    return FileResponse(path, filename=filename, media_type="text/csv")


@app.get("/api/consolidated/{filename}")
def download_consolidated(filename: str):
    if "/" in filename or ".." in filename or not filename.endswith(".csv"):
        return {"error": "Invalid filename"}
    path = DOWNLOAD_DIR / "consolidated" / filename
    if not path.exists():
        return {"error": "File not found"}
    return FileResponse(path, filename=filename, media_type="text/csv")


@app.get("/api/generate-bulk")
async def generate_bulk(limit: int = 0):
    """SSE: download active clients (all if limit=0, else first N) and consolidate."""
    queue: asyncio.Queue = asyncio.Queue()

    async def run_pipeline():
        try:
            clients = load_active_clients()
            client_ids = list(clients.keys())
            if limit > 0:
                client_ids = client_ids[:limit]
            if not client_ids:
                await queue.put({"type": "error", "message": "No hay clientes activos configurados"})
                return

            await queue.put({"type": "progress",
                             "message": f"Procesando {len(client_ids)} clientes activos"})

            def emit(msg):
                queue.put_nowait(msg)

            per_client_files, failures, consolidated = await _run_bulk_pipeline(emit, client_ids, clients)

            if not per_client_files:
                await queue.put({"type": "error",
                                 "message": f"Ningún cliente OK. Errores: {failures}"})
                return

            done_msg = f"Listo. {len(per_client_files)}/{len(client_ids)} clientes consolidados."
            if failures:
                done_msg += f" Fallidos ({len(failures)}): {', '.join(f.split(':')[0] for f in failures)}"
            await queue.put({"type": "done", "message": done_msg})

        except Exception as e:
            traceback.print_exc()
            await queue.put({"type": "error", "message": str(e)})

    async def event_generator():
        task = asyncio.create_task(run_pipeline())
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield {"event": "message", "data": json.dumps(msg)}
                if msg["type"] in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                yield {"comment": "keepalive"}
        await task

    return EventSourceResponse(event_generator())


@app.post("/api/send-today")
async def send_today():
    """Busca los CSVs consolidados de hoy y los envía por email."""
    today = datetime.now(PERU_UTC_OFFSET).date().isoformat()
    consolidated_dir = DOWNLOAD_DIR / "consolidated"

    found = {}
    for kind, prefix in [("people", "people_consolidated"), ("email_activity", "email_activity_consolidated")]:
        path = consolidated_dir / f"{prefix}_{today}.csv"
        if path.exists():
            found[kind] = path

    if not found:
        return {"error": f"No hay archivos consolidados para hoy ({today}) en {consolidated_dir}"}

    try:
        send_consolidated_report(found)
        return {"sent": True, "files": [p.name for p in found.values()], "date": today}
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


@app.post("/api/sync-clients")
async def sync_clients():
    clients = await _sync_workspaces()
    if clients is None:
        return {"error": "No se encontraron workspaces"}
    return {"synced": len(clients), "clients": clients}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── Serve frontend static files ───────────────────────────────────────────────
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    # Extensions that are never SPA routes — return 404 immediately
    _BLOCKED_EXTENSIONS = {
        ".env", ".json", ".xml", ".php", ".sql", ".bak", ".cfg",
        ".yaml", ".yml", ".ini", ".log", ".sh", ".py",
    }

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Block obvious credential/config probes
        suffix = Path(full_path).suffix.lower()
        if suffix in _BLOCKED_EXTENSIONS or full_path.startswith("."):
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        file_path = STATIC_DIR / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return HTMLResponse((STATIC_DIR / "index.html").read_text())
