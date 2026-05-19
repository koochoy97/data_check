## Why

El pipeline ELT actual (scrape Reply.io → consolidación → entrega) funciona pero está armado con decisiones implícitas que provocan **silencios y descartes inesperados** en producción. Hoy, de los 35 clientes que se procesan diariamente, 12 quedan fuera **sin alerta** porque Siete API no tiene su `team_id` cargado, 6 quedan con `display_name` vacío por mismatch de slugs entre Reply.io y Siete, y los reportes de hoy ni siquiera llegaron a Slack porque las env vars de producción no estaban verificadas. Necesitamos un spec explícito que defina la fuente de verdad de clientes, cómo se manejan los desfases, y cómo se entrega y observa el resultado — antes de seguir agregando integraciones.

## What Changes

- **BREAKING** — Unificar la fuente de verdad de clientes: definir explícitamente cuál de los dos sistemas (Reply.io vía scrape Playwright o Siete API) manda, y bajo qué reglas. Documentar la política de reconciliación entre ambos.
- Definir normalización de slug única (lower + `re.sub('[^a-z0-9]+','_')`) usada consistentemente entre ambas fuentes. Eliminar los 6 mismatches actuales (`agencia_brocco` vs `brocco`, etc.).
- Definir semántica de cada `status` de Siete (`Active`/`Churn`/`None`/`archived`/`Pending`) — cuáles se procesan, cuáles se ignoran, cuáles se reportan como warning.
- Definir comportamiento cuando hay un cliente en Reply.io pero **no** en Siete, y viceversa: hoy es un descarte silencioso, debe ser un warning observable.
- Definir comportamiento cuando un cliente está `Active` en Siete pero con `team_id NULL`: hoy se descarta silenciosamente; debe haber un mecanismo de reconciliación (auto-fill desde Reply.io o alerta).
- Definir política de retención de los CSVs consolidados (`/tmp/reports/...`): hoy se pierden en cada redeploy. Debe haber persistencia o regeneración automática.
- Definir contrato de entrega a Slack: multi-destinatario (`SLACK_DESTINATIONS`), formato del mensaje, comportamiento de fallback, manejo de fallas parciales (1 de N destinos falla).
- Definir timezone canónico (Perú UTC-5) para fechas de generación y nombres de archivo, y cómo se relaciona con el cron diario.
- Agregar capa de **observabilidad mínima**: endpoint `/api/diagnostics` que reporte (a) clientes esperados vs procesados hoy, (b) env vars críticas seteadas, (c) últimos errores del cron, (d) fecha del último run exitoso.
- Eliminar definitivamente la entrega por Gmail (ya implementado en el último commit, pero falta documentarlo en spec).

## Capabilities

### New Capabilities
- `client-registry`: Fuente de verdad de clientes, normalización de slug, reconciliación Reply.io ↔ Siete API, manejo de mismatches y team_id faltantes.
- `report-extraction`: Login + scrape por cliente desde Reply.io (Personas + Email Activity), con retries, paralelización y manejo de fallas parciales.
- `report-consolidation`: Merge de CSVs por cliente en archivos diarios consolidados, retención y disponibilidad vía endpoint público.
- `report-delivery`: Entrega de los reportes consolidados a múltiples destinatarios de Slack (canales/DMs por email/IDs), con reintentos y manejo de fallas independientes por destino.
- `pipeline-observability`: Endpoints de diagnóstico (`/api/diagnostics`, `/api/test-slack`) y formato estructurado de logs del cron diario.

### Modified Capabilities
<!-- No hay specs previos en openspec/specs — todo es greenfield -->

## Impact

**Código afectado:**
- `backend/app/main.py` — `_sync_workspaces`, `_daily_bulk_cron`, `/api/send-today`, `/api/sync-clients`, `/api/diagnostics` (nuevo)
- `backend/app/siete_api.py` — `fetch_active_clients` + nueva función de reconciliación o write-back
- `backend/app/scraper/reply_io.py` — `fetch_workspaces`, `download_reports`
- `backend/app/processing/consolidator.py` — política de retención
- `backend/app/processing/send_slack.py` — ya soporta multi-destino, falta especificar contrato
- `backend/clients.json` — pasará a ser cache local del scrape, no fuente de verdad

**APIs externas:**
- Siete API (`apirest.wearesiete.com/core/clientes/`) — solo lectura hoy; puede pasar a write si optamos por write-back de `team_id`.
- Reply.io — scraping Playwright (sin cambios de contrato).
- Slack `chat.postMessage`, `users.lookupByEmail` — sin cambios.

**Infraestructura:**
- Env vars críticas a documentar/verificar en prod: `SLACK_BOT_TOKEN`, `SLACK_DESTINATIONS`, `X-HEADER-SIETE-API`, `REPLY_IO_EMAIL`, `REPLY_IO_PASSWORD`, `GOOGLE_*`, `PUBLIC_BASE_URL`.
- Volumen persistente para `/tmp/reports` (decisión: persistir o auto-regenerar tras restart).

**Dependencias:**
- `httpx`, `playwright`, `gspread` (sin cambios).
- Posiblemente: agregar `prometheus_client` o similar si se decide instrumentación métrica (decisión abierta en `design.md`).
