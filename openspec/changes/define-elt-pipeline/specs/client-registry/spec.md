## ADDED Requirements

### Requirement: Siete API es la única fuente de verdad
El sistema SHALL usar Siete API (`GET /core/clientes/`, `PATCH /core/clientes/{id}/`) como única fuente de verdad de clientes. NO SHALL existir ningún archivo local (`clients.json`, `client_overrides.json`, etc.) que persista listas o atributos de clientes.

#### Scenario: Listar clientes para procesar
- **WHEN** el cron diario o un endpoint necesita la lista de clientes
- **THEN** consulta `GET {SIETE_API_ENDPOINT}/core/clientes/?limit=500` con header `x-api-key`
- **AND** filtra `status == "Active"` AND `team_id IS NOT NULL`
- **AND** excluye los nombres en `EXCLUDED_CLIENT_NAMES`
- **AND** retorna `[{client_id (slug), client_name, team_id, siete_id}, ...]`

#### Scenario: Actualizar team_id de un cliente
- **WHEN** el operador confirma un match en la UI de reconciliación
- **THEN** el backend hace `PATCH /core/clientes/{siete_id}/` con body `{"team_id": N}`
- **AND** la respuesta 200 confirma el guardado en Siete
- **AND** NO se persiste en ningún archivo local

### Requirement: Slug normalization canónica
El sistema SHALL usar una única función `slug(name: str) -> str` definida como `re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")`. Toda comparación cross-source (Siete ↔ Reply.io) SHALL pasar por esta normalización.

#### Scenario: Sugerir match Siete → Reply.io
- **WHEN** se busca el workspace de Reply.io correspondiente a un cliente Siete
- **THEN** se compara `slug(siete_client_name) == slug(reply_workspace_name)`
- **AND** un match exacto produce sugerencia con `confidence: "exact"`
- **AND** un match parcial (substring después de slug) produce `confidence: "partial"`
- **AND** sin match produce `confidence: "none"`

#### Scenario: Nombres con caracteres especiales producen el mismo slug
- **WHEN** Siete devuelve "Agencia Brocco"
- **AND** Reply.io devuelve workspace "agencia brocco"
- **THEN** ambos producen `slug == "agencia_brocco"` y matchean exactamente

### Requirement: Scrape de Reply.io on-demand (sin cache persistente)
El sistema SHALL invocar `fetch_reply_workspaces_live()` (scrape Playwright) únicamente cuando la UI de reconciliación lo pida. NO SHALL existir caché persistente entre invocaciones.

#### Scenario: UI pide workspaces para reconciliar
- **WHEN** el frontend hace `GET /api/reconciliation/pending`
- **THEN** el backend invoca `fetch_reply_workspaces_live()`
- **AND** el scrape login con `REPLY_IO_EMAIL`/`REPLY_IO_PASSWORD`
- **AND** intercepta la API interna de Reply.io para obtener `[{name, team_id}]`
- **AND** retorna esa lista junto con los clientes Siete pendientes

#### Scenario: Reply.io scrape falla
- **WHEN** `fetch_reply_workspaces_live()` retorna `None` o levanta excepción
- **THEN** el endpoint responde con HTTP 200 y `{"pending": [...], "reply_options": [], "scrape_error": "..."}`
- **AND** la UI muestra warning y permite que el operador tipee `team_id` manualmente

### Requirement: Endpoint manual de sync DEPRECATED
El sistema SHALL eliminar `POST /api/sync-clients` (que escribía a `clients.json`). En su lugar, el scrape vive dentro del flujo de reconciliación.

#### Scenario: Cliente intenta llamar al endpoint legacy
- **WHEN** se hace `POST /api/sync-clients`
- **THEN** la respuesta es HTTP 410 Gone con body `{"error": "Removed: use /reconciliation instead"}`
