"""
Deterministischer Mock des ZAW/jumomind-API für Tests.

Bildet die vier genutzten Endpunkte nach:
  ?r=cities_web
  ?r=streets&city_id=ID
  ?r=trash&city_id=ID&area_id=ID
  ?r=dates/0&city_id=ID&area_id=ID&ws=3

Besonderheiten, die echte ZAW-Eigenheiten abdecken:
  - eine Straße MIT Hausnummern (je Nummer eigene area_id)
  - eine Straße OHNE Hausnummern (Frankensteiner-Str.-Fall -> Freitext im Picker)
  - eine Gemeinde OHNE Straßen (has_streets=false)
  - Namen mit Umlaut/ß (Encoding-Test)
  - zwei verschiedene Restmüll-Typen (ZAW_REST_2W vs ZAW_REST_W)

Der Mock ZÄHLT alle Upstream-Anfragen (counts), damit Cache-Tests prüfen können,
dass eine zweite identische Anfrage NICHT erneut beim "ZAW" landet.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# --------------------------------------------------------------------------- #
# Seed-Daten (von Tests importierbar)
# --------------------------------------------------------------------------- #
# Gemeinden
CITY_WITH_STREETS = {"id": "100", "name": "Testheim", "_name": "Testheim",
                     "area_id": "0", "has_streets": True}
CITY_UMLAUT = {"id": "101", "name": "Groß-Umstadt", "_name": "Groß-Umstadt",
               "area_id": "0", "has_streets": True}
CITY_NO_STREETS = {"id": "102", "name": "Inselstadt", "_name": "Inselstadt",
                   "area_id": "50", "has_streets": False}

CITIES = [CITY_WITH_STREETS, CITY_UMLAUT, CITY_NO_STREETS]

# Straßen je city_id
STREET_WITH_HN = {
    "name": "Hauptstraße", "_name": "Hauptstraße", "area_id": "200",
    "houseNumbers": [["1", "201"], ["2", "202"], ["5", "205"]],
}
STREET_NO_HN = {
    "name": "Frankensteiner Str.", "_name": "Frankensteiner Str.", "area_id": "210",
    "houseNumbers": [],
}
STREET_UMLAUT = {
    "name": "Bahnhofstraße", "_name": "Bahnhofstraße", "area_id": "300",
    "houseNumbers": [],
}

STREETS = {
    "100": [STREET_WITH_HN, STREET_NO_HN],
    "101": [STREET_UMLAUT],
    # 102 hat keine Straßen (has_streets=false) -> wird nie abgefragt
}

# Abfalltypen (kanonisch, für jede Adresse identisch)
# Farben exakt wie die echte ZAW/jumomind-API (Hex ohne #). ZAW_REST_W liefert
# real den fehlerhaften 5-stelligen Wert "99999" -> testet die _norm_color-
# Fallback-Logik (ungültig -> neutrales Grau).
TRASH_TYPES = [
    {"name": "ZAW_BIO", "_name": "ZAW_BIO", "title": "Bioabfall", "color": "008d34"},
    {"name": "ZAW_GELB", "_name": "ZAW_GELB", "title": "Gelber Sack", "color": "fecb00"},
    {"name": "ZAW_PAP", "_name": "ZAW_PAP",
     "title": "Papier Tonnen und Container", "color": "0061a6"},
    {"name": "ZAW_REST_2W", "_name": "ZAW_REST_2W",
     "title": "Restmüll Tonnen und Container 14-täglich", "color": "2f3639"},
    {"name": "ZAW_REST_W", "_name": "ZAW_REST_W",
     "title": "Restmüll Container wöchentlich", "color": "99999"},
    {"name": "ZAW_SCHAD", "_name": "ZAW_SCHAD", "title": "Schadstoffmobil", "color": "e3000e"},
]
TRASH_NAMES = [t["name"] for t in TRASH_TYPES]


def _make_dates():
    """Erzeugt Termine relativ zu HEUTE, damit sie im build_ics-Fenster liegen.

    Jeder der sechs Typen bekommt mehrere zukünftige Termine.
    """
    today = dt.date.today()
    out = []
    for k, t in enumerate(TRASH_TYPES):
        # je Typ vier Termine, gestaffelt, sicher in der Zukunft
        for j in range(4):
            day = today + dt.timedelta(days=2 + k + j * 14)
            out.append({"trash_name": t["name"], "day": day.isoformat()})
    return out


# --------------------------------------------------------------------------- #
# Mock-HTTP-Handler mit Request-Zähler
# --------------------------------------------------------------------------- #
class _Counter:
    def __init__(self):
        self.lock = threading.Lock()
        self.counts: dict[str, int] = {}

    def hit(self, key: str):
        with self.lock:
            self.counts[key] = self.counts.get(key, 0) + 1

    def reset(self):
        with self.lock:
            self.counts.clear()

    def snapshot(self) -> dict[str, int]:
        with self.lock:
            return dict(self.counts)


def make_handler(counter: _Counter):
    class MockZAWHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: D401 - keine Konsolen-Logs im Test
            pass

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            r = (qs.get("r") or [""])[0]
            city_id = (qs.get("city_id") or [""])[0]
            area_id = (qs.get("area_id") or [""])[0]

            # interne Test-Endpunkte
            if parsed.path == "/__stats__":
                self._send(200, counter.snapshot())
                return
            if parsed.path == "/__reset__":
                counter.reset()
                self._send(200, {"ok": True})
                return

            if r == "cities_web":
                counter.hit("cities_web")
                self._send(200, CITIES)
            elif r == "streets":
                counter.hit(f"streets:{city_id}")
                self._send(200, STREETS.get(city_id, []))
            elif r == "trash":
                counter.hit(f"trash:{city_id}:{area_id}")
                self._send(200, TRASH_TYPES)
            elif r.startswith("dates"):
                counter.hit(f"dates:{city_id}:{area_id}")
                self._send(200, _make_dates())
            else:
                self._send(404, {"error": f"unknown r={r!r}"})

    return MockZAWHandler


def start_mock(host: str = "127.0.0.1", port: int = 0):
    """Startet den Mock in einem Hintergrund-Thread.

    Gibt (server, base_url, counter) zurück. base_url ist als ZAW_API_BASE nutzbar.
    """
    counter = _Counter()
    server = ThreadingHTTPServer((host, port), make_handler(counter))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    actual_port = server.server_address[1]
    base_url = f"http://{host}:{actual_port}/mmapp/api.php"
    return server, base_url, counter


if __name__ == "__main__":
    srv, url, _ = start_mock(port=8888)
    print("Mock ZAW läuft auf", url)
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.shutdown()
