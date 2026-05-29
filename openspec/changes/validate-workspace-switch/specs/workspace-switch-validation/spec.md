## ADDED Requirements

### Requirement: Switch HTTP status validation

El scraper SHALL inspeccionar el status code de la response devuelta por la navegación a `https://run.reply.io/Home/SwitchTeam?teamId={team_id}` y abortar el procesamiento del cliente cuando la response sea ausente o no-2xx.

#### Scenario: SwitchTeam devuelve HTTP 403
- **WHEN** el scraper navega al SwitchTeam URL para un `team_id` al que el usuario no tiene acceso
- **AND** Reply.io responde con HTTP 403 y body `{"statusCode":403,"message":"You are not a member of specified team"}`
- **THEN** el scraper MUST levantar `WorkspaceUnavailable` con un mensaje que incluya el status code (`403`) y un extracto del body recibido
- **AND** el scraper MUST NOT disparar ningún export (people o email) para ese cliente
- **AND** el scraper MUST registrar el cliente en `failures` con el mensaje de la excepción
- **AND** el scraper MUST continuar al siguiente cliente del loop

#### Scenario: SwitchTeam devuelve cualquier otro 4xx/5xx
- **WHEN** la response del SwitchTeam tiene status code distinto de 2xx (por ejemplo, 500 transitorio, 404)
- **THEN** el scraper MUST levantar `WorkspaceUnavailable` incluyendo el status code observado
- **AND** el cliente afectado MUST quedar en `failures` sin contaminar archivos de otros clientes

#### Scenario: page.goto no devuelve Response
- **WHEN** Playwright devuelve `None` como response del `page.goto(SwitchTeam_url)` (por ejemplo, por timeout)
- **THEN** el scraper MUST levantar `WorkspaceUnavailable` con mensaje indicando ausencia de response del servidor

### Requirement: Active workspace verification post-switch

El scraper SHALL verificar, después de un SwitchTeam aparentemente exitoso (HTTP 2xx), que el workspace activo de la sesión efectivamente coincide con el `team_id` esperado, consultando el endpoint interno `/Team/GetTeamData` de Reply.io.

#### Scenario: Workspace activo coincide con el esperado
- **WHEN** el SwitchTeam devolvió 2xx
- **AND** la llamada subsiguiente a `/Team/GetTeamData` devuelve un objeto cuyo campo `teamId` (o `id` o `currentTeamId`) iguala al `team_id` esperado
- **THEN** el scraper MUST proceder con los exports

#### Scenario: Workspace activo NO coincide con el esperado
- **WHEN** el SwitchTeam devolvió 2xx
- **AND** la llamada a `/Team/GetTeamData` devuelve un `teamId` distinto al esperado
- **THEN** el scraper MUST levantar `WorkspaceUnavailable` con mensaje indicando el `team_id` esperado y el `teamId` realmente activo
- **AND** el cliente afectado MUST registrarse en `failures` sin disparar exports

#### Scenario: /Team/GetTeamData no es invocable o devuelve forma desconocida
- **WHEN** la llamada a `/Team/GetTeamData` falla por red, parse, o devuelve un objeto sin campos `teamId`/`id`/`currentTeamId`
- **THEN** el scraper MUST loguear un warning con el detalle del error
- **AND** el scraper MUST tolerar la falla (no levantar `WorkspaceUnavailable`) si el SwitchTeam HTTP fue 2xx — la Capa 1 ya cubrió el caso patológico, la Capa 2 es defensa en profundidad

### Requirement: No exports without confirmed workspace

El scraper SHALL garantizar que ningún export de people o de email_activity se dispare para un cliente sin que su workspace haya sido confirmado como activo en la sesión vigente.

#### Scenario: Cliente con SwitchTeam fallido no produce CSVs
- **WHEN** `WorkspaceUnavailable` se levanta para un cliente
- **THEN** no se MUST crear ningún archivo en `download_dir/{client_id}/`
- **AND** el CSV consolidado del día MUST NOT contener filas bajo ese `client_id`

#### Scenario: Falla de un cliente no contamina al siguiente
- **WHEN** el cliente N falla con `WorkspaceUnavailable`
- **AND** el cliente N+1 tiene un workspace válido y accesible
- **THEN** el SwitchTeam del cliente N+1 MUST ejecutarse independientemente
- **AND** los datos del cliente N+1 MUST corresponder exclusivamente a su propio workspace, no al del cliente N ni a ningún otro

### Requirement: Failure isolation and no retries for inaccessible workspaces

El scraper SHALL tratar `WorkspaceUnavailable` como una falla persistente (no transitoria) y NO debe reintentar el cliente afectado.

#### Scenario: WorkspaceUnavailable no dispara retry
- **WHEN** `WorkspaceUnavailable` se levanta dentro del loop de clientes
- **THEN** el bloque except MUST NOT ejecutar `recycle_pages` ni reiniciar la sesión
- **AND** el bloque except MUST NOT volver a intentar el procesamiento del cliente
- **AND** el control MUST avanzar al siguiente cliente

#### Scenario: Crash de Chromium sigue reintentándose como antes
- **WHEN** se levanta una excepción cuyo mensaje contiene `"Page crashed"`, `"Target closed"` o `"Target page"`
- **AND** la excepción NO es `WorkspaceUnavailable`
- **THEN** el comportamiento existente de recycle + retry MUST preservarse

### Requirement: Slack alert on workspace inaccessibility

El sistema SHALL emitir una alerta a Slack en el momento en que se detecta un workspace inaccesible, conteniendo información suficiente para que el operador actúe sin necesidad de revisar logs.

#### Scenario: Alerta inmediata al detectar 403
- **WHEN** `WorkspaceUnavailable` se levanta para un cliente
- **THEN** el sistema MUST emitir un mensaje a Slack a través de los destinos configurados en `SLACK_DESTINATIONS` (o `SLACK_CHANNEL` como fallback)
- **AND** el mensaje MUST incluir: `client_name`, `siete_id`, `team_id`, status code recibido (o causa de falla de la Capa 2), y una línea sugiriendo la acción operativa ("Revisar si el cliente fue dado de baja o si hay que re-invitar al bot al workspace en Reply.io")
- **AND** la emisión MUST ocurrir antes de continuar con el siguiente cliente, no diferida al final del run

#### Scenario: Falla de Slack no aborta el cron
- **WHEN** la llamada a Slack para emitir la alerta falla (token vencido, 5xx, red caída)
- **THEN** el sistema MUST loguear la falla con detalle
- **AND** el cliente afectado MUST quedar registrado en `failures` igualmente (la alerta es bonus, el registro es obligatorio)
- **AND** el cron MUST continuar con el siguiente cliente sin abortar

### Requirement: Typed exception for workspace access failures

El scraper SHALL exponer una excepción tipada `WorkspaceUnavailable` (subclase de `Exception`) que represente exclusivamente fallas de acceso a workspace (status no-2xx en SwitchTeam o mismatch en validación post-switch). Esta excepción MUST distinguirse semánticamente de errores transitorios de Chromium o de red.

#### Scenario: La excepción puede inspeccionarse por tipo
- **WHEN** código consumidor del scraper captura una excepción levantada por la validación de workspace
- **THEN** debe poder hacer `isinstance(exc, WorkspaceUnavailable)` y obtener `True`
- **AND** el mensaje de la excepción MUST ser legible y orientado al operador (no traceback crudo)
