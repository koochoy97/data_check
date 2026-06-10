## Why

Hoy el flujo de reconciliación tiene tres puntos de fricción que hacen que clientes pendientes queden olvidados o que el operador no tenga visibilidad del estado real del mapeo Siete ↔ Reply.io:

1. **El mensaje diario a Slack** (donde los consumidores del reporte miran) no menciona que hay clientes pendientes de reconciliar. Existe `send_reconciliation_alert` pero solo va al canal de alertas operativas — la gente que recibe los CSVs no ve esa señal y no entra a `/reconciliation`.
2. **No hay forma de descartar un cliente** que aparece como pendiente pero que el equipo ya no quiere procesar (ejemplo concreto: Liberu aparece como Active sin team_id en Siete, pero el equipo ya no lo trabaja). Hoy o se completa el team_id o queda como pendiente para siempre.
3. **No hay vista del mapeo actual**. El operador no puede auditar qué team_id tiene cada cliente activo ni cambiar uno fuera del flujo de "pendientes". Para corregir un team_id mal asignado hay que ir a la app de Siete a mano.

Sin estas tres piezas, el operador termina ignorando alertas, los clientes "fantasma" se acumulan, y los errores de mapeo solo se descubren cuando explotan (como pasó con 7Graus).

## What Changes

- **Mensaje diario a Slack**: cuando hay clientes pendientes de reconciliar, `_build_message` agrega una línea final con conteo y link a `/reconciliation`. Cuando `pending_count == 0`, el mensaje queda idéntico a hoy. `send_consolidated_slack` y `_run_bulk_pipeline` propagan el conteo.
- **Descartar local**: nuevo concepto de "cliente descartado" — lista persistente de `siete_id`s que NO afecta a Siete API pero excluye al cliente de aparecer en `/api/reconciliation/pending`. Endpoints `POST /api/reconciliation/discard`, `POST /api/reconciliation/restore`, `GET /api/reconciliation/discarded`. UI: botón "Descartar" por fila pendiente + sección colapsable "Descartados" con "Restaurar".
- **Vista de mapeo actual**: nueva ruta (o tab) que lista TODOS los clientes Siete con `client_name`, `status`, `team_id`, `slug`, y matching contra workspaces Reply.io vivos. Cada fila permite editar el `team_id` en línea — al guardar hace PATCH a Siete. Reutiliza `patch_team_id`. Cubre el caso "vi un team_id mal asignado a Caleidos, quiero corregirlo sin esperar al próximo cron". También admite `team_id=null` para desvincular.
- **No-breaking**: ningún endpoint público existente cambia su contrato. Los nuevos endpoints son aditivos. La línea extra en el mensaje de Slack solo aparece cuando hay pendientes, así que el caso típico (cero pendientes) sigue igual.

## Capabilities

### New Capabilities
- `client-discard-local`: lista persistente de clientes Siete ignorados localmente (no toca Siete API), con CRUD y filtrado en el endpoint de pendientes.
- `client-mapping-view`: endpoint y UI que muestran el mapeo completo de clientes Siete ↔ workspaces Reply.io, con edición inline del team_id.

### Modified Capabilities
<!-- Las specs anteriores (report-delivery, client-registry, pipeline-observability) viven en otro change todavía no archivado (define-elt-pipeline). Para no acoplar este fix a esa migración, esta capability introduce las extensiones del mensaje de Slack como parte de client-discard-local (donde nace el conteo) en vez de modificar una capability inexistente en openspec/specs/. -->

## Impact

**Código afectado:**
- `backend/app/main.py` — 4 endpoints nuevos (`discard`, `restore`, `discarded`, `clients/mapping`, `clients/{id}/team-id`) + modificación de `/api/reconciliation/pending` para filtrar descartados + propagación de `pending_count` al consolidated Slack.
- `backend/app/processing/send_slack.py` — `_build_message` y `send_consolidated_slack` aceptan `pending_count`.
- `backend/app/discarded_clients.py` — nuevo módulo: load/save de la lista persistente (path análogo a `last_cron_run.json`, que vive en `DOWNLOAD_DIR / "discarded_clients.json"`).
- `backend/app/siete_api.py` — extender `patch_team_id` o agregar variante que permita `team_id=None` (desvincular).
- `backend/app/reconciliation.py` — exponer helper para filtrar pending por la lista de descartados (mantiene la lógica de matching donde ya vive).
- `frontend/src/App.jsx` — nueva ruta `/clients` o tab dentro de `/reconciliation`.
- `frontend/src/ReconciliationPage.jsx` — botones "Descartar" + sección "Descartados" + link a vista de mapeo.
- `frontend/src/ClientsMappingPage.jsx` — nuevo componente (tabla + edición inline).

**APIs externas:**
- Siete API: nuevo uso de `PATCH /core/clientes/{id}/` con `team_id=null` cuando se desvincula desde la vista de mapeo. Ya soporta `team_id=N`; falta validar que acepta `null` — si no, fallback a setear a 0 o documentar la limitación.
- Reply.io: la vista de mapeo invoca `fetch_reply_workspaces_live()` (ya existe). Costo: un scrape extra cuando se carga la vista. Aceptable porque es uso esporádico, no automático.
- Slack: la línea extra cuando hay pendientes va al destino habitual (`SLACK_DESTINATIONS`), no a un canal nuevo. Cero cambios de configuración.

**Persistencia:**
- `DOWNLOAD_DIR / "discarded_clients.json"`. Mismo path-pattern que `last_cron_run.json`. **Limitación conocida**: si `DOWNLOAD_DIR=/tmp/reports` y el contenedor se redeploya, se pierde — igual que `last_cron_run.json` hoy. Si esto duele, se aborda en un change separado de persistencia.

**Sin cambios:**
- El cron diario sigue ejecutándose igual; solo se entera del conteo de pendientes para pasarlo al mensaje.
- El flujo del scraper.
- La estructura de los CSVs consolidados.
- La función `send_reconciliation_alert` al canal de alertas operativas (se mantiene; el link en `send_consolidated_slack` es un canal complementario, no un reemplazo).
