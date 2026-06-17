## Context

El pipeline diario ya genera `REUNIONES_GLOBAL.xlsx` para el .tflx de Tableau via `generate_reuniones_xlsx()`. La función `send_consolidated_slack()` enviaba solo texto. La API antigua de Slack (`files.upload`) fue deprecada en 2024; la nueva requiere 3 pasos: obtener URL de upload, subir el contenido, completar y compartir.

## Goals / Non-Goals

**Goals:**
- Adjuntar `REUNIONES_GLOBAL.xlsx` fresco al mensaje diario de Slack
- Reutilizar `fetch_all_meetings()` y `generate_reuniones_xlsx()` ya existentes
- Upload best-effort: falla del xlsx no bloquea el mensaje de texto

**Non-Goals:**
- Cambiar el formato o contenido del xlsx
- Cachear el xlsx entre ejecuciones
- Soporte para otros tipos de adjuntos

## Decisions

**Nueva API de Slack (getUploadURLExternal)**
La API antigua `files.upload` está deprecada desde 2024. Se usa el flujo nuevo de 3 pasos. Alternativa descartada: mantener `files.upload` — funciona todavía pero Slack la eliminará eventualmente.

**Best-effort para el upload**
Si `fetch_all_meetings()` o el upload a Slack falla, el mensaje de texto se envía igual. El xlsx es información complementaria; una falla de Siete API no debe silenciar el reporte principal.

**Generación en main.py, no en send_slack.py**
`fetch_all_meetings()` es async; `send_consolidated_slack()` es sync. La generación se hace en los call sites en `main.py` antes de llamar a Slack, y se pasa `xlsx_bytes` como parámetro. Esto mantiene `send_slack.py` sin dependencias async.

## Risks / Trade-offs

- [Latencia] `fetch_all_meetings()` agrega ~2-5s al cron → aceptable, corre de madrugada
- [Cuota Slack] archivos xlsx grandes podrían acercarse al límite de storage del workspace → xlsx de reuniones es ~500KB, no es un problema en la práctica
