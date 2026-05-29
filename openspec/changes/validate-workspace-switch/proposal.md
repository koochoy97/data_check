## Why

El reporte consolidado del 28-05-2026 entregó **44,406 filas en email_activity y 8,049 en people bajo `client_id=7graus`** que en realidad pertenecían al workspace de Caleidos. Confirmamos por cruce de emails (100% overlap con caleidos) y por temática de las 35+ sequences (todas son campañas de Caleidos: AWS Perú/Chile/Ecuador, Monday Service, Monday TalentMatch, etc.) que **ninguna de esas filas corresponde a 7Graus**. La causa es que el workspace de 7graus probablemente fue eliminado o el bot fue desinvitado, y al hacer `goto https://run.reply.io/Home/SwitchTeam?teamId=463109` Reply.io responde **HTTP 403 con body `{"statusCode":403,"message":"You are not a member of specified team"}`** — pero el scraper no inspecciona el status code, asume que el switch funcionó y procede a exportar lo que haya en el workspace activo (Caleidos, procesado justo antes). El sistema es frágil ante cualquier workspace eliminado o acceso perdido y produce data corrupta sin alerta. Necesitamos hacerlo resistente para que la única alternativa al éxito sea un failure controlado, nunca un cliente con datos ajenos.

## What Changes

- Capturar la `Response` HTTP del `SwitchTeam` en `backend/app/scraper/reply_io.py` y abortar el procesamiento del cliente si no es 2xx (capa primaria de defensa contra 403/4xx/5xx).
- Agregar verificación post-switch que consulta `/Team/GetTeamData` y valida que el workspace activo en la sesión coincide con el `team_id` esperado (defensa secundaria contra fallas silenciosas: redirects raros, race conditions, cookies stale).
- Introducir excepción tipada `WorkspaceUnavailable` para distinguir fallas de acceso a workspace de errores genéricos. Cae en el bloque `except` existente del loop de clientes y se registra como failure normal — el siguiente cliente arranca con su propio switch limpio.
- Emitir alerta accionable a Slack cuando se detecta un workspace inaccesible, indicando nombre del cliente, `siete_id`, `team_id`, status code/mensaje recibido y sugerencia operativa ("Revisar si el cliente fue dado de baja o si hay que re-invitar al bot al workspace en Reply.io").
- **Garantía de invariante**: ningún export (people o email) se ejecuta sin que el workspace activo haya sido confirmado como el esperado. Si la validación falla, el cliente queda en `failures` y los CSVs consolidados no contienen filas espurias bajo ese `client_id`.

## Capabilities

### New Capabilities
- `workspace-switch-validation`: validación de que el cambio de workspace en Reply.io fue efectivo antes de disparar exports, con manejo de failure controlado y alerta operativa cuando un workspace es inaccesible.

### Modified Capabilities
<!-- report-extraction aún no está archivado en openspec/specs/, por eso esta funcionalidad se introduce como nueva capability autocontenida. -->

## Impact

**Código afectado:**
- `backend/app/scraper/reply_io.py` — nueva función `_switch_workspace(page, team_id, emit)` con doble validación + nueva excepción `WorkspaceUnavailable`. Reemplaza los dos call sites del `SwitchTeam` (líneas 276-282 en `download_all_reports` y 388-395 en `download_reports`).
- `backend/app/processing/send_slack.py` (o helper análogo) — nueva función para emitir alerta de workspace inaccesible. Reutiliza el cliente Slack y configuración existente.
- `backend/app/main.py` — ajustes mínimos para pasar `client_name` y `siete_id` al scraper de modo que la alerta a Slack pueda incluirlos (hoy el scraper solo recibe `client_id` y `team_id`).

**APIs externas:**
- Reply.io: nuevo consumo del endpoint interno `/Team/GetTeamData` (ya usado por la propia UI de Reply.io tras un SwitchTeam exitoso — observado en la prueba reproductora del bug, devuelve 200 con datos del team activo).
- Slack: un mensaje extra por cada workspace inaccesible detectado por run (esperado: ~0-1 por día en estado estable).

**Comportamiento del cron diario:**
- Antes: workspace eliminado → cliente afectado con data ajena en el CSV consolidado (silent corruption).
- Después: workspace eliminado → cliente en `failures` del reporte + alerta a Slack + CSVs consolidados limpios.

**Sin cambios:**
- `backend/app/processing/consolidator.py` (su inyección de `client_id`/`client_name` ya es correcta; el problema era upstream).
- `backend/app/siete_api.py` (la limpieza del status del cliente afectado es una acción operativa manual, fuera del scope del fix).
- Contratos públicos de la API HTTP, esquema de los CSVs, formato del reporte a Slack para los casos exitosos.
