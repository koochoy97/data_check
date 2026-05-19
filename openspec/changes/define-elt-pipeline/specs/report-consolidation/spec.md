## ADDED Requirements

### Requirement: Consolidación diaria de CSVs por cliente
El sistema SHALL generar dos archivos consolidados por día agrupando los CSVs de todos los clientes procesados: `people_consolidated_{YYYY-MM-DD}.csv` y `email_activity_consolidated_{YYYY-MM-DD}.csv`.

#### Scenario: Estructura del archivo consolidado
- **WHEN** el consolidador ejecuta tras el bulk-cron
- **THEN** cada archivo contiene una columna `client_id` y `client_name` como las primeras dos columnas
- **AND** las filas de cada cliente preservan sus columnas originales de Reply.io
- **AND** el archivo se guarda en `{DOWNLOAD_DIR}/consolidated/`

### Requirement: Fecha del archivo en timezone Perú
El sistema SHALL nombrar los archivos consolidados usando la fecha en timezone Perú (`UTC-5`), no UTC.

#### Scenario: Cron corre a las 05:00 UTC
- **WHEN** el cron arranca a las 05:00 UTC del día N
- **AND** termina ~40 minutos después
- **THEN** la fecha calculada como `datetime.now(timezone(timedelta(hours=-5))).date()` SHALL ser la fecha del día N en Perú (00:00–01:00 Perú)
- **AND** los archivos se llaman `*_{fecha_peru}.csv`

#### Scenario: Endpoint busca con misma fecha
- **WHEN** `POST /api/send-today` o `/api/diagnostics` busca el archivo del día
- **THEN** usa el mismo cálculo de fecha Perú
- **AND** matchea con el nombre de archivo generado por el cron

### Requirement: Endpoint público de descarga de consolidados
El sistema SHALL exponer `GET /api/consolidated/{filename}` para servir los archivos consolidados.

#### Scenario: Archivo existe
- **WHEN** el archivo solicitado existe en `{DOWNLOAD_DIR}/consolidated/{filename}`
- **AND** el filename pasa validación (no contiene `/` ni `..` y termina en `.csv`)
- **THEN** se sirve con `FileResponse`, `media_type=text/csv`

#### Scenario: Archivo no existe
- **WHEN** el archivo solicitado no existe
- **THEN** la respuesta es HTTP 404 con body `{"error": "File not found"}`
- **AND** NO se devuelve HTTP 200 con JSON de error (cambio respecto al comportamiento actual)

#### Scenario: Filename inválido
- **WHEN** el filename contiene `/`, `..`, o no termina en `.csv`
- **THEN** la respuesta es HTTP 400 con body `{"error": "Invalid filename"}`

### Requirement: Sin persistencia entre redeploys
El sistema NO SHALL persistir los archivos consolidados tras un reinicio del contenedor. Se acepta que tras un redeploy los links del día pierdan validez.

#### Scenario: Redeploy del contenedor
- **WHEN** el contenedor se reinicia (deploy nuevo, restart, OOM kill, etc.)
- **THEN** el contenido de `{DOWNLOAD_DIR}` se pierde
- **AND** los próximos requests a `/api/consolidated/{file}` retornan 404
- **AND** el operador puede regenerar manualmente con `GET /api/generate-bulk` (~40 minutos)
