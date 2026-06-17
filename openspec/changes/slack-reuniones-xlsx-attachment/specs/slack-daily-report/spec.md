## MODIFIED Requirements

### Requirement: Reporte diario de Slack incluye xlsx de reuniones y link de logs
El reporte diario de Slack SHALL incluir:
- El archivo `REUNIONES_GLOBAL.xlsx` como adjunto, generado en tiempo real desde la API de Siete.
- Un link fijo "Logs de descarga" apuntando a `/download-logs`, siempre presente.

#### Scenario: Envío exitoso completo
- **WHEN** el cron diario o `/api/send-today` completa la consolidación
- **THEN** cada destino de SLACK_DESTINATIONS recibe:
  1. Mensaje de texto con links de descarga + link "Logs de descarga"
  2. `REUNIONES_GLOBAL.xlsx` como archivo adjunto

#### Scenario: Fallo en generación de xlsx
- **WHEN** `fetch_all_meetings()` o `generate_reuniones_xlsx()` falla
- **THEN** el mensaje de texto se envía igual sin adjunto, y el error se loguea como warning

#### Scenario: Fallo en upload de xlsx a un destino
- **WHEN** el upload del xlsx falla para un destino específico
- **THEN** el error se loguea pero no afecta el envío al resto de destinos ni lanza excepción

#### Scenario: Link de logs siempre presente
- **WHEN** se construye el mensaje de Slack
- **THEN** el link "Logs de descarga" apunta a `{PUBLIC_BASE_URL}/download-logs` y se incluye siempre, independientemente del estado del xlsx o de reconciliación
