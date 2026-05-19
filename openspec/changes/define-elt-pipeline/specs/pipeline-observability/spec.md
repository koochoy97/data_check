## ADDED Requirements

### Requirement: Endpoint de diagnóstico del pipeline
El sistema SHALL exponer `GET /api/diagnostics` que devuelve un JSON con el estado actual del pipeline, sin exponer secretos.

#### Scenario: Diagnóstico solicitado
- **WHEN** un operador hace `GET /api/diagnostics`
- **THEN** la respuesta es un JSON con la siguiente shape:
```
{
  "today_peru": "YYYY-MM-DD",
  "env": {
    "SLACK_BOT_TOKEN": bool,
    "SLACK_DESTINATIONS": bool,
    "SLACK_CHANNEL": bool,
    "SIETE_API_KEY": bool,
    "REPLY_IO_EMAIL": bool,
    "REPLY_IO_PASSWORD": bool,
    "PUBLIC_BASE_URL": "..."
  },
  "siete_api": {
    "total": N,
    "by_status": {"Active": N, "Churn": N, ...},
    "active_with_team_id": N,
    "active_missing_team_id": ["slug1", "slug2", ...]
  },
  "reply_io_cache": {
    "total": N,
    "last_modified": "ISO8601"
  },
  "consolidated_today": {
    "people":         {"exists": bool, "size_mb": float | null},
    "email_activity": {"exists": bool, "size_mb": float | null}
  },
  "last_cron_run": {
    "started_at":  "ISO8601" | null,
    "finished_at": "ISO8601" | null,
    "clients_processed": N,
    "failures": [{"slug": "...", "error": "..."}],
    "slack_delivery": {"sent_to": [...], "failed": [...]}
  }
}
```
- **AND** los valores `*_set` son booleanos (`true` si la env var está definida y no vacía); NO se exponen los valores literales

### Requirement: Endpoint de prueba de Slack
El sistema SHALL exponer `GET /api/test-slack` que valida el token y manda un ping de prueba a cada destino.

#### Scenario: Token válido y destinos configurados
- **WHEN** un operador hace `GET /api/test-slack`
- **THEN** la respuesta incluye `SLACK_BOT_TOKEN_set: true`, `auth_test: {ok: true, team: "...", user: "..."}`
- **AND** `test_send` es una lista con un item por destino: `{dest, channel, status: "sent"}` para éxito o `{dest, status: "failed", error: "..."}` para falla

#### Scenario: Token ausente
- **WHEN** `SLACK_BOT_TOKEN` no está seteado
- **THEN** la respuesta indica `SLACK_BOT_TOKEN_set: false`
- **AND** `auth_test: "skipped: no SLACK_BOT_TOKEN"`
- **AND** NO se manda ningún ping

### Requirement: Registro estructurado del último cron run
El sistema SHALL persistir el resultado de cada bulk-cron en `{DOWNLOAD_DIR}/last_cron_run.json` para que `/api/diagnostics` pueda leerlo.

#### Scenario: Cron termina exitosamente
- **WHEN** el bulk-cron termina (con o sin fallas parciales)
- **THEN** se escribe `last_cron_run.json` con `started_at`, `finished_at`, `clients_processed`, `failures`, `reconciliation` (clientes con team_id faltante / huérfanos) y `slack_delivery`

#### Scenario: Cron falla catastróficamente
- **WHEN** el bulk-cron levanta excepción antes de terminar (ej. Siete API caída)
- **THEN** se intenta escribir `last_cron_run.json` con `finished_at: null`, `error: "..."`
- **AND** si la escritura misma falla, el error se logea pero no se propaga

### Requirement: Alerta diaria de reconciliación al canal de alertas
El sistema SHALL enviar a `#automations_notifications` (canal `C093XM2UV9C`), AL FINAL del bulk-cron, un mensaje breve con el conteo de clientes pendientes de reconciliación y un link a la UI. El reporte principal (a `SLACK_DESTINATIONS`) NO SHALL incluir esta info.

#### Scenario: Hay clientes con team_id faltante
- **WHEN** el bulk-cron termina y hay N > 0 clientes Active en Siete con `team_id IS NULL`
- **THEN** se envía un mensaje al canal `C093XM2UV9C` con título `*⚠️ Reconciliación pendiente — {fecha}*`
- **AND** body: `"{N} clientes Active en Siete sin team_id. Resolvé en {PUBLIC_BASE_URL}/reconciliation"`
- **AND** NO se envía nada a `SLACK_DESTINATIONS` por este concepto

#### Scenario: No hay nada que reconciliar
- **WHEN** todos los clientes Active de Siete tienen `team_id`
- **THEN** NO se envía mensaje de reconciliación

### Requirement: Alerta de Siete API caída
El sistema SHALL enviar un mensaje crítico al canal `C093XM2UV9C` cuando el cron diario aborte por fallo de Siete API.

#### Scenario: fetch_active_clients levanta excepción
- **WHEN** el cron arranca y `fetch_active_clients()` retorna error (timeout, 5xx, conexión refused)
- **THEN** el cron aborta sin procesar
- **AND** envía a `C093XM2UV9C` con título `*🚨 Cron diario abortado — Siete API caída*`
- **AND** incluye en el body: error literal, timestamp UTC y URL del endpoint que falló
- **AND** marca `last_cron_run.json` con `error: "siete_api_down"`, `finished_at: null`

### Requirement: UI de reconciliación con dropdown Reply.io y PATCH a Siete
El sistema SHALL proveer una página web en `/reconciliation` que permita al operador asignar manualmente el `team_id` de un workspace Reply.io a clientes Siete con `team_id IS NULL`. El valor se guarda directamente en Siete API via PATCH; no hay persistencia local.

#### Scenario: Operador abre la página
- **WHEN** un operador navega a `{PUBLIC_BASE_URL}/reconciliation`
- **THEN** el frontend hace `GET /api/reconciliation/pending`
- **AND** el backend obtiene en paralelo: clientes Active sin team_id desde Siete, y workspaces desde Reply.io (scrape live)
- **AND** computa la sugerencia automática por slug-match
- **AND** retorna `[{siete_id, siete_name, suggested: {name, team_id, confidence}, reply_options: [...]}]`
- **AND** la UI muestra tabla con dropdown por fila, prellenado cuando `confidence == "exact"`

#### Scenario: Operador acepta sugerencias y guarda
- **WHEN** el operador hace click en "Guardar todos"
- **THEN** el frontend hace `POST /api/reconciliation/save` con `[{siete_id, team_id}, ...]`
- **AND** el backend valida que `team_id` sea int positivo
- **AND** por cada item hace `PATCH /core/clientes/{siete_id}/ {"team_id": N}` a Siete API
- **AND** la respuesta es `{"saved": N, "errors": [{"siete_id": ..., "reason": "..."}]}`
- **AND** la UI muestra confirmación y recarga la lista (debería quedar vacía si todo OK)

#### Scenario: Operador tipea team_id manualmente (escape hatch)
- **WHEN** Reply.io scrape falló o el cliente no aparece en el dropdown
- **THEN** la UI ofrece un input de texto para tipear `team_id` directamente
- **AND** el save funciona igual: PATCH a Siete con ese team_id

#### Scenario: PATCH a Siete falla
- **WHEN** Siete API devuelve error (404, 5xx) durante el PATCH
- **THEN** el item se incluye en `errors` con el `reason` del status code
- **AND** los otros items que sí guardaron correctamente NO se revierten
- **AND** la UI muestra los errores y permite reintentar

#### Scenario: Reply.io scrape falla pero hay clientes pendientes
- **WHEN** `fetch_reply_workspaces_live()` falla
- **THEN** `GET /api/reconciliation/pending` retorna `{"pending": [...], "reply_options": [], "scrape_error": "..."}`
- **AND** la UI muestra warning visible "Reply.io no respondió, no hay sugerencias"
- **AND** el operador puede usar el input manual

#### Scenario: No hay clientes pendientes
- **WHEN** `GET /api/reconciliation/pending` retorna pending vacío
- **THEN** la UI muestra mensaje "✅ Sin clientes pendientes de reconciliación"
- **AND** NO se ejecuta el scrape de Reply.io (optimización)

### Requirement: Logs del cron prefixados
El sistema SHALL prefijar los logs del cron diario con `[bulk-cron]`, `[scraper]`, `[consolidator]`, `[slack]`, `[reconcile]` según la etapa, sin duplicar líneas.

#### Scenario: Wrapper del cron y función interna NO ambos imprimen
- **WHEN** la función interna del scraper imprime `[scraper] people.csv descargado: N bytes`
- **THEN** el wrapper del cron NO repite la misma línea con prefijo `[bulk-cron]`
- **AND** cada evento aparece exactamente una vez en stdout
