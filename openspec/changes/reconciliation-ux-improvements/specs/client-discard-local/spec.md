## ADDED Requirements

### Requirement: Local discard list for Siete clients

El sistema SHALL mantener una lista persistente de `siete_id`s "descartados localmente" que NO afecta el estado del cliente en Siete API pero excluye al cliente del listado de pendientes de reconciliación. La lista vive en `DOWNLOAD_DIR / "discarded_clients.json"` con estructura `{"siete_ids": [int], "updated_at": iso8601}`.

#### Scenario: Descartar un cliente lo excluye de pendientes
- **WHEN** el operador llama `POST /api/reconciliation/discard` con body `{"siete_id": 99}`
- **AND** `99` era un cliente Active sin team_id en Siete
- **THEN** el sistema MUST agregar `99` al archivo de descartados
- **AND** el siguiente `GET /api/reconciliation/pending` MUST NOT incluir al cliente con `siete_id=99`
- **AND** Siete API NO MUST haber recibido ningún PATCH ni modificación

#### Scenario: Restaurar un cliente lo vuelve a mostrar como pendiente
- **WHEN** el operador llama `POST /api/reconciliation/restore` con body `{"siete_id": 99}`
- **AND** `99` estaba en la lista de descartados
- **THEN** el sistema MUST quitar `99` del archivo de descartados
- **AND** si el cliente sigue siendo Active sin team_id en Siete, el siguiente `GET /api/reconciliation/pending` MUST incluirlo de nuevo

#### Scenario: Listar descartados
- **WHEN** el operador llama `GET /api/reconciliation/discarded`
- **THEN** el sistema MUST devolver un objeto con `discarded: [{siete_id, siete_name, siete_slug, status}]`
- **AND** los nombres MUST resolverse consultando Siete API en el momento del GET (no se persisten en el archivo local — solo el `siete_id`)

#### Scenario: Descartar un siete_id ya descartado no falla
- **WHEN** el operador llama `POST /api/reconciliation/discard` con un `siete_id` que ya estaba en la lista
- **THEN** la operación MUST ser idempotente (devolver 200 OK) sin duplicar el id en el archivo

#### Scenario: Restaurar un siete_id que no estaba descartado no falla
- **WHEN** el operador llama `POST /api/reconciliation/restore` con un `siete_id` ausente de la lista
- **THEN** la operación MUST ser idempotente (devolver 200 OK) sin error

#### Scenario: Archivo inexistente o corrupto se trata como lista vacía
- **WHEN** el archivo `discarded_clients.json` no existe o está malformado
- **THEN** `load()` MUST devolver `set()` (lista vacía)
- **AND** el sistema MUST loguear un warning si el archivo existía pero estaba malformado
- **AND** la operación de write siguiente MUST regenerar el archivo correcto

### Requirement: Pending endpoint excludes discarded clients

El endpoint `GET /api/reconciliation/pending` SHALL excluir todos los clientes cuyo `siete_id` figura en la lista de descartados, antes de armar el payload con sugerencias.

#### Scenario: Pending filtra descartados
- **WHEN** Siete API devuelve 5 clientes Active sin team_id, con `siete_ids = [10, 20, 30, 40, 50]`
- **AND** el archivo de descartados contiene `[20, 40]`
- **THEN** `GET /api/reconciliation/pending` MUST devolver solo los items para `siete_ids = [10, 30, 50]`
- **AND** el conteo `len(pending)` MUST ser 3, no 5

### Requirement: Slack consolidated message links to reconciliation when pending exists

El mensaje diario consolidado enviado a `SLACK_DESTINATIONS` SHALL incluir una línea final con conteo y link a `/reconciliation` cuando haya al menos un cliente pendiente. Si el conteo (filtrado por descartados) es cero, el mensaje queda idéntico al actual.

#### Scenario: Pendientes > 0 agrega la línea
- **WHEN** `_run_bulk_pipeline` invoca `send_consolidated_slack(consolidated, pending_count=3)`
- **THEN** el texto del mensaje MUST terminar con una línea conteniendo el número `3` y un link clickeable a `{PUBLIC_BASE_URL}/reconciliation`
- **AND** la línea MUST estar precedida por un indicador visual (ej. emoji ⚠️) que el operador reconozca como "acción pendiente"

#### Scenario: Pendientes == 0 deja el mensaje como hoy
- **WHEN** `send_consolidated_slack(consolidated, pending_count=0)` (o sin parámetro)
- **THEN** el mensaje MUST ser idéntico al actual: fecha + lista de archivos
- **AND** no MUST aparecer ninguna línea mencionando reconciliación

#### Scenario: Conteo se calcula descontando descartados
- **WHEN** Siete reporta 5 pendientes pero 2 están en la lista de descartados
- **AND** `_run_bulk_pipeline` deriva `pending_count` del resultado filtrado
- **THEN** el mensaje a Slack MUST decir "3 cliente(s) pendiente(s)", no 5
