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
3. Optional: Abfalltypen filtern, Erinnerungszeiten anpassen
4. Klicke **"+ Google Kalender"** oder kopiere die URL

Pro Abholung entstehen bis zu **zwei** Kalender-Eintraege:

- **morgens am Abholtag** -- ganztaegiger, sichtbarer Eintrag
- **Vorabend** (Standard 22:00) -- Termin mit VALARM ("Tonne rausstellen")

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
- Kein Caching noetig, kein Cron -- bei jedem Abruf werden live die aktuellen
  Termine geholt.
