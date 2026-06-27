"""Kleine ICS-Helfer für Tests."""

from __future__ import annotations


def unfold(ics: str) -> str:
    """Macht RFC-5545-Zeilenfaltung rückgängig (CRLF + Space -> nichts).

    Nötig, weil lange Werte (z.B. Tonnen-Titel) über Zeilen gefaltet werden und
    naive Substring-Prüfungen sonst fehlschlagen.
    """
    return ics.replace("\r\n ", "").replace("\n ", "")
