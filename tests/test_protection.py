"""
Tests für den ZAW-Schutz: 24h-Cache, Rate-Limit, robots.txt, Edge-Cache-Header.
Der Mock zählt Upstream-Requests, sodass das Cache-Verhalten messbar ist.
"""

from __future__ import annotations

import requests

import zaw_ics_gen


HAUPT = {"city": "Testheim", "street": "Hauptstraße", "nr": "1"}


# --------------------------------------------------------------------------- #
# 24h-Cache: zweite identische Anfrage trifft die ZAW-API NICHT erneut
# --------------------------------------------------------------------------- #
def test_cache_prevents_repeat_upstream(app_server, mock_zaw_server):
    counter = mock_zaw_server["counter"]
    zaw_ics_gen.clear_cache()
    counter.reset()

    r1 = requests.get(app_server + "/feed", params=HAUPT, timeout=10)
    assert r1.status_code == 200
    first = counter.snapshot()
    assert sum(first.values()) > 0, "erste Anfrage muss die ZAW-API treffen"

    r2 = requests.get(app_server + "/feed", params=HAUPT, timeout=10)
    assert r2.status_code == 200
    second = counter.snapshot()
    assert second == first, f"2. Abruf hätte aus dem Cache kommen müssen: {first} -> {second}"


def test_cache_shared_between_feed_and_picker_apis(app_server, mock_zaw_server):
    """Picker (/api/cities) und Feed teilen denselben cities_web-Cache."""
    counter = mock_zaw_server["counter"]
    zaw_ics_gen.clear_cache()
    counter.reset()

    requests.get(app_server + "/api/cities", timeout=10)
    cities_calls = counter.snapshot().get("cities_web", 0)
    assert cities_calls == 1

    # Feed-Abruf braucht ebenfalls cities_web -> aus dem Cache, kein neuer Upstream
    requests.get(app_server + "/feed", params=HAUPT, timeout=10)
    assert counter.snapshot().get("cities_web", 0) == 1


def test_cache_can_be_disabled(app_server, mock_zaw_server, monkeypatch):
    counter = mock_zaw_server["counter"]
    monkeypatch.setenv("ZAW_CACHE_TTL", "0")
    zaw_ics_gen.clear_cache()
    counter.reset()

    requests.get(app_server + "/feed", params=HAUPT, timeout=10)
    c1 = sum(counter.snapshot().values())
    requests.get(app_server + "/feed", params=HAUPT, timeout=10)
    c2 = sum(counter.snapshot().values())
    assert c2 > c1, "ohne Cache muss jede Anfrage erneut upstream gehen"


# --------------------------------------------------------------------------- #
# Rate-Limit
# --------------------------------------------------------------------------- #
def test_rate_limit_returns_429(app_server, app_module, monkeypatch):
    monkeypatch.setenv("ZAW_RATE_PER_MIN", "3")
    app_module.clear_rate()
    try:
        codes = [requests.get(app_server + "/api/cities", timeout=10).status_code
                 for _ in range(6)]
    finally:
        app_module.clear_rate()
    assert codes[:3] == [200, 200, 200], codes
    assert 429 in codes[3:], codes


def test_rate_limit_disabled_when_zero(app_server, app_module, monkeypatch):
    monkeypatch.setenv("ZAW_RATE_PER_MIN", "0")
    app_module.clear_rate()
    codes = [requests.get(app_server + "/api/cities", timeout=10).status_code
             for _ in range(5)]
    assert all(c == 200 for c in codes)


# --------------------------------------------------------------------------- #
# robots.txt + Edge-Cache-Header
# --------------------------------------------------------------------------- #
def test_robots_txt(app_server):
    r = requests.get(app_server + "/robots.txt", timeout=10)
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/plain")
    assert "Disallow: /api/" in r.text
    assert "Disallow: /feed" in r.text


def test_feed_has_24h_edge_cache(app_server):
    r = requests.get(app_server + "/feed", params=HAUPT, timeout=10)
    assert "s-maxage=86400" in r.headers.get("Cache-Control", "")


def test_api_has_edge_cache(app_server):
    r = requests.get(app_server + "/api/cities", timeout=10)
    assert "s-maxage=86400" in r.headers.get("Cache-Control", "")
