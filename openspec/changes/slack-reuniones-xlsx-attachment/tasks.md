## Tasks

- [x] Agregar `_upload_file_to_channel()` en `send_slack.py` con flujo de 3 pasos de la API nueva de Slack
- [x] Modificar firma de `send_consolidated_slack()` para aceptar `xlsx_bytes: bytes | None = None`
- [x] Subir xlsx a cada destino en el loop de `send_consolidated_slack` (best-effort, no interrumpe si falla)
- [x] Actualizar call site del cron diario en `main.py` (línea ~148): fetch meetings + generate xlsx antes de llamar a Slack
- [x] Actualizar call site de `/api/send-today` en `main.py` (línea ~517): ídem
- [x] Agregar link fijo "Logs de descarga" en `_build_message` apuntando a `/download-logs`
- [x] Agregar endpoint `GET /api/client-stats` en `main.py`: lee CSVs consolidados más recientes, retorna conteos por cliente
- [x] Crear `DownloadLogsPage.jsx`: tabla Cliente / People / Email Activity con totales
- [x] Registrar ruta `/download-logs` en `App.jsx`
