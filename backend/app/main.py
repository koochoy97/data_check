"""FastAPI backend with SSE for Reply.io report validation"""
import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from app.config import load_clients, REPLY_IO_EMAIL, REPLY_IO_PASSWORD, DOWNLOAD_DIR
from app.google_auth import get_gspread_client, get_sheets_service, get_drive_service
from app.scraper.reply_io import download_reports
from app.processing.carga_personas import procesar_carga
from app.processing.envio_correos import procesar_correos
from app.sheets.builder import crear_spreadsheet

app = FastAPI(title="Reply.io Report Validator")

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
        {"id": k, "name": v.get("display_name", k), "team_id": v["team_id"]}
        for k, v in clients.items()
    ]


@app.get("/api/generate/{client_id}")
async def generate_report(client_id: str):
    """SSE endpoint that streams progress while generating the report"""

    queue: asyncio.Queue = asyncio.Queue()

    async def run_pipeline():
        """Run the full pipeline, pushing progress messages to the queue."""
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

            def on_file(name, size, path):
                queue.put_nowait({"type": "file", "name": name, "size": size, "path": path})

            # Step 1: Download reports from Reply.io
            on_progress("Conectando a Reply.io...")
            download_dir = DOWNLOAD_DIR / client_id
            headless = os.getenv("HEADLESS", "true").lower() != "false"
            reports = await download_reports(
                email=email,
                password=password,
                team_id=team_id,
                download_dir=download_dir,
                on_progress=on_progress,
                headless=headless,
            )

            people_size = reports["personas"].stat().st_size
            on_progress(f"people.csv descargado ({people_size:,} bytes)")
            on_file("people.csv", people_size, f"/api/files/{client_id}/people.csv")

            email_size = reports["correos"].stat().st_size
            on_progress(f"email_activity.csv descargado ({email_size:,} bytes)")
            on_file("email_activity.csv", email_size, f"/api/files/{client_id}/email_activity.csv")

            # Step 2: Create Google Sheet
            on_progress("Creando Google Sheet...")
            gc = get_gspread_client()
            sheets_service = get_sheets_service()
            drive_service = get_drive_service()
            spreadsheet = crear_spreadsheet(display_name, gc, drive_service)
            on_progress("Google Sheet creado")

            # Step 3: Process People CSV
            on_progress("Inicio analisis people.csv...")
            result_personas = procesar_carga(
                csv_path=reports["personas"],
                spreadsheet=spreadsheet,
                service=sheets_service,
            )
            on_progress(f"Analisis people.csv exitoso — {result_personas['rows']} filas, {result_personas['pivots']} pivots")

            # Step 4: Process Email Activity CSV
            on_progress("Inicio analisis email_activity.csv...")
            result_correos = procesar_correos(
                csv_path=reports["correos"],
                spreadsheet=spreadsheet,
                service=sheets_service,
            )
            on_progress(f"Analisis email_activity.csv exitoso — {result_correos['rows']} filas, {result_correos['pivots']} pivots, {result_correos['reply_rate_sheets']} reply rates")

            # Step 5: Delete temp sheet
            try:
                temp_sheet = spreadsheet.worksheet("_temp")
                spreadsheet.del_worksheet(temp_sheet)
            except Exception:
                pass

            # Done
            await queue.put({
                "type": "done",
                "message": f"Listo! Reporte generado para {display_name}",
                "url": spreadsheet.url,
            })

        except Exception as e:
            import traceback
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
    """Download a generated CSV file"""
    allowed = {"people.csv", "email_activity.csv"}
    if filename not in allowed:
        return {"error": "File not found"}
    path = DOWNLOAD_DIR / client_id / filename
    if not path.exists():
        return {"error": "File not found"}
    return FileResponse(path, filename=filename, media_type="text/csv")


@app.get("/api/health")
def health():
    return {"status": "ok"}
