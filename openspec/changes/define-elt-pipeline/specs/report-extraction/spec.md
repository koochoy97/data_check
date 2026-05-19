## ADDED Requirements

### Requirement: Descarga por cliente desde Reply.io
El sistema SHALL descargar dos CSVs por cada cliente activo: `people.csv` (Personas) y `email_activity.csv` (Correos), usando Playwright para automatizar la UI de Reply.io.

#### Scenario: Cliente con team_id válido procesado correctamente
- **WHEN** el bulk-cron procesa un cliente con `team_id` válido
- **THEN** se hace `SwitchTeam` al workspace correspondiente
- **AND** se dispara el export asíncrono de Personas y Correos
- **AND** se espera la notificación de descarga lista
- **AND** ambos archivos se guardan en `{DOWNLOAD_DIR}/{client_slug}/{kind}.csv`
- **AND** se emite `[scraper] <kind>.csv descargado: N bytes`

### Requirement: Resiliencia ante fallas individuales
El sistema SHALL aislar las fallas de cada cliente: si la descarga de un cliente falla, los demás SHALL continuar procesándose.

#### Scenario: Cliente individual falla en trigger de export
- **WHEN** el clic en "Last Year" o "Date" en la UI de Reply.io supera el timeout
- **THEN** el sistema reintenta hasta 3 veces con backoff (6s, 11s)
- **AND** si los 3 intentos fallan, el cliente se registra en `failures: [{slug, error}]`
- **AND** el bulk-cron continúa con el siguiente cliente

#### Scenario: Reciclaje de páginas Playwright cada 10 clientes
- **WHEN** se procesaron 10 clientes consecutivos
- **THEN** el sistema cierra y reabre las páginas de Playwright para evitar memory leaks

### Requirement: Endpoint manual de descarga por cliente
El sistema SHALL exponer `GET /api/generate/{client_id}` (SSE) para forzar la descarga de un cliente específico fuera del cron, y `GET /api/generate-bulk` (SSE) para forzar el bulk completo en demanda.

#### Scenario: Generate-bulk en demanda
- **WHEN** un operador hace `GET /api/generate-bulk`
- **THEN** la conexión SSE emite eventos `progress`, `file`, `error` por cliente y `done` al final
- **AND** los CSVs por cliente quedan en `{DOWNLOAD_DIR}/{slug}/` y los consolidados en `{DOWNLOAD_DIR}/consolidated/`

#### Scenario: Generate-bulk con limit
- **WHEN** se invoca con `?limit=5`
- **THEN** solo se procesan los primeros 5 clientes (útil para pruebas)

### Requirement: Cron diario de descarga masiva
El sistema SHALL ejecutar el bulk-cron diariamente a las 05:00 UTC (00:00 Perú).

#### Scenario: Cron arranca a las 05:00 UTC
- **WHEN** la hora actual UTC alcanza las 05:00
- **THEN** se obtienen los clientes activos desde Siete API (capability `client-registry`)
- **AND** se inicia la sesión Reply.io vía Playwright
- **AND** se itera sobre los clientes en orden
- **AND** se consolida al terminar
- **AND** se entrega vía Slack (capability `report-delivery`)
