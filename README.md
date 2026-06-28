# ZAWAbfallkalenderZuGoogleCalendarURL

Konvertiert die ZAW-Abfuhrtermine (Landkreis Darmstadt-Dieburg) in eine
abonnierbare Google-Kalender-URL. Gehostet als **Vercel Serverless Function** --
die Adresse wird einfach als URL-Parameter uebergeben.

**[>> Zum Picker: Kalender-URL erstellen](https://zaw-abfallkalender-zu-google-calend.vercel.app/)**

> **Disclaimer:** Dieser Code wurde von Claude Code erzeugt und ist ein reines
> Hobby-Projekt ohne jegliche Kooperation mit ZAW. Jegliche Nutzung ist auf
> eigene Gefahr, ohne jegliche Garantie auf Funktionstuechtigkeit und ohne
> Garantie auf Hilfe bei dadurch auftretenden Problemen. Es kann jederzeit
> aufhoeren zu funktionieren, wenn z.B. die ZAW ihr API aendert oder die Nutzung
> ihres APIs auf diese Weise nicht mehr moechte.

---

## So funktioniert's

1. Oeffne den **[Picker](https://zaw-abfallkalender-zu-google-calend.vercel.app/)**
2. Waehle Gemeinde, Strasse, Hausnummer
3. Optional: Abfalltypen filtern (mit **ZAW-Farb-Swatch**), Erinnerungszeiten anpassen
4. Optional: **Vorschau** anzeigen -- die Termine erscheinen direkt auf der Seite,
   je Abfalltyp in der **exakten ZAW-Farbe** (Bio gruen, Papier blau, Gelber Sack
   gelb, Restmuell schwarz/grau, Schadstoff rot)
5. Klicke **"Zu Google Kalender hinzufuegen"** (URL wird kopiert) oder kopiere die URL

Pro Abholung entstehen bis zu **zwei** Kalender-Eintraege:

- **morgens am Abholtag** -- ganztaegiger, sichtbarer Eintrag
- **Vorabend** (Standard 22:00) -- Termin mit VALARM ("Tonne rausstellen")

### Immer aktuell -- und schonend zur ZAW

Die Termine kommen direkt aus der ZAW-API; **kein Cron, keine manuelle Pflege**.
Damit die ZAW-Server **nicht ueberlastet** werden, sind Antworten **bis zu 24 h
gecacht** (Edge-Cache + In-Function-Cache, siehe unten). Verschiebungen (z.B. wegen
Feiertagen) erscheinen daher spaetestens nach ~24 h plus Googles Poll-Intervall
(~8-24 h) automatisch -- fuer Mülltermine voellig ausreichend.

> **Hinweis:** Google ignoriert VALARM in abonnierten Kalendern. Die Vorabend-Eintraege
> sind sichtbar, piepen aber nicht. Apple Kalender und Thunderbird ehren VALARM.

---

## URL-Parameter

| Parameter | Pflicht | Beispiel | Beschreibung |
|---|---|---|---|
| `city` | ja | `Griesheim` | ZAW-Gemeindename |
| `street` | ja | `Goethestr.` | Strassenname |
| `nr` | ja | `1` | Hausnummer |
| `name` | nein | `Abfall` | Kalender-Anzeigename |
| `types` | nein | `bio,papier` | Abfalltypen kommagetrennt (bio, papier, restm, gelb, schad) |
| `eve` | nein | `22:00` | Vorabend-Uhrzeit (Standard: 22:00, `off` = keine Vorabend-Eintraege) |
| `morn` | nein | `allday` | Abholtag-Modus: `allday` (Standard), `HH:MM`, oder `off` |

---

## Beispiel-URLs (Buergeraemter/Rathaeuser im ZAW-Gebiet)

Diese URLs zeigen die Abfuhrtermine fuer die Rathaeuser verschiedener Gemeinden.
Zum Ausprobieren einfach anklicken -- der ICS-Feed wird direkt angezeigt:

| Gemeinde | Beispiel-URL |
|---|---|
| Alsbach-Haehnlein | [/feed?city=Alsbach-Haehnlein&street=Hauptstr.&nr=26](https://zaw-abfallkalender-zu-google-calend.vercel.app/feed?city=Alsbach-H%C3%A4hnlein&street=Hauptstr.&nr=26) |
| Babenhausen | [/feed?city=Babenhausen&street=Marktplatz&nr=2](https://zaw-abfallkalender-zu-google-calend.vercel.app/feed?city=Babenhausen&street=Marktplatz&nr=2) |
| Bickenbach | [/feed?city=Bickenbach&street=Darmstaedter+Str.&nr=7](https://zaw-abfallkalender-zu-google-calend.vercel.app/feed?city=Bickenbach&street=Darmst%C3%A4dter+Str.&nr=7) |
| Dieburg | [/feed?city=Dieburg&street=Markt&nr=4](https://zaw-abfallkalender-zu-google-calend.vercel.app/feed?city=Dieburg&street=Markt&nr=4) |
| Eppertshausen | [/feed?city=Eppertshausen&street=Schulstr.&nr=1](https://zaw-abfallkalender-zu-google-calend.vercel.app/feed?city=Eppertshausen&street=Schulstr.&nr=1) |
| Erzhausen | [/feed?city=Erzhausen&street=Bahnstr.&nr=44](https://zaw-abfallkalender-zu-google-calend.vercel.app/feed?city=Erzhausen&street=Bahnstr.&nr=44) |
| Griesheim | [/feed?city=Griesheim&street=Wilhelm-Leuschner-Str.&nr=75](https://zaw-abfallkalender-zu-google-calend.vercel.app/feed?city=Griesheim&street=Wilh.-Leuschner-Str.&nr=75) |
| Gross-Bieberau | [/feed?city=Gross-Bieberau&street=Marktstr.&nr=20](https://zaw-abfallkalender-zu-google-calend.vercel.app/feed?city=Gro%C3%9F-Bieberau&street=Marktstr.&nr=20) |
| Gross-Umstadt | [/feed?city=Gross-Umstadt&street=Markt&nr=1](https://zaw-abfallkalender-zu-google-calend.vercel.app/feed?city=Gro%C3%9F-Umstadt&street=Markt&nr=1) |
| Muehltal | [/feed?city=Muehltal&street=Odenwaldstr.&nr=8](https://zaw-abfallkalender-zu-google-calend.vercel.app/feed?city=M%C3%BChltal&street=Odenwaldstr.&nr=8) |

> **Tipp:** Im [Picker](https://zaw-abfallkalender-zu-google-calend.vercel.app/) werden
> die korrekten Strassen- und Hausnummern direkt aus dem ZAW-System geladen -- das ist
> der einfachste Weg zur eigenen URL.

---

## Selbst deployen

### Vercel (empfohlen)

1. Repository forken
2. In Vercel importieren (vercel.com -> "Add New Project" -> GitHub-Repo waehlen)
3. Fertig -- Vercel deployt automatisch bei jedem Push

### Lokal testen

```bash
cp .env.example .env && $EDITOR .env

python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python3 zaw_ics_gen.py --discover     # Adresse/IDs/Termine pruefen
python3 zaw_ics_gen.py --stdout       # ICS zur Sichtpruefung
```

---

## Technik

- `zaw_ics_gen.py` -- Kernlogik: fragt die jumomind-API (`zaw.jumomind.com`) ab,
  erzeugt eine RFC-5545-konforme ICS-Datei.
- `api/index.py` -- Vercel Serverless Function: Landing Page, Feed-Endpunkt,
  Gemeinde/Strassen/Abfalltyp-APIs fuer den Picker.
- Termine werden bei Bedarf aus der ZAW-API geholt (kein Cron) -- aber gecacht
  (siehe naechster Abschnitt), damit die ZAW-Server nicht ueberlastet werden.

---

## Schonung der ZAW-Server (Anforderung: ZAW nicht ueberlasten)

Das Projekt nutzt die ZAW-API als unkooperierter Dritter. Damit Crawler, Bots
oder massenhaftes Durchprobieren von Adressen **weder diese App noch die
ZAW-Server ueberlasten**, sind mehrere Schutzschichten aktiv:

1. **24h Edge-Cache (Vercel CDN):** `/feed` und alle `/api/*` antworten mit
   `Cache-Control: s-maxage=86400`. Wiederholte Abrufe **derselben URL**
   (z.B. Googles Kalender-Poller) werden vom CDN bedient und treffen weder die
   Function noch ZAW.
2. **24h In-Function-Cache:** Jede ZAW-Antwort (Gemeinden, Strassen, Tonnen,
   Termine) wird in der warmen Function-Instanz bis zu 24 h zwischengespeichert
   (`ZAW_CACHE_TTL`, Default `86400`). Identische Abfragen gehen nicht erneut zu ZAW.
3. **Best-effort Rate-Limit pro IP:** Standard 120 Anfragen/Minute/IP
   (`ZAW_RATE_PER_MIN`), danach `429 Too Many Requests`. Greift besonders gegen
   Cache-umgehende Adress-Enumeration. (Serverless-bedingt nur pro Instanz.)
4. **robots.txt:** verbietet wohlerzogenen Crawlern `/api/` und `/feed`.

**Empfehlung fuer Produktion:** zusaetzlich die **Vercel Firewall / WAF**
(Dashboard -> Firewall) als plattformweites Rate-Limit aktivieren -- das ist die
einzige instanzuebergreifende, wirklich harte Schranke.

Konfiguration per Umgebungsvariable:

| Variable | Default | Wirkung |
|---|---|---|
| `ZAW_CACHE_TTL` | `86400` | Cache-Dauer in Sekunden (`0` = aus) |
| `ZAW_RATE_PER_MIN` | `120` | Anfragen/Minute/IP (`0` = aus) |
| `ZAW_API_BASE` | (ZAW) | API-Basis ueberschreiben (Tests/Mock) |

---

## Tests (Selbst-Test, lokal -- vor dem Deploy)

Ein vollstaendiger Selbst-Test laeuft **offline**: ein Mock des ZAW-API und die
echte Vercel-Function werden lokal als HTTP-Server gestartet, ein **headless
Chromium** bedient den Picker. Es wird **kein** echter ZAW-Server getroffen und
nichts nach Vercel deployt.

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest            # alle Tests (Unit + HTTP + Browser)
python -m pytest -m "not ui" # nur ohne Browser
```

Abgedeckt:

- **Unit** (`tests/test_unit_build_ics.py`): RFC-5545-Struktur/Faltung, DST
  (22:00 lokal -> Winter 21:00Z / Sommer 20:00Z), stabile UIDs, eve/morn an/aus,
  exakte Abfalltyp-Filterung (`ZAW_REST_2W` vs `ZAW_REST_W`).
- **HTTP** (`tests/test_api_feed.py`): `/feed` und `/api/*`, Fehlerfaelle,
  Inhaltspruefung, Gemeinde ohne Strassen.
- **Browser** (`tests/test_picker_ui.py`): **alle** Kombinationen aus
  Abfalltyp-Teilmengen x Vorabend(6) x Abholtag(5), Korrektheit aller drei
  erzeugten URLs (Feed / Google / vorausgefuellt), tatsaechlicher Abruf der
  Feed-URLs und **Prefill-Roundtrip** (vorausgefuellte URL laden -> Auswahl exakt
  wiederhergestellt).
