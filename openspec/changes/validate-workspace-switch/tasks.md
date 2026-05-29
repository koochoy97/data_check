## 1. Excepción y función de switch validado

- [x] 1.1 En `backend/app/scraper/reply_io.py`, definir `class WorkspaceUnavailable(Exception)` cerca del top del archivo (después de `CHROMIUM_ARGS`).
- [x] 1.2 Implementar `async def _switch_workspace(page, team_id: int, emit, alert_context: dict | None = None) -> None` que ejecute la Capa 1 (validar status code de `page.goto(SwitchTeam_url)`).
- [x] 1.3 Extender `_switch_workspace` con la Capa 2: tras `await asyncio.sleep(3)`, llamar a `/Team/GetTeamData` vía `page.evaluate(fetch(...))` y validar que el `teamId`/`id`/`currentTeamId` coincide con `team_id`. Tolerar formas desconocidas con warning (no levantar).
- [x] 1.4 En el catch interno de Capa 2, si la verificación de tipo (`int(observed) != int(expected)`) detecta mismatch, levantar `WorkspaceUnavailable` con mensaje legible incluyendo ambos IDs.
- [x] 1.5 Si `alert_context` no es `None`, en el momento de levantar `WorkspaceUnavailable` invocar el helper de alerta Slack (ver sección 2) en un `try/except` que solo loguee fallas (no aborte).

## 2. Helper de alerta Slack

- [x] 2.1 En `backend/app/processing/send_slack.py` (o módulo análogo), agregar función `send_workspace_unavailable_alert(client_name: str, siete_id: int, team_id: int, reason: str) -> None` que arme el mensaje y lo envíe a los destinos configurados.
- [x] 2.2 El mensaje debe incluir: nombre del cliente (bold), `siete_id`, `team_id`, `reason` (status code y body extracto, o causa de mismatch de Capa 2), y línea final con sugerencia operativa ("Revisar si el cliente fue dado de baja o si hay que re-invitar al bot al workspace en Reply.io").
- [x] 2.3 Reutilizar el cliente Slack y la lógica multi-destino existente; envolver cada `send` en try/except y loguear fallas sin propagarlas.

## 3. Integración en los call sites del scraper

- [x] 3.1 En `download_all_reports` (`backend/app/scraper/reply_io.py:257-305`), reemplazar el bloque `await page.goto(SwitchTeam...)` + `await asyncio.sleep(8)` por una llamada a `await _switch_workspace(page, team_id, emit_client, alert_context={...})`, construyendo el `alert_context` con `client_id`, `client_name` y `siete_id` desde el dict `client`.
- [x] 3.2 Eliminar el `await asyncio.sleep(8)` original (la función nueva ya maneja sus propios sleeps de gracia).
- [x] 3.3 En `download_reports` (single-client, líneas 388-395), reemplazar el mismo patrón por la nueva función. Como esta variante no recibe `client_name`/`siete_id`, pasar `alert_context=None` o un dict con valores opcionales (no romper la firma del helper).
- [x] 3.4 Ajustar el bloque `except` (líneas 307-327) para que detecte `WorkspaceUnavailable` ANTES de la rama de crashes y la trate sin recycle ni reintentos: registrar el cliente en `results[cid] = {"error": str(e)}` y hacer `break` del while.

## 4. Propagar metadatos al scraper

- [x] 4.1 En `backend/app/main.py:_run_bulk_pipeline` (líneas 87-94), incluir `client_name` y `siete_id` en cada entry de `scraper_clients` (hoy solo se pasa `client_id`, `team_id`, `download_dir`).
- [x] 4.2 Verificar que `fetch_active_clients` ya devuelve `siete_id` (revisar `backend/app/siete_api.py`); si no, agregarlo al mapping.

## 5. Validación en local

- [x] 5.1 Adaptar el script de prueba reproductor (`/tmp/test_switch_7graus.py` ya existe — moverlo a un lugar versionable, ej. `backend/scripts/probe_workspace.py` o similar) para que use `_switch_workspace` directamente.
- [ ] 5.2 Ejecutar el script contra `team_id=463109` (7graus) y confirmar que levanta `WorkspaceUnavailable` con mensaje legible.
- [ ] 5.3 Ejecutar contra `team_id=454974` (caleidos) y confirmar que no levanta excepción y que la Capa 2 confirma el `team_id` activo.
- [ ] 5.4 Ejecutar `download_all_reports` con una lista corta `[caleidos, 7graus, otro_cliente_válido]` y verificar: caleidos OK, 7graus en failures con mensaje 403, tercer cliente OK con sus propios datos.

## 6. Validación de la alerta Slack

- [ ] 6.1 Disparar manualmente `send_workspace_unavailable_alert(...)` con datos de prueba y confirmar que el mensaje llega al destino esperado.
- [ ] 6.2 Simular falla de Slack (token inválido o destino inexistente) y confirmar que el cron no aborta y el cliente queda en failures.

## 7. Deploy y observación

- [ ] 7.1 Mergear el cambio a `main` y desplegar.
- [ ] 7.2 Esperar el cron diario siguiente y verificar en logs y en Slack que 7graus dispara la alerta y queda en failures.
- [ ] 7.3 Verificar que el CSV consolidado del día NO contiene filas con `client_id=7graus`.
- [ ] 7.4 Coordinar con el equipo operativo para marcar 7Graus como Churn en Siete API (acción separada al fix; el sistema seguirá generando la alerta hasta que esto se haga).

## 8. Archive del change

- [ ] 8.1 Una vez confirmado en producción que el comportamiento es el esperado, archivar el change con `/opsx:archive validate-workspace-switch`.
