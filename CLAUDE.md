# CLAUDE.md — ZAWAbfallkalenderZuGoogleCalendarURL

Vercel Serverless Function die ZAW-Abfuhrtermine (Landkreis Darmstadt-Dieburg)
als abonnierbaren ICS-Feed bereitstellt. Adresse kommt als URL-Parameter.

**Disclaimer:** Dieser Code wurde von Claude Code erzeugt und ist ein reines
Hobby-Projekt ohne jegliche Kooperation mit ZAW. Jegliche Nutzung ist auf
eigene Gefahr, ohne jegliche Garantie auf Funktionstüchtigkeit und ohne
Garantie auf Hilfe bei dadurch auftretenden Problemen. Es kann jederzeit
aufhören zu funktionieren, wenn z.B. die ZAW ihr API ändert oder die Nutzung
ihres APIs auf diese Weise nicht mehr möchte.

## Verifizierte Fakten (NICHT neu herleiten)
- ZAW-Backend ist **jumomind**. service_id = `zaw`.
- API-Basis: `https://zaw.jumomind.com/mmapp/api.php`
- Endpunkte:
  - `?r=cities_web` → Gemeinden `{name,_name,id,area_id,has_streets}`
  - `?r=streets&city_id=ID` → Straßen `{name,_name,area_id,houseNumbers:[[nr,area_id]]}`
  - `?r=trash&city_id=ID&area_id=ID` → Tonnenarten `{name,_name,title,color}`
  - `?r=dates/0&city_id=ID&area_id=ID&ws=3` → Termine `{trash_name, day:"YYYY-MM-DD"}`
- Straßen-Normalisierung: lowercase/casefold, `straße`→`strasse`, `str.`→`strasse`.
- **Tonnenfarben** (exakt, aus `trash.color`, Hex ohne `#`):
  Bio `008d34`, Gelber Sack `fecb00`, Papier `0061a6`, Restmüll 14-täglich
  `2f3639`, Restmüll wöchentlich `99999` (ZAW-Bug, 5-stellig → Fallback Grau
  `9e9e9e`), Schadstoffmobil `e3000e`. `_norm_color()` validiert/normalisiert.

## Architektur
- `zaw_ics_gen.py` — Kernlogik: jumomind-API abfragen, ICS erzeugen.
  Alle Funktionen nehmen Parameter entgegen (kein globaler State).
  Reine, unit-testbare Helfer: `build_ics(...)`, `filter_dates_by_trash(...)`.
  CLI-Modus liest aus `.env` / Umgebungsvariablen.
  API-Basis über `ZAW_API_BASE` überschreibbar (`api_base()`), für Tests/Mock.
- `api/index.py` — **einziger** Vercel-Entrypoint (BaseHTTPRequestHandler).
  Routen: `/` (Picker-HTML inline), `/feed` (+`/api/feed`), `/api/cities`,
  `/api/streets`, `/api/trash`. URL-Parameter des Feeds: `city`, `nr` (Pflicht),
  `street` (optional – nur bei Gemeinden mit Straßen), `name`, `types`
  (exakte API-Namen, z.B. `ZAW_REST_2W`), `eve` (HH:MM oder `off`),
  `morn` (`allday`|HH:MM|`off`). Liest `ZAW_API_BASE` per Request (`_api()`).
- `pyproject.toml` — `[tool.vercel] entrypoint = "api.index:handler"` + Deps.
- `vercel.json` — Rewrite `/feed` → `/api/feed`.

## Farben & eingebettete Vorschau
- Jedes VEVENT trägt `X-ZAW-COLOR:#rrggbb` (exakte ZAW-Tonnenfarbe). Google/Apple
  ignorieren das unbekannte Property folgenlos; nur die Vorschau nutzt es.
  Quelle: `fetch_trash_colors()` (gleicher 24h-`trash`-Cache, kein Extra-Upstream).
- `/api/trash` liefert `color` mit → farbiger Swatch pro Abfalltyp-Checkbox.
- **Vorschau** (Landing Page): FullCalendar v6 (Core-Bundle) + **ical.js ES5**.
  Wir parsen das ICS **selbst** mit ical.js und lesen `X-ZAW-COLOR` (darum KEIN
  `@fullcalendar/icalendar`-Plugin – es würde X-Props nicht durchreichen, und nur
  so lassen sich die zwei Restmüll-Typen unterschiedlich einfärben).
  **ical.js `.cjs` MUSS von unpkg** kommen (jsdelivr liefert `application/node`
  → Chromium blockt unter nosniff → globales `ICAL` bliebe undefiniert).

## WICHTIGE Stolperfalle
**Google ignoriert VALARM in abonnierten Kalendern.** Die 22-Uhr-Einträge sind
sichtbar, piepen aber nicht. VALARM bleibt im Feed (Apple/Thunderbird ehren sie).

## Schonung der ZAW-Server (Pflicht-Anforderung: ZAW nicht überlasten)
Mehrschichtiger Schutz gegen Überlastung von App **und** ZAW-Backend:
- **24h Edge-Cache:** `/feed` + `/api/*` senden `s-maxage=86400` → Vercel-CDN
  bedient wiederholte gleiche URLs (z.B. Google-Poller) ohne Function/ZAW.
- **24h In-Function-Cache** (`cached_get_json` in `zaw_ics_gen.py`): jede
  ZAW-Antwort wird pro warmer Instanz bis 24h gecacht. `ZAW_CACHE_TTL` (0=aus).
- **Rate-Limit pro IP** (`_rate_ok` in `api/index.py`): `ZAW_RATE_PER_MIN`
  (Default 120), sonst 429. Best-effort (serverless: nur pro Instanz).
- **robots.txt** verbietet Crawlern `/api/` und `/feed`.
- Produktion zusätzlich: **Vercel Firewall/WAF** im Dashboard (harte Schranke).
Env-Knöpfe: `ZAW_CACHE_TTL`, `ZAW_RATE_PER_MIN`, `ZAW_API_BASE` (Tests/Mock).
Cache/Rate sind durch `tests/test_protection.py` abgedeckt (Mock zählt Upstream).

## Tests (vor dem Deploy)
Offline-Selbsttest mit Mock-ZAW + echter Function + headless Chromium:
```bash
pip install -r requirements-dev.txt && python -m playwright install chromium
python -m pytest
```
`tests/mock_zaw.py` (deterministischer ZAW-Mock inkl. Farben, zählt Upstream),
`tests/conftest.py` (startet Mock + echte Function lokal). Deckt u.a. den
Prefill-Roundtrip, alle Picker-Kombinationen und die **farbige Vorschau** ab
(`test_preview_colors_events_like_zaw` mockt per `page.route` ein selbst
erzeugtes, bekanntes ICS und prüft die real gerenderten Termin-Farben – inkl.
unterscheidbarer Restmüll-Typen; Checkbox-Swatches via
`test_trash_checkboxes_show_api_colors`). **Vor jedem Deploy grün.**

Hinweis: Code ist 3.10+-kompatibel (keine Backslashes in f-string-Ausdrücken);
Vercel nutzt 3.12. Auf Windows braucht `zoneinfo` das `tzdata`-Paket.

## Befehle (lokal)
```bash
cp .env.example .env && $EDITOR .env
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python3 zaw_ics_gen.py --discover
python3 zaw_ics_gen.py --stdout
```
