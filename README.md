# elt_data_compliance — Reply.io Report Validator

Pipeline diario que descarga reportes de Reply.io de los clientes activos en
Siete CRM, los consolida en CSVs por día y los entrega a Slack.

## Arquitectura

- **Source of truth:** Siete API (`https://apirest.wearesiete.com/core/clientes/`).
- **Scraper:** Playwright que se loguea en Reply.io y descarga `people.csv` + `email_activity.csv` por workspace.
- **Consolidación:** `consolidator.py` merge en `people_consolidated_{YYYY-MM-DD}.csv` y `email_activity_consolidated_{YYYY-MM-DD}.csv` (fecha Perú, UTC-5).
- **Entrega:** Slack vía `chat.postMessage` a `SLACK_DESTINATIONS` (mix de emails, canales, IDs).

## Env vars requeridas

| Var | Para qué |
|---|---|
| `SIETE_API_KEY` (o `X-HEADER-SIETE-API`) | Auth contra Siete API |
| `SIETE_API_ENDPOINT` | Default `https://apirest.wearesiete.com` |
| `REPLY_IO_EMAIL` / `REPLY_IO_PASSWORD` | Login Playwright en Reply.io |
| `SLACK_BOT_TOKEN` | Bot user OAuth token (`xoxb-...`) |
| `SLACK_DESTINATIONS` | Lista separada por `,`. Items: emails (→ DM), `#canal`, IDs (`C…/D…/U…/G…`) |
| `SLACK_CHANNEL` | Fallback si `SLACK_DESTINATIONS` está vacío |
| `SLACK_ALERTS_CHANNEL` | Canal para alertas operativas (default `C093XM2UV9C` = `#automations_notifications`) |
| `PUBLIC_BASE_URL` | Para armar links absolutos en mensajes Slack (default `https://data-check.wearesiete.com`) |
| `DOWNLOAD_DIR` | Default `/tmp/reports`. Se borra en cada redeploy. |
| `HEADLESS` | `true` (default) o `false` para debugging local de Playwright |

### Verificar env vars en producción

```
GET /api/diagnostics    → reporta qué env vars están seteadas (booleans, sin exponer valores)
GET /api/test-slack     → valida token y manda un ping de prueba a cada destino
```

## Endpoints

| Endpoint | Descripción |
|---|---|
| `GET /api/clients` | Lista clientes Active con `team_id` desde Siete |
| `GET /api/generate/{client_id}` | SSE: descarga reportes de UN cliente |
| `GET /api/generate-bulk?limit=N` | SSE: descarga + consolida todos los activos (o primeros N) |
| `GET /api/consolidated/{filename}` | Descarga un CSV consolidado |
| `POST /api/send-today` | Reenvía el reporte de hoy a Slack |
| `GET /api/diagnostics` | Estado pipeline (env, Siete, CSVs, último cron run) |
| `GET /api/test-slack` | Diagnóstico Slack |
| `GET /api/reconciliation/pending` | Clientes Siete Active sin team_id + sugerencias Reply.io |
| `POST /api/reconciliation/save` | Body `[{siete_id, team_id}, ...]` → PATCH a Siete |
| `POST /api/sync-clients` | **Deprecated** (410 Gone) |
| `GET /reconciliation` | UI para resolver clientes sin team_id |

## Cron diario

Corre a las **00:00 hora Perú (05:00 UTC)**. Hace:

1. `GET /core/clientes/` → lista clientes Active con team_id.
   - Si Siete API falla → alerta crítica al canal `#automations_notifications` y aborta.
2. Recolecta clientes Active **sin** team_id → quedan en "pendientes de reconciliación".
3. Por cada cliente activo: scrape Reply.io → descarga personas + correos.
4. Consolida los CSVs.
5. Envía a Slack (`SLACK_DESTINATIONS`).
6. Si hay pendientes de reconciliación, envía mensaje breve al canal de alertas con link a `/reconciliation`.
7. Persiste el resultado en `{DOWNLOAD_DIR}/last_cron_run.json` (best-effort).

## Flujo de reconciliación

Algunos clientes están `Active` en Siete pero sin `team_id` cargado. El cron los salta. Para resolverlos:

1. Esperá la alerta diaria en `#automations_notifications`, o abrí `/reconciliation` directamente.
2. La UI muestra una tabla con cada cliente Siete pendiente.
3. Para cada uno, elegí del dropdown el workspace de Reply.io correspondiente (sugerencias automáticas por slug match), o tipeá el `team_id` manualmente.
4. Click "Guardar" → backend hace `PATCH /core/clientes/{id}/` a Siete API.
5. Al próximo cron, esos clientes ya entran al pipeline normal.

## Tras un redeploy

Los CSVs consolidados viven en `/tmp` y se pierden con cada restart del container. Para regenerar manualmente:

```
GET /api/generate-bulk     # ~40 minutos, SSE con progreso
POST /api/send-today       # reenvía a Slack (cuando ya están los CSVs)
```

## Especificación

El comportamiento del pipeline está formalizado en `openspec/specs/`. Para proponer cambios, usar:

```
openspec new change <kebab-case-name>
openspec validate <change-name>
```
