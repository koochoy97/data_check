## Why

El mensaje diario de Slack solo incluye links de descarga de los CSVs de Reply.io. Los datos de reuniones (REUNIONES_GLOBAL) no estaban disponibles sin acceder manualmente al sistema. Adjuntar el xlsx directamente en Slack da acceso inmediato a los datos de reuniones cada mañana.

## What Changes

- `send_consolidated_slack()` acepta nuevo parámetro `xlsx_bytes: bytes | None` y sube el archivo a cada destino si está presente
- Se agrega `_upload_file_to_channel()` en `send_slack.py` usando la API nueva de Slack (getUploadURLExternal + completeUploadExternal)
- En `main.py`, los dos call sites de `send_consolidated_slack` (cron diario y `/api/send-today`) generan el xlsx antes de llamar a Slack: `fetch_all_meetings()` → `generate_reuniones_xlsx()`
- El upload es best-effort: si falla, el mensaje de texto se envía igual

## Capabilities

### New Capabilities
- `slack-xlsx-upload`: Subida de archivos xlsx a Slack via API nueva (getUploadURLExternal → upload → completeUploadExternal), reutilizable para cualquier adjunto futuro

### Modified Capabilities
- `slack-daily-report`: El reporte diario ahora incluye adjunto xlsx además de los links de CSVs

## Impact

- `backend/app/processing/send_slack.py`: nueva función `_upload_file_to_channel`, firma modificada de `send_consolidated_slack`
- `backend/app/main.py`: dos call sites actualizados con fetch de reuniones + generación de xlsx
- Dependencia implícita en `generate_reuniones_xlsx` de `tableau_exporter.py` y `fetch_all_meetings` de `siete_api.py`
- Sin nuevas dependencias de paquetes (httpx ya está instalado)
