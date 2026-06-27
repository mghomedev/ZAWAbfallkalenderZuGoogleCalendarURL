"""
Vercel Serverless Function: ZAW-Abfuhrtermine als ICS-Feed.

URL-Parameter:
  city   – Gemeinde (z.B. Meine-Gemeinde)
  street – Straße (z.B. Musterstraße)
  nr     – Hausnummer (z.B. 1)
  name   – (optional) Kalender-Anzeigename

Beispiel:
  /api/feed?city=Meine-Gemeinde&street=Meine+Straße&nr=1

HINWEIS: Dieser Code wurde von Claude Code erzeugt und ist ein reines Hobby-Projekt
ohne jegliche Kooperation mit ZAW. Jegliche Nutzung ist auf eigene Gefahr, ohne
jegliche Garantie auf Funktionstüchtigkeit und ohne Garantie auf Hilfe bei dadurch
auftretenden Problemen. Es kann jederzeit aufhören zu funktionieren, wenn z.B. die
ZAW ihr API ändert oder die Nutzung ihres APIs auf diese Weise nicht mehr möchte.
"""

from __future__ import annotations

import sys
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# zaw_ics_gen.py liegt im Repo-Root, eine Ebene über api/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from zaw_ics_gen import get_schedule, build_ics  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        city = _first(params, "city")
        street = _first(params, "street")
        nr = _first(params, "nr")

        if not city or not street or not nr:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "Pflichtparameter fehlen: city, street, nr\n\n"
                "Beispiel: /api/feed?city=Meine-Gemeinde&street=Meine+Straße&nr=1\n".encode()
            )
            return

        cal_name = _first(params, "name") or f"Abfall {city} (ZAW)"

        try:
            dates, _, _ = get_schedule("zaw", city, street, nr)
            ics = build_ics(dates, cal_name=cal_name)
        except ValueError as ex:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(str(ex).encode())
            return
        except Exception as ex:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Fehler bei der ZAW-API-Abfrage: {ex}\n".encode())
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/calendar; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=3600, s-maxage=21600")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(ics.encode())


def _first(params: dict, key: str) -> str | None:
    vals = params.get(key)
    return vals[0] if vals else None
