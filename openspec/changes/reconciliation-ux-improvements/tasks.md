## 1. Módulo de descartados locales

- [x] 1.1 Crear `backend/app/discarded_clients.py` con: `load() -> set[int]`, `add(siete_id: int) -> None`, `remove(siete_id: int) -> None`, `path() -> Path`. Archivo: `DOWNLOAD_DIR / "discarded_clients.json"`. Estructura: `{"siete_ids": [int], "updated_at": iso8601}`. Si el archivo no existe o está corrupto, `load()` devuelve `set()` y loguea warning si estaba corrupto.
- [x] 1.2 `add` y `remove` MUST ser idempotentes (no fallan si el id ya está / no estaba).
- [x] 1.3 Cada escritura debe actualizar `updated_at` con `datetime.now(timezone.utc).isoformat()`.

## 2. Endpoints de descarte / restauración

- [x] 2.1 En `backend/app/main.py`, agregar `POST /api/reconciliation/discard` con body `{"siete_id": int}`. Valida que `siete_id` sea int positivo. Llama `discarded_clients.add(siete_id)`. Devuelve `{"discarded": True, "siete_id": int}`.
- [x] 2.2 Agregar `POST /api/reconciliation/restore` con body `{"siete_id": int}`. Análogo a discard pero llama `remove`. Devuelve `{"restored": True, "siete_id": int}`.
- [x] 2.3 Agregar `GET /api/reconciliation/discarded`. Llama `discarded_clients.load()`, fetch all clientes de Siete, devuelve solo los matching: `{"discarded": [{siete_id, siete_name, siete_slug, status, team_id}]}`. Si un id descartado ya no existe en Siete, lo omite del response (pero NO lo borra del archivo — eso lo hace el operador con restore).

## 3. Filtrado de pendientes y mapeo

- [x] 3.1 Modificar `GET /api/reconciliation/pending` en `backend/app/main.py`: después de `siete_pending = await fetch_active_missing_team_id()`, filtrar por la lista de descartados (`discarded = discarded_clients.load(); siete_pending = [p for p in siete_pending if p["siete_id"] not in discarded]`). Antes del scrape de Reply.io (corto-circuita si quedó vacío).
- [x] 3.2 No cambiar el formato del response: estructura existente se respeta.

## 4. Endpoint y módulo de mapeo completo

- [x] 4.1 Agregar `GET /api/clients/mapping` en `backend/app/main.py`. Hace en paralelo: `siete_api._fetch_all_clientes()` y `fetch_reply_workspaces_live()`. Arma response `{"clients": [{siete_id, siete_name, siete_slug, status, team_id, reply_match}], "scrape_error": str|null}`.
- [x] 4.2 `reply_match` es `{"name", "team_id"}` cuando hay un workspace cuyo team_id coincide con el `team_id` del cliente, o `null` en otro caso (incluyendo `team_id=None`).
- [x] 4.3 Si el scrape falla, devolver `scrape_error: "<msg>"` y `reply_match: null` para todos. Status HTTP 200.
- [x] 4.4 Lógica de matching: extraer una función `_build_mapping_payload(siete_clients, reply_workspaces)` en `backend/app/reconciliation.py` para mantener `main.py` limpio.

## 5. Endpoint de edición inline del team_id

- [x] 5.1 Extender `patch_team_id` en `backend/app/siete_api.py`: cambiar signature a `patch_team_id(siete_id: int, team_id: int | None)`. Si `team_id is None`, body es `{"team_id": None}` (httpx serializa como JSON null). Si es int, validar `> 0` como hoy.
- [x] 5.2 Agregar `PATCH /api/clients/{siete_id}/team-id` en `backend/app/main.py`. Body Pydantic-validable: `team_id: int | None`. Si recibe int <= 0 (excepto null), 400. Llama `patch_team_id`. Si Siete devuelve 4xx, propagar el mensaje en un 400 con `{"error": "<siete-msg>"}`.
- [x] 5.3 Validar manualmente en local (smoke test) que Siete acepta `{"team_id": null}` desvinculando. **Validado**: round-trip contra cliente "test" (siete_id=79) responde 200 OK al `PATCH {"team_id": null}` y persiste el valor null. No requiere ajustes.

## 6. Mensaje de Slack con link a reconciliación

- [x] 6.1 Modificar `_build_message` en `backend/app/processing/send_slack.py`: aceptar `pending_count: int = 0`. Si > 0, agregar línea final:
  `⚠️ Hay {N} cliente(s) pendiente(s) de reconciliar: <{PUBLIC_BASE_URL}/reconciliation|abrir reconciliación>`
- [x] 6.2 Modificar `send_consolidated_slack(consolidated, pending_count: int = 0)` para propagar el parámetro a `_build_message`.
- [x] 6.3 En `backend/app/main.py:_run_bulk_pipeline`, después del scrape ya hace `fetch_active_missing_team_id()`; reutilizar esa lista (no segundo fetch), aplicar el filtro de descartados, y pasar `pending_count=len(filtered)` a `send_consolidated_slack`. Si la pipeline corre desde la ruta `/api/send-today` u otro entrypoint que no calcula pendientes, hacer el fetch ahí también.

## 7. Frontend: descartar / restaurar en ReconciliationPage

- [x] 7.1 En `frontend/src/ReconciliationPage.jsx`, agregar botón "Descartar" en cada fila de pendientes. Al hacer click, abrir confirmación; al confirmar, llamar `POST /api/reconciliation/discard`. Tras éxito, remover la fila del DOM y refetch pendientes (para mantener conteos sincronizados).
- [x] 7.2 Agregar sección colapsable "Clientes descartados" debajo de pendientes. Al expandir, fetch `GET /api/reconciliation/discarded`. Cada item con botón "Restaurar" que llama `POST /api/reconciliation/restore`.
- [x] 7.3 Agregar link/botón "Ver mapeo completo →" en el header de la página, ruteado a `/clients`.

## 8. Frontend: vista de mapeo completo

- [x] 8.1 Crear `frontend/src/ClientsMappingPage.jsx` (estilo coherente con `ReconciliationPage`). Al montar, `GET /api/clients/mapping`.
- [x] 8.2 Mostrar tabla con columnas: Nombre, Status, team_id (input editable), Slug, Match Reply.io (texto: nombre del workspace o "—").
- [x] 8.3 Edición inline: el input de team_id muestra el valor actual. Al cambiar y hacer blur o presionar enter, llama `PATCH /api/clients/{siete_id}/team-id`. Muestra spinner durante request; muestra check verde si OK, mensaje rojo si error.
- [x] 8.4 Botón "Limpiar" (×) junto a cada input que envía `team_id=null` (con confirmación, porque desvincula).
- [x] 8.5 Link "← Volver a reconciliación" en el header.
- [x] 8.6 Agregar la ruta `/clients` en `frontend/src/App.jsx` apuntando al nuevo componente.

## 9. Build estático del frontend

- [x] 9.1 Correr `npm run build` (o equivalente) desde `frontend/` y verificar que el output va a `backend/static/` (o donde FastAPI sirve assets, ver `backend/app/main.py:597-599`).
- [x] 9.2 Verificar que las dos rutas (`/reconciliation` y `/clients`) cargan en local (con backend corriendo) sin errores.

## 10. Validación end-to-end en local

- [x] 10.1 Smoke test manual: arrancar backend + frontend en local. Verificar que `/reconciliation` muestra los pendientes filtrando los descartados.
- [x] 10.2 Descartar un cliente, verificar que desaparece de pendientes y aparece en "Descartados".
- [x] 10.3 Restaurarlo, verificar que vuelve a pendientes.
- [x] 10.4 Ir a `/clients`, editar el team_id de un cliente de prueba, verificar que el PATCH a Siete llegó (revisar con un GET a Siete o leer el row).
- [x] 10.5 Probar el endpoint `PATCH /api/clients/{id}/team-id` con `team_id=null`. Si Siete rechaza, ajustar el código de tarea 5.3.
- [x] 10.6 Disparar `/api/generate-bulk` (o el cron-once endpoint) con pendientes > 0 y verificar que el mensaje a Slack incluye la línea de reconciliación con el conteo correcto.

## 11. Deploy y observación

- [x] 11.1 Commit + push a main.
- [ ] 11.2 Confirmar deploy.
- [ ] 11.3 Validar próximo cron diario: el mensaje a Slack incluye la línea (si hay pendientes) y el operador puede entrar al link.

## 12. Archive

- [ ] 12.1 Una vez confirmado en producción, archivar el change con `/opsx:archive reconciliation-ux-improvements`.
