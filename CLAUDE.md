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
  CLI-Modus liest aus `.env` / Umgebungsvariablen.
- `api/feed.py` — Vercel Serverless Function (BaseHTTPRequestHandler).
  URL-Parameter `city`, `street`, `nr`, optional `name`.
  Importiert `get_schedule` und `build_ics` aus `zaw_ics_gen`.
- `vercel.json` — Rewrite `/feed` → `/api/feed`.

## WICHTIGE Stolperfalle
**Google ignoriert VALARM in abonnierten Kalendern.** Die 22-Uhr-Einträge sind
sichtbar, piepen aber nicht. VALARM bleibt im Feed (Apple/Thunderbird ehren sie).

## Befehle (lokal)
```bash
cp .env.example .env && $EDITOR .env
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python3 zaw_ics_gen.py --discover
python3 zaw_ics_gen.py --stdout
```
