## Context

El backend hoy expone dos endpoints relacionados con reconciliación:
- `GET /api/reconciliation/pending` ([main.py:547-554](backend/app/main.py#L547)) — fetch Siete + Reply.io en vivo + matching.
- `POST /api/reconciliation/save` ([main.py:557-579](backend/app/main.py#L557)) — PATCH `team_id` en Siete.

`fetch_active_missing_team_id()` en [siete_api.py:54-71](backend/app/siete_api.py#L54) filtra Siete por `status="Active"` AND `not team_id`. El frontend en `frontend/src/ReconciliationPage.jsx` consume los dos endpoints.

El reporte diario de Slack se arma en `_build_message` ([send_slack.py:111-122](backend/app/processing/send_slack.py#L111)) — pura concatenación de strings, sin estado externo. `send_consolidated_slack` es invocado desde `_run_bulk_pipeline` ([main.py:134](backend/app/main.py#L134)) sin parámetros opcionales.

La persistencia local sigue el patrón de `last_cron_run.json` ([cron_report.py:12-50](backend/app/cron_report.py#L12)): archivo JSON en `DOWNLOAD_DIR / "..."` con load/save sincronos best-effort. `DOWNLOAD_DIR=/tmp/reports` por defecto — no sobrevive a redeploys del contenedor, limitación conocida y aceptada para este change.

Constraints relevantes:
- No introducir DB ni dependencias nuevas (httpx/fastapi/dotenv ya están).
- Siete API es la única fuente de verdad para datos de clientes; el archivo de descartados es state local complementario, no autoritativo.
- Reply.io workspace scrape es ~30s y headless; aceptable bajo demanda, no en cada request.
- Stakeholder: operador (Jaime) que entra a `/reconciliation` desde Slack y resuelve manualmente.

## Goals / Non-Goals

**Goals:**
- Cero confusión sobre "qué cliente debería procesar mañana": los pendientes que aparecen son los que realmente requieren acción.
- Los consumidores del reporte diario en Slack se enteran de los pendientes en el mismo mensaje, no en un canal separado.
- El operador puede auditar y corregir cualquier mapeo Siete ↔ Reply.io sin abrir la app de Siete.
- Aditivo: nada de lo existente cambia de contrato. Frontend antiguo seguiría funcionando si solo desplegáramos el backend.

**Non-Goals:**
- No tocamos status de clientes en Siete desde el botón "Descartar" (decisión explícita del usuario).
- No agregamos persistencia durable a nivel infra (sigue siendo `/tmp/reports`).
- No agregamos bulk actions (descartar/restaurar varios a la vez).
- No agregamos auth — la app sigue confiando en que el operador tiene acceso al dominio.
- No agregamos cache del scrape de Reply.io entre requests — cada carga de la vista de mapeo dispara un scrape fresh (~30s).

## Decisions

### D1 — Descartar es state LOCAL, no cambia Siete
**Decisión**: Mantener `DOWNLOAD_DIR / "discarded_clients.json"` con `{"siete_ids": [int], "updated_at": iso8601}`. `fetch_active_missing_team_id_filtered()` (o un wrap en main.py) excluye esos ids antes de devolver.

**Rationale**: el usuario fue explícito — descartar no significa Churn. Quizás el cliente vuelva. Quizás Siete está mal y el dueño del CRM lo arreglará. La app no puede asumir qué quiso decir el operador al "descartar". Estado local separado evita side-effects en el CRM.

**Alternativas consideradas:**
- *PATCH `status=Churn` en Siete*: descartado — invade el CRM con una decisión técnica.
- *DB sqlite local*: descartado — overkill, agrega dependencia. La lista en JSON es chica y se lee una vez por request.

### D2 — Archivo JSON con merge en lectura (no mutaciones concurrentes)
**Decisión**: `discarded_clients.py` expone `load() -> set[int]`, `add(siete_id)`, `remove(siete_id)`. Cada operación lee, modifica, escribe el archivo completo. No file locking — el operador es uno solo a la vez y la prob. de colisión es despreciable.

**Alternativas consideradas:**
- *Append-only log*: overkill para 50 entries.
- *File lock con `fcntl`*: agrega complejidad para un caso que no va a pasar (single operator).

### D3 — Vista de mapeo: GET en vivo, sin cache
**Decisión**: `GET /api/clients/mapping` hace en paralelo `_fetch_all_clientes()` (Siete) + `fetch_reply_workspaces_live()` (scrape) y devuelve cada cliente Siete con: name, status, slug, team_id, reply_match (objeto con name/team_id si el team_id coincide con un workspace conocido, o `null`). Sin cache porque la vista se carga raramente y la verdad cambia: workspaces nuevos aparecen, team_ids se reasignan.

**Riesgo**: Reply.io scrape puede fallar. **Mitigación**: si falla, devolver `reply_workspaces: []` y `scrape_error: "<msg>"` igual que ya hace `build_pending_payload`. La UI muestra el mapeo sin la columna "match Reply.io" enriquecida pero sigue siendo útil.

**Alternativas consideradas:**
- *Cache de 10 min en memoria*: tentador pero introduce stale-vs-fresh confusion. Si vale la pena se mete después.

### D4 — Edición inline del team_id: PATCH directo + null permitido
**Decisión**: `PATCH /api/clients/{siete_id}/team-id` con body `{"team_id": int | null}`. Internamente llama `patch_team_id(siete_id, team_id)` extendido para aceptar `None`. Si Siete API no acepta `null` literal, fallback a `{"team_id": null}` JSON (httpx serializa Python `None` como JSON null) y manejamos el error.

**Por qué un endpoint nuevo y no extender `/api/reconciliation/save`**: ese endpoint recibe una lista, valida `team_id > 0`, y semánticamente representa "completar pendientes". Mezclar "editar/desvincular existente" en el mismo endpoint complica validación. Endpoint focused, single-resource, RESTful.

**Alternativas consideradas:**
- *Mantener un único `/api/reconciliation/save` con flag `allow_null`*: descartado, mata la claridad de uso.

### D5 — Mensaje de Slack: línea extra solo si pending > 0
**Decisión**: `_build_message(consolidated, pending_count=0)`. Si `pending_count > 0`:
```
*Reportes consolidados de Reply.io del {date}*

Links de descarga (válidos por 48h):
• <url1|file1> (X MB)
• <url2|file2> (Y MB)

⚠️ Hay {N} cliente(s) pendiente(s) de reconciliar: <{base_url}/reconciliation|abrir reconciliación>
```

Si `pending_count == 0`, no se agrega nada — mensaje idéntico a hoy.

**Por qué `pending_count` y no la lista completa**: el mensaje a Slack tiene que ser corto. Conteo + link respeta la jerarquía: "te aviso, mirá la UI para el detalle".

**Source of `pending_count`**: `_run_bulk_pipeline` ya consulta los pendientes (`fetch_active_missing_team_id`) para construir `report.reconciliation` ([main.py:182-188](backend/app/main.py#L182)). Reutiliza esa misma lista y pasa `len(filtered_pending)` a `send_consolidated_slack`. **Filtrado**: aplicar la lista de descartados ANTES de contar, para que coincida con lo que el operador ve en la UI.

### D6 — Frontend: nueva ruta `/clients` y tab dentro de `/reconciliation`
**Decisión**: agregar ruta `/clients` con el componente `ClientsMappingPage`. Desde `/reconciliation` un link/botón "Ver mapeo completo →" lleva a `/clients`. Inverso también: desde `/clients` un link "Volver a reconciliación".

Sección "Descartados" en `/reconciliation`: colapsable, debajo de pendientes. Cada item tiene "Restaurar".

**Alternativas consideradas:**
- *Tabs dentro de `/reconciliation`*: posible pero rompería el state actual de la página. Rutas separadas mantienen cada vista simple.

### D7 — `siete_api.patch_team_id` acepta `None` para team_id
**Decisión**: cambiar la firma a `patch_team_id(siete_id: int, team_id: int | None)`. Validación: si `team_id is None`, body es `{"team_id": None}` (serializado como JSON `null`). Si `team_id` es int, debe ser > 0.

**Verificación pendiente** (probar en local antes de mergear): que Siete API acepta `null` para desvincular. Si rechaza, fallback documentado en task de implementación.

## Risks / Trade-offs

- **[Riesgo] La lista de descartados se pierde en redeploy** → Mitigación: documentar la limitación. Si el equipo nota que descarta a Liberu hoy y mañana vuelve a aparecer, abrir un change separado para volcar `/tmp/reports` a un volumen persistente. No bloqueante.

- **[Riesgo] PATCH `team_id=null` no acepta de Siete API** → Mitigación: validar manualmente con un cliente de prueba antes de mergear el frontend; si rechaza, ofrecer solo "actualizar a otro team_id válido" (sin desvincular) y documentar la limitación.

- **[Riesgo] Race condition al editar el mismo `discarded_clients.json` desde dos requests concurrentes** → Mitigación: usar `Path.write_text` (atómico a nivel POSIX para tamaños chicos) y aceptar que la última escritura gana. Probabilidad de colisión: irrelevante con un operador.

- **[Trade-off] La vista de mapeo dispara scrape Reply.io en cada GET** → costo: ~30 segundos por carga. Aceptable porque la vista es de uso esporádico (auditar, no monitorear). Si crece el uso, agregar cache.

- **[Trade-off] El conteo de pendientes en Slack puede desfasarse si el operador descarta a alguien entre el cron y que ve el mensaje** → No es un bug: el mensaje refleja el estado al momento del cron. El operador entra al link y ve el estado real. Aceptable.

- **[Riesgo] El frontend nuevo (`ClientsMappingPage`) no se compila si no actualizamos el bundle estático que sirve FastAPI** → Mitigación: incluir en las tasks el build del frontend (`npm run build` o equivalente) y verificación de que los assets se sirven desde `backend/static/`.

## Migration Plan

1. Implementar backend: módulo `discarded_clients.py`, nuevos endpoints, extensión de `patch_team_id`. Tests rápidos contra Siete API en local.
2. Implementar frontend: actualizar `ReconciliationPage` con descartar/restaurar + link, agregar `ClientsMappingPage`. Build estático.
3. Probar en local con datos reales: descartar uno, ver que desaparece de pending; ir a mapeo, editar un team_id, confirmar PATCH llegó a Siete; correr cron-once manualmente y verificar el mensaje a Slack.
4. Merge a main → deploy.
5. Validar próximo cron diario: el mensaje incluye la línea extra (asumiendo pendientes en Siete).

**Rollback**: revertir el commit. Los endpoints nuevos desaparecen, el frontend viejo seguía funcionando con los endpoints viejos, el archivo `discarded_clients.json` queda en disco pero no se lee — sin efecto.

## Open Questions

- ¿La vista de mapeo debería mostrar también los workspaces de Reply.io que NO matchean ningún cliente Siete (workspaces huérfanos)? Útil para detectar workspaces creados sin cliente registrado. **Decisión actual**: no, fuera de scope (out of scope question 2 que el usuario eligió "edición inline" y no "huérfanos"). Documentado para revisión.
- ¿Conviene cachear el scrape de Reply.io con TTL? Diferido hasta que el uso lo justifique.
