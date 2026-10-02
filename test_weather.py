# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Check daily weather joins and the meaning of hourly rainfall windows.

Run: uv run test_weather.py
Fixtures exercise errors and boundaries; they are never used by the artwork.
Every check reads local files or in-memory records. Nothing requests the network.
"""

import csv
import datetime as dt
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from weather import parse_daily, parse_hourly_snapshots, read_weather

# ---------------------------------------------------------------------------
# Small publisher-shaped fixtures, separate from the real data in data/weather/.
# ---------------------------------------------------------------------------

TITLES = {
    "maxTemp": "Daily Maximum Temperature (degrees Celsius)",
    "minTemp": "Daily Minimum Temperature (degrees Celsius)",
    "humidity": "Daily Mean Relative Humidity (%)",
    "cloud": "Daily Mean Amount of Cloud (%)",
}
HERE = Path(__file__).resolve().parent


def daily_text(metric, rows):
    """Keep the title, columns, and quality notes used by the publisher's CSV."""
    return (
        "Weather parser test fixture\n"
        + TITLES[metric] + " at the Hong Kong Observatory\n"
        + "Year,Month,Day,Value,data Completeness\n"
        + "\n".join(rows)
        + "\n\n*** unavailable\n# data incomplete\nC data Complete\n"
    )


def daily_records(metric, rows):
    """Parse a tiny CSV without creating a file or making a request."""
    return parse_daily(csv.reader(io.StringIO(daily_text(metric, rows))), metric)


def hourly_snapshot(when, amount, station_id="HKO", station="Hong Kong Observatory"):
    """A station reading describes the hour ending at its observation timestamp."""
    return {
        "obsTime": when,
        "hourlyRainfall": [{
            "automaticWeatherStation": station,
            "automaticWeatherStationID": station_id,
            "value": str(amount),
            "unit": "mm",
        }],
    }


def write_daily_fixture(folder, metric, rows):
    """Save one fixture and return the provenance needed to verify its bytes."""
    raw = daily_text(metric, rows).encode("utf-8")
    name = f"daily_HKO_{metric}_2026.csv"
    (folder / name).write_bytes(raw)
    dates = [dt.date(*(int(value) for value in row.split(",")[:3])) for row in rows]
    return {
        "raw_file": name,
        "metric": metric,
        "year": 2026,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "source_page": "https://example.test/daily-weather",
        "requested_url": f"https://example.test/{name}",
        "received_url": f"https://example.test/{name}",
        "snapshotUTC": "2026-10-02T00:00:00+00:00",
        "station": "Hong Kong Observatory",
        "coverageStart": min(dates).isoformat(),
        "coverageEnd": max(dates).isoformat(),
    }


def write_manifest(folder, daily_files):
    """An empty hourly archive is honest: it does not become a dry day."""
    manifest = {
        "version": 1,
        "publisher": "Hong Kong Observatory",
        "dailyFiles": daily_files,
        "hourlyFiles": [],
        "hourlyQueries": {},
        "dailyQueries": {},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

# ---------------------------------------------------------------------------
# Daily values: preserve missingness and quality, and join by calendar date.
# ---------------------------------------------------------------------------


class DailyWeatherTests(unittest.TestCase):
    """Guard against plausible-looking but false daily weather summaries."""

    def test_zero_missing_and_incomplete_are_distinct(self):
        records = daily_records("humidity", [
            "2026,6,15,0,C", "2026,6,16,***,", "2026,6,17,86,#",
        ])
        self.assertEqual(records["2026-06-15"]["value"], 0.0)
        self.assertEqual(records["2026-06-15"]["status"], "complete")
        self.assertIsNone(records["2026-06-16"]["value"])
        self.assertEqual(records["2026-06-16"]["status"], "missing")
        self.assertEqual(records["2026-06-17"]["status"], "incomplete")
        self.assertEqual(records["2026-06-17"]["flag"], "#")

    def test_negative_temperature_is_valid_but_nonfinite_values_are_not(self):
        records = daily_records("minTemp", ["2026,1,1,-1.5,C"])
        self.assertEqual(records["2026-01-01"]["value"], -1.5)
        for value in ("nan", "inf", "-inf", "not a number"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                daily_records("maxTemp", [f"2026,1,1,{value},C"])

    def test_percentage_ranges_and_quality_flags_are_checked(self):
        for metric in ("humidity", "cloud"):
            for value in ("-1", "101"):
                with self.subTest(metric=metric, value=value), self.assertRaises(ValueError):
                    daily_records(metric, [f"2026,1,1,{value},C"])
        with self.assertRaises(ValueError):
            daily_records("cloud", ["2026,1,1,50,NEW-FLAG"])

    def test_duplicate_and_impossible_dates_do_not_enter_the_calendar(self):
        with self.assertRaises(ValueError):
            daily_records("humidity", ["2026,1,1,90,C", "2026,1,1,80,C"])
        with self.assertRaises(ValueError):
            daily_records("cloud", ["2026,2,29,50,C"])

    def test_independent_files_are_joined_by_date_not_row_position(self):
        """A gap in cloud data must not shift its next value onto the wrong day."""
        with tempfile.TemporaryDirectory() as location:
            folder = Path(location)
            files = [
                write_daily_fixture(folder, "maxTemp", ["2026,6,15,27.1,C", "2026,6,16,28,C"]),
                write_daily_fixture(folder, "minTemp", ["2026,6,15,25.2,C", "2026,6,16,***,"]),
                write_daily_fixture(folder, "humidity", ["2026,6,15,91,C", "2026,6,16,86,#"]),
                write_daily_fixture(folder, "cloud", ["2026,6,15,96,C", "2026,6,17,77,C"]),
            ]
            write_manifest(folder, files)
            weather = read_weather(data_dir=folder)
            first = weather["daily"]["2026-06-15"]
            self.assertEqual(first["maxTemp"]["value"], 27.1)
            self.assertEqual(first["minTemp"]["value"], 25.2)
            self.assertEqual(first["humidity"]["value"], 91.0)
            self.assertEqual(first["cloud"]["value"], 96.0)
            second = weather["daily"]["2026-06-16"]
            self.assertIsNone(second["minTemp"]["value"])
            self.assertEqual(second["humidity"]["status"], "incomplete")
            self.assertIsNone(second.get("cloud", {"value": None})["value"])
            self.assertEqual(weather["daily"]["2026-06-17"]["cloud"]["value"], 77.0)
            self.assertFalse(weather["hourly"])

    def test_changed_raw_bytes_are_rejected_before_display(self):
        with tempfile.TemporaryDirectory() as location:
            folder = Path(location)
            entry = write_daily_fixture(folder, "humidity", ["2026,6,15,91,C"])
            write_manifest(folder, [entry])
            target = folder / entry["raw_file"]
            target.write_bytes(target.read_bytes().replace(b"91,C", b"81,C"))
            with self.assertRaises(ValueError):
                read_weather(data_dir=folder)

# ---------------------------------------------------------------------------
# Hourly values: choose non-overlapping windows and keep maintenance gaps blank.
# ---------------------------------------------------------------------------


class HourlyWeatherTests(unittest.TestCase):
    """One day contains the 24 windows ending at 01:00 through next-day 00:00."""

    def test_twenty_four_windows_belong_to_the_date_they_cover(self):
        start = dt.datetime(2026, 6, 15, 1, tzinfo=dt.timezone(dt.timedelta(hours=8)))
        snapshots = [hourly_snapshot((start + dt.timedelta(hours=index)).isoformat(), index + 1)
                     for index in range(24)]
        days = parse_hourly_snapshots(snapshots)
        self.assertEqual(set(days), {"2026-06-15"})
        day = days["2026-06-15"]
        self.assertEqual(day["completeHours"], 24)
        self.assertEqual([item["hour"] for item in day["hours"]], list(range(24)))
        self.assertEqual([item["mm"] for item in day["hours"]], list(range(1, 25)))
        self.assertEqual(day["hours"][0]["observationTime"], "2026-06-15T01:00:00+08:00")
        self.assertEqual(day["hours"][23]["observationTime"], "2026-06-16T00:00:00+08:00")

    def test_midnight_reading_belongs_to_the_previous_day(self):
        days = parse_hourly_snapshots([hourly_snapshot("2026-06-15T00:00:00+08:00", 2.5)])
        self.assertEqual(set(days), {"2026-06-14"})
        self.assertEqual(days["2026-06-14"]["hours"][23]["mm"], 2.5)
        self.assertEqual(days["2026-06-14"]["completeHours"], 1)

    def test_quarter_hour_updates_and_duplicate_snapshots_are_not_added(self):
        first = hourly_snapshot("2026-06-15T01:00:00+08:00", 4)
        snapshots = [first, first, hourly_snapshot("2026-06-15T01:15:00+08:00", 40),
                     hourly_snapshot("2026-06-15T01:30:00+08:00", 50),
                     hourly_snapshot("2026-06-15T01:45:00+08:00", 60)]
        day = parse_hourly_snapshots(snapshots)["2026-06-15"]
        self.assertEqual(day["completeHours"], 1)
        self.assertEqual(day["hours"][0]["mm"], 4.0)
        self.assertEqual(sum(item["mm"] or 0 for item in day["hours"]), 4.0)

    def test_conflicting_duplicate_observations_fail_loudly(self):
        snapshots = [hourly_snapshot("2026-06-15T01:00:00+08:00", 4),
                     hourly_snapshot("2026-06-15T01:00:00+08:00", 5)]
        with self.assertRaises(ValueError):
            parse_hourly_snapshots(snapshots)

    def test_zero_is_observed_while_maintenance_and_absence_are_missing(self):
        snapshots = [hourly_snapshot("2026-06-15T01:00:00+08:00", 0),
                     hourly_snapshot("2026-06-15T06:00:00+08:00", "M")]
        day = parse_hourly_snapshots(snapshots)["2026-06-15"]
        self.assertEqual(day["completeHours"], 1)
        self.assertEqual(day["hours"][0]["status"], "observed")
        self.assertEqual(day["hours"][0]["mm"], 0.0)
        for index in (1, 5, 23):
            self.assertEqual(day["hours"][index]["status"], "missing")
            self.assertIsNone(day["hours"][index]["mm"])

    def test_other_stations_do_not_fill_gaps_at_the_observatory(self):
        snapshots = [hourly_snapshot("2026-06-15T01:00:00+08:00", 2),
                     hourly_snapshot("2026-06-15T02:00:00+08:00", 99, "OTHER", "Other station")]
        day = parse_hourly_snapshots(snapshots, station_id="HKO")["2026-06-15"]
        self.assertEqual(day["completeHours"], 1)
        self.assertEqual(day["hours"][0]["mm"], 2.0)
        self.assertIsNone(day["hours"][1]["mm"])

# ---------------------------------------------------------------------------
# Real cached observations. A failed download must never create invented data.
# ---------------------------------------------------------------------------


class CachedWeatherTests(unittest.TestCase):
    """Check downloaded evidence when it exists; report unavailable checks as skips."""

    def test_real_june_fifteenth_humidity_and_cloud(self):
        manifest = HERE / "data" / "weather" / "manifest.json"
        if not manifest.is_file():
            self.skipTest("No weather snapshot has been downloaded.")
        weather = read_weather()
        day = weather["daily"].get("2026-06-15", {})
        if not all(metric in day and day[metric]["status"] == "complete"
                   for metric in ("humidity", "cloud")):
            self.skipTest("The unchanged 2026 humidity and cloud files are not both cached.")
        self.assertEqual(day["humidity"]["value"], 91.0)
        self.assertEqual(day["cloud"]["value"], 96.0)
        if all(metric in day and day[metric]["status"] == "complete"
               for metric in ("maxTemp", "minTemp")):
            self.assertLessEqual(day["minTemp"]["value"], day["maxTemp"]["value"])


if __name__ == "__main__":
    unittest.main()
