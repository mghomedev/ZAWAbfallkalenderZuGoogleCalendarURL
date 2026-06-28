"""
Vercel Serverless Function: Einziger Entrypoint für alle Routen.

Routen:
  GET /              -> Landing Page
  GET /feed          -> ICS-Feed
  GET /api/cities    -> JSON: ZAW-Gemeinden
  GET /api/streets   -> JSON: Straßen + Hausnummern
  GET /api/trash     -> JSON: Abfalltypen für eine Adresse

HINWEIS: Dieser Code wurde von Claude Code erzeugt und ist ein reines Hobby-Projekt
ohne jegliche Kooperation mit ZAW. Jegliche Nutzung ist auf eigene Gefahr, ohne
jegliche Garantie auf Funktionstüchtigkeit und ohne Garantie auf Hilfe bei dadurch
auftretenden Problemen. Es kann jederzeit aufhören zu funktionieren, wenn z.B. die
ZAW ihr API ändert oder die Nutzung ihres APIs auf diese Weise nicht mehr möchte.
"""

from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from zaw_ics_gen import (  # noqa: E402
    get_schedule, build_ics, resolve_address, fetch_trash_types,
    cached_get_json, clear_cache,
)


def _api() -> str:
    """ZAW-API-Basis. Über ZAW_API_BASE überschreibbar (z.B. für Tests/Mock)."""
    return os.environ.get("ZAW_API_BASE", "https://zaw.jumomind.com/mmapp/api.php")


# --------------------------------------------------------------------------- #
# Best-effort Rate-Limit pro IP (schützt App + ZAW vor Crawlern/Enumeration).
# Hinweis: serverless -> nur pro warmer Instanz, nicht global. Die eigentliche
# Verteidigung ist Edge-Caching (s-maxage) + Vercel WAF/Firewall (Dashboard).
# --------------------------------------------------------------------------- #
_RATE: dict[str, tuple[float, int]] = {}


def _rate_per_min() -> int:
    try:
        return int(os.environ.get("ZAW_RATE_PER_MIN", "120"))
    except ValueError:
        return 120


def clear_rate() -> None:
    _RATE.clear()


def _rate_ok(ip: str) -> bool:
    limit = _rate_per_min()
    if limit <= 0:
        return True
    now = time.monotonic()
    win, cnt = _RATE.get(ip, (now, 0))
    if now - win >= 60:
        win, cnt = now, 0
    cnt += 1
    _RATE[ip] = (win, cnt)
    return cnt <= limit


ROBOTS_TXT = (
    "User-agent: *\n"
    "Allow: /$\n"
    "Disallow: /api/\n"
    "Disallow: /feed\n"
)


class handler(BaseHTTPRequestHandler):
    def _client_ip(self) -> str:
        xff = self.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "?"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        if path == "/robots.txt":
            self._text(200, ROBOTS_TXT, content_type="text/plain")
            return

        # Best-effort Rate-Limit (greift v.a. bei Cache-umgehender Enumeration).
        if not _rate_ok(self._client_ip()):
            self.send_response(429)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Retry-After", "60")
            self.end_headers()
            self.wfile.write(b"Too Many Requests\n")
            return

        routes = {
            "/": self._handle_index,
            "/feed": lambda: self._handle_feed(params),
            "/api/feed": lambda: self._handle_feed(params),
            "/api/cities": self._handle_cities,
            "/api/streets": lambda: self._handle_streets(params),
            "/api/trash": lambda: self._handle_trash(params),
        }
        handler_fn = routes.get(path)
        if handler_fn:
            handler_fn()
        else:
            self._text(404, "Not Found")

    def _handle_index(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "public, s-maxage=3600, max-age=300")
        self.end_headers()
        self.wfile.write(INDEX_HTML.encode())

    def _handle_feed(self, params):
        city = _first(params, "city")
        street = _first(params, "street")
        nr = _first(params, "nr")

        # street ist optional: Gemeinden ohne Straßenauswahl (has_streets=false)
        # liefern auch ohne street-Parameter einen Feed.
        if not city or not nr:
            self._text(400,
                "Pflichtparameter fehlen: city, nr (street nur bei Gemeinden mit Straßen)\n\n"
                "Beispiel: /feed?city=Meine-Gemeinde&street=Meine+Stra%C3%9Fe&nr=1\n"
                "\nOptionale Parameter:\n"
                "  name    – Kalender-Anzeigename\n"
                "  types   – Abfalltypen kommagetrennt (z.B. ZAW_BIO,ZAW_GELB)\n"
                "  eve     – Vorabend-Uhrzeit (z.B. 22:00, oder off)\n"
                "  morn    – Morgen-Modus: allday (default), HH:MM, oder off\n")
            return

        cal_name = _first(params, "name") or f"Abfall {city} (ZAW)"
        types_raw = _first(params, "types")
        trash_filter = [t.strip() for t in types_raw.split(",") if t.strip()] if types_raw else None
        eve_time = _first(params, "eve")
        morn_mode = _first(params, "morn")

        # Konfiguration aus URL-Parametern ableiten
        kw = {}
        if eve_time == "off" or eve_time == "":
            kw["evening_enabled"] = False
        elif eve_time:
            kw["evening_time"] = eve_time

        if morn_mode == "off":
            kw["morning_enabled"] = False
        elif morn_mode and morn_mode != "allday":
            kw["morning_all_day"] = False
            kw["morning_time"] = morn_mode

        try:
            dates, _, _ = get_schedule("zaw", city, street or "", nr, trash_filter=trash_filter)
            ics = build_ics(dates, cal_name=cal_name, **kw)
        except ValueError as ex:
            self._text(404, str(ex))
            return
        except Exception as ex:
            self._text(502, f"Fehler bei der ZAW-API-Abfrage: {ex}\n")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/calendar; charset=utf-8")
        # 24h Edge-Cache: wiederholte Abrufe derselben Feed-URL (z.B. Googles
        # Poller) werden von Vercels CDN bedient und treffen weder uns noch ZAW.
        self.send_header("Cache-Control", "public, max-age=3600, s-maxage=86400")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(ics.encode())

    def _handle_cities(self):
        try:
            data = cached_get_json(None, _api(), {"r": "cities_web"})
            cities = sorted(
                [{"id": c["id"], "name": c["name"], "area_id": c["area_id"],
                  "has_streets": c["has_streets"]} for c in data],
                key=lambda c: c["name"],
            )
            self._json(200, cities)
        except Exception as ex:
            self._json(502, {"error": str(ex)})

    def _handle_streets(self, params):
        city_id = _first(params, "city_id")
        if not city_id:
            self._json(400, {"error": "city_id parameter required"})
            return
        try:
            data = cached_get_json(None, _api(), {"r": "streets", "city_id": city_id})
            streets = sorted(
                [{"name": s["name"], "area_id": s["area_id"],
                  "house_numbers": s.get("houseNumbers", [])} for s in data],
                key=lambda s: s["name"],
            )
            self._json(200, streets)
        except Exception as ex:
            self._json(502, {"error": str(ex)})

    def _handle_trash(self, params):
        city_id = _first(params, "city_id")
        area_id = _first(params, "area_id")
        if not city_id or not area_id:
            self._json(400, {"error": "city_id and area_id parameters required"})
            return
        try:
            s = requests.Session()
            s.headers.update({"Accept-Encoding": "identity"})
            types = fetch_trash_types(s, "zaw", city_id, area_id)
            self._json(200, types)
        except Exception as ex:
            self._json(502, {"error": str(ex)})

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        # Nur Erfolge lange cachen; Fehler (z.B. transientes 502) nicht, sonst
        # bliebe der Picker bis zu 24h kaputt, obwohl ZAW längst wieder läuft.
        if code == 200:
            self.send_header("Cache-Control", "public, s-maxage=86400, max-age=3600")
        else:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, code, msg, content_type="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        if code == 200:
            self.send_header("Cache-Control", "public, s-maxage=86400, max-age=3600")
        self.end_headers()
        self.wfile.write(msg.encode())


def _first(params: dict, key: str) -> str | None:
    vals = params.get(key)
    return vals[0] if vals else None


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZAW Abfallkalender zu Google Calendar URL</title>
<style>
  :root { --accent: #2563eb; --bg: #f8fafc; --card: #fff; --border: #e2e8f0; --text: #1e293b; --muted: #64748b; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 2rem 1rem; }
  h1 { font-size: 1.5rem; margin-bottom: .25rem; text-align: center; }
  .subtitle { color: var(--muted); font-size: .9rem; margin-bottom: 2rem; text-align: center; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 2rem; width: 100%; max-width: 520px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
  label { display: block; font-weight: 600; font-size: .85rem; margin-bottom: .35rem; margin-top: 1.25rem; }
  label:first-child { margin-top: 0; }
  select, input { width: 100%; padding: .6rem .75rem; border: 1px solid var(--border); border-radius: 8px; font-size: .95rem; background: var(--bg); color: var(--text); }
  select { appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2364748b' d='M2 4l4 4 4-4'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right .75rem center; padding-right: 2rem; cursor: pointer; }
  select:disabled { opacity: .5; cursor: not-allowed; }
  .cb-group { margin-top: .5rem; display: flex; flex-wrap: wrap; gap: .5rem; }
  .cb-group label { display: inline-flex; align-items: center; gap: .35rem; font-weight: 400; font-size: .9rem; margin: 0; cursor: pointer; }
  .cb-group input[type=checkbox] { width: auto; }
  .section { margin-top: 1.5rem; padding-top: 1.25rem; border-top: 1px solid var(--border); }
  .section-title { font-weight: 700; font-size: .9rem; margin-bottom: .75rem; color: var(--muted); }
  .row { display: flex; gap: .75rem; align-items: end; }
  .row > * { flex: 1; }
  .result { display: none; margin-top: 1.5rem; padding-top: 1.5rem; border-top: 1px solid var(--border); }
  .result.visible { display: block; }
  .url-box { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: .6rem .75rem; font-family: monospace; font-size: .78rem; word-break: break-all; margin: .75rem 0; user-select: all; }
  .buttons { display: flex; gap: .75rem; margin-top: 1rem; flex-wrap: wrap; }
  .btn { flex: 1; min-width: 140px; padding: .7rem 1rem; border: none; border-radius: 8px; font-size: .85rem; font-weight: 600; cursor: pointer; text-align: center; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; gap: .4rem; transition: opacity .15s; }
  .btn:hover { opacity: .85; }
  .btn-copy { background: var(--accent); color: #fff; }
  .btn-gcal { background: #16a34a; color: #fff; }
  .spinner { display: none; width: 1rem; height: 1rem; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .6s linear infinite; margin-left: .5rem; vertical-align: middle; }
  .spinner.active { display: inline-block; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .gcal-hint { margin-top: .6rem; font-size: .78rem; color: var(--muted); line-height: 1.4; text-align: center; }
  .prefill-link { display: block; margin-top: .75rem; font-size: .8rem; color: var(--muted); text-align: center; text-decoration: underline; cursor: pointer; }
  .prefill-link:hover { color: var(--accent); }
  .disclaimer { max-width: 520px; margin-top: 2rem; padding: 1rem; font-size: .72rem; color: var(--muted); line-height: 1.5; text-align: center; }
  .note { margin-top: 1rem; font-size: .8rem; color: var(--muted); line-height: 1.4; }
  .how-to { max-width: 520px; margin-top: 1.5rem; }
  .how-to summary { cursor: pointer; font-weight: 600; font-size: .9rem; color: var(--accent); }
  .how-to p, .how-to ol { font-size: .85rem; margin-top: .5rem; line-height: 1.6; color: var(--muted); }
  .how-to ol { padding-left: 1.25rem; }
  .how-to code { background: var(--bg); padding: .1rem .3rem; border-radius: 4px; font-size: .8rem; }
  a { color: var(--accent); }
  .btn-preview { width: 100%; margin-top: .75rem; padding: .6rem 1rem; border: 1px solid var(--border);
    background: var(--card); color: var(--accent); border-radius: 8px; font-size: .85rem;
    font-weight: 600; cursor: pointer; }
  .btn-preview:hover { background: var(--bg); }
  #preview-wrap { display: none; margin-top: 1rem; }
  #calendar { font-size: .85rem; }
</style>
<!-- Vorschau: FullCalendar v6 + iCalendar-Plugin + ical.js (ES5, registriert globales ICAL).
     Reihenfolge (defer erhält sie): Core -> ical.js -> Plugin.
     WICHTIG: ical.js als .cjs MUSS von unpkg kommen (Content-Type text/javascript);
     jsdelivr liefert .cjs als application/node -> Chromium blockt die Ausführung
     (nosniff), dann bleibt das globale ICAL undefiniert und das Plugin stumm. -->
<script defer src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.21/index.global.min.js"></script>
<script defer src="https://unpkg.com/ical.js@2.1.0/dist/ical.es5.min.cjs"></script>
<script defer src="https://cdn.jsdelivr.net/npm/@fullcalendar/icalendar@6.1.21/index.global.min.js"></script>
</head>
<body>

<h1>ZAW Abfallkalender zu Google Calendar URL</h1>
<p class="subtitle">Abfuhrtermine als abonnierbare Kalender-URL</p>

<div class="card">
  <label for="city">Gemeinde</label>
  <select id="city" disabled><option value="">Wird geladen...</option></select>
  <span id="city-spinner" class="spinner active"></span>

  <label for="street">Stra&szlig;e</label>
  <select id="street" disabled><option value="">Bitte zuerst Gemeinde w&auml;hlen</option></select>
  <span id="street-spinner" class="spinner"></span>

  <div id="hn-group" style="display:none">
    <label for="hn">Hausnummer</label>
    <select id="hn"><option value="">Bitte w&auml;hlen</option></select>
    <input id="hn-input" type="text" placeholder="Hausnummer eingeben" style="display:none">
  </div>

  <div id="trash-group" style="display:none" class="section">
    <div class="section-title">Abfalltypen</div>
    <div id="trash-checks" class="cb-group"></div>
  </div>

  <div class="section">
    <div class="section-title">Erinnerungen</div>
    <div class="row">
      <div>
        <label for="eve-time">Vorabend</label>
        <select id="eve-time">
          <option value="22:00" selected>22:00 Uhr</option>
          <option value="21:00">21:00 Uhr</option>
          <option value="20:00">20:00 Uhr</option>
          <option value="19:00">19:00 Uhr</option>
          <option value="18:00">18:00 Uhr</option>
          <option value="off">Aus</option>
        </select>
      </div>
      <div>
        <label for="morn-mode">Abholtag</label>
        <select id="morn-mode">
          <option value="allday" selected>Ganzt&auml;gig</option>
          <option value="06:00">06:00 Uhr</option>
          <option value="07:00">07:00 Uhr</option>
          <option value="08:00">08:00 Uhr</option>
          <option value="off">Aus</option>
        </select>
      </div>
    </div>
  </div>

  <div id="result" class="result">
    <label>Deine Kalender-URL</label>
    <div id="url-box" class="url-box"></div>
    <div class="buttons">
      <button class="btn btn-copy" id="btn-copy" onclick="copyUrl()">In Zwischenablage kopieren</button>
      <a class="btn btn-gcal" id="btn-gcal" href="#" target="_blank" rel="noopener"
         onclick="gcalClick()">Zu Google Kalender hinzuf&uuml;gen</a>
    </div>
    <p id="gcal-hint" class="gcal-hint">Google fragt nach der URL &ndash; sie wird beim Klick
      <strong>automatisch kopiert</strong>, also im ge&ouml;ffneten Google-Feld einfach
      einf&uuml;gen (Strg+V) und &bdquo;Kalender hinzuf&uuml;gen&ldquo; klicken.</p>
    <a id="btn-prefill" href="#" class="prefill-link">Diese Auswahl als vorausgef&uuml;llte URL</a>
    <button class="btn-preview" id="btn-preview" type="button" onclick="previewClick()">
      Vorschau anzeigen (Termine pr&uuml;fen)</button>
    <div id="preview-wrap"><div id="calendar"></div></div>
    <p class="note">
      <strong>Immer aktuell:</strong> Die Termine kommen direkt aus der ZAW-API &ndash; kein Cron,
      keine manuelle Pflege. Zum Schutz der ZAW-Server werden Antworten bis zu 24 h
      zwischengespeichert; Verschiebungen (z.B. wegen Feiertagen) erscheinen daher sp&auml;testens
      nach ~24 h plus Googles Poll-Intervall (~8&ndash;24 h) automatisch.
      <br><br>
      Die Vorabend-Eintr&auml;ge sind sichtbar; in Google piepen sie aber nicht (VALARM-Einschr&auml;nkung).
      Apple Kalender und Thunderbird ehren VALARM.
    </p>
  </div>
</div>

<details class="how-to">
  <summary>Wie funktioniert das?</summary>
  <ol>
    <li>W&auml;hle oben deine Gemeinde, Stra&szlig;e und Hausnummer.</li>
    <li>Optional: filtere Abfalltypen und stelle die Erinnerungszeiten ein.</li>
    <li>Klicke &bdquo;Zu Google Kalender hinzuf&uuml;gen&ldquo; (URL wird kopiert) und f&uuml;ge sie
        auf der Google-Seite ein &ndash; oder nutze &bdquo;In Zwischenablage kopieren&ldquo;.</li>
    <li>Optional: &bdquo;Vorschau&ldquo; zeigt die Termine direkt hier zur Pr&uuml;fung.</li>
    <li>Google pollt den Feed automatisch &ndash; neue Termine erscheinen von selbst.</li>
  </ol>
  <p>
    Quellcode:
    <a href="https://github.com/mghomedev/ZAWAbfallkalenderZuGoogleCalendarURL" target="_blank">
      github.com/mghomedev/ZAWAbfallkalenderZuGoogleCalendarURL
    </a>
  </p>
</details>

<div class="disclaimer">
  Dieser Code wurde von Claude Code erzeugt und ist ein reines Hobby-Projekt ohne jegliche
  Kooperation mit ZAW. Jegliche Nutzung ist auf eigene Gefahr, ohne jegliche Garantie auf
  Funktionst&uuml;chtigkeit und ohne Garantie auf Hilfe bei dadurch auftretenden Problemen. Es kann
  jederzeit aufh&ouml;ren zu funktionieren, wenn z.B. die ZAW ihr API &auml;ndert oder die Nutzung ihres
  APIs auf diese Weise nicht mehr m&ouml;chte.
</div>

<script>
const BASE = location.origin;
const QS = Object.fromEntries(new URLSearchParams(location.search));
let streetsData = [], selectedCity = null, trashTypes = [];

const cityEl = document.getElementById("city");
const streetEl = document.getElementById("street");
const hnEl = document.getElementById("hn");
const hnInput = document.getElementById("hn-input");
const hnGroup = document.getElementById("hn-group");
const trashGroup = document.getElementById("trash-group");
const trashChecks = document.getElementById("trash-checks");
const eveEl = document.getElementById("eve-time");
const mornEl = document.getElementById("morn-mode");
const resultEl = document.getElementById("result");
const urlBox = document.getElementById("url-box");
const btnGcal = document.getElementById("btn-gcal");
const btnCopy = document.getElementById("btn-copy");
const btnPrefill = document.getElementById("btn-prefill");

// Pre-fill eve/morn from URL
if (QS.eve) eveEl.value = QS.eve;
if (QS.morn) mornEl.value = QS.morn;

async function loadCities() {
  try {
    const res = await fetch(BASE + "/api/cities");
    const cities = await res.json();
    cityEl.innerHTML = '<option value="">-- Gemeinde w\u00e4hlen --</option>';
    cities.forEach(c => {
      const o = document.createElement("option");
      o.value = c.id;
      o.textContent = c.name;
      o.dataset.hasStreets = c.has_streets;
      o.dataset.areaId = c.area_id;
      cityEl.appendChild(o);
    });
    cityEl.disabled = false;
    // Pre-fill city from URL
    if (QS.city) {
      for (const o of cityEl.options) {
        if (o.textContent === QS.city) { cityEl.value = o.value; break; }
      }
      if (cityEl.value) await onCityChange();
    }
  } catch (e) {
    cityEl.innerHTML = '<option value="">Fehler beim Laden</option>';
  }
  document.getElementById("city-spinner").classList.remove("active");
}

async function onCityChange() {
  streetEl.innerHTML = '<option value="">Wird geladen...</option>';
  streetEl.disabled = true;
  hnGroup.style.display = "none";
  resetResult();
  streetsData = [];

  const cityId = cityEl.value;
  if (!cityId) { streetEl.innerHTML = '<option value="">Bitte zuerst Gemeinde w\u00e4hlen</option>'; return; }

  const opt = cityEl.options[cityEl.selectedIndex];
  selectedCity = { id: cityId, name: opt.textContent, areaId: opt.dataset.areaId };

  if (opt.dataset.hasStreets === "false") {
    streetEl.innerHTML = '<option value="">Keine Stra\u00dfenauswahl n\u00f6tig</option>';
    await loadTrash(cityId, selectedCity.areaId);
    buildUrl(opt.textContent, "", "");
    return;
  }

  const spinner = document.getElementById("street-spinner");
  spinner.classList.add("active");
  try {
    const res = await fetch(BASE + "/api/streets?city_id=" + cityId);
    streetsData = await res.json();
    streetEl.innerHTML = '<option value="">-- Stra\u00dfe w\u00e4hlen --</option>';
    streetsData.forEach((s, i) => {
      const o = document.createElement("option");
      o.value = i;
      o.textContent = s.name;
      streetEl.appendChild(o);
    });
    streetEl.disabled = false;
    // Pre-fill street from URL
    if (QS.street) {
      const norm = v => v.toLowerCase().replace(/stra\u00dfe/g,"strasse").replace(/str\./g,"strasse");
      for (const o of streetEl.options) {
        if (o.textContent === QS.street || norm(o.textContent) === norm(QS.street)) {
          streetEl.value = o.value; break;
        }
      }
      if (streetEl.value) await onStreetChange();
    }
  } catch (e) {
    streetEl.innerHTML = '<option value="">Fehler beim Laden</option>';
  }
  spinner.classList.remove("active");
}

cityEl.addEventListener("change", onCityChange);

async function onStreetChange() {
  hnGroup.style.display = "none";
  resetResult();

  const idx = streetEl.value;
  if (idx === "") return;
  const street = streetsData[parseInt(idx)];
  const cityName = cityEl.options[cityEl.selectedIndex].textContent;

  if (street.house_numbers && street.house_numbers.length > 0) {
    hnEl.innerHTML = '<option value="">-- Hausnummer w\u00e4hlen --</option>';
    street.house_numbers.forEach(hn => {
      const o = document.createElement("option");
      o.value = hn[0];
      o.textContent = hn[0];
      hnEl.appendChild(o);
    });
    hnEl.style.display = "";
    hnInput.style.display = "none";
    hnGroup.style.display = "block";
    hnGroup.dataset.mode = "select";
    // Pre-fill house number from URL (select mode)
    if (QS.nr) {
      for (const o of hnEl.options) {
        if (o.value === QS.nr) { hnEl.value = o.value; break; }
      }
      if (hnEl.value) await onHnSelectChange();
    }
  } else {
    hnInput.value = QS.nr || "";
    hnInput.style.display = "";
    hnEl.style.display = "none";
    hnGroup.style.display = "block";
    hnGroup.dataset.mode = "input";
    // Pre-fill house number from URL (input mode)
    if (QS.nr) {
      await loadTrash(selectedCity.id, street.area_id);
      buildUrl(cityName, street.name, QS.nr);
    }
  }
}

streetEl.addEventListener("change", onStreetChange);

async function onHnSelectChange() {
  if (!hnEl.value) { resetResult(); return; }
  const cityName = cityEl.options[cityEl.selectedIndex].textContent;
  const street = streetsData[parseInt(streetEl.value)];
  let areaId = street.area_id;
  const hn = street.house_numbers.find(h => h[0] === hnEl.value);
  if (hn) areaId = hn[1];
  await loadTrash(selectedCity.id, areaId);
  buildUrl(cityName, street.name, hnEl.value);
}

hnEl.addEventListener("change", onHnSelectChange);

hnInput.addEventListener("input", async () => {
  const val = hnInput.value.trim();
  if (!val) { resetResult(); return; }
  const cityName = cityEl.options[cityEl.selectedIndex].textContent;
  const idx = parseInt(streetEl.value);
  const street = streetsData[idx];
  await loadTrash(selectedCity.id, street.area_id);
  buildUrl(cityName, street.name, val);
});

async function loadTrash(cityId, areaId) {
  try {
    const res = await fetch(BASE + "/api/trash?city_id=" + cityId + "&area_id=" + areaId);
    trashTypes = await res.json();
    trashChecks.innerHTML = "";
    // Schlüssel aus der URL (kleingeschrieben). Spiegelt die Backend-Filterlogik:
    // ein Typ ist angehakt, wenn ein Schlüssel == API-Name, Teil des API-Namens
    // oder Teil des Titels ist (case-insensitiv). So entspricht der Haken exakt
    // dem, was der Feed tatsächlich liefert.
    const typeKeys = QS.types
      ? QS.types.split(",").map(t => t.trim().toLowerCase()).filter(Boolean)
      : null;
    trashTypes.forEach(t => {
      const lbl = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = t.name;
      if (typeKeys) {
        const n = (t.name || "").toLowerCase();
        const tl = (t.title || "").toLowerCase();
        cb.checked = typeKeys.some(k => k === n || n.includes(k) || tl.includes(k));
      } else {
        cb.checked = true;
      }
      cb.addEventListener("change", updateUrl);
      lbl.appendChild(cb);
      lbl.appendChild(document.createTextNode(" " + t.title));
      trashChecks.appendChild(lbl);
    });
    trashGroup.style.display = "block";
  } catch (e) { /* ignore */ }
}

eveEl.addEventListener("change", updateUrl);
mornEl.addEventListener("change", updateUrl);

let currentCity = "", currentStreet = "", currentNr = "";

function buildUrl(city, street, nr) {
  currentCity = city; currentStreet = street; currentNr = nr;
  updateUrl();
}

// Versteckt das Ergebnis UND verwirft den generierten Zustand, damit eine
// spätere Änderung an den Erinnerungs-Dropdowns nicht die alte Adresse zeigt.
function resetResult() {
  resultEl.classList.remove("visible");
  currentCity = currentStreet = currentNr = "";
  trashChecks.innerHTML = "";
  trashGroup.style.display = "none";
}

function updateUrl() {
  if (!currentCity) return;
  const p = new URLSearchParams();
  p.set("city", currentCity);
  if (currentStreet) p.set("street", currentStreet);
  p.set("nr", currentNr || "1");

  // Abfalltyp-Filter: exakte API-Namen verwenden (z.B. ZAW_BIO, ZAW_REST_2W)
  const allCbs = [...trashChecks.querySelectorAll("input[type=checkbox]")];
  const checked = allCbs.filter(cb => cb.checked);
  if (checked.length > 0) {
    p.set("types", checked.map(cb => cb.value).join(","));
  }

  p.set("eve", eveEl.value);
  p.set("morn", mornEl.value);

  const url = BASE + "/feed?" + p.toString();
  urlBox.textContent = url;
  // Google prefüllt das url=-Feld NICHT zuverlässig. Wir öffnen die
  // "Per URL hinzufügen"-Seite und kopieren die Feed-URL in die Zwischenablage,
  // damit der Nutzer sie dort nur noch einfügen muss.
  btnGcal.href = "https://calendar.google.com/calendar/u/0/r/settings/addbyurl";
  btnPrefill.href = BASE + "/?" + p.toString();
  resultEl.classList.add("visible");
  btnCopy.textContent = "In Zwischenablage kopieren";
}

async function gcalClick() {
  // Feed-URL in die Zwischenablage legen (Klick ist eine User-Geste).
  try { await navigator.clipboard.writeText(urlBox.textContent); } catch (e) { /* egal */ }
  // der Link öffnet danach die Google-Seite (kein preventDefault).
}

// --- Vorschau via FullCalendar + iCalendar-Plugin ------------------------- //
let _calendar = null;
function _previewReady() {
  return typeof FullCalendar !== "undefined" && typeof FullCalendar.Calendar !== "undefined"
    && typeof ICAL !== "undefined";  // ICAL ist Peer-Dependency des iCalendar-Plugins
}
function previewClick() {
  const wrap = document.getElementById("preview-wrap");
  const el = document.getElementById("calendar");
  wrap.style.display = "block";
  el.innerHTML = '<p style="color:var(--muted);font-size:.85rem">Vorschau lädt…</p>';
  _renderPreviewWhenReady(0);
}
function _renderPreviewWhenReady(tries) {
  const el = document.getElementById("calendar");
  if (!_previewReady()) {
    if (tries > 120) {  // ~12s gewartet
      el.innerHTML = '<p style="color:var(--muted);font-size:.85rem">' +
        'Vorschau nicht verfügbar (CDN blockiert?). Die Feed-URL funktioniert trotzdem.</p>';
      return;
    }
    setTimeout(() => _renderPreviewWhenReady(tries + 1), 100);
    return;
  }
  if (_calendar) { _calendar.destroy(); _calendar = null; }
  el.innerHTML = "";
  _calendar = new FullCalendar.Calendar(el, {
    initialView: "listMonth",
    headerToolbar: { left: "prev,next today", center: "title", right: "dayGridMonth,listMonth" },
    events: { url: urlBox.textContent, format: "ics" },
    height: "auto",
    firstDay: 1,
    noEventsContent: "Keine Termine im Zeitraum",
  });
  _calendar.render();
  document.getElementById("preview-wrap").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function copyUrl() {
  try {
    await navigator.clipboard.writeText(urlBox.textContent);
    btnCopy.textContent = "Kopiert!";
    setTimeout(() => { btnCopy.textContent = "In Zwischenablage kopieren"; }, 2000);
  } catch (e) {
    const range = document.createRange();
    range.selectNodeContents(urlBox);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);
  }
}

loadCities();
</script>
</body>
</html>"""
