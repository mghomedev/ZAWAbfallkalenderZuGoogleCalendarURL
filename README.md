# ZAWAbfallkalenderZuGoogleCalendarURL

Konvertiert die ZAW-Abfuhrtermine (Landkreis Darmstadt-Dieburg) in eine
abonnierbare Google-Kalender-URL. Gehostet als **Vercel Serverless Function** –
die Adresse wird einfach als URL-Parameter übergeben.

> **Disclaimer:** Dieser Code wurde von Claude Code erzeugt und ist ein reines
> Hobby-Projekt ohne jegliche Kooperation mit ZAW. Jegliche Nutzung ist auf
> eigene Gefahr, ohne jegliche Garantie auf Funktionstüchtigkeit und ohne
> Garantie auf Hilfe bei dadurch auftretenden Problemen. Es kann jederzeit
> aufhören zu funktionieren, wenn z.B. die ZAW ihr API ändert oder die Nutzung
> ihres APIs auf diese Weise nicht mehr möchte.

---

## So funktioniert's

Pro Abholung entstehen **zwei** Kalender-Einträge:

- **morgens am Abholtag** – ganztägiger, sichtbarer Eintrag
- **Vorabend 22:00** – Termin mit VALARM („Tonne rausstellen")

> **Hinweis:** Google ignoriert VALARM in abonnierten Kalendern. Die 22-Uhr-Einträge
> sind sichtbar, piepen aber nicht. Apple Kalender und Thunderbird ehren VALARM.

---

## Schnellstart

### 1. Kalender-URL zusammenbauen

```
https://zawabfallkalenderzugooglecalendarurl.vercel.app/feed?city=GEMEINDE&street=STRASSE&nr=HAUSNUMMER
```

| Parameter | Beispiel | Beschreibung |
|---|---|---|
| `city` | `Meine-Gemeinde` | ZAW-Gemeindename |
| `street` | `Musterstraße` | Straßenname |
| `nr` | `1` | Hausnummer |
| `name` | `Abfall (ZAW)` | _(optional)_ Kalender-Anzeigename |

### 2. In Google Kalender abonnieren

1. https://calendar.google.com/calendar/u/0/r/settings/addbyurl
2. Deine URL von oben einfügen.
3. „Kalender hinzufügen".

Google pollt den Feed alle ~8–24 h automatisch. Bei jedem Poll werden die
aktuellen Termine frisch von der ZAW-API geholt.

---

## Selbst deployen

### Vercel (empfohlen)

1. Repository forken
2. In Vercel importieren (vercel.com → „Add New Project" → GitHub-Repo wählen)
3. Fertig – Vercel deployt automatisch bei jedem Push

### Lokal testen

```bash
cp .env.example .env && $EDITOR .env

python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python3 zaw_ics_gen.py --discover     # Adresse/IDs/Termine prüfen
python3 zaw_ics_gen.py --stdout       # ICS zur Sichtprüfung
```

---

## Technik

- `zaw_ics_gen.py` – Kernlogik: fragt die jumomind-API (`zaw.jumomind.com`) ab,
  erzeugt eine RFC-5545-konforme ICS-Datei.
- `api/feed.py` – Vercel Serverless Function: nimmt URL-Parameter entgegen,
  ruft die Kernlogik auf, liefert `text/calendar` zurück.
- Kein Caching nötig, kein Cron – bei jedem Abruf werden live die aktuellen
  Termine geholt.
