## Context

El scraper Playwright de Reply.io procesa N clientes en un loop secuencial dentro de una sola sesión autenticada (`download_all_reports` en `backend/app/scraper/reply_io.py:203-335`). Para cada cliente, hace tres cosas: cambiar al workspace del cliente vía `page.goto("https://run.reply.io/Home/SwitchTeam?teamId={team_id}")`, disparar exports de Personas y Email Activity (en `page` y `page2` respectivamente), y descargar los CSVs cuando aparecen en el panel de notificaciones.

Reply.io maneja el "workspace activo" como **estado server-side por sesión** (cookie). Las URLs de la SPA usan hash routing (`#/people/list`, `#/reports/emails`) y **no** llevan el `team_id` en la URL — operan sobre el workspace que el servidor tenga marcado como activo para esa sesión.

Cuando el `SwitchTeam` falla (verificado experimentalmente: HTTP 403 al intentar cambiar a un workspace del que el bot no es miembro), la cookie de sesión NO se actualiza — la sesión sigue apuntando al último workspace válido. El scraper, que solo espera `domcontentloaded` y no inspecciona el status code, no detecta la falla y continúa el flujo: dispara exports, descarga lo que Reply.io genere para el workspace activo, y guarda esos CSVs bajo la carpeta del cliente que se *suponía* iba a procesar. El consolidator en `backend/app/processing/consolidator.py:41-49` inyecta `client_id`/`client_name` basado en metadata del loop, no en el contenido del archivo, así que la corrupción es indetectable a nivel data.

**Restricciones:**
- No podemos modificar el comportamiento del servidor de Reply.io. Operamos con lo que la UI/API nos expone.
- El bot scraper usa credenciales de un único usuario humano (`nicolas@wearesiete.com`). Si ese usuario pierde acceso a un workspace, no hay forma programática de recuperarlo.
- No podemos confiar en `wait_until` ni en heurísticas visuales (el DOM del workspace anterior se renderiza igual de bien).

**Stakeholders:** Jaime (operador del pipeline), Nicolas (consumidor de reportes y dueño de las credenciales Reply.io), equipo de cuenta de Caleidos/Siete (afectados por la data corrupta del 28-05).

## Goals / Non-Goals

**Goals:**
- Convertir cualquier falla de SwitchTeam (HTTP error o silenciosa) en un **failure controlado** del cliente afectado, sin contaminar los datos de los demás.
- Garantizar el invariante: **nunca se ejecuta un export sin que el workspace activo haya sido confirmado**.
- Dar al operador visibilidad accionable cuando un workspace queda inaccesible (alerta a Slack con cliente, IDs, status y siguiente acción sugerida).
- Hacer el sistema resistente al churn futuro: si mañana otro cliente es dado de baja en Reply.io, el cron sigue produciendo data limpia.

**Non-Goals:**
- Limpiar el reporte corrupto del 28-05 (es un script ad-hoc separado, no parte de este fix).
- Cambiar el status de 7Graus a `Churn` en Siete API (acción operativa manual del equipo).
- Refactorizar el scraper a fondo (recycle de páginas, paralelización, etc. quedan como están).
- Detectar otros tipos de falla del workspace (workspace existente pero con cero data, exports que devuelven vacíos, etc.) — esta capability cubre específicamente "no se puede entrar al workspace".
- Auto-PATCH a Siete cuando se detecta el 403 (debate operativo separado: ¿es correcto que el bot dé de baja clientes automáticamente?).

## Decisions

### D1 — Doble capa de validación (status code + post-switch check)
**Decisión**: Implementar validación en dos capas independientes:

1. **Capa primaria**: capturar la `Response` devuelta por `page.goto(SwitchTeam_url)` y abortar si `resp is None` o `not resp.ok`. Esto detecta el caso del 28-05 (HTTP 403) de forma directa y barata.

2. **Capa secundaria**: tras `sleep(3)` (gracia para que la sesión se asiente), llamar a `/Team/GetTeamData` vía `page.evaluate(fetch(...))` y validar que el campo `teamId`/`id` devuelto coincide con el esperado. Esto cubre fallas más sutiles: redirects raros que devuelven 200 pero no aplican el switch, cookies stale, race conditions.

**Alternativas consideradas:**
- *Solo Capa 1*: descartado — Reply.io podría devolver 200 con una página de error genérica o redirigir al workspace por defecto, pasando inadvertido.
- *Solo Capa 2*: descartado — agregaría una llamada HTTP extra incluso en el camino feliz (que es 99% del tiempo). La Capa 1 corta temprano sin costo.
- *Interceptar todas las responses con `page.on("response")`*: descartado — más invasivo, más estado mutable, y la Capa 1 es trivialmente más simple porque `page.goto` ya devuelve la Response principal.

### D2 — Excepción tipada `WorkspaceUnavailable`
**Decisión**: Definir `class WorkspaceUnavailable(Exception)` en `backend/app/scraper/reply_io.py`. La función `_switch_workspace` la levanta en cualquier falla de validación. Cae en el `except Exception` existente del loop (líneas 307-327) — **sin** reintentos, **sin** recycle de páginas (porque no es un crash de Chromium, es un rechazo del servidor que no se va a resolver reintentando).

**Por qué tipada y no `RuntimeError` genérico**: permite que el bloque except la trate de forma distinta a un crash de página (que sí merece retry). Mantiene el contrato explícito: "esto significa que el workspace no es accesible, no es un error transitorio".

**Alternativas consideradas:**
- *Reusar `RuntimeError`*: pierde la distinción semántica. El `except` actual ya reintenta crashes de página; necesitamos garantizar que esta clase NO se reintente.

### D3 — Ningún reintento ante WorkspaceUnavailable
**Decisión**: Cuando se detecta el 403/mismatch, el cliente se marca como failure inmediatamente. No reintentar.

**Rationale**: el 403 es persistente (refleja un cambio de estado en Reply.io — workspace borrado o membresía revocada). Reintentar consume tiempo del run y no cambia el resultado. Si en el futuro descubrimos que hay casos transitorios (raro), se puede agregar lógica específica.

### D4 — Alerta a Slack en el momento del descubrimiento, no al final del run
**Decisión**: Al levantar `WorkspaceUnavailable`, además del log y del registro en `failures`, emitir inmediatamente un mensaje a Slack con: nombre del cliente, `siete_id`, `team_id`, status code/mensaje recibido, sugerencia operativa.

**Por qué inmediato y no al final del cron**: el cron diario tarda ~40 minutos. Si el operador ve la alerta apenas se detecta, puede empezar a actuar mientras el resto de los clientes terminan. El reporte final consolidado igual incluirá el cliente en `failures`.

**Reutilización**: usar el cliente Slack y el destino configurados (ya existe el patrón en `backend/app/processing/send_slack.py` y `backend/app/cron_report.py`). No introducir un canal nuevo ni una configuración nueva — la alerta va al mismo destino que el resto de los avisos operativos del pipeline.

**Alternativas consideradas:**
- *Solo log + reporte final*: descartado — pierde la oportunidad de respuesta temprana. Si el cliente está realmente dado de baja, el operador quiere saberlo apenas detectado para descartar Slack del análisis del día.
- *Email/PagerDuty*: descartado — el canal Slack ya es el medio del equipo y agregar más canales es overkill para un evento raro.

### D5 — Pasar `client_name` y `siete_id` al scraper para que la alerta sea útil
**Decisión**: Modificar la lista `scraper_clients` en `backend/app/main.py:87-94` para incluir `client_name` y `siete_id` en cada entry. El scraper los pasa a la alerta cuando se levanta `WorkspaceUnavailable`. Sin esto la alerta diría solo "client_id=7graus, team_id=463109" — IDs en lugar de nombres legibles.

**Alternativas consideradas:**
- *Pasar solo `client_id` y resolver nombre en el callback de alerta*: posible pero acopla la función Slack al store de clientes. Inyectar el nombre desde el caller es más simple.

### D6 — `_switch_workspace` recibe un `alert_context` opcional
**Decisión**: La signature será `_switch_workspace(page, team_id, emit, alert_context=None)`. El `alert_context` es un dict con `client_id`, `client_name`, `siete_id` que usa la función para construir la alerta a Slack. Si es `None`, no se emite alerta (útil para tests/scripts ad-hoc que pueden usar la función sin querer disparar Slack).

## Risks / Trade-offs

- **[Riesgo] El endpoint `/Team/GetTeamData` cambia o se renombra en Reply.io** → Mitigación: si la Capa 2 falla por error de red/parse, loguear warning pero NO levantar `WorkspaceUnavailable` — la Capa 1 (status code del SwitchTeam) ya cubre el caso patológico del 28-05. La Capa 2 es defensa en profundidad: su ausencia degrada a "solo Capa 1", no a "sistema roto".

- **[Riesgo] La alerta a Slack falla (token vencido, rate limit, etc.) y oculta el evento** → Mitigación: wrappear la llamada a Slack en try/except, loguear la falla de la alerta, y **siempre** seguir registrando el cliente en `failures` (la alerta es bonus, el registro es obligatorio). El reporte final del cron ya muestra los failures.

- **[Trade-off] Una llamada HTTP extra por cliente** (`/Team/GetTeamData`) → costo aceptable: 48 clientes × 1 request liviano = ~5 segundos adicionales sobre un run de ~40 minutos.

- **[Riesgo] Falsos positivos de la Capa 2** (Reply.io devuelve teamId como string vs int, campo distinto al esperado, etc.) → Mitigación: normalizar a `int()` con try/except, y tolerar campos alternativos (`teamId`, `id`, `currentTeamId`). Si la respuesta no contiene ninguno reconocible, loguear warning y aceptar el switch (no romper si el endpoint cambia su forma).

- **[Riesgo] Comportamiento distinto entre `download_all_reports` (bulk) y `download_reports` (single)** → Mitigación: extraer una sola función `_switch_workspace` y llamarla desde ambos sitios para mantener consistencia.

- **[Trade-off] No auto-PATCH a Siete cuando se detecta el 403** → un humano debe marcar al cliente como Churn manualmente. Acepta el costo operativo a cambio de no introducir un side-effect que modifique el CRM automáticamente. Si la frecuencia de este evento crece, se puede agregar después.

## Migration Plan

1. Implementar y testear en local con el caso real (7graus, team_id=463109). Verificar que: (a) la Capa 1 detecta el 403, (b) el cliente se registra en failures, (c) los demás clientes se procesan normal, (d) la alerta llega a Slack.
2. Deploy a producción. El próximo cron diario ejercitará el código en condiciones reales — esperar que 7graus dispare la alerta y aparezca en failures sin contaminar.
3. Una vez confirmado, el equipo operativo marca 7Graus como Churn en Siete (acción separada, fuera del fix).
4. Limpieza de los CSVs del 28-05 vía script ad-hoc (fuera del scope).

**Rollback**: el cambio es contenido a `_switch_workspace` y dos call sites. Revertir el commit restaura el comportamiento previo (con la corrupción silenciosa) sin migraciones de datos ni cambios de schema.

## Open Questions

- ¿La alerta a Slack debería ir al mismo destino que el reporte diario (`SLACK_DESTINATIONS`) o a un canal específico de operaciones? Decisión por defecto: mismo destino. Reabrir si el equipo prefiere separar.
- ¿Conviene a futuro auto-llamar `patch_team_id(siete_id, None)` cuando se detecta 403, para que el cliente quede en estado "pendiente de reconciliación" automáticamente? Out of scope para este fix, pero anotado para revisión posterior.
