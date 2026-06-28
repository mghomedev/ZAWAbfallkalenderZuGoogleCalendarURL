"""
Playwright-UI-Tests gegen die echte Seite (api/index.py INDEX_HTML) + Mock-ZAW.

Deckt ab:
  - Hausnummer-Modus: Dropdown (mit Hausnummern) und Freitext (ohne)
  - exhaustive URL-Erzeugung: alle Abfalltyp-Teilmengen x eve(6) x morn(5)
  - die drei erzeugten URLs (feed / google / vorausgefüllt) auf Korrektheit
  - die erzeugten Feed-URLs wirklich abrufen und Inhalt prüfen
  - Prefill-Roundtrip: vorausgefüllte URL laden -> Auswahl exakt wiederhergestellt
  - Gemeinde ohne Straßen
"""

from __future__ import annotations

from urllib.parse import urlencode, urlparse, parse_qs

import requests
import pytest
from playwright.sync_api import expect, TimeoutError as PlaywrightTimeout

from icsutil import unfold

pytestmark = pytest.mark.ui

EVE_OPTIONS = ["22:00", "21:00", "20:00", "19:00", "18:00", "off"]
MORN_OPTIONS = ["allday", "06:00", "07:00", "08:00", "off"]
TRASH = ["ZAW_BIO", "ZAW_GELB", "ZAW_PAP", "ZAW_REST_2W", "ZAW_REST_W", "ZAW_SCHAD"]


# --------------------------------------------------------------------------- #
# Navigations-Helfer
# --------------------------------------------------------------------------- #
def _open(page, app_server, query: str = ""):
    page.goto(app_server + "/" + (("?" + query) if query else ""))
    page.wait_for_function("document.querySelectorAll('#city option').length > 1",
                           timeout=10000)


def _pick_address_with_hn(page):
    """Testheim / Hauptstraße / Hausnummer 1 (Dropdown-Modus) -> Ergebnis sichtbar."""
    page.select_option("#city", label="Testheim")
    page.wait_for_function(
        "!document.querySelector('#street').disabled && "
        "document.querySelectorAll('#street option').length > 1", timeout=10000)
    page.select_option("#street", label="Hauptstraße")
    page.wait_for_selector("#hn-group", state="visible")
    assert page.eval_on_selector("#hn-group", "e => e.dataset.mode") == "select"
    page.select_option("#hn", value="1")
    _wait_result(page)


def _wait_result(page):
    page.wait_for_selector("#result.visible", timeout=10000)
    page.wait_for_function(
        "document.querySelectorAll('#trash-checks input').length === 6", timeout=10000)
    page.wait_for_function(
        "document.getElementById('url-box').textContent.includes('/feed?')", timeout=10000)


# --------------------------------------------------------------------------- #
# Hausnummer-Modi
# --------------------------------------------------------------------------- #
def test_housenumber_dropdown_mode(app_server, page):
    _open(page, app_server)
    page.select_option("#city", label="Testheim")
    page.wait_for_function("document.querySelectorAll('#street option').length > 1")
    page.select_option("#street", label="Hauptstraße")
    page.wait_for_selector("#hn-group", state="visible")
    assert page.eval_on_selector("#hn-group", "e => e.dataset.mode") == "select"
    nums = page.eval_on_selector_all("#hn option", "els => els.map(e => e.value).filter(Boolean)")
    assert nums == ["1", "2", "5"]


def test_housenumber_freetext_mode(app_server, page):
    """Frankensteiner Str. hat KEINE Hausnummern -> Freitextfeld (kein stilles nr=1)."""
    _open(page, app_server)
    page.select_option("#city", label="Testheim")
    page.wait_for_function("document.querySelectorAll('#street option').length > 1")
    page.select_option("#street", label="Frankensteiner Str.")
    page.wait_for_selector("#hn-group", state="visible")
    assert page.eval_on_selector("#hn-group", "e => e.dataset.mode") == "input"
    assert page.is_visible("#hn-input")
    assert page.is_hidden("#hn")
    page.fill("#hn-input", "56")
    page.dispatch_event("#hn-input", "input")
    _wait_result(page)
    feed = page.text_content("#url-box")
    qs = parse_qs(urlparse(feed).query)
    assert qs["nr"] == ["56"]
    assert qs["street"] == ["Frankensteiner Str."]


# --------------------------------------------------------------------------- #
# Exhaustive URL-Erzeugung: alle Teilmengen x eve x morn  (in-page, schnell)
# --------------------------------------------------------------------------- #
def test_exhaustive_url_generation(app_server, page):
    _open(page, app_server)
    _pick_address_with_hn(page)

    # Der gesamte Kreuzproduktraum wird im Browser durchlaufen; updateUrl() ist
    # die echte Produktionsfunktion. Wir prüfen, dass die erzeugten Query-Parameter
    # die Auswahl exakt widerspiegeln. Rückgabe: nur Fehlversuche.
    result = page.evaluate(
        """({eveOpts, mornOpts}) => {
            const cbs = [...document.querySelectorAll('#trash-checks input')];
            const eve = document.getElementById('eve-time');
            const morn = document.getElementById('morn-mode');
            const box = document.getElementById('url-box');
            const prefill = document.getElementById('btn-prefill');
            const gcal = document.getElementById('btn-gcal');
            const dl = document.getElementById('btn-dl');
            const fails = [];
            let total = 0;
            for (let mask = 0; mask < (1 << cbs.length); mask++) {
              const selected = [];
              cbs.forEach((cb, i) => { cb.checked = !!(mask & (1 << i)); if (cb.checked) selected.push(cb.value); });
              for (const ev of eveOpts) {
                for (const mo of mornOpts) {
                  eve.value = ev; morn.value = mo;
                  window.updateUrl();
                  total++;
                  const feed = box.textContent;
                  const u = new URL(feed);
                  const sp = u.searchParams;
                  const errs = [];
                  if (!feed.includes('/feed?')) errs.push('not a feed url');
                  if (sp.get('city') !== 'Testheim') errs.push('city');
                  if (sp.get('street') !== 'Hauptstraße') errs.push('street');
                  if (sp.get('nr') !== '1') errs.push('nr');
                  if (sp.get('eve') !== ev) errs.push('eve');
                  if (sp.get('morn') !== mo) errs.push('morn');
                  const typesParam = sp.get('types');
                  if (selected.length === 0) {
                    if (typesParam !== null) errs.push('types should be absent');
                  } else {
                    const got = (typesParam || '').split(',').filter(Boolean).sort().join(',');
                    const want = [...selected].sort().join(',');
                    if (got !== want) errs.push('types ' + got + ' != ' + want);
                  }
                  // prefill teilt denselben Querystring, nur Pfad '/' statt '/feed'
                  const pf = new URL(prefill.href);
                  if (pf.search !== u.search) errs.push('prefill query mismatch');
                  if (pf.pathname !== '/') errs.push('prefill path');
                  // gcal verweist auf die statische "Per URL hinzufügen"-Seite
                  // (Google prefüllt url= nicht zuverlässig; wir kopieren stattdessen)
                  if (gcal.href !== 'https://calendar.google.com/calendar/u/0/r/settings/addbyurl')
                    errs.push('gcal href ' + gcal.href);
                  // Download-Button zeigt immer auf die aktuelle Feed-URL (.ics)
                  if (dl.href !== feed) errs.push('dl href ' + dl.href);
                  if (!(dl.getAttribute('download') || '').endsWith('.ics')) errs.push('dl filename');
                  if (errs.length) fails.push({mask, ev, mo, errs});
                }
              }
            }
            return {total, fails: fails.slice(0, 25), failCount: fails.length};
        }""",
        {"eveOpts": EVE_OPTIONS, "mornOpts": MORN_OPTIONS},
    )
    assert result["total"] == (1 << len(TRASH)) * len(EVE_OPTIONS) * len(MORN_OPTIONS)
    assert result["failCount"] == 0, f"{result['failCount']} Fehlkombinationen, z.B.: {result['fails']}"


# --------------------------------------------------------------------------- #
# Die erzeugten Feed-URLs wirklich abrufen und Inhalt prüfen
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("selected,eve,morn,checks", [
    (["ZAW_BIO"], "22:00", "allday",
     {"has": ["Bioabfall"], "hasnot": ["Gelber Sack", "Restmüll"]}),
    (["ZAW_REST_2W"], "21:00", "allday",
     {"has": ["Restmüll Tonnen und Container 14-täglich"],
      "hasnot": ["Restmüll Container wöchentlich"]}),
    (["ZAW_REST_W"], "22:00", "off",
     {"has": ["Restmüll Container wöchentlich"],
      "hasnot": ["Restmüll Tonnen und Container 14-täglich", "Abholung"]}),
    (TRASH, "off", "allday",
     {"has": ["Bioabfall"], "hasnot": ["Tonne rausstellen"]}),
])
def test_generated_feed_urls_are_correct(app_server, page, selected, eve, morn, checks):
    _open(page, app_server)
    _pick_address_with_hn(page)
    feed = page.evaluate(
        """({selected, eve, morn}) => {
            const cbs = [...document.querySelectorAll('#trash-checks input')];
            cbs.forEach(cb => cb.checked = selected.includes(cb.value));
            document.getElementById('eve-time').value = eve;
            document.getElementById('morn-mode').value = morn;
            window.updateUrl();
            return document.getElementById('url-box').textContent;
        }""",
        {"selected": selected, "eve": eve, "morn": morn},
    )
    # Genau diese vom Browser erzeugte URL abrufen
    r = requests.get(feed, timeout=10)
    assert r.status_code == 200, feed
    body = unfold(r.text)
    for s in checks["has"]:
        assert s in body, f"'{s}' fehlt in {feed}"
    for s in checks["hasnot"]:
        assert s not in body, f"'{s}' sollte fehlen in {feed}"


# --------------------------------------------------------------------------- #
# Prefill-Roundtrip: vorausgefüllte URL laden -> Auswahl exakt wiederhergestellt
# --------------------------------------------------------------------------- #
def _state(page):
    return {
        "checked": sorted(page.eval_on_selector_all(
            "#trash-checks input", "els => els.filter(e=>e.checked).map(e=>e.value)")),
        "eve": page.eval_on_selector("#eve-time", "e => e.value"),
        "morn": page.eval_on_selector("#morn-mode", "e => e.value"),
        "feed": page.text_content("#url-box"),
    }


ROUNDTRIP_CASES = [
    dict(city="Testheim", street="Hauptstraße", nr="1",
         types=["ZAW_BIO", "ZAW_GELB"], eve="21:00", morn="allday"),
    dict(city="Testheim", street="Hauptstraße", nr="2",
         types=["ZAW_REST_2W"], eve="22:00", morn="off"),
    dict(city="Testheim", street="Hauptstraße", nr="5",
         types=TRASH, eve="off", morn="06:00"),
    dict(city="Testheim", street="Frankensteiner Str.", nr="56",
         types=["ZAW_BIO"], eve="20:00", morn="allday"),
]


@pytest.mark.parametrize("case", ROUNDTRIP_CASES,
                         ids=lambda c: f"{c['street']}-{','.join(c['types'])}-{c['eve']}-{c['morn']}")
def test_prefill_roundtrip(app_server, page, case):
    query = urlencode({
        "city": case["city"], "street": case["street"], "nr": case["nr"],
        "types": ",".join(case["types"]), "eve": case["eve"], "morn": case["morn"],
    })
    _open(page, app_server, query)
    _wait_result(page)
    st = _state(page)

    # Abfalltypen exakt wiederhergestellt (DAS ist der wiederkehrende Bug)
    assert st["checked"] == sorted(case["types"]), \
        f"Checkboxen falsch wiederhergestellt: {st['checked']} != {sorted(case['types'])}"
    # eve/morn wiederhergestellt
    assert st["eve"] == case["eve"]
    assert st["morn"] == case["morn"]
    # Idempotenz: regenerierte Feed-URL spiegelt die Auswahl exakt
    qs = parse_qs(urlparse(st["feed"]).query)
    assert qs["city"] == [case["city"]]
    assert qs["nr"] == [case["nr"]]
    assert qs["eve"] == [case["eve"]]
    assert qs["morn"] == [case["morn"]]
    assert sorted(qs["types"][0].split(",")) == sorted(case["types"])


# --------------------------------------------------------------------------- #
# Vorschau (FullCalendar + ical.js, selbst geparst) + ZAW-Farben
# --------------------------------------------------------------------------- #
# Exakte ZAW-Tonnenfarben (wie von der API geliefert / normalisiert).
ZAW_HEX = {
    "ZAW_BIO": "#008d34", "ZAW_GELB": "#fecb00", "ZAW_PAP": "#0061a6",
    "ZAW_REST_2W": "#2f3639", "ZAW_REST_W": "#9e9e9e", "ZAW_SCHAD": "#e3000e",
}


def _hex_to_rgb(h: str) -> str:
    h = h.lstrip("#")
    return f"rgb({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)})"


def _known_color_ics() -> str:
    """Selbst erzeugter ICS-Kalender: pro Abfalltyp ein ganztägiger Termin im
    AKTUELLEN Monat mit eingebetteter X-ZAW-COLOR. Dient als deterministisches
    'Mock'-ICS, um die farbige Anzeige in der Vorschau zu prüfen."""
    import datetime as _dt
    base = _dt.date.today().replace(day=10)  # sicher im aktuellen Monat
    entries = [
        ("Bioabfall", "008d34"),
        ("Gelber Sack", "fecb00"),
        ("Papier", "0061a6"),
        ("Restmüll 14-täglich", "2f3639"),
        ("Restmüll wöchentlich", "9e9e9e"),
        ("Schadstoffmobil", "e3000e"),
    ]
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//known-ics//DE"]
    for i, (title, hexc) in enumerate(entries):
        d = base + _dt.timedelta(days=i)
        nxt = d + _dt.timedelta(days=1)
        L += [
            "BEGIN:VEVENT",
            f"UID:known-{i}@test.local",
            f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{nxt.strftime('%Y%m%d')}",
            f"SUMMARY:{title}",
            f"X-ZAW-COLOR:#{hexc}",
            "END:VEVENT",
        ]
    L.append("END:VCALENDAR")
    return "\r\n".join(L) + "\r\n"


def test_trash_checkboxes_show_api_colors(app_server, page):
    """Jede Abfalltyp-Checkbox trägt einen Swatch in der exakten ZAW-Farbe."""
    _open(page, app_server)
    _pick_address_with_hn(page)
    data = page.evaluate(
        """() => [...document.querySelectorAll('#trash-checks label')].map(l => {
            const cb = l.querySelector('input');
            const sw = l.querySelector('.swatch');
            return { name: cb.value, color: sw ? getComputedStyle(sw).backgroundColor : '' };
        })""")
    got = {d["name"]: d["color"] for d in data}
    for name, hexc in ZAW_HEX.items():
        assert got.get(name) == _hex_to_rgb(hexc), f"{name}: {got.get(name)} != {hexc}"


def test_preview_renders_feed_events(app_server, page):
    """Die Vorschau lädt die Feed-URL, parst sie selbst (ical.js) und rendert.

    Übersprungen, falls das CDN im Test-Netz nicht erreichbar ist.
    """
    _open(page, app_server)
    _pick_address_with_hn(page)
    page.click("#btn-preview")
    try:
        # FullCalendar rendert seine Toolbar in #calendar (Klasse fc-toolbar)
        page.wait_for_function(
            "typeof FullCalendar !== 'undefined' "
            "&& typeof ICAL !== 'undefined' "
            "&& document.querySelector('#calendar .fc-toolbar')", timeout=20000)
    except PlaywrightTimeout:
        pytest.skip("FullCalendar-CDN im Test-Netz nicht erreichbar")

    assert page.is_visible("#calendar .fc-toolbar")  # FullCalendar gerendert

    # Verifiziert, dass unsere echte Parserfunktion den Feed in Events umsetzt.
    feed = page.text_content("#url-box")
    count = page.evaluate(
        """async (url) => {
            const ics = await (await fetch(url)).text();
            return (typeof _icsToEvents === 'function') ? _icsToEvents(ics).length : -1;
        }""", feed)
    assert count > 0, "Vorschau lud keine Events aus dem Feed"


def test_preview_colors_events_like_zaw(app_server, page):
    """Vorschau-Termine werden je Abfalltyp in der exakten ZAW-Farbe angezeigt.

    Wir mocken den Feed mit einem selbst erzeugten, bekannten ICS (ein Termin
    pro Typ inkl. X-ZAW-COLOR) und prüfen die tatsächlich gerenderten Farben.
    """
    _open(page, app_server)
    _pick_address_with_hn(page)

    ics = _known_color_ics()
    page.route("**/feed*", lambda route: route.fulfill(
        status=200, content_type="text/calendar; charset=utf-8", body=ics))

    page.click("#btn-preview")
    try:
        page.wait_for_function(
            "typeof FullCalendar !== 'undefined' && typeof ICAL !== 'undefined' "
            "&& document.querySelectorAll('#calendar .fc-list-event').length >= 6",
            timeout=20000)
    except PlaywrightTimeout:
        pytest.skip("FullCalendar-CDN im Test-Netz nicht erreichbar")

    rows = page.evaluate(
        """() => [...document.querySelectorAll('#calendar .fc-list-event')].map(r => {
            const t = r.querySelector('.fc-list-event-title');
            const dot = r.querySelector('.fc-list-event-dot');
            return { title: t ? t.textContent.trim() : '',
                     color: dot ? getComputedStyle(dot).borderTopColor : '' };
        })""")
    titles = {r["title"]: r["color"] for r in rows}

    expect_map = {
        "Bioabfall": "#008d34",
        "Gelber Sack": "#fecb00",
        "Papier": "#0061a6",
        "Restmüll 14-täglich": "#2f3639",
        "Restmüll wöchentlich": "#9e9e9e",
        "Schadstoffmobil": "#e3000e",
    }
    for title, hexc in expect_map.items():
        color = next((c for t, c in titles.items() if title in t), None)
        assert color is not None, f"Termin '{title}' fehlt in der Vorschau: {titles}"
        assert color == _hex_to_rgb(hexc), \
            f"{title}: angezeigt {color}, erwartet {_hex_to_rgb(hexc)} ({hexc})"

    # Die beiden Restmüll-Typen MÜSSEN sich farblich unterscheiden (ZAW-Vorgabe).
    rest_2w = next(c for t, c in titles.items() if "14-täglich" in t)
    rest_w = next(c for t, c in titles.items() if "wöchentlich" in t)
    assert rest_2w != rest_w, f"Restmüll-Typen gleich gefärbt: {rest_2w}"


def test_download_button_serves_ics(app_server, page):
    """Der 'iCal herunterladen'-Button zeigt auf die aktuelle Feed-URL und
    erzwingt via download-Attribut eine .ics-Datei (same-origin)."""
    _open(page, app_server)
    _pick_address_with_hn(page)
    info = page.eval_on_selector(
        "#btn-dl", "e => ({href: e.href, dl: e.getAttribute('download')})")
    feed = page.text_content("#url-box")
    assert info["href"] == feed, f"Download zeigt nicht auf die Feed-URL: {info['href']}"
    assert info["dl"].endswith(".ics")
    assert "Testheim" in info["dl"]  # sprechender Dateiname
    # die verlinkte Datei ist wirklich ein gültiger ICS-Kalender
    r = requests.get(info["href"], timeout=10)
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in r.text


# --------------------------------------------------------------------------- #
# Stale-Result / Gemeinde ohne Straßen
# --------------------------------------------------------------------------- #


def _result_visible(page):
    return page.eval_on_selector("#result", "e => e.classList.contains('visible')")


def test_clearing_city_resets_stale_result(app_server, page):
    """Nach Leeren der Gemeinde darf das Anpassen eines Erinnerungs-Dropdowns
    nicht das Ergebnis der ALTEN Adresse wieder einblenden."""
    _open(page, app_server)
    _pick_address_with_hn(page)
    assert _result_visible(page)

    page.select_option("#city", value="")          # zurück auf "-- Gemeinde wählen --"
    assert not _result_visible(page)
    page.select_option("#eve-time", value="21:00")  # Erinnerungs-Dropdown anfassen
    assert not _result_visible(page), "veraltetes Ergebnis erschien erneut"


def test_city_without_streets_ui(app_server, page):
    _open(page, app_server)
    page.select_option("#city", label="Inselstadt")
    _wait_result(page)
    feed = page.text_content("#url-box")
    qs = parse_qs(urlparse(feed).query)
    assert qs["city"] == ["Inselstadt"]
    assert "street" not in qs
    # und die URL liefert tatsächlich einen Feed
    r = requests.get(feed, timeout=10)
    assert r.status_code == 200, feed
    assert "BEGIN:VCALENDAR" in r.text
