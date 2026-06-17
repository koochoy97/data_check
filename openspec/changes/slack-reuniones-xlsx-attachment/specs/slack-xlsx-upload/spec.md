## ADDED Requirements

### Requirement: Upload de archivo xlsx a canal de Slack
El sistema SHALL subir un archivo xlsx a un canal de Slack usando la API de upload externo (getUploadURLExternal → upload → completeUploadExternal).

#### Scenario: Upload exitoso
- **WHEN** se llama `_upload_file_to_channel(channel, xlsx_bytes, filename, headers)`
- **THEN** el archivo aparece como adjunto en el canal especificado

#### Scenario: Fallo en getUploadURLExternal
- **WHEN** la API de Slack devuelve `ok: false` en el paso de obtener URL
- **THEN** se lanza `RuntimeError` con el mensaje de error de Slack

#### Scenario: Fallo en el upload del contenido
- **WHEN** el PUT al upload URL devuelve status != 200/201
- **THEN** se lanza `RuntimeError` con el HTTP status code
