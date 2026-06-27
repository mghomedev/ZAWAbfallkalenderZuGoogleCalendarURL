"""
Reine Unit-Tests für zaw_ics_gen: build_ics() und filter_dates_by_trash().
Kein Netzwerk, kein Server – deterministisch über festes `now`.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

import zaw_ics_gen as z

UTC = ZoneInfo("UTC")

# Kanonische Mock-Namen (wie ZAW)
NAMES = {
    "ZAW_BIO": "Bioabfall",
    "ZAW_GELB": "Gelber Sack",
    "ZAW_PAP": "Papier Tonnen und Container",
    "ZAW_REST_2W": "Restmüll Tonnen und Container 14-täglich",
    "ZAW_REST_W": "Restmüll Container wöchentlich",
    "ZAW_SCHAD": "Schadstoffmobil",
}


def _dates(*pairs):
    return [(dt.date(*d) if isinstance(d, tuple) else d, t) for d, t in pairs]


# --------------------------------------------------------------------------- #
# Struktur / RFC 5545
# --------------------------------------------------------------------------- #
def test_calendar_envelope():
    ics = z.build_ics([], now=dt.datetime(2026, 1, 1, tzinfo=UTC))
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.rstrip().endswith("END:VCALENDAR")
    assert "VERSION:2.0" in ics
    assert "PRODID:" in ics
    assert ics.endswith("\r\n")


def test_crlf_line_endings():
    ics = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC))
    # jede physische Zeile endet mit CRLF; keine nackten \n
    assert "\r\n" in ics
    for line in ics.split("\r\n"):
        assert "\n" not in line


def test_line_folding_75_octets():
    # langer Titel erzwingt Faltung
    long_title = "Restmüll Tonnen und Container 14-täglich mit sehr langem Zusatztext üäöß"
    ics = z.build_ics(_dates(((2026, 7, 15), long_title)),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC))
    for line in ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75, f"Zeile zu lang: {line!r}"


def test_folded_continuation_starts_with_space():
    long_title = "X" * 200
    ics = z.build_ics(_dates(((2026, 7, 15), long_title)),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC))
    lines = ics.split("\r\n")
    # mindestens eine Fortsetzungszeile (beginnt mit Space)
    assert any(l.startswith(" ") for l in lines)


def test_balanced_begin_end():
    ics = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC))
    assert ics.count("BEGIN:VEVENT") == ics.count("END:VEVENT")
    assert ics.count("BEGIN:VALARM") == ics.count("END:VALARM")
    assert ics.count("BEGIN:VCALENDAR") == 1 == ics.count("END:VCALENDAR")


# --------------------------------------------------------------------------- #
# Zwei VEVENTs pro Abholung; morgen + Vorabend
# --------------------------------------------------------------------------- #
def test_two_events_per_pickup_by_default():
    ics = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC))
    assert ics.count("BEGIN:VEVENT") == 2
    assert "– Abholung" in ics
    assert "Tonne rausstellen" in ics
    assert ics.count("BEGIN:VALARM") == 1  # nur Vorabend hat Alarm


def test_morning_disabled_removes_abholung():
    ics = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC),
                      morning_enabled=False)
    assert "Abholung" not in ics
    assert "Tonne rausstellen" in ics
    assert ics.count("BEGIN:VEVENT") == 1


def test_evening_disabled_removes_reminder():
    ics = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC),
                      evening_enabled=False)
    assert "Tonne rausstellen" not in ics
    assert "BEGIN:VALARM" not in ics
    assert "Abholung" in ics
    assert ics.count("BEGIN:VEVENT") == 1


def test_both_disabled_yields_empty_calendar():
    ics = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC),
                      morning_enabled=False, evening_enabled=False)
    assert ics.count("BEGIN:VEVENT") == 0


# --------------------------------------------------------------------------- #
# DST-Korrektheit (Europe/Berlin)
# --------------------------------------------------------------------------- #
def test_dst_winter_evening_2100Z():
    # Vorabend 22:00 lokal, Winter -> 21:00Z am Vortag
    ics = z.build_ics(_dates(((2026, 1, 15), "Bioabfall")),
                      now=dt.datetime(2026, 1, 1, tzinfo=UTC))
    assert "DTSTART:20260114T210000Z" in ics


def test_dst_summer_evening_2000Z():
    # Vorabend 22:00 lokal, Sommer -> 20:00Z am Vortag
    ics = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC))
    assert "DTSTART:20260714T200000Z" in ics


def test_custom_evening_time():
    ics = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC),
                      evening_time="21:00")
    # 21:00 Sommer -> 19:00Z
    assert "DTSTART:20260714T190000Z" in ics


# --------------------------------------------------------------------------- #
# Morgen: ganztägig vs. getimt
# --------------------------------------------------------------------------- #
def test_morning_all_day():
    ics = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC),
                      evening_enabled=False)
    assert "DTSTART;VALUE=DATE:20260715" in ics
    assert "DTEND;VALUE=DATE:20260716" in ics
    assert "TRANSP:TRANSPARENT" in ics


def test_morning_timed():
    ics = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC),
                      evening_enabled=False,
                      morning_all_day=False, morning_time="06:00")
    # 06:00 Sommer -> 04:00Z
    assert "DTSTART:20260715T040000Z" in ics
    assert "VALUE=DATE" not in ics


# --------------------------------------------------------------------------- #
# Stabile, deterministische UIDs
# --------------------------------------------------------------------------- #
def test_uids_stable_and_distinct():
    args = dict(now=dt.datetime(2026, 7, 1, tzinfo=UTC))
    a = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")), **args)
    b = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")), **args)
    assert a == b  # voll deterministisch
    uids = [l for l in a.split("\r\n") if l.startswith("UID:")]
    assert len(uids) == 2
    assert uids[0] != uids[1]               # morgen != vorabend
    assert uids[0].startswith("UID:m-")
    assert uids[1].startswith("UID:e-")
    assert all(u.endswith("@zaw-abfall.local") for u in uids)


def test_uid_changes_with_date_and_title():
    args = dict(now=dt.datetime(2026, 7, 1, tzinfo=UTC), evening_enabled=False)
    u1 = z.build_ics(_dates(((2026, 7, 15), "Bioabfall")), **args)
    u2 = z.build_ics(_dates(((2026, 7, 16), "Bioabfall")), **args)
    u3 = z.build_ics(_dates(((2026, 7, 15), "Gelber Sack")), **args)
    get = lambda s: [l for l in s.split("\r\n") if l.startswith("UID:")][0]
    assert get(u1) != get(u2) != get(u3) and get(u1) != get(u3)


# --------------------------------------------------------------------------- #
# Fensterung (days_back / days_ahead)
# --------------------------------------------------------------------------- #
def test_dates_outside_window_excluded():
    now = dt.datetime(2026, 7, 1, tzinfo=UTC)
    items = _dates(
        ((2026, 1, 1), "Bioabfall"),     # weit in der Vergangenheit -> raus
        ((2026, 7, 10), "Bioabfall"),    # drin
        ((2030, 1, 1), "Bioabfall"),     # weit in der Zukunft -> raus
    )
    ics = z.build_ics(items, now=now, evening_enabled=False)
    assert ics.count("BEGIN:VEVENT") == 1
    assert "20260710" in ics


# --------------------------------------------------------------------------- #
# Escaping
# --------------------------------------------------------------------------- #
def test_special_chars_escaped():
    ics = z.build_ics(_dates(((2026, 7, 15), "Test; mit, Sonder\\zeichen")),
                      now=dt.datetime(2026, 7, 1, tzinfo=UTC), evening_enabled=False)
    assert "\\;" in ics and "\\," in ics and "\\\\" in ics


# --------------------------------------------------------------------------- #
# Emoji-Labels
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("title,emoji", [
    ("Bioabfall", "🟤"),
    ("Papier Tonnen und Container", "🔵"),
    ("Gelber Sack", "🟡"),
    ("Restmüll Container wöchentlich", "⚫"),
    ("Schadstoffmobil", "☣"),
    ("Unbekannte Tonne", "🗑"),
])
def test_pretty_label(title, emoji):
    assert emoji in z.pretty_label(title)


# --------------------------------------------------------------------------- #
# filter_dates_by_trash – exakte Typunterscheidung (Regressionskern)
# --------------------------------------------------------------------------- #
ALL_DATES = _dates(
    ((2026, 7, 1), "Bioabfall"),
    ((2026, 7, 2), "Gelber Sack"),
    ((2026, 7, 3), "Papier Tonnen und Container"),
    ((2026, 7, 4), "Restmüll Tonnen und Container 14-täglich"),
    ((2026, 7, 5), "Restmüll Container wöchentlich"),
    ((2026, 7, 6), "Schadstoffmobil"),
)


def test_filter_none_returns_all():
    assert z.filter_dates_by_trash(ALL_DATES, NAMES, None) == ALL_DATES
    assert z.filter_dates_by_trash(ALL_DATES, NAMES, []) == ALL_DATES


def test_filter_exact_rest_2w_only():
    out = z.filter_dates_by_trash(ALL_DATES, NAMES, ["ZAW_REST_2W"])
    titles = {t for _, t in out}
    assert titles == {"Restmüll Tonnen und Container 14-täglich"}


def test_filter_exact_rest_w_only():
    out = z.filter_dates_by_trash(ALL_DATES, NAMES, ["ZAW_REST_W"])
    titles = {t for _, t in out}
    assert titles == {"Restmüll Container wöchentlich"}


def test_filter_multiple_types():
    out = z.filter_dates_by_trash(ALL_DATES, NAMES, ["ZAW_BIO", "ZAW_GELB"])
    titles = {t for _, t in out}
    assert titles == {"Bioabfall", "Gelber Sack"}


def test_filter_both_rest_types():
    out = z.filter_dates_by_trash(ALL_DATES, NAMES, ["ZAW_REST_2W", "ZAW_REST_W"])
    titles = {t for _, t in out}
    assert titles == {"Restmüll Tonnen und Container 14-täglich",
                      "Restmüll Container wöchentlich"}


def test_filter_legacy_substring_keys_still_work():
    # alte Lesezeichen-Schlüssel (bio) sollen weiterhin matchen
    out = z.filter_dates_by_trash(ALL_DATES, NAMES, ["bio"])
    assert {t for _, t in out} == {"Bioabfall"}
