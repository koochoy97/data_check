## ADDED Requirements

### Requirement: Entrega exclusiva por Slack
El sistema SHALL entregar los reportes consolidados únicamente vía Slack. Gmail SHALL NOT ser utilizado para entrega de reportes.

#### Scenario: Bulk-cron finaliza consolidación
- **WHEN** el bulk-cron termina la consolidación con archivos generados
- **THEN** invoca `send_consolidated_slack(consolidated)`
- **AND** NO invoca ningún sistema de email

### Requirement: Multi-destino vía SLACK_DESTINATIONS
El sistema SHALL leer `SLACK_DESTINATIONS` como lista separada por `,` o `;`. Cada item SHALL ser uno de:
- Email (contiene `@`): se resuelve a `user_id` vía `users.lookupByEmail` y se envía como DM
- `#nombre-canal`: se usa tal cual
- ID de Slack (`C…`, `D…`, `U…`, `G…`): se usa tal cual

#### Scenario: SLACK_DESTINATIONS con mezcla
- **WHEN** `SLACK_DESTINATIONS=jaime@wearesiete.com,nicolas@wearesiete.com,#reportes`
- **THEN** se envía un DM a Jaime, un DM a Nicolas y un mensaje al canal `#reportes`
- **AND** cada envío usa `chat.postMessage` independientemente

#### Scenario: Fallback a SLACK_CHANNEL
- **WHEN** `SLACK_DESTINATIONS` está vacío o no seteado
- **AND** `SLACK_CHANNEL` está seteado
- **THEN** se envía solo a `SLACK_CHANNEL`

#### Scenario: Sin token ni destinos
- **WHEN** `SLACK_BOT_TOKEN` no está seteado
- **THEN** el sistema omite el envío con log `[slack] SLACK_BOT_TOKEN no configurado, omitiendo envío`
- **AND** NO levanta excepción que bloquee el cron

### Requirement: Fallas independientes por destino
El sistema SHALL enviar a cada destino independientemente. Una falla en un destino NO SHALL impedir el envío a los demás.

#### Scenario: Un destino falla
- **WHEN** se envía a 3 destinos y `users.lookupByEmail` falla para 1
- **THEN** los otros 2 reciben el mensaje
- **AND** al final `send_consolidated_slack` SHALL levantar `RuntimeError` listando los destinos fallidos
- **AND** el caller logueará el error pero no bloqueará el pipeline

### Requirement: Reintentos en errores transitorios
El sistema SHALL reintentar 3× con backoff `30s, 60s, 90s` solo en errores transitorios (`ratelimited`, `service_unavailable`, errores HTTP de red).

#### Scenario: Slack devuelve ratelimited
- **WHEN** `chat.postMessage` devuelve `{"ok": false, "error": "ratelimited"}`
- **THEN** el sistema espera 30s y reintenta
- **AND** tras 3 intentos fallidos, marca el destino como fallido y continúa

#### Scenario: Slack devuelve error permanente
- **WHEN** `chat.postMessage` devuelve `{"ok": false, "error": "channel_not_found"}` (u otro permanente)
- **THEN** NO se reintenta
- **AND** el destino se marca fallido inmediatamente

### Requirement: Formato del mensaje
El sistema SHALL formatear el mensaje de Slack siguiendo el contrato:
```
*Reportes consolidados de Reply.io del {YYYY-MM-DD}*

Links de descarga (válidos por 24h):
• <{url}|{filename}> ({size_mb} MB)
• <{url}|{filename}> ({size_mb} MB)
```

#### Scenario: Mensaje generado
- **WHEN** se envía el reporte del día 2026-05-18 con 2 archivos
- **THEN** el `text` contiene el título con la fecha en bold
- **AND** una lista con bullet `•` por archivo
- **AND** cada link en formato Slack `<url|texto>` para que se renderice como hipervínculo
- **AND** `unfurl_links: false` y `unfurl_media: false` para que Slack no expanda preview

### Requirement: Endpoint manual de reenvío
El sistema SHALL exponer `POST /api/send-today` para reenviar los reportes del día actual (Perú).

#### Scenario: Archivos existen
- **WHEN** un operador hace `POST /api/send-today`
- **AND** existen los CSVs consolidados del día
- **THEN** se invoca `send_consolidated_slack(found)`
- **AND** la respuesta es `{"sent": true, "files": [...], "date": "..."}` en caso de éxito
- **AND** la respuesta es `{"sent": false, "slack_error": "..."}` si Slack falla

#### Scenario: Archivos no existen
- **WHEN** `POST /api/send-today` se invoca después de un redeploy (archivos perdidos)
- **THEN** la respuesta es `{"error": "No hay archivos consolidados para hoy (...)"}` con HTTP 200
- **AND** el operador puede correr `GET /api/generate-bulk` para regenerar
