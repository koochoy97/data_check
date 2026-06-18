# Reglas del proyecto

## PROHIBIDO: silenciar excepciones

`except Exception: pass` o `except Exception: [ignorar silenciosamente]` está **terminantemente prohibido**.

Si algo falla, el error DEBE propagarse, loguearse con `raise`, o al menos imprimirse con el traceback completo. Nunca usar `except` para esconder un error sin que quede registro visible.

Esto aplica a TODO el código: scraper, pipeline, Slack, exporters, endpoints.
