#!/usr/bin/env python3
"""
zaw_ics_gen.py
==============
Erzeugt eine .ics-Datei (iCalendar-Feed) für die ZAW-Abfuhrtermine
einer konkreten Adresse (Backend: jumomind, Landkreis Darmstadt-Dieburg).

Pro Abholung werden ZWEI VEVENTs erzeugt:
  1) MORGENS am Abholtag      -> ganztägiger, sichtbarer Eintrag
  2) ABENDS am Vortag, 22:00  -> getimter Eintrag inkl. VALARM (Ton/Anzeige)

Kann als CLI-Tool oder als Bibliothek (von der Vercel-Function) genutzt werden.

WICHTIG: Google ignoriert VALARM in ABONNIERTEN Kalendern. Die 22-Uhr-Einträge
sind dort sichtbar, der TON kommt in Google aber nicht zuverlässig aus dem Feed.
Andere Clients (Apple, Thunderbird) ehren VALARM.

CLI-Aufruf:
  python3 zaw_ics_gen.py --discover            # Adresse/IDs/Termine prüfen
  python3 zaw_ics_gen.py --stdout              # ICS auf die Konsole
  python3 zaw_ics_gen.py -o /var/www/feed.ics  # ICS in Datei schreiben

HINWEIS: Dieser Code wurde von Claude Code erzeugt und ist ein reines Hobby-Projekt
ohne jegliche Kooperation mit ZAW. Jegliche Nutzung ist auf eigene Gefahr, ohne
jegliche Garantie auf Funktionstüchtigkeit und ohne Garantie auf Hilfe bei dadurch
auftretenden Problemen. Es kann jederzeit aufhören zu funktionieren, wenn z.B. die
ZAW ihr API ändert oder die Nutzung ihres APIs auf diese Weise nicht mehr möchte.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import logging
import os
import sys
import tempfile
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")
log = logging.getLogger("zaw_ics")

EMOJI_MAP = [
    ("bio", "\U0001f7e4 Biotonne"),
    ("papier", "\U0001f535 Papier"),
    ("gelb", "\U0001f7e1 Gelber Sack"),
    ("restm", "\u26ab Restm\u00fcll"),
    ("schadstoff", "\u2623\ufe0f Schadstoffmobil"),
]

API_URL = "https://{provider}.jumomind.com/mmapp/api.php"


def api_base(service_id: str) -> str:
    """API-Basis-URL. Über ZAW_API_BASE überschreibbar (z.B. für Tests/Mock)."""
    override = os.environ.get("ZAW_API_BASE")
    return override if override else API_URL.format(provider=service_id)

# --------------------------------------------------------------------------- #
# Defaults für optionale Parameter
# --------------------------------------------------------------------------- #
DEFAULTS = {
    "service_id": "zaw",
    "cal_name": "Abfall (ZAW)",
    "morning_all_day": True,
    "morning_time": "06:00",
    "evening_time": "22:00",
    "evening_offset_days": 1,
    "event_duration_min": 15,
    "alarm_min_before": 0,
    "days_back": 7,
    "days_ahead": 400,
    "uid_domain": "zaw-abfall.local",
}


# --------------------------------------------------------------------------- #
# .env-Loader (nur für CLI-Modus)
# --------------------------------------------------------------------------- #
def _load_dotenv(path: str | None = None) -> None:
    """Minimaler .env-Loader (kein externes Paket nötig)."""
    p = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(p):
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            os.environ.setdefault(key, value)


# --------------------------------------------------------------------------- #
# jumomind-API
# --------------------------------------------------------------------------- #
def _norm_street(v: str | None) -> str | None:
    if not v:
        return None
    return v.lower().strip().casefold().replace("straße", "strasse").replace("str.", "strasse")


def resolve_address(
    session: requests.Session,
    service_id: str,
    city: str,
    street: str,
    house_number: str,
) -> tuple[str, str]:
    """Löst Gemeinde + Straße(+Hausnr.) in (city_id, area_id) auf."""
    api = api_base(service_id)
    city_lower = city.lower().strip()
    house = house_number.lower().strip().lstrip("0") or None

    cities = session.get(api, params={"r": "cities_web"}, timeout=30).json()
    city_id = area_id = None
    has_streets = True
    for c in cities:
        if c["name"].lower().strip() == city_lower or c["_name"].lower().strip() == city_lower:
            city_id, area_id, has_streets = c["id"], c["area_id"], c["has_streets"]
            break
    if city_id is None:
        available = ", ".join(sorted(c["name"] for c in cities))
        raise ValueError(f"Gemeinde '{city}' nicht gefunden. Verfügbar: {available}")

    if has_streets:
        streets = session.get(api, params={"r": "streets", "city_id": city_id}, timeout=30).json()
        match = None
        for st in streets:
            if _norm_street(st["name"]) == _norm_street(street) or \
               _norm_street(st.get("_name")) == _norm_street(street):
                match = st
                break
        if match is None:
            sug = sorted({st.get("name") for st in streets} - {None})
            raise ValueError(f"Straße '{street}' nicht gefunden. Vorschläge: {', '.join(sug)}")
        area_id = match["area_id"]
        if house and "houseNumbers" in match:
            for hn in match["houseNumbers"]:
                if hn[0].lower().strip().lstrip("0") == house:
                    area_id = hn[1]
                    break
            else:
                log.warning("Hausnummer %s nicht exakt gefunden – nutze Straßen-Zone %s", house, area_id)
    return city_id, area_id


def fetch_trash_names(session: requests.Session, service_id: str, city_id, area_id) -> dict[str, str]:
    api = api_base(service_id)
    data = session.get(api, params={"r": "trash", "city_id": city_id, "area_id": area_id}, timeout=30).json()
    m: dict[str, str] = {}
    for b in data:
        m[b["name"]] = b["title"]
        m.setdefault(b["_name"], b["title"])
    return m


def fetch_dates(session: requests.Session, service_id: str, city_id, area_id, names) -> list[tuple[dt.date, str]]:
    api = api_base(service_id)
    data = session.get(api, params={"r": "dates/0", "city_id": city_id, "area_id": area_id, "ws": 3},
                       timeout=30).json()
    out = [(dt.datetime.strptime(e["day"], "%Y-%m-%d").date(),
            names.get(e["trash_name"], e["trash_name"])) for e in data]
    out.sort()
    return out


def fetch_trash_types(session: requests.Session, service_id: str, city_id, area_id) -> list[dict]:
    """Gibt die verfügbaren Abfalltypen als Liste von {name, title} zurück."""
    api = api_base(service_id)
    data = session.get(api, params={"r": "trash", "city_id": city_id, "area_id": area_id}, timeout=30).json()
    return [{"name": b["name"], "title": b["title"]} for b in data]


def filter_dates_by_trash(
    dates: list[tuple[dt.date, str]],
    names: dict[str, str],
    trash_filter: list[str] | None,
) -> list[tuple[dt.date, str]]:
    """Filtert die Terminliste auf die gewünschten Abfalltypen.

    `trash_filter` ist eine Liste von Schlüsseln. Bevorzugt exakte API-Namen
    (z.B. "ZAW_REST_2W"), akzeptiert aber auch Teil-Schlüssel (z.B. "bio").
    Ein Schlüssel matcht einen Abfalltyp, wenn er (case-insensitiv) gleich dem
    API-Namen ist, ein Substring des API-Namens ist, oder ein Substring des
    Titels ist. Ohne Filter wird die Liste unverändert zurückgegeben.

    Reine Funktion – ohne Netzwerk, unit-testbar.
    """
    if not trash_filter:
        return dates
    keys = [k.lower() for k in trash_filter]
    allowed = set()
    for api_name, title in names.items():
        an, tl = api_name.lower(), title.lower()
        if any(k == an or k in an or k in tl for k in keys):
            allowed.add(title)
    return [(d, t) for d, t in dates if t in allowed]


def get_schedule(
    service_id: str,
    city: str,
    street: str,
    house_number: str,
    trash_filter: list[str] | None = None,
) -> tuple[list[tuple[dt.date, str]], str, str]:
    """Holt den Abfuhrplan für eine Adresse. Gibt (dates, city_id, area_id) zurück.

    trash_filter: siehe filter_dates_by_trash().
    """
    s = requests.Session()
    s.headers.update({"Accept-Encoding": "identity"})
    city_id, area_id = resolve_address(s, service_id, city, street, house_number)
    names = fetch_trash_names(s, service_id, city_id, area_id)
    dates = fetch_dates(s, service_id, city_id, area_id, names)
    dates = filter_dates_by_trash(dates, names, trash_filter)
    return dates, city_id, area_id


def pretty_label(title: str) -> str:
    low = title.lower()
    for key, label in EMOJI_MAP:
        if key in low:
            return label
    return f"\U0001f5d1 {title}"


# --------------------------------------------------------------------------- #
# ICS-Erzeugung (RFC 5545, ohne externe Abhängigkeit)
# --------------------------------------------------------------------------- #
def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))


def _fold(line: str) -> str:
    """RFC5545-Zeilenfaltung nach 75 Oktetts (UTF-8-sicher)."""
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        e = ch.encode("utf-8")
        if len(cur) + len(e) > 75:
            out.append(cur.decode("utf-8"))
            cur = b" " + e
        else:
            cur += e
    out.append(cur.decode("utf-8"))
    return "\r\n".join(out)


def _uid(day: dt.date, title: str, slot: str, uid_domain: str) -> str:
    h = hashlib.sha1(f"{day.isoformat()}|{title}|{slot}".encode()).hexdigest()[:16]
    return f"{slot}-{h}@{uid_domain}"


def _dt_utc(d: dt.date, hh: int, mm: int) -> str:
    local = dt.datetime.combine(d, dt.time(hh, mm), TZ)
    return local.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_ics(
    dates: list[tuple[dt.date, str]],
    *,
    cal_name: str = DEFAULTS["cal_name"],
    uid_domain: str = DEFAULTS["uid_domain"],
    morning_enabled: bool = True,
    morning_all_day: bool = DEFAULTS["morning_all_day"],
    morning_time: str = DEFAULTS["morning_time"],
    evening_enabled: bool = True,
    evening_time: str = DEFAULTS["evening_time"],
    evening_offset_days: int = DEFAULTS["evening_offset_days"],
    event_duration_min: int = DEFAULTS["event_duration_min"],
    alarm_min_before: int = DEFAULTS["alarm_min_before"],
    days_back: int = DEFAULTS["days_back"],
    days_ahead: int = DEFAULTS["days_ahead"],
    now: dt.datetime | None = None,
) -> str:
    """Erzeugt den ICS-String aus einer Terminliste."""
    now = now or dt.datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    today = now.astimezone(TZ).date()
    lo = today - dt.timedelta(days=days_back)
    hi = today + dt.timedelta(days=days_ahead)

    morn_h, morn_m = (int(x) for x in morning_time.split(":"))
    eve_h, eve_m = (int(x) for x in evening_time.split(":"))
    dur = event_duration_min

    L = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ZAWAbfallkalenderZuGoogleCalendarURL//ics-feed//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(cal_name)}",
        "X-WR-TIMEZONE:Europe/Berlin",
        "X-PUBLISHED-TTL:PT12H",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
    ]

    for day, title in dates:
        if not (lo <= day <= hi):
            continue
        label = pretty_label(title)

        # --- 1) Eintrag am Abholtag (morgens / ganztägig) ---
        if morning_enabled:
            L.append("BEGIN:VEVENT")
            L.append(f"UID:{_uid(day, title, 'm', uid_domain)}")
            L.append(f"DTSTAMP:{stamp}")
            if morning_all_day:
                L.append(f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}")
                L.append(f"DTEND;VALUE=DATE:{(day + dt.timedelta(days=1)).strftime('%Y%m%d')}")
                L.append("TRANSP:TRANSPARENT")
            else:
                L.append(f"DTSTART:{_dt_utc(day, morn_h, morn_m)}")
                end = (dt.datetime.combine(day, dt.time(morn_h, morn_m), TZ)
                       + dt.timedelta(minutes=dur)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
                L.append(f"DTEND:{end}")
            L.append(f"SUMMARY:{_esc(label + ' – Abholung')}")
            L.append(f"DESCRIPTION:{_esc(title + ' · Quelle: ZAW (zaw-online.de)')}")
            L.append("END:VEVENT")

        # --- 2) Erinnerung am Vorabend (mit VALARM) ---
        if evening_enabled:
            eday = day - dt.timedelta(days=evening_offset_days)
            if eday < lo:
                continue
            L.append("BEGIN:VEVENT")
            L.append(f"UID:{_uid(day, title, 'e', uid_domain)}")
            L.append(f"DTSTAMP:{stamp}")
            L.append(f"DTSTART:{_dt_utc(eday, eve_h, eve_m)}")
            end = (dt.datetime.combine(eday, dt.time(eve_h, eve_m), TZ)
                   + dt.timedelta(minutes=dur)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
            L.append(f"DTEND:{end}")
            L.append(f"SUMMARY:{_esc('🔔 ' + label + ' morgen früh – Tonne rausstellen')}")
            morgen = day.strftime("%a %d.%m.")
            desc = (f"Morgen ({morgen}) wird abgeholt: {title}. "
                    "ZAW sammelt z.T. ab 05:00 Uhr \u2013 heute Abend bereitstellen.")
            L.append(f"DESCRIPTION:{_esc(desc)}")
            L.append("BEGIN:VALARM")
            L.append("ACTION:DISPLAY")
            L.append("DESCRIPTION:Tonne rausstellen")
            L.append(f"TRIGGER:-PT{alarm_min_before}M")
            L.append("END:VALARM")
            L.append("END:VEVENT")

    L.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in L) + "\r\n"


def write_atomic(path: str, content: str) -> None:
    """Atomar schreiben, damit ein gerade pollender Client nie eine halbe Datei sieht."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "ja", "on")


def discover() -> None:
    city = _env("CITY")
    street = _env("STREET")
    house = _env("HOUSE_NUMBER")
    service_id = _env("SERVICE_ID", "zaw")
    dates, city_id, area_id = get_schedule(service_id, city, street, house)
    print(f"Gemeinde : {city}")
    print(f"Stra\u00dfe   : {street} {house}")
    print(f"city_id  : {city_id}")
    print(f"area_id  : {area_id}")
    today = dt.date.today()
    print(f"\nN\u00e4chste Termine:")
    shown = 0
    for day, title in dates:
        if day < today:
            continue
        print(f"  {day.strftime('%a %d.%m.%Y')}  {pretty_label(title)}")
        shown += 1
        if shown >= 12:
            break


def main() -> None:
    _load_dotenv()

    ap = argparse.ArgumentParser(description="ZAW-Abfuhrtermine -> .ics-Feed")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--stdout", action="store_true", help="ICS auf stdout statt in Datei")
    ap.add_argument("-o", "--output", help="Zielpfad")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    required = ["CITY", "STREET", "HOUSE_NUMBER"]
    missing = [k for k in required if not _env(k)]
    if missing:
        raise SystemExit(
            f"Pflichtfelder nicht gesetzt: {', '.join(missing)}\n"
            "Bitte .env-Datei anlegen (siehe .env.example)."
        )

    try:
        if args.discover:
            discover()
            return

        service_id = _env("SERVICE_ID", "zaw")
        city = _env("CITY")
        street = _env("STREET")
        house = _env("HOUSE_NUMBER")
        cal_name = _env("CAL_NAME", DEFAULTS["cal_name"])

        dates, city_id, area_id = get_schedule(service_id, city, street, house)
        ics = build_ics(
            dates,
            cal_name=cal_name,
            uid_domain=_env("UID_DOMAIN", DEFAULTS["uid_domain"]),
            morning_all_day=_env_bool("MORNING_ALL_DAY", DEFAULTS["morning_all_day"]),
            morning_time=_env("MORNING_TIME", DEFAULTS["morning_time"]),
            evening_time=_env("EVENING_TIME", DEFAULTS["evening_time"]),
            evening_offset_days=int(_env("EVENING_OFFSET_DAYS", str(DEFAULTS["evening_offset_days"]))),
            event_duration_min=int(_env("EVENT_DURATION_MIN", str(DEFAULTS["event_duration_min"]))),
            alarm_min_before=int(_env("ALARM_MIN_BEFORE", str(DEFAULTS["alarm_min_before"]))),
            days_back=int(_env("DAYS_BACK", str(DEFAULTS["days_back"]))),
            days_ahead=int(_env("DAYS_AHEAD", str(DEFAULTS["days_ahead"]))),
        )
        if args.stdout:
            sys.stdout.write(ics)
        else:
            out = args.output or _env("OUTPUT", "abfall.ics")
            write_atomic(out, ics)
            n = ics.count("BEGIN:VEVENT")
            log.info("Feed geschrieben: %s (%d VEVENTs, city_id=%s area_id=%s)",
                     out, n, city_id, area_id)
    except requests.RequestException as ex:
        log.error("Netzwerk-/API-Fehler bei jumomind: %s", ex)
        sys.exit(2)


if __name__ == "__main__":
    main()
