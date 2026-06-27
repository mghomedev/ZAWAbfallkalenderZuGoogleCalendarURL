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
  - `?r=trash&city_id=ID&area_id=ID` → Tonnenarten `{name,_name,title}`
  - `?r=dates/0&city_id=ID&area_id=ID&ws=3` → Termine `{trash_name, day:"YYYY-MM-DD"}`
- Straßen-Normalisierung: lowercase/casefold, `straße`→`strasse`, `str.`→`strasse`.

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

## WICHTIGE Stolperfalle
**Google ignoriert VALARM in abonnierten Kalendern.** Die 22-Uhr-Einträge sind
sichtbar, piepen aber nicht. VALARM bleibt im Feed (Apple/Thunderbird ehren sie).

## Tests (vor dem Deploy)
Offline-Selbsttest mit Mock-ZAW + echter Function + headless Chromium:
```bash
pip install -r requirements-dev.txt && python -m playwright install chromium
python -m pytest
```
`tests/mock_zaw.py` (deterministischer ZAW-Mock, zählt Upstream-Requests),
`tests/conftest.py` (startet Mock + echte Function lokal). Deckt u.a. den
Prefill-Roundtrip und alle Picker-Kombinationen ab. **Vor jedem Deploy grün.**

Hinweis: Code ist 3.10+-kompatibel (keine Backslashes in f-string-Ausdrücken);
Vercel nutzt 3.12. Auf Windows braucht `zoneinfo` das `tzdata`-Paket.

## Befehle (lokal)
```bash
cp .env.example .env && $EDITOR .env
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python3 zaw_ics_gen.py --discover
python3 zaw_ics_gen.py --stdout
```
