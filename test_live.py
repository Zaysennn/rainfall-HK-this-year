# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Check recent daily reports, live timestamps, and honest cache fallback.

Run: uv run test_live.py
The small fixtures are test cases, never observations used by the artwork.
Requests are mocked; temporary cache files stay inside a temporary directory.
"""

import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from explore import build_payload
from live import (
    parse_current_rain, parse_current_weather, parse_daily_report,
    read_live, refresh_live,
)
from number import read_records
from weather import read_weather

# ---------------------------------------------------------------------------
# Publisher-shaped fixtures. Each feed keeps its own observation timestamp.
# ---------------------------------------------------------------------------

HKT = dt.timezone(dt.timedelta(hours=8))
HERE = Path(__file__).resolve().parent
NOW = dt.datetime(2026, 10, 2, 23, 45, tzinfo=HKT)


def daily_report(**changes):
    """The report date differs from its publication date just after midnight."""
    raw = {
        "ReportTimeInfoDate": "20261001",
        "BulletinDate": "20261002",
        "BulletinTime": "0015",
        "HKOReadingsRainfall": "0",
        "HKOReadingsAccumRainfall": "2451.9",
        "HKOReadingsMaxTemp": "33.6",
        "HKOReadingsMinTemp": "28.3",
        "HKOReadingsMaxRH": "86",
        "HKOReadingsMinRH": "61",
        "NoteDesc3": "The data displayed is provisional. Only limited data validation has been carried out.",
    }
    raw.update(changes)
    return raw


def current_weather():
    """The update time is newer than the station's measured temperature and humidity."""
    return {
        "updateTime": "2026-10-02T22:46:00+08:00",
        "temperature": {
            "recordTime": "2026-10-02T22:00:00+08:00",
            "data": [{"place": "Hong Kong Observatory", "value": 28, "unit": "C"}],
        },
        "humidity": {
            "recordTime": "2026-10-02T22:00:00+08:00",
            "data": [{"place": "Hong Kong Observatory", "value": 82, "unit": "percent"}],
        },
    }


def current_rain(value="0", when="2026-10-02T22:30:00+08:00"):
    """A rolling hour ending at 22:30 is not the 22:00-23:00 calendar interval."""
    return {
        "obsTime": when,
        "hourlyRainfall": [{
            "automaticWeatherStation": "Hong Kong Observatory",
            "automaticWeatherStationID": "RF023",
            "value": value,
            "unit": "mm",
        }],
    }


def save_snapshot(folder, name, feed, date, value):
    """Keep fixture bytes and their separate manifest checksum consistent."""
    raw = json.dumps(value).encode("utf-8")
    target = folder / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {
        "raw_file": name, "feed": feed, "date": date,
        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "requested_url": "https://example.test/weather.json",
        "received_url": "https://example.test/weather.json",
        "snapshotUTC": "2026-10-02T00:20:00+00:00",
    }


def saved_cache(folder):
    """One finished day and two current feeds make a minimal offline cache."""
    daily = save_snapshot(folder, "raw/daily-20261001.json", "recentDaily", "2026-10-01", daily_report())
    weather = save_snapshot(folder, "raw/current-weather.json", "currentWeather", "2026-10-02", current_weather())
    rain = save_snapshot(folder, "raw/current-rain.json", "currentRain", "2026-10-02", current_rain())
    manifest = {
        "version": 1,
        "snapshots": [daily, weather, rain],
        "daily": {"2026-10-01": daily["raw_file"]},
        "current": {"weather": weather["raw_file"], "rain": rain["raw_file"]},
        "checkedAt": "2026-10-02T00:21:00+00:00",
        "lastSuccessAt": "2026-10-02T00:21:00+00:00",
        "errors": [],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest

# ---------------------------------------------------------------------------
# Daily reports are provisional records, not reviewed climate observations.
# ---------------------------------------------------------------------------


class RecentDailyTests(unittest.TestCase):
    """Never assign the next day's publication time to the previous day's rain."""

    def test_report_date_and_provisional_quality_are_preserved(self):
        result = parse_daily_report(daily_report(), expected_date="2026-10-01")
        self.assertEqual(result["date"], "2026-10-01")
        self.assertEqual(result["publicationTime"], "2026-10-02T00:15:00+08:00")
        self.assertEqual(result["status"], "provisional")
        self.assertEqual(result["source"], "recentDaily")
        self.assertEqual((result["minHumidity"], result["maxHumidity"]), (61.0, 86.0))
        self.assertNotIn("flag", result)
        self.assertNotIn("humidity", result)
        self.assertNotIn("meanHumidity", result)
        self.assertNotIn("cloud", result)

    def test_wrong_day_and_html_reply_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_daily_report(daily_report(), expected_date="2026-10-02")
        with self.assertRaises(ValueError):
            parse_daily_report(b"<html>Temporary error page</html>")

    def test_trace_dry_and_missing_rain_are_different(self):
        trace = parse_daily_report(daily_report(HKOReadingsRainfall="Trace"))
        dry = parse_daily_report(daily_report(HKOReadingsRainfall="0"))
        missing = parse_daily_report(daily_report(HKOReadingsRainfall=""))
        self.assertEqual((trace["mm"], trace["trace"]), (0.0, True))
        self.assertEqual((dry["mm"], dry["trace"]), (0.0, False))
        self.assertIsNone(missing["mm"])
        self.assertFalse(missing["trace"])

    def test_missing_extremes_do_not_become_zero_or_an_estimated_mean(self):
        result = parse_daily_report(daily_report(HKOReadingsMinTemp="", HKOReadingsMinRH=""))
        self.assertIsNone(result["minTemp"])
        self.assertIsNone(result["minHumidity"])
        self.assertEqual(result["maxHumidity"], 86.0)
        self.assertNotIn("humidity", result)

    def test_nonfinite_negative_rain_and_impossible_percentages_are_rejected(self):
        for value in ("nan", "inf", "-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_daily_report(daily_report(HKOReadingsRainfall=value))
        for value in ("-1", "101", "nan"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_daily_report(daily_report(HKOReadingsMaxRH=value))

# ---------------------------------------------------------------------------
# Current feeds have independent times and cannot fill a complete daily record.
# ---------------------------------------------------------------------------


class CurrentObservationTests(unittest.TestCase):
    """Inspect the measured station reading rather than a report update timestamp."""

    def test_temperature_and_humidity_keep_their_record_times(self):
        result = parse_current_weather(current_weather())
        self.assertEqual(result["date"], "2026-10-02")
        self.assertEqual(result["temperature"]["value"], 28.0)
        self.assertEqual(result["humidity"]["value"], 82.0)
        self.assertEqual(result["temperature"]["observationTime"], "2026-10-02T22:00:00+08:00")
        self.assertEqual(result["humidity"]["observationTime"], "2026-10-02T22:00:00+08:00")

    def test_different_feed_dates_and_utc_input_are_not_forced_to_today(self):
        raw = current_weather()
        raw["updateTime"] = "2026-10-01T16:02:00Z"
        raw["temperature"]["recordTime"] = "2026-10-01T15:00:00Z"
        result = parse_current_weather(raw)
        rain = parse_current_rain(current_rain(when="2026-10-01T23:45:00+08:00"))
        self.assertEqual(result["date"], "2026-10-02")
        self.assertEqual(result["temperature"]["observationTime"], "2026-10-01T23:00:00+08:00")
        self.assertEqual(rain["date"], "2026-10-01")

    def test_rolling_window_keeps_its_actual_start_and_end(self):
        result = parse_current_rain(current_rain("4"))
        reading = result["rainfall"]
        self.assertEqual(reading["value"], 4.0)
        self.assertEqual(reading["intervalStart"], "2026-10-02T21:30:00+08:00")
        self.assertEqual(reading["intervalEnd"], "2026-10-02T22:30:00+08:00")
        self.assertEqual(reading["observationTime"], reading["intervalEnd"])
        self.assertEqual(reading["stationID"], "RF023")
        self.assertEqual(reading["station"], "Hong Kong Observatory")

    def test_midnight_window_can_span_two_calendar_dates(self):
        reading = parse_current_rain(current_rain("2", "2026-10-01T16:30:00Z"))["rainfall"]
        self.assertEqual(reading["intervalStart"], "2026-10-01T23:30:00+08:00")
        self.assertEqual(reading["intervalEnd"], "2026-10-02T00:30:00+08:00")

    def test_maintenance_is_missing_and_other_stations_do_not_replace_hko(self):
        missing = parse_current_rain(current_rain("M"))["rainfall"]
        self.assertIsNone(missing["value"])
        self.assertEqual(missing["observationTime"], "2026-10-02T22:30:00+08:00")
        raw = current_rain("99")
        raw["hourlyRainfall"][0]["automaticWeatherStation"] = "Other station"
        raw["hourlyRainfall"][0]["automaticWeatherStationID"] = "OTHER"
        self.assertIsNone(parse_current_rain(raw)["rainfall"])

    def test_empty_current_station_arrays_do_not_invent_observations(self):
        raw = current_weather()
        raw["temperature"]["data"] = []
        raw["humidity"]["data"] = []
        result = parse_current_weather(raw)
        self.assertIsNone(result["temperature"])
        self.assertIsNone(result["humidity"])

    def test_current_values_and_timezone_are_validated(self):
        for value in ("nan", "inf", "-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_current_rain(current_rain(value))
        raw = current_weather()
        raw["humidity"]["data"][0]["value"] = 101
        with self.assertRaises(ValueError):
            parse_current_weather(raw)
        with self.assertRaises(ValueError):
            parse_current_rain(current_rain(when="2026-10-02T22:30:00"))

# ---------------------------------------------------------------------------
# Cache checks. Failed refreshes preserve old evidence and report the failure.
# ---------------------------------------------------------------------------


class LiveCacheTests(unittest.TestCase):
    """A disconnected computer must retain its snapshot without pretending it is fresh."""

    def test_cached_reports_are_read_offline_and_checksum_changes_fail(self):
        with tempfile.TemporaryDirectory() as location:
            folder = Path(location)
            manifest = saved_cache(folder)
            with patch("live.download", side_effect=AssertionError("read_live requested the network")):
                result = read_live(now=NOW, data_dir=folder)
            self.assertEqual(result["daily"]["2026-10-01"]["mm"], 0.0)
            self.assertEqual(result["current"]["temperature"]["value"], 28.0)
            target = folder / manifest["daily"]["2026-10-01"]
            target.write_bytes(target.read_bytes().replace(b'"HKOReadingsRainfall": "0"',
                                                          b'"HKOReadingsRainfall": "9"'))
            with self.assertRaises(ValueError):
                read_live(now=NOW, data_dir=folder)

    def test_manifest_paths_cannot_leave_the_live_cache(self):
        with tempfile.TemporaryDirectory() as location:
            container = Path(location)
            folder = container / "cache"
            folder.mkdir()
            manifest = saved_cache(folder)
            original = folder / manifest["daily"]["2026-10-01"]
            (container / "outside.json").write_bytes(original.read_bytes())
            manifest["snapshots"][0]["raw_file"] = "../outside.json"
            manifest["daily"]["2026-10-01"] = "../outside.json"
            (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_live(now=NOW, data_dir=folder)

    def test_failed_refresh_retains_successful_snapshots_and_exposes_errors(self):
        with tempfile.TemporaryDirectory() as location:
            folder = Path(location)
            manifest = saved_cache(folder)
            with patch("live.download", side_effect=OSError("fixture network unavailable")) as request:
                result = refresh_live(dt.date(2026, 9, 30), now=NOW, data_dir=folder)
            request.assert_called()
            self.assertEqual(result["daily"]["2026-10-01"]["mm"], 0.0)
            self.assertEqual(result["current"]["temperature"]["value"], 28.0)
            self.assertEqual(result["lastSuccessAt"], manifest["lastSuccessAt"])
            self.assertTrue(result["errors"])

# ---------------------------------------------------------------------------
# The actual completed record stops on 1 October; the live 2 October card does not.
# ---------------------------------------------------------------------------


class RecentPayloadTests(unittest.TestCase):
    """Check the real cached extension without changing the original monthly baseline."""

    def test_current_day_is_visible_but_excluded_from_completed_totals(self):
        live = read_live(now=NOW)
        required = {(dt.date(2026, 9, 1) + dt.timedelta(days=index)).isoformat()
                    for index in range(31)}
        if not required.issubset(live["daily"]) or live.get("current", {}).get("date") != "2026-10-02":
            self.skipTest("The 31 original recent daily reports and 2 October live feeds are not all cached.")
        records, excluded = read_records()
        payload = build_payload(records, excluded, weather=read_weather(), live=live)
        current = payload["years"]["2026"]
        prior = payload["years"]["2025"]
        self.assertEqual((current["observedCount"], current["displayCount"]), (274, 275))
        self.assertEqual((current["coverageEnd"], current["displayCoverageEnd"]),
                         ("2026-10-01", "2026-10-02"))
        self.assertEqual((current["matchedCount"], current["matchedDisplayCount"]), (274, 275))
        completed, today = current["days"][273:275]
        self.assertAlmostEqual(completed["stats"]["total"], 2451.9, places=6)
        self.assertEqual((completed["stats"]["complete"], completed["stats"]["verified"],
                          completed["stats"]["provisional"]), (274, 243, 31))
        self.assertEqual(completed["quality"], "provisional")
        self.assertEqual(today["status"], "ongoing")
        self.assertIsNone(today["mm"])
        self.assertIsNone(today["cumulative"])
        self.assertFalse(today["trace"])
        self.assertEqual(today["stats"], completed["stats"])
        self.assertEqual(today["counterpart"], prior["days"][274]["index"])
        self.assertEqual(today["currentObservation"]["date"], "2026-10-02")


    def test_missing_saved_temperature_uses_report_but_incomplete_value_stays(self):
        """A present-but-missing climate entry must not block a real provisional value."""
        records, excluded = read_records()
        report = parse_daily_report(daily_report(ReportTimeInfoDate="20260901", BulletinDate="20260902"))
        missing = {"value": None, "status": "missing", "flag": "", "source": "maxTemp"}
        incomplete = {"value": 20.0, "status": "incomplete", "flag": "#", "source": "minTemp"}
        weather = {
            "daily": {"2026-09-01": {"maxTemp": missing, "minTemp": incomplete}},
            "hourly": {}, "sources": {}, "hourlyNote": "Fixture has no hourly observations.",
            "timezone": "Asia/Hong_Kong",
        }
        live = {"daily": {"2026-09-01": report}, "current": {}, "sources": {},
                "errors": [], "today": "2026-10-02", "enabled": False}
        payload = build_payload(records, excluded, weather=weather, live=live)
        day = next(day for day in payload["years"]["2026"]["days"] if day["date"] == "2026-09-01")
        self.assertEqual(day["weather"]["maxTemp"]["value"], 33.6)
        self.assertEqual(day["weather"]["maxTemp"]["status"], "provisional")
        self.assertEqual(day["weather"]["maxTemp"]["source"], "recentDaily")
        self.assertEqual(day["weather"]["minTemp"], incomplete)
        self.assertIsNone(missing["value"])

    def test_reports_for_today_and_future_dates_do_not_enter_completed_stats(self):
        """Ignore even an injected report that claims an unfinished day is complete."""
        records, excluded = read_records()
        completed = parse_daily_report(daily_report(HKOReadingsRainfall="2.5"))
        today = parse_daily_report(daily_report(ReportTimeInfoDate="20261002", BulletinDate="20261003",
                                               HKOReadingsRainfall="5000"))
        future = parse_daily_report(daily_report(ReportTimeInfoDate="20261003", BulletinDate="20261004",
                                                HKOReadingsRainfall="6000"))
        base = {"daily": {"2026-10-01": completed}, "current": {"date": "2026-10-02"},
                "sources": {}, "errors": [], "today": "2026-10-02", "enabled": False}
        injected = {**base, "daily": {**base["daily"], "2026-10-02": today, "2026-10-03": future}}
        baseline = build_payload(records, excluded, weather=read_weather(), live=base)["years"]["2026"]
        result = build_payload(records, excluded, weather=read_weather(), live=injected)["years"]["2026"]
        self.assertEqual((result["observedCount"], result["displayCount"]), (274, 275))
        self.assertEqual(result["days"][273]["stats"], baseline["days"][273]["stats"])
        self.assertAlmostEqual(result["days"][273]["stats"]["total"], 2360.1, places=6)
        self.assertEqual(result["days"][274]["status"], "ongoing")
        self.assertIsNone(result["days"][274]["mm"])
        self.assertIsNone(result["days"][274]["recentDaily"])
        self.assertEqual(result["days"][274]["stats"], result["days"][273]["stats"])
        self.assertEqual(result["days"][275]["status"], "unpublished")
        self.assertIsNone(result["days"][275]["mm"])
        self.assertIsNone(result["days"][275]["recentDaily"])

if __name__ == "__main__":
    unittest.main()
