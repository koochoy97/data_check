"""FastAPI backend with SSE for Reply.io report validation.

Source of truth: Siete API (`/core/clientes/`).
Clients are listed and updated exclusively through Siete API; no local JSON cache.
Reports are delivered via Slack only (no Gmail). Reconciliation of clients
without team_id happens via the `/reconciliation` UI.
"""
import asyncio
import io
import json
import os
import traceback
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app.config import REPLY_IO_EMAIL, REPLY_IO_PASSWORD, DOWNLOAD_DIR, PUBLIC_BASE_URL, TFLX_PATH
from app import discarded_clients
from app.cron_report import CronRunReport, load_last_cron_run
from app.processing.consolidator import consolidate
from app.processing.tableau_exporter import run_tableau_export
from app.processing.send_slack import (
    send_consolidated_slack,
    send_reconciliation_alert,
    send_siete_down_alert,
)
from app.scraper.reply_io import download_all_reports, download_reports
from app.reconciliation import (
    build_mapping_payload,
    build_pending_payload,
    fetch_reply_workspaces_live,
)
from app.siete_api import (
    _fetch_all_clientes,
    fetch_active_clients,
    fetch_active_missing_team_id,
    fetch_all_meetings,
    patch_team_id,
)
from app.utils.slug import slug as _slug
from app.utils.dates import PERU_UTC_OFFSET, today_peru_iso

MAX_FILE_AGE_HOURS = 48


# ── Cleanup ──────────────────────────────────────────────────────────────────

def _cleanup_old_files(root: Path, max_age_hours: int = MAX_FILE_AGE_HOURS) -> int:
    """Delete files under `root` older than `max_age_hours`. Returns count deleted."""
    if not root.exists():
        return 0
    cutoff = datetime.now().timestamp() - max_age_hours * 3600
    deleted = 0
    for path in root.rglob("*"):
        if path.suffix == ".tflx":
            continue
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


# ── Bulk pipeline ─────────────────────────────────────────────────────────────

async def _run_bulk_pipeline(emit, clients: list[dict], pending_count: int = 0):
    """
    Download + consolidate reports for the given clients.
    `clients` is a list of {"client_id", "client_name", "team_id"}.
    Uses a single browser session (one login) for all clients.
    `pending_count` se pasa al mensaje de Slack para mostrar el aviso de
    reconciliación pendiente cuando hay clientes a resolver.
    """
    headless = os.getenv("HEADLESS", "true").lower() != "false"
    per_client_files: list[dict] = []
    failures: list[str] = []

    scraper_clients = [
        {
            "client_id": c["client_id"],
            "client_name": c["client_name"],
            "siete_id": c.get("siete_id"),
            "team_id": c["team_id"],
            "download_dir": DOWNLOAD_DIR / c["client_id"],
        }
        for c in clients
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

    run_summary_clients = []
    for c in clients:
        cid = c["client_id"]
        display_name = c["client_name"]
        result = results.get(cid, {"error": "sin resultado"})
        if "error" in result:
            failures.append(f"{display_name}: {result['error']}")
            run_summary_clients.append({"name": display_name, "status": "failed", "error": result["error"]})
        else:
            per_client_files.append({
                "client_id": cid,
                "client_name": display_name,
                "people_csv": result.get("personas"),
                "email_csv": result.get("correos"),
            })
            run_summary_clients.append({"name": display_name, "status": "ok", "error": None})

    # Persist run summary so /api/last-run can show all clients with their status
    summary_path = DOWNLOAD_DIR / "last_run_summary.json"
    import json as _json
    summary_path.write_text(_json.dumps({
        "date": datetime.now(PERU_UTC_OFFSET).strftime("%Y-%m-%d"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(clients),
        "ok_count": len(per_client_files),
        "failed_count": len(failures),
        "clients": run_summary_clients,
    }))

    # Emit full per-client outcome summary so operators can see all clients at a glance
    ok_names = [f["client_name"] for f in per_client_files]
    fail_names = [f.split(":", 1)[0].strip() for f in failures]
    emit({"type": "progress",
          "message": f"Resumen: {len(ok_names)}/{len(clients)} OK, {len(failures)} fallidos"})
    emit({"type": "progress",
          "message": f"OK ({len(ok_names)}): {', '.join(ok_names) or '(ninguno)'}"})
    if fail_names:
        emit({"type": "progress",
              "message": f"FALLIDOS ({len(fail_names)}): {', '.join(fail_names)}"})

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

        emit({"type": "progress", "message": "Enviando a Slack..."})
        xlsx_bytes: bytes | None = None
        try:
            from app.processing.tableau_exporter import generate_reuniones_xlsx
            meetings = await fetch_all_meetings()
            xlsx_bytes = generate_reuniones_xlsx(meetings)
            emit({"type": "progress", "message": f"Xlsx de reuniones generado ({len(xlsx_bytes):,} bytes)"})
        except Exception as e:
            traceback.print_exc()
            emit({"type": "progress", "message": f"[warn] No se pudo generar xlsx de reuniones: {e}"})
        try:
            send_consolidated_slack(consolidated, pending_count=pending_count, xlsx_bytes=xlsx_bytes)
            xlsx_status = "con xlsx" if xlsx_bytes else "sin xlsx (falló generación)"
            emit({"type": "progress", "message": f"Slack enviado ({xlsx_status})"})
        except Exception as e:
            traceback.print_exc()
            emit({"type": "progress", "message": f"ERROR Slack: {e}"})
            raise

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
        await _run_daily_cron_once()


async def _run_daily_cron_once() -> CronRunReport:
    """Ejecuta una vez el bulk-cron y guarda el reporte. Reusable para tests/diagnóstico."""
    report = CronRunReport.start()

    # Paso 1: obtener clientes activos. Si Siete API está caída, alertar y abortar.
    try:
        clients = await fetch_active_clients()
    except Exception as e:
        traceback.print_exc()
        err = f"{type(e).__name__}: {e}"
        print(f"[bulk-cron] Error fatal al consultar Siete API: {err}")
        send_siete_down_alert(err, endpoint="/core/clientes/")
        report.finish(error="siete_api_down")
        report.error = err
        report.save()
        return report

    # Paso 2: recolectar pendientes de reconciliación (no aborta, sigue con los que sí tienen team_id)
    try:
        pending = await fetch_active_missing_team_id()
    except Exception as e:
        print(f"[bulk-cron] Warning: no se pudo obtener pendientes de reconciliación: {e}")
        pending = []

    # Filtrar los descartados localmente para que no cuenten ni se muestren al operador.
    discarded = discarded_clients.load()
    pending = [p for p in pending if p["siete_id"] not in discarded]

    report.clients_total = len(clients)
    report.reconciliation = {
        "missing_team_id": [
            {"siete_id": p["siete_id"], "siete_name": p["siete_name"], "siete_slug": p["siete_slug"]}
            for p in pending
        ]
    }

    print(f"[bulk-cron] Iniciando descarga de {len(clients)} clientes activos "
          f"({len(pending)} pendientes de reconciliación)")

    def emit(msg):
        if msg.get("type") == "progress":
            print(f"[bulk-cron] {msg['message']}")

    try:
        per_client_files, failures, consolidated = await _run_bulk_pipeline(
            emit, clients, pending_count=len(pending),
        )
    except Exception as e:
        traceback.print_exc()
        report.finish(error=f"pipeline_error: {e}")
        report.save()
        return report

    report.clients_processed = len(per_client_files)
    report.failures = [
        {"slug": f.split(":", 1)[0].strip(), "error": f.split(":", 1)[1].strip() if ":" in f else ""}
        for f in failures
    ]
    report.slack_delivery = {"consolidated": list(consolidated.keys())}

    print(f"[bulk-cron] Completado: {len(per_client_files)}/{len(clients)} clientes OK, "
          f"{len(failures)} fallidos, {len(consolidated)} archivos consolidados")
    if failures:
        print(f"[bulk-cron] Fallidos: {failures}")

    # Paso 3: alerta de reconciliación si hay pendientes
    if pending:
        send_reconciliation_alert(pending_count=len(pending), base_url=PUBLIC_BASE_URL)

    # Paso 4: export a Tableau Cloud (no aborta el pipeline si falla)
    if consolidated:
        try:
            print("[bulk-cron] Iniciando export a Tableau...")
            meetings = await fetch_all_meetings()
            tableau_result = await run_tableau_export(consolidated, meetings)
            for step, status in tableau_result.items():
                print(f"[tableau] {step}: {status}")
        except Exception as e:
            print(f"[tableau] ERROR en export: {e}")

    report.finish()
    report.save()
    return report


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    tasks = [
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
async def list_clients():
    """Lista de clientes Active con team_id desde Siete API."""
    clients = await fetch_active_clients()
    return [
        {"id": c["client_id"], "name": c["client_name"], "team_id": c["team_id"],
         "siete_id": c["siete_id"]}
        for c in clients
    ]


@app.get("/api/generate/{client_id}")
async def generate_report(client_id: str):
    """SSE: download reports for a single client (by slug)."""
    queue: asyncio.Queue = asyncio.Queue()

    async def run_pipeline():
        try:
            clients = await fetch_active_clients()
            client = next((c for c in clients if c["client_id"] == client_id), None)
            if not client:
                await queue.put({"type": "error",
                                 "message": f"Cliente '{client_id}' no encontrado o sin team_id en Siete"})
                return

            team_id = client["team_id"]
            display_name = client["client_name"]

            def on_progress(msg):
                queue.put_nowait({"type": "progress", "message": msg})

            on_progress("Conectando a Reply.io...")
            download_dir = DOWNLOAD_DIR / client_id
            headless = os.getenv("HEADLESS", "true").lower() != "false"
            reports = await download_reports(
                email=REPLY_IO_EMAIL, password=REPLY_IO_PASSWORD, team_id=team_id,
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
        raise HTTPException(status_code=404, detail="File not found")
    path = DOWNLOAD_DIR / client_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename, media_type="text/csv")


@app.get("/api/consolidated/{filename}")
def download_consolidated(filename: str):
    if "/" in filename or ".." in filename or not filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = DOWNLOAD_DIR / "consolidated" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path,
        filename=filename,
        media_type="text/csv",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/generate-bulk")
async def generate_bulk(limit: int = 0):
    """SSE: download active clients (all if limit=0, else first N) and consolidate."""
    queue: asyncio.Queue = asyncio.Queue()

    async def run_pipeline():
        try:
            clients = await fetch_active_clients()
            if limit > 0:
                clients = clients[:limit]
            if not clients:
                await queue.put({"type": "error", "message": "No hay clientes activos en Siete API"})
                return

            await queue.put({"type": "progress",
                             "message": f"Procesando {len(clients)} clientes activos (Siete API)"})

            # Pendientes para el aviso en el mensaje de Slack (filtrando descartados localmente)
            try:
                pending = await fetch_active_missing_team_id()
                discarded = discarded_clients.load()
                pending_count = sum(1 for p in pending if p["siete_id"] not in discarded)
            except Exception as e:
                print(f"[generate-bulk] Warning pendientes: {e}")
                pending_count = 0

            def emit(msg):
                queue.put_nowait(msg)

            per_client_files, failures, consolidated = await _run_bulk_pipeline(
                emit, clients, pending_count=pending_count,
            )

            if not per_client_files:
                await queue.put({"type": "error",
                                 "message": f"Ningún cliente OK. Errores: {failures}"})
                return

            done_msg = f"Listo. {len(per_client_files)}/{len(clients)} clientes consolidados."
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


@app.get("/api/test-slack")
def test_slack():
    """Diagnóstico: reporta qué env vars de Slack están seteadas y manda un mensaje de prueba."""
    from app.config import SLACK_BOT_TOKEN, SLACK_CHANNEL, SLACK_DESTINATIONS
    from app.processing.send_slack import _parse_destinations, _resolve_destination, _post_with_retry
    import httpx

    report: dict = {
        "SLACK_BOT_TOKEN_set": bool(SLACK_BOT_TOKEN),
        "SLACK_BOT_TOKEN_prefix": (SLACK_BOT_TOKEN or "")[:5] + "..." if SLACK_BOT_TOKEN else None,
        "SLACK_CHANNEL_set": bool(SLACK_CHANNEL),
        "SLACK_DESTINATIONS_set": bool(SLACK_DESTINATIONS),
        "parsed_destinations": _parse_destinations(),
    }
    if not SLACK_BOT_TOKEN:
        report["auth_test"] = "skipped: no SLACK_BOT_TOKEN"
        return report

    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}",
               "Content-Type": "application/json; charset=utf-8"}
    try:
        r = httpx.post("https://slack.com/api/auth.test", headers=headers, timeout=15)
        data = r.json()
        report["auth_test"] = {"ok": data.get("ok"), "team": data.get("team"),
                                "user": data.get("user"), "error": data.get("error")}
    except Exception as e:
        report["auth_test"] = {"error": str(e)}

    if not report["parsed_destinations"]:
        report["test_send"] = "skipped: no destinations"
        return report

    send_results = []
    for raw in report["parsed_destinations"]:
        ch = _resolve_destination(raw, headers)
        if not ch:
            send_results.append({"dest": raw, "status": "could_not_resolve"})
            continue
        try:
            _post_with_retry(ch, "[test-slack] ping desde data-check", headers, label=raw)
            send_results.append({"dest": raw, "channel": ch, "status": "sent"})
        except Exception as e:
            send_results.append({"dest": raw, "channel": ch, "status": "failed", "error": str(e)})
    report["test_send"] = send_results
    return report


@app.post("/api/send-today")
async def send_today():
    """Busca los CSVs consolidados de hoy (Perú) y los envía a Slack."""
    today = today_peru_iso()
    consolidated_dir = DOWNLOAD_DIR / "consolidated"

    found = {}
    for kind, prefix in [("people", "people_consolidated"), ("email_activity", "email_activity_consolidated")]:
        path = consolidated_dir / f"{prefix}_{today}.csv"
        if path.exists():
            found[kind] = path

    if not found:
        return {"error": f"No hay archivos consolidados para hoy ({today}) en {consolidated_dir}"}

    try:
        pending = await fetch_active_missing_team_id()
        discarded = discarded_clients.load()
        pending_count = sum(1 for p in pending if p["siete_id"] not in discarded)
    except Exception as e:
        print(f"[send-today] Warning pendientes: {e}")
        pending_count = 0

    xlsx_bytes: bytes | None = None
    try:
        from app.processing.tableau_exporter import generate_reuniones_xlsx
        meetings = await fetch_all_meetings()
        xlsx_bytes = generate_reuniones_xlsx(meetings)
    except Exception as e:
        print(f"[send-today] Warning: no se pudo generar xlsx de reuniones: {e}")

    try:
        send_consolidated_slack(found, pending_count=pending_count, xlsx_bytes=xlsx_bytes)
    except Exception as e:
        traceback.print_exc()
        return {
            "sent": False,
            "files": [p.name for p in found.values()],
            "date": today,
            "slack_error": str(e),
        }

    return {
        "sent": True,
        "files": [p.name for p in found.values()],
        "date": today,
    }


@app.post("/api/upload-tflx")
async def upload_tflx(file: UploadFile = File(...)):
    """Sube el .tflx al servidor y lo guarda en TFLX_PATH.

    Uso:
        curl -X POST https://data-check.wearesiete.com/api/upload-tflx \\
             -F "file=@/ruta/local/flujo.tflx"
    """
    dest = Path(TFLX_PATH) if TFLX_PATH else DOWNLOAD_DIR / file.filename
    dest.parent.mkdir(parents=True, exist_ok=True)

    data = await file.read()

    # Validar que sea un ZIP válido (los .tflx son ZIPs)
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise HTTPException(status_code=400, detail="El archivo no es un .tflx válido (no es un ZIP)")

    dest.write_bytes(data)
    return {"saved_to": str(dest), "size_mb": round(len(data) / 1024 / 1024, 1)}


@app.post("/api/export-tableau")
async def export_tableau():
    """Genera los 3 archivos Tableau, actualiza el .tflx y publica a Tableau Cloud.

    Usa los CSVs consolidados del día (hora Perú) que ya existan en disco.
    No re-descarga Reply.io — requiere haber corrido /api/generate-bulk primero.
    """
    today = today_peru_iso()
    consolidated_dir = DOWNLOAD_DIR / "consolidated"

    found: dict[str, Path] = {}
    for kind, prefix in [("people", "people_consolidated"), ("email_activity", "email_activity_consolidated")]:
        path = consolidated_dir / f"{prefix}_{today}.csv"
        if path.exists():
            found[kind] = path

    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"No hay CSVs consolidados para hoy ({today}). Correr /api/generate-bulk primero.",
        )

    try:
        meetings = await fetch_all_meetings()
    except Exception as e:
        traceback.print_exc()
        # Generamos los CSVs igual aunque REUNIONES falle
        meetings = []
        reuniones_error = str(e)
    else:
        reuniones_error = None

    try:
        result = await run_tableau_export(found, meetings)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    if reuniones_error:
        result["reuniones_fetch"] = f"error: {reuniones_error}"

    return {
        "date": today,
        "csvs_found": list(found.keys()),
        "meetings_fetched": len(meetings),
        "steps": result,
    }


@app.get("/api/diagnostics")
async def diagnostics():
    """Diagnóstico del pipeline: env vars, Siete API, CSVs de hoy, último cron run."""
    from app.config import (
        SLACK_BOT_TOKEN, SLACK_CHANNEL, SLACK_DESTINATIONS,
        SIETE_API_KEY, REPLY_IO_EMAIL, REPLY_IO_PASSWORD,
    )
    from app.siete_api import _fetch_all_clientes

    env_state = {
        "SLACK_BOT_TOKEN": bool(SLACK_BOT_TOKEN),
        "SLACK_DESTINATIONS": bool(SLACK_DESTINATIONS),
        "SLACK_CHANNEL": bool(SLACK_CHANNEL),
        "SIETE_API_KEY": bool(SIETE_API_KEY),
        "REPLY_IO_EMAIL": bool(REPLY_IO_EMAIL),
        "REPLY_IO_PASSWORD": bool(REPLY_IO_PASSWORD),
        "PUBLIC_BASE_URL": PUBLIC_BASE_URL,
    }

    # Siete API health
    siete_state: dict = {"reachable": False}
    try:
        data = await _fetch_all_clientes()
        siete_state["reachable"] = True
        siete_state["total"] = len(data)
        by_status: dict[str, int] = {}
        active_with_team = 0
        active_missing: list[dict] = []
        for c in data:
            st = c.get("status") or "None"
            by_status[st] = by_status.get(st, 0) + 1
            if c.get("status") == "Active":
                if c.get("team_id"):
                    active_with_team += 1
                else:
                    active_missing.append({"siete_id": c["id"], "siete_name": c["cliente"]})
        siete_state["by_status"] = by_status
        siete_state["active_with_team_id"] = active_with_team
        siete_state["active_missing_team_id"] = active_missing
    except Exception as e:
        siete_state["error"] = f"{type(e).__name__}: {e}"

    # Consolidated CSVs of today (Peru)
    today = today_peru_iso()
    consolidated_dir = DOWNLOAD_DIR / "consolidated"
    consolidated_today: dict[str, dict] = {}
    for kind, prefix in [("people", "people_consolidated"),
                         ("email_activity", "email_activity_consolidated")]:
        path = consolidated_dir / f"{prefix}_{today}.csv"
        if path.exists():
            consolidated_today[kind] = {
                "exists": True,
                "size_mb": round(path.stat().st_size / 1024 / 1024, 2),
                "name": path.name,
            }
        else:
            consolidated_today[kind] = {"exists": False, "size_mb": None, "name": None}

    return {
        "today_peru": today,
        "env": env_state,
        "siete_api": siete_state,
        "consolidated_today": consolidated_today,
        "last_cron_run": load_last_cron_run(),
    }


@app.get("/api/reconciliation/pending")
async def reconciliation_pending():
    """Lista los clientes Active en Siete sin team_id (filtrando descartados localmente)
    + sugerencias de Reply.io."""
    siete_pending = await fetch_active_missing_team_id()
    discarded = discarded_clients.load()
    siete_pending = [p for p in siete_pending if p["siete_id"] not in discarded]
    if not siete_pending:
        return {"pending": [], "reply_options": [], "scrape_error": None}
    reply_workspaces = await fetch_reply_workspaces_live()  # None si falla
    return build_pending_payload(siete_pending, reply_workspaces)


@app.post("/api/reconciliation/discard")
async def reconciliation_discard(body: dict):
    """Agrega un siete_id a la lista local de descartados (idempotente).
    NO toca Siete API.
    """
    siete_id = body.get("siete_id")
    if not isinstance(siete_id, int) or siete_id <= 0:
        return JSONResponse(status_code=400, content={"error": f"siete_id inválido: {siete_id!r}"})
    discarded_clients.add(siete_id)
    return {"discarded": True, "siete_id": siete_id}


@app.post("/api/reconciliation/restore")
async def reconciliation_restore(body: dict):
    """Quita un siete_id de la lista local de descartados (idempotente)."""
    siete_id = body.get("siete_id")
    if not isinstance(siete_id, int) or siete_id <= 0:
        return JSONResponse(status_code=400, content={"error": f"siete_id inválido: {siete_id!r}"})
    discarded_clients.remove(siete_id)
    return {"restored": True, "siete_id": siete_id}


@app.get("/api/reconciliation/discarded")
async def reconciliation_discarded():
    """Lista los clientes descartados localmente resolviendo nombre vía Siete API.

    Si un id descartado ya no existe en Siete, se omite del response
    (pero NO se borra del archivo — eso lo hace el operador con restore).
    """
    ids = discarded_clients.load()
    if not ids:
        return {"discarded": []}
    try:
        data = await _fetch_all_clientes()
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": f"siete_api: {type(e).__name__}: {e}"})
    by_id = {c["id"]: c for c in data}
    out = []
    for sid in sorted(ids):
        c = by_id.get(sid)
        if not c:
            continue
        out.append({
            "siete_id": sid,
            "siete_name": c.get("cliente"),
            "siete_slug": _slug(c.get("cliente") or ""),
            "status": c.get("status"),
            "team_id": c.get("team_id"),
        })
    return {"discarded": out}


@app.get("/api/clients/mapping")
async def clients_mapping():
    """Devuelve el mapeo completo de clientes Siete con match contra workspaces Reply.io."""
    try:
        siete_clients = await _fetch_all_clientes()
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": f"siete_api: {type(e).__name__}: {e}"})
    reply_workspaces = await fetch_reply_workspaces_live()  # None si falla
    return build_mapping_payload(siete_clients, reply_workspaces)


@app.patch("/api/clients/{siete_id}/team-id")
async def patch_client_team_id(siete_id: int, body: dict):
    """Actualiza el team_id de un cliente en Siete. Acepta `null` para desvincular.

    Body: {"team_id": int | null}
    """
    if "team_id" not in body:
        return JSONResponse(status_code=400, content={"error": "falta campo 'team_id'"})
    team_id = body["team_id"]
    if team_id is not None and (not isinstance(team_id, int) or team_id <= 0):
        return JSONResponse(
            status_code=400,
            content={"error": f"team_id inválido: {team_id!r} (debe ser int > 0 o null)"},
        )
    try:
        updated = await patch_team_id(siete_id=siete_id, team_id=team_id)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"{type(e).__name__}: {e}"})
    return updated


@app.post("/api/reconciliation/save")
async def reconciliation_save(items: list[dict]):
    """Guarda los matches en Siete API vía PATCH.

    Body: [{"siete_id": int, "team_id": int}, ...]
    """
    saved = []
    errors = []
    for item in items:
        siete_id = item.get("siete_id")
        team_id = item.get("team_id")
        if not isinstance(siete_id, int) or not isinstance(team_id, int) or team_id <= 0:
            errors.append({
                "siete_id": siete_id,
                "reason": f"invalid input: siete_id={siete_id!r}, team_id={team_id!r}",
            })
            continue
        try:
            updated = await patch_team_id(siete_id=siete_id, team_id=team_id)
            saved.append({"siete_id": siete_id, "team_id": team_id, "client_name": updated.get("cliente")})
        except Exception as e:
            errors.append({"siete_id": siete_id, "reason": f"{type(e).__name__}: {e}"})
    return {"saved": saved, "errors": errors}


@app.post("/api/sync-clients")
async def sync_clients_gone():
    """Legacy endpoint: clients.json was eliminated; Siete API is the source of truth."""
    return JSONResponse(
        status_code=410,
        content={"error": "Removed: clients.json was eliminated. Use /reconciliation to add team_ids to Siete."},
    )


@app.get("/api/last-run")
def last_run():
    """Estado del último pipeline: todos los clientes con su resultado (OK/FAILED)."""
    import json as _json
    summary_path = DOWNLOAD_DIR / "last_run_summary.json"
    if not summary_path.exists():
        return JSONResponse(status_code=404, content={"error": "No hay resumen de corrida anterior"})
    return _json.loads(summary_path.read_text())


@app.get("/api/client-stats")
def client_stats():
    """Conteo de filas por cliente en los CSVs consolidados más recientes."""
    import pandas as pd

    consolidated_dir = DOWNLOAD_DIR / "consolidated"
    result: dict = {"date": None, "clients": []}

    def _latest(prefix: str):
        files = sorted(consolidated_dir.glob(f"{prefix}_*.csv"), reverse=True)
        return files[0] if files else None

    people_path = _latest("people_consolidated")
    email_path  = _latest("email_activity_consolidated")

    if not people_path and not email_path:
        return JSONResponse(status_code=404, content={"error": "No hay CSVs consolidados"})

    if people_path:
        stem = people_path.stem
        result["date"] = stem.split("_")[-1]

    people_counts: dict = {}
    email_counts:  dict = {}

    if people_path:
        df = pd.read_csv(people_path, usecols=["client_name"], low_memory=False)
        people_counts = df["client_name"].value_counts().to_dict()

    if email_path:
        df = pd.read_csv(email_path, usecols=["client_name"], low_memory=False)
        email_counts = df["client_name"].value_counts().to_dict()

    all_clients = sorted(set(people_counts) | set(email_counts))
    result["clients"] = [
        {
            "name": c,
            "people": people_counts.get(c, 0),
            "email_activity": email_counts.get(c, 0),
        }
        for c in all_clients
    ]
    return result


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
