"""
HTTP-Tests gegen die echte Vercel-Function (api/index.py) über den lokalen
Server + Mock-ZAW. Prüft Endpunkte, Feed-Inhalt und Parameter-Logik.
"""

from __future__ import annotations

import requests
import pytest

from icsutil import unfold


# --------------------------------------------------------------------------- #
# JSON-Endpunkte
# --------------------------------------------------------------------------- #
def test_cities_shape_and_sorted(app_server):
    data = requests.get(app_server + "/api/cities", timeout=10).json()
    assert isinstance(data, list) and data
    names = [c["name"] for c in data]
    assert names == sorted(names)
    for c in data:
        assert {"id", "name", "area_id", "has_streets"} <= set(c)


def test_streets_with_and_without_housenumbers(app_server):
    data = requests.get(app_server + "/api/streets",
                        params={"city_id": "100"}, timeout=10).json()
    by_name = {s["name"]: s for s in data}
    assert by_name["Hauptstraße"]["house_numbers"], "sollte Hausnummern haben"
    assert by_name["Frankensteiner Str."]["house_numbers"] == [], "keine Hausnummern"


def test_streets_requires_city_id(app_server):
    r = requests.get(app_server + "/api/streets", timeout=10)
    assert r.status_code == 400


def test_trash_endpoint(app_server):
    data = requests.get(app_server + "/api/trash",
                        params={"city_id": "100", "area_id": "201"}, timeout=10).json()
    names = [t["name"] for t in data]
    assert names == ["ZAW_BIO", "ZAW_GELB", "ZAW_PAP",
                     "ZAW_REST_2W", "ZAW_REST_W", "ZAW_SCHAD"]


def test_trash_requires_params(app_server):
    assert requests.get(app_server + "/api/trash",
                        params={"city_id": "100"}, timeout=10).status_code == 400


def test_unknown_path_404(app_server):
    assert requests.get(app_server + "/nope", timeout=10).status_code == 404


def test_landing_page_has_preview_assets(app_server):
    """Landing Page bindet FullCalendar + ical.js (ES5) ein und hat #calendar."""
    html = requests.get(app_server + "/", timeout=10).text
    assert "fullcalendar@6" in html
    assert "@fullcalendar/icalendar@6" in html
    assert "ical.es5.min.cjs" in html  # ES5-Build registriert globales ICAL
    assert 'id="calendar"' in html
    assert 'id="btn-preview"' in html


def test_landing_page_gcal_button_static(app_server):
    """Google-Button verweist auf die Add-by-URL-Seite (kein unzuverlässiges url=)."""
    html = requests.get(app_server + "/", timeout=10).text
    assert "addbyurl" in html
    assert 'onclick="gcalClick()"' in html


# --------------------------------------------------------------------------- #
# Feed: Pflichtparameter & Fehlerfälle
# --------------------------------------------------------------------------- #
def test_feed_missing_params_400(app_server):
    r = requests.get(app_server + "/feed", params={"city": "Testheim"}, timeout=10)
    assert r.status_code == 400


def test_feed_unknown_city_404(app_server):
    r = requests.get(app_server + "/feed",
                     params={"city": "Nirgendwo", "street": "X", "nr": "1"}, timeout=10)
    assert r.status_code == 404
    assert "nicht gefunden" in r.text


def test_feed_unknown_street_404(app_server):
    r = requests.get(app_server + "/feed",
                     params={"city": "Testheim", "street": "Gibtsnicht", "nr": "1"},
                     timeout=10)
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Feed: Inhalt & Header
# --------------------------------------------------------------------------- #
def test_feed_basic_content(app_server):
    r = requests.get(app_server + "/feed",
                     params={"city": "Testheim", "street": "Hauptstraße", "nr": "1"},
                     timeout=10)
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/calendar")
    assert "Cache-Control" in r.headers
    body = r.text
    assert "BEGIN:VCALENDAR" in body and "END:VCALENDAR" in body
    assert "BEGIN:VEVENT" in body


def test_feed_name_param_sets_calname(app_server):
    r = requests.get(app_server + "/feed",
                     params={"city": "Testheim", "street": "Hauptstraße", "nr": "1",
                             "name": "Mein Müll"}, timeout=10)
    assert "X-WR-CALNAME:Mein Müll" in r.text


def test_feed_eve_off_no_reminder(app_server):
    r = requests.get(app_server + "/feed",
                     params={"city": "Testheim", "street": "Hauptstraße", "nr": "1",
                             "eve": "off"}, timeout=10)
    assert "Tonne rausstellen" not in r.text
    assert "BEGIN:VALARM" not in r.text


def test_feed_morn_off_no_pickup(app_server):
    r = requests.get(app_server + "/feed",
                     params={"city": "Testheim", "street": "Hauptstraße", "nr": "1",
                             "morn": "off"}, timeout=10)
    assert "Abholung" not in r.text


def test_feed_eve_custom_time(app_server):
    # 21:00 lokal; je nach Jahreszeit 19:00Z (Sommer) oder 20:00Z (Winter) – nur Existenz prüfen
    r = requests.get(app_server + "/feed",
                     params={"city": "Testheim", "street": "Hauptstraße", "nr": "1",
                             "eve": "21:00"}, timeout=10)
    assert r.status_code == 200
    assert "Tonne rausstellen" in r.text


def test_feed_morn_timed(app_server):
    r = requests.get(app_server + "/feed",
                     params={"city": "Testheim", "street": "Hauptstraße", "nr": "1",
                             "morn": "06:00", "eve": "off"}, timeout=10)
    assert "VALUE=DATE" not in r.text  # nicht ganztägig
    assert "Abholung" in r.text


# --------------------------------------------------------------------------- #
# Feed: Abfalltyp-Filter (exakte API-Namen) – Regressionskern
# --------------------------------------------------------------------------- #
def _titles_in(raw: str) -> set[str]:
    body = unfold(raw)
    found = set()
    for key in ["Bioabfall", "Gelber Sack", "Papier",
                "Restmüll Tonnen und Container 14-täglich",
                "Restmüll Container wöchentlich", "Schadstoffmobil"]:
        if key in body:
            found.add(key)
    return found


def test_feed_filter_only_rest_2w(app_server):
    r = requests.get(app_server + "/feed",
                     params={"city": "Testheim", "street": "Hauptstraße", "nr": "1",
                             "types": "ZAW_REST_2W"}, timeout=10)
    body = unfold(r.text)
    assert "Restmüll Tonnen und Container 14-täglich" in body
    assert "Restmüll Container wöchentlich" not in body
    assert "Bioabfall" not in body


def test_feed_filter_only_rest_w(app_server):
    r = requests.get(app_server + "/feed",
                     params={"city": "Testheim", "street": "Hauptstraße", "nr": "1",
                             "types": "ZAW_REST_W"}, timeout=10)
    body = unfold(r.text)
    assert "Restmüll Container wöchentlich" in body
    assert "Restmüll Tonnen und Container 14-täglich" not in body


def test_feed_filter_multiple(app_server):
    r = requests.get(app_server + "/feed",
                     params={"city": "Testheim", "street": "Hauptstraße", "nr": "1",
                             "types": "ZAW_BIO,ZAW_GELB"}, timeout=10)
    found = _titles_in(r.text)
    assert found == {"Bioabfall", "Gelber Sack"}


# --------------------------------------------------------------------------- #
# Gemeinde OHNE Straßen (has_streets=false)
# --------------------------------------------------------------------------- #
def test_feed_city_without_streets(app_server):
    """Eine Gemeinde ohne Straßenauswahl muss auch ohne street-Parameter gehen."""
    r = requests.get(app_server + "/feed",
                     params={"city": "Inselstadt", "nr": "1"}, timeout=10)
    assert r.status_code == 200, r.text
    assert "BEGIN:VCALENDAR" in r.text
    assert "BEGIN:VEVENT" in r.text
