## 1. Slug normalization canónica (D5)

- [ ] 1.1 Crear `app/utils/slug.py` con función `slug(name: str) -> str` usando `re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")`
- [ ] 1.2 Migrar `siete_api.py` para usar la función compartida
- [ ] 1.3 Eliminar `_sync_workspaces` y `_daily_sync_cron` en `main.py` — ya no se mantiene `clients.json`
- [ ] 1.4 Test: `slug("Agencia Brocco") == slug("agencia_brocco") == "agencia_brocco"`
- [ ] 1.5 `git rm backend/clients.json` y agregar a `.gitignore`

## 2. Reconciliación con UI y PATCH a Siete (D1 + D9)

- [ ] 2.1 Crear `app/reconciliation.py` con: `fetch_reply_workspaces_live()` (mover lógica de `_sync_workspaces` pero retornar lista en memoria, no escribir archivo), `suggest_matches(siete_pending, reply_workspaces)`
- [ ] 2.2 Modificar `fetch_active_clients` para retornar tupla `(active_with_team_id, active_missing_team_id)` o agregar función separada `fetch_active_missing_team_id()`
- [ ] 2.3 Backend: `GET /api/reconciliation/pending` que obtiene pendientes Siete + scrape Reply.io en paralelo, computa sugerencias por slug-match, retorna shape definida en spec
- [ ] 2.4 Backend: `POST /api/reconciliation/save` que acepta `[{siete_id, team_id}, ...]`, valida (int positivo), hace PATCH a Siete por cada uno, agrega errores parciales sin abortar el resto, retorna `{saved, errors}`
- [ ] 2.5 Frontend: nuevo componente `ReconciliationPage.jsx` en `frontend/src/`
- [ ] 2.6 Frontend: routing simple (path `/reconciliation` con condicional sobre `window.location.pathname` o `react-router-dom`)
- [ ] 2.7 Frontend: tabla editable con dropdown por fila, prellenado cuando match exact
- [ ] 2.8 Frontend: input manual de texto como escape hatch cuando scrape falla o no hay sugerencia
- [ ] 2.9 Frontend: handler "Guardar todos" → POST → mostrar resultado (saved/errors) → recargar lista
- [ ] 2.10 Frontend: build → asegurar que `vite build` produce static que el FastAPI app sirve en `/reconciliation` (mismo patrón que home actual)
- [ ] 2.11 Backend: `GET /reconciliation` sirve el `index.html` del frontend (catch-all en main.py ya está, verificar que funciona)
- [ ] 2.12 Test integración: con Siete mock, simular pendientes + sugerencias + save → verificar PATCH calls

## 3. Fix retención y endpoint de descarga (D4)

- [ ] 3.1 Cambiar `/api/consolidated/{filename}` para devolver HTTP 404 real cuando el archivo no existe (hoy devuelve 200 con JSON)
- [ ] 3.2 Cambiar invalid filename a HTTP 400 (hoy devuelve 200 con JSON)
- [ ] 3.3 Documentar en README que tras un redeploy los archivos se pierden y `GET /api/generate-bulk` regenera (~40 min)

## 4. Timezone canónico Perú (D7)

- [ ] 4.1 Centralizar `PERU_UTC_OFFSET` en `app/utils/dates.py` con función `today_peru() -> date`
- [ ] 4.2 Migrar `_daily_bulk_cron`, `/api/send-today`, `/api/diagnostics`, consolidator a usar `today_peru()`
- [ ] 4.3 Test: con mock `datetime.now()` a las 04:30 UTC del día N, `today_peru()` devuelve `N-1`

## 5. Slack delivery — refinamientos (D6) y alertas operativas

- [ ] 5.1 Verificar que `send_consolidated_slack` ya levanta `RuntimeError` con lista de fallidos (ya implementado)
- [ ] 5.2 Verificar fallback `SLACK_DESTINATIONS` → `SLACK_CHANNEL` (ya implementado)
- [ ] 5.3 Test integración: simular 1 destino fallando y 2 OK → estado esperado
- [ ] 5.4 Nueva función `send_reconciliation_alert(N: int, base_url: str)` que envía mensaje breve al canal `C093XM2UV9C` solo si N > 0
- [ ] 5.5 Nueva función `send_siete_down_alert(error: str, endpoint: str)` que envía mensaje crítico al canal `C093XM2UV9C` cuando Siete API falla en el cron
- [ ] 5.6 Integrar ambas en `_daily_bulk_cron` (D3 y D10)

## 6. Observabilidad — endpoint /api/diagnostics (D8)

- [ ] 6.1 Implementar `GET /api/diagnostics`
- [ ] 6.2 `_diagnostics_env() -> dict[str, bool]` (booleans sin exponer valores)
- [ ] 6.3 `_diagnostics_siete() -> dict` que consulta Siete API y agrupa por status + lista `active_missing_team_id`
- [ ] 6.4 `_diagnostics_consolidated_today() -> dict` chequea existencia + size
- [ ] 6.5 `_load_last_cron_run() -> dict` que lee `{DOWNLOAD_DIR}/last_cron_run.json` o devuelve None
- [ ] 6.6 Test smoke con Siete mockeado

## 7. Registro del último cron run (D8)

- [ ] 7.1 Estructura `CronRunReport`: `started_at`, `finished_at`, `clients_processed`, `failures`, `reconciliation`, `slack_delivery`
- [ ] 7.2 Inicializar al inicio del cron, llenar progresivamente, escribir al final
- [ ] 7.3 Si escritura falla, loguear sin propagar (best-effort)

## 8. Logs sin duplicación

- [ ] 8.1 Identificar wrappers que imprimen con prefijo `[bulk-cron]` y eliminar duplicación con función interna
- [ ] 8.2 Estandarizar prefijos: `[bulk-cron]`, `[scraper]`, `[consolidator]`, `[slack]`, `[reconcile]`
- [ ] 8.3 Test manual: `GET /api/generate-bulk?limit=2` → cada evento aparece una sola vez

## 9. Documentación

- [ ] 9.1 README con sección "Env vars requeridas en producción" y cómo verificarlas via `/api/diagnostics`
- [ ] 9.2 Documentar flujo de regeneración post-redeploy
- [ ] 9.3 Documentar flujo de reconciliación: cuándo aparece la alerta, cómo usar `/reconciliation`

## 10. Validación final

- [ ] 10.1 Correr `openspec validate` y resolver cualquier issue
- [ ] 10.2 Dry-run del cron localmente con `limit=2`
- [ ] 10.3 Verificar `/api/diagnostics`, `/api/test-slack`, `/api/reconciliation/pending` en local
- [ ] 10.4 Deploy a prod, esperar siguiente cron diario, validar Slack + diagnóstico + UI
- [ ] 10.5 Resolver los 8 pendientes actuales desde la UI y verificar PATCH a Siete
- [ ] 10.6 Esperar al siguiente cron y confirmar que los 8 ahora se procesan
- [ ] 10.7 Archivar con `openspec archive define-elt-pipeline`
