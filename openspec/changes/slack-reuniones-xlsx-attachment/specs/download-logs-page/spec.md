## ADDED Requirements

### Requirement: Página de logs de descarga con conteos por cliente
El sistema SHALL exponer una página en `/download-logs` que muestre una tabla con el conteo de filas por cliente en los CSVs consolidados más recientes.

#### Scenario: Carga exitosa
- **WHEN** el usuario abre `/download-logs`
- **THEN** se muestra una tabla con columnas Cliente, People, Email Activity y una fila de totales al final

#### Scenario: Datos del último consolidado disponible
- **WHEN** se llama `GET /api/client-stats`
- **THEN** el backend usa los CSVs consolidados más recientes disponibles (no necesariamente los de hoy) y devuelve `{date, clients: [{name, people, email_activity}]}`

#### Scenario: Sin CSVs disponibles
- **WHEN** no existe ningún archivo consolidado en `DOWNLOAD_DIR/consolidated/`
- **THEN** `/api/client-stats` devuelve HTTP 404 con `{"error": "No hay CSVs consolidados"}`

#### Scenario: Link desde Slack
- **WHEN** el usuario hace click en "Logs de descarga" en el mensaje de Slack
- **THEN** llega directamente a esta página con la tabla actualizada
