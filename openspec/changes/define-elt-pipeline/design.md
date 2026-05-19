## Context

El pipeline existente fue creciendo por capas (scrape Reply.io → consolidar → email → Slack) sin un contrato explícito. Cada decisión implícita generó un punto de falla silencioso:

- **Dos sistemas de clientes coexistiendo**: `clients.json` (scrape Playwright) y Siete API — sin reglas claras de cuál manda.
- **Slug-collision invisible**: `agencia_brocco` (Reply.io) vs `brocco` (Siete) descartan el `display_name`.
- **`team_id` nulos en Siete**: 12 clientes Active no se procesan y nadie se entera.
- **`/tmp` volátil**: los CSVs publicados a Slack desaparecen al primer redeploy.
- **Modos de falla en cadena**: email 429 → cron muere → Slack tampoco se envía (ya parcheado).
- **Datos duplicados** (`clients.json` + `client_overrides.json` + Siete) sin reglas de reconciliación.

Stakeholders: Jaime (operador), Nicolas (consumidor de reportes en Slack), Siete CRM como sistema de verdad de clientes.

**Capacidades verificadas durante el spec:**
- `GET /core/clientes/?limit=500` (Siete API) — listado completo, ya en uso
- `PATCH /core/clientes/{row_id}/` — documentado en `/openapi.json`, probado 200 OK con body `{"team_id": N}`. Siete acepta escritura.

## Goals / Non-Goals

**Goals**
- **Siete API es la única fuente de verdad**, tanto para lectura como para escritura. No hay JSONs locales con datos canónicos de clientes.
- Slug-normalización determinista, una única función pública.
- Reconciliación manual via UI dedicada cuando Siete tiene `team_id NULL`. El operador resuelve con dropdown de workspaces Reply.io; el backend PATCHea Siete.
- Modos de falla independientes por destino Slack y por cliente.
- Alerta clara al canal de operaciones cuando: (a) Siete API se cae, (b) hay clientes pendientes de reconciliación.

**Non-Goals**
- Re-implementar el scraper Playwright (queda como está).
- Persistencia local de listas de clientes: `clients.json` y `client_overrides.json` **se eliminan**. El scrape de Reply.io se ejecuta on-demand cuando la UI lo pide.
- Persistencia durable de los CSVs consolidados: se mantiene `/tmp` volátil; regenerar bajo demanda.
- Métricas avanzadas (Prometheus). Solo logs estructurados + endpoint `/api/diagnostics`.

## Decisions

### D1 — Siete API es la única fuente de verdad (lectura + escritura)
**Decisión**: El cron diario lista clientes desde `GET /core/clientes/`. Para clientes con `team_id IS NULL`, el operador completa el dato vía UI; el backend hace `PATCH /core/clientes/{id}/ {"team_id": N}` a Siete. Reply.io aporta nombres y team_ids candidatos en el momento de la reconciliación, no como cache.

**Alternativas consideradas**: (a) Reply.io manda — pierde control desde CRM; (b) JSON local con overrides — duplica el estado, complicación innecesaria ya que Siete acepta PATCH.

### D2 — Filtro de status: SOLO `Active`
**Decisión**: `status == "Active"` AND `team_id IS NOT NULL`. Cualquier otro status (`Churn`, `archived`, `Pending`, `None`) se descarta **sin ventana de gracia** ni warning. Si el operador marcó Churn por error, lo arregla en Siete.

### D3 — Cliente Active sin team_id → registrar pendiente
**Decisión**: Si Siete lo marca `Active` pero `team_id IS NULL`:
1. El cron NO procesa el cliente.
2. Lo registra en `last_cron_run.json` bajo `reconciliation.missing_team_id`.
3. **Al final del cron**, envía un mensaje breve al canal `C093XM2UV9C` con el conteo y link a `/reconciliation`.
4. El operador resuelve via UI (D9). Backend hace PATCH a Siete. Próximo cron lo procesa normalmente.

### D4 — Retención: sin persistencia, regenerar bajo demanda
**Decisión**: `DOWNLOAD_DIR=/tmp/reports`. Tras redeploy los CSVs del día se pierden. Mitigación:
1. `/api/consolidated/<file>` devuelve **HTTP 404 real** cuando el archivo no existe (no 200 con JSON, que es el bug actual).
2. Documentar que `GET /api/generate-bulk` regenera todo en demanda (~40 min).
3. El operador puede correr `generate-bulk` y luego `POST /api/send-today` para re-enviar a Slack.

### D5 — Slug normalization unificado
**Decisión**: Una sola función pública `slug(name) -> str = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')`, usada en:
- `siete_api.fetch_active_clients()` (ya lo hace).
- Cualquier matching cross-source (al sugerir workspace Reply.io vs cliente Siete).

`clients.json` se elimina. `_sync_workspaces` también — su lógica se mueve a una función `fetch_reply_workspaces_live()` que se invoca solo cuando la UI lo pide.

### D6 — Slack delivery: multi-destino con fallas independientes
**Decisión** (ya implementado):
- `SLACK_DESTINATIONS` (coma-separada): emails (→ DM via `users.lookupByEmail`), `#canal`, IDs.
- Fallback a `SLACK_CHANNEL` si vacío.
- Cada destino independiente; un fallo no aborta los demás.
- Reintentos 3× con backoff 30/60/90s solo para errores transitorios.

### D7 — Timezone canónico Perú (UTC-5)
**Decisión**: Centralizar `today_peru() -> date` y usarla en cron, consolidador, endpoints. Cron diario a las 05:00 UTC = 00:00 Perú.

### D8 — Observabilidad mínima
**Decisión**: Endpoint `GET /api/diagnostics` que devuelve JSON con env vars seteadas (boolean), estado de Siete API, estado de CSVs del día, y resumen del `last_cron_run.json`. Mantener `/api/test-slack`.

### D9 — UI de reconciliación con dropdown Reply.io + PATCH a Siete
**Decisión**: Página nueva en el frontend React (`frontend/src/ReconciliationPage.jsx`) ruteada en `/reconciliation`. Flujo:

1. La UI hace `GET /api/reconciliation/pending`.
2. El backend hace en paralelo:
   - `GET /core/clientes/?limit=500` filtra Active con `team_id IS NULL`.
   - `fetch_reply_workspaces_live()` — scrape Playwright en tiempo real, devuelve `[{name, team_id}]`.
3. Por cada cliente pendiente, el backend calcula la mejor sugerencia con `slug()` y devuelve:
```
[{
  "siete_id": 42, "siete_name": "Muta", "siete_slug": "muta",
  "suggested": {"name": "Muta", "team_id": 474105, "confidence": "exact"},
  "reply_options": [{"name": "Muta", "team_id": 474105}, {"name": "Asasul", "team_id": 475246}, ...]
}, ...]
```
4. La UI muestra tabla:

| # | Cliente Siete | Reply.io workspace | Acción |
|---|---|---|---|
| 1 | Muta | `[Muta (474105) ▾]` (prellenado) | ✓ |
| 2 | Asasul | `[Asasul (475246) ▾]` | ✓ |
| 8 | FINNEGANS QUIPPOS | `[— elegir —]` | ⚠ sin sugerencia |

5. El operador acepta sugerencias y/o elige del dropdown.
6. Click "Guardar todos" → `POST /api/reconciliation/save` con `[{siete_id, team_id}, ...]`.
7. El backend hace, por cada item, `PATCH /core/clientes/{siete_id}/ {"team_id": N}` a Siete.
8. Responde `{"saved": N, "errors": [...]}`.
9. Próximo cron diario procesa esos clientes normalmente (sin pasos extra).

**Costo**: el scrape de Reply.io toma ~30s. Aceptable porque es una acción manual del operador.

**Trade-off**: si Reply.io scrape falla, la UI no puede ofrecer sugerencias y el operador no puede completar la reconciliación. **Mitigación**: la UI permite al operador tipear `team_id` manualmente (texto libre) como escape hatch, además del dropdown.

### D10 — Siete API caída → alerta + abort
**Decisión**: Si `fetch_active_clients()` levanta excepción:
1. El cron aborta sin procesar.
2. Envía mensaje crítico al canal `C093XM2UV9C` con título `*🚨 Cron diario abortado — Siete API caída*`.
3. Marca `last_cron_run.json` con `error: "siete_api_down"`, `finished_at: null`.

## Risks / Trade-offs

- **[Redeploy borra los CSVs del día]** → operador regenera con `generate-bulk`. Aceptado por D4.
- **[Reply.io cambia su UI y `fetch_reply_workspaces_live` rompe]** → la UI ofrece text-input para que el operador tipee `team_id` manualmente.
- **[Siete acepta PATCH a cualquier campo sin schema estricto]** (`additionalProperties: True`) → riesgo de tipear mal el body. **Mitigación**: el backend valida que solo se envíe `{"team_id": N}` con `N: int`.
- **[Reconciliación masiva]** Si hay 50 clientes pendientes, el operador puede tardar. **Mitigación**: el dropdown viene prellenado cuando hay match exacto; en la mayoría de casos es 1 click "Guardar todos".

## Migration Plan

1. **Deploy del backend** con: nuevo módulo `app/reconciliation.py`, endpoints `/api/reconciliation/{pending,save}`, `/api/diagnostics`, fix 404 en consolidated, eliminación de Gmail.
2. **Deploy del frontend** con la página `/reconciliation`.
3. **Verificar env vars en prod** vía `/api/test-slack` y `/api/diagnostics`.
4. **Borrar `clients.json` del repo** (`git rm`) — opcional, queda como histórico si no se borra, pero ya no se lee.
5. **Resolver pendientes en la UI** (los 8-12 clientes Active sin team_id de hoy).
6. **Esperar próximo cron** y validar que los pendientes ya se procesaron.

**Rollback**: revert del commit. `clients.json` sigue siendo válido como referencia si hay que volver al esquema anterior.

## Resolved Decisions

1. **Siete API caída** → alerta a `C093XM2UV9C` y abort (D10).
2. **Sin ventana de gracia para Churn** — se descartan inmediatamente.
3. **Reconciliación** → UI dedicada en `/reconciliation` con dropdown de workspaces Reply.io scrapeados live + PATCH a Siete (D9).
4. **Persistencia** → ninguna local. Siete es source of truth. `clients.json` y `client_overrides.json` se eliminan.
