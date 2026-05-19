"""Slug normalization canónica usada en todo el pipeline.

Toda comparación cross-source (Reply.io ↔ Siete API) DEBE pasar por esta función.
"""
import re


def slug(name: str) -> str:
    """Normaliza un nombre a un slug canónico.

    >>> slug("Agencia Brocco")
    'agencia_brocco'
    >>> slug("FINNEGANS QUIPPOS")
    'finnegans_quippos'
    >>> slug("  Re-9 ")
    're_9'
    >>> slug("UDEM (México)")
    'udem_mexico'
    """
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
