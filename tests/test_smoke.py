"""Smoke-Test: validiert die gesamte Test-Infrastruktur (Mock + App + Browser)."""

from __future__ import annotations

import requests
import pytest


def test_cities_endpoint(app_server):
    r = requests.get(app_server + "/api/cities", timeout=10)
    assert r.status_code == 200
    names = [c["name"] for c in r.json()]
    assert "Testheim" in names
    assert "Groß-Umstadt" in names


def test_feed_endpoint(app_server):
    r = requests.get(app_server + "/feed",
                     params={"city": "Testheim", "street": "Hauptstraße", "nr": "1"},
                     timeout=10)
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in r.text
    assert "END:VCALENDAR" in r.text


@pytest.mark.ui
def test_page_loads_cities(app_server, page):
    page.goto(app_server + "/")
    # warte bis die Gemeinde-Dropdown befüllt ist
    page.wait_for_function(
        "document.querySelectorAll('#city option').length > 1", timeout=10000
    )
    options = page.eval_on_selector_all(
        "#city option", "els => els.map(e => e.textContent)"
    )
    assert "Testheim" in options
