## ADDED Requirements

### Requirement: Full client mapping endpoint

El sistema SHALL exponer `GET /api/clients/mapping` que devuelve TODOS los clientes Siete (sin filtros de status ni team_id) enriquecidos con información de matching contra workspaces Reply.io en vivo.

#### Scenario: Devuelve todos los clientes Siete con sus campos
- **WHEN** el operador llama `GET /api/clients/mapping`
- **THEN** la respuesta MUST contener `clients: [{siete_id, siete_name, siete_slug, status, team_id, reply_match}]`
- **AND** la lista MUST incluir clientes Active, Churn, archived, Pending y sin status
- **AND** el campo `team_id` MUST ser el valor crudo de Siete (puede ser `null`)
- **AND** el campo `reply_match` MUST ser `{"name": str, "team_id": int}` cuando el `team_id` del cliente coincide con un workspace Reply.io conocido, o `null` cuando no hay match (incluido el caso `team_id=null`)

#### Scenario: Scrape de Reply.io falla pero el endpoint sigue funcionando
- **WHEN** `fetch_reply_workspaces_live()` falla (timeout, login error)
- **THEN** la respuesta MUST devolver los clientes con `reply_match: null` para todos
- **AND** un campo `scrape_error: str` describe la falla
- **AND** el status HTTP MUST seguir siendo 200 (la lista de clientes sigue siendo útil sin el enriquecimiento)

### Requirement: Inline team_id editing from mapping view

El sistema SHALL exponer `PATCH /api/clients/{siete_id}/team-id` para actualizar el `team_id` de un cliente desde la vista de mapeo. Acepta valores enteros positivos o `null` para desvincular.

#### Scenario: Asignar nuevo team_id
- **WHEN** el operador llama `PATCH /api/clients/42/team-id` con body `{"team_id": 123456}`
- **THEN** el sistema MUST invocar `patch_team_id(siete_id=42, team_id=123456)` que hace PATCH a Siete API
- **AND** la respuesta MUST contener el registro actualizado devuelto por Siete

#### Scenario: Desvincular team_id (set null)
- **WHEN** el operador llama `PATCH /api/clients/42/team-id` con body `{"team_id": null}`
- **THEN** el sistema MUST intentar hacer PATCH a Siete con `team_id=None`
- **AND** si Siete acepta `null`, la respuesta MUST ser 200 con el registro actualizado
- **AND** si Siete rechaza `null`, la respuesta MUST ser 400 con un mensaje claro indicando la limitación

#### Scenario: Validación de team_id inválido
- **WHEN** el operador llama el endpoint con body `{"team_id": 0}` o `{"team_id": -1}` o `{"team_id": "abc"}`
- **THEN** el sistema MUST devolver 400 sin llamar a Siete
- **AND** la respuesta MUST contener un mensaje describiendo el campo inválido

### Requirement: Frontend mapping view

El frontend SHALL exponer una ruta `/clients` (o equivalente accesible desde un botón en `/reconciliation`) que muestra la tabla del mapeo completo con edición inline.

#### Scenario: Carga la tabla con todos los clientes
- **WHEN** el operador navega a `/clients`
- **THEN** el frontend MUST hacer `GET /api/clients/mapping`
- **AND** mostrar una tabla con columnas: nombre, status, team_id, slug, match Reply.io
- **AND** el orden por defecto MUST ser alfabético por nombre

#### Scenario: Editar team_id de una fila
- **WHEN** el operador edita el valor de `team_id` en una fila y confirma
- **THEN** el frontend MUST llamar `PATCH /api/clients/{siete_id}/team-id` con el nuevo valor
- **AND** mostrar feedback visual del éxito o falla
- **AND** la fila MUST reflejar el nuevo valor sin requerir recarga manual

#### Scenario: Navegación desde reconciliación
- **WHEN** el operador está en `/reconciliation`
- **THEN** debe existir un link/botón "Ver mapeo completo" que lleva a `/clients`
- **AND** desde `/clients` debe existir un link "Volver a reconciliación"
