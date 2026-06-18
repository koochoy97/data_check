"""Genera los 3 archivos para Tableau Prep, actualiza el .tflx y publica a Tableau Cloud."""
import io
import os
import zipfile
from pathlib import Path

import pandas as pd

from app.config import (
    TFLX_PATH,
    TABLEAU_SERVER_URL,
    TABLEAU_SITE_ID,
    TABLEAU_PAT_NAME,
    TABLEAU_PAT_SECRET,
)

# ── Schemas exactos para Tableau Prep ────────────────────────────────────────

PEOPLE_COLUMNS = [
    "client_id", "client_name",
    "First Name", "Last Name", "Email", "Title", "Phone", "City", "State",
    "Country", "Account Name", "TimeZone", "Added On", "Last Touch",
    "Sequence", "Status", "Opted Out", "InboxCategory", "LinkedIn",
    "Company size", "Industry", "SalesNavigator", "Opens", "Views",
    "Deliveries", "Replies", "Bounces", "CurrentStepStatus", "MeetingBooked",
    "CurrentStep", "CallResolution", "MeetingIntent", "Owner", "Provider",
    "Replies_by_sms", "Replies_by_LinkedIn", "Domain", "ValidationStatus",
    "Will Start At", "Subject 1", "Cuerpo 1", "Subject 2", "Cuerpo 2",
    "Subject 3", "Cuerpo 3", "Subject 4", "Cuerpo 4", "Account Name Subject",
]

EMAIL_COLUMNS = [
    "client_id", "client_name",
    "Contact Id", "Contact First name", "Contact Last name", "Contact email",
    "Contact country", "Contact company", "Contact industry",
    "Contact company size", "Email account", "Sequence", "Sequence step",
    "Subject", "Template", "Contacted", "Do not contact", "Delivered",
    "Delivery date", "Opened", "Opens", "Replied", "Interested",
    "Not interested", "Not now", "OptedOut", "Bounced", "AutoReplied",
    "Forwarded", "OutOfOffice", "Active", "Paused", "Clicked", "Unsorted",
    "Subject 1", "Cuerpo 1", "Subject 2", "Cuerpo 2", "Subject 3", "Cuerpo 3",
    "Subject 4", "Cuerpo 4", "Account Name Subject",
]

REUNIONES_COLUMNS = [
    "company", "client", "celebration_date", "status", "kdm", "kdm_title",
    "industry", "employers_quantity", "score", "feedback", "created_at",
    "updated_at", "client_id", "id", "lineas_negocio_ids", "company_linkedin",
    "person_linkedin", "web_url", "comments", "ae_mails", "archived",
    "kdm_mail", "telefono_cliente", "categoria_llamada", "icp_id",
    "prospection_source", "deal_status",
]

# Rutas internas en el .tflx (UUID fijos del flujo)
TFLX_DYNAMIC_PATHS = {
    "Data/2be547a9-184e-4873-ade9-5ef6eb6c497a/people_consolidated.csv": "people",
    "Data/e58741f8-9e3e-453f-9d34-abdfb53b12ea/email_activity_consolidated.csv": "email_activity",
    "Data/0301d819-1742-464e-b9f2-f4916732f15d/REUNIONES_GLOBAL.xlsx": "reuniones",
}


# ── Funciones de generación ───────────────────────────────────────────────────

def enforce_schema(src_csv: Path, columns: list[str]) -> bytes:
    """Lee un CSV consolidado, reindexar a las columnas exactas, devuelve bytes."""
    df = pd.read_csv(src_csv, low_memory=False)
    df = df.reindex(columns=columns, fill_value="")
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def generate_reuniones_xlsx(meetings: list[dict]) -> bytes:
    """Genera el XLSX de reuniones con hoja 'Datos' y 27 columnas exactas."""
    df = pd.DataFrame(meetings, columns=REUNIONES_COLUMNS)

    # Tipos de fecha/datetime
    df["celebration_date"] = pd.to_datetime(df["celebration_date"], errors="coerce")
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["updated_at"] = pd.to_datetime(df["updated_at"], errors="coerce")

    # Strings vacíos → NaN
    df = df.replace("", None)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Datos", index=False)
    return buf.getvalue()


def update_tflx(tflx_path: Path, replacements: dict[str, bytes]) -> None:
    """Reemplaza los archivos dinámicos en el .tflx (ZIP) usando escritura atómica."""
    tmp_path = tflx_path.with_suffix(".tflx.tmp")
    try:
        with zipfile.ZipFile(tflx_path, "r") as zin, \
             zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename in replacements:
                    zout.writestr(item, replacements[item.filename])
                else:
                    zout.writestr(item, zin.read(item.filename))
        os.replace(tmp_path, tflx_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def publish_to_tableau(tflx_path: Path) -> dict:
    """Publica el .tflx a Tableau Cloud vía TSC y dispara el run del flujo."""
    if not all([TABLEAU_SERVER_URL, TABLEAU_PAT_NAME, TABLEAU_PAT_SECRET]):
        return {"published": False, "job_id": None, "error": "Tableau Cloud no configurado (faltan env vars)"}

    try:
        import tableauserverclient as TSC
    except ImportError:
        return {"published": False, "job_id": None, "error": "tableauserverclient no instalado"}

    try:
        server = TSC.Server(TABLEAU_SERVER_URL, use_server_version=True)
        auth = TSC.PersonalAccessTokenAuth(TABLEAU_PAT_NAME, TABLEAU_PAT_SECRET, TABLEAU_SITE_ID)
        with server.auth.sign_in(auth):
            # Publicar con overwrite
            flow_item = TSC.FlowItem(project_id=None)
            flow_item, _ = server.flows.publish(
                flow_item,
                str(tflx_path),
                TSC.Server.PublishMode.Overwrite,
            )
            # Disparar el run
            job = server.flows.run(flow_item)
            job_id = job.id if hasattr(job, "id") else str(job)
            return {"published": True, "job_id": job_id, "error": None}
    except Exception as e:
        return {"published": False, "job_id": None, "error": str(e)}


# ── Orquestador principal ─────────────────────────────────────────────────────

async def run_tableau_export(
    consolidated: dict[str, Path],
    meetings: list[dict],
) -> dict:
    """
    Orquesta el export completo a Tableau:
      1. enforce_schema en people y email_activity CSVs
      2. generate_reuniones_xlsx
      3. update_tflx
      4. publish_to_tableau

    Args:
        consolidated: {"people": Path, "email_activity": Path} — salida del consolidador
        meetings: lista de dicts de fetch_all_meetings()

    Returns: dict con status de cada paso
    """
    result: dict = {
        "people_schema": None,
        "email_schema": None,
        "reuniones_xlsx": None,
        "tflx_update": None,
        "tableau_publish": None,
    }

    if not TFLX_PATH:
        result["tflx_update"] = "skipped: TFLX_PATH no configurado"
        result["tableau_publish"] = "skipped: TFLX_PATH no configurado"
        return result

    tflx_path = Path(TFLX_PATH)
    if not tflx_path.exists():
        result["tflx_update"] = f"error: .tflx no encontrado en {tflx_path}"
        result["tableau_publish"] = "skipped: .tflx no encontrado"
        return result

    replacements: dict[str, bytes] = {}

    # Paso 1: schema enforcement en CSVs
    people_path = consolidated.get("people")
    if people_path and Path(people_path).exists():
        try:
            replacements[_key("people")] = enforce_schema(people_path, PEOPLE_COLUMNS)
            result["people_schema"] = "ok"
        except Exception as e:
            result["people_schema"] = f"error: {e}"
    else:
        result["people_schema"] = "skipped: sin archivo de personas"

    email_path = consolidated.get("email_activity")
    if email_path and Path(email_path).exists():
        try:
            replacements[_key("email_activity")] = enforce_schema(email_path, EMAIL_COLUMNS)
            result["email_schema"] = "ok"
        except Exception as e:
            result["email_schema"] = f"error: {e}"
    else:
        result["email_schema"] = "skipped: sin archivo de actividad"

    # Paso 2: generar reuniones xlsx
    try:
        replacements[_key("reuniones")] = generate_reuniones_xlsx(meetings)
        result["reuniones_xlsx"] = f"ok ({len(meetings)} reuniones)"
    except Exception as e:
        result["reuniones_xlsx"] = f"error: {e}"

    if not replacements:
        result["tflx_update"] = "skipped: sin archivos para reemplazar"
        result["tableau_publish"] = "skipped"
        return result

    # Paso 3: actualizar .tflx
    try:
        update_tflx(tflx_path, replacements)
        result["tflx_update"] = "ok"
    except Exception as e:
        result["tflx_update"] = f"error: {e}"
        result["tableau_publish"] = "skipped: fallo el update del .tflx"
        return result

    # Paso 4: publicar a Tableau Cloud
    pub = publish_to_tableau(tflx_path)
    if pub["published"]:
        result["tableau_publish"] = f"ok (job_id={pub['job_id']})"
    else:
        result["tableau_publish"] = f"error: {pub['error']}"

    return result


def _key(name: str) -> str:
    """Devuelve la ruta interna del .tflx para el archivo dado."""
    return next(k for k, v in TFLX_DYNAMIC_PATHS.items() if v == name)
