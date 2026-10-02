# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Check the boundaries between observed rain, model estimates, and saved bytes.

Run: uv run test_hourly.py
Every response below is a test fixture, never a weather observation.
Network requests are mocked. Small test caches stay in the approved backup area
so that the tests never delete or alter an existing project cache.
"""

import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from hourly import (
    capture_observation, get_day, parse_model_response, parse_observation,
    read_hourly, refresh_models,
)

# ---------------------------------------------------------------------------
# Provider-shaped fixtures keep the reported interval end separate from its day.
# ---------------------------------------------------------------------------

HKT = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime(2026, 10, 3, 3, 0, tzinfo=HKT)
HERE = Path(__file__).resolve().parent
TEST_WORK = HERE / ".backups" / "hourly-details-20261003" / "test-work"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OBSERVATION = "https://data.weather.gov.hk/weatherAPI/opendata/hourlyRainfall.php?lang=en"


def raw_json(value):
    """Keep the fixture bytes explicit so cache checks can inspect the original."""
    return (json.dumps(value, separators=(",", ":")) + "\n").encode("utf-8")


def model_fixture(start_date="2026-06-15", source_end="2026-06-16"):
    """Build complete provider days, including the extra day for midnight rain."""
    start = dt.datetime.combine(dt.date.fromisoformat(start_date), dt.time())
    end = dt.datetime.combine(dt.date.fromisoformat(source_end), dt.time()) + dt.timedelta(days=1)
    hours = int((end - start).total_seconds() // 3600)
    return {
        "latitude": 22.30,
        "longitude": 114.20,
        "elevation": 46.0,
        "timezone": "Asia/Hong_Kong",
        "utc_offset_seconds": 28800,
        "hourly_units": {"time": "iso8601", "rain": "mm"},
        "hourly": {
            "time": [(start + dt.timedelta(hours=hour)).isoformat(timespec="minutes")
                     for hour in range(hours)],
            "rain": [round((hour % 11) / 10, 1) for hour in range(hours)],
        },
    }


def observation_fixture(time="2026-10-03T02:00:00+08:00", value="0"):
    """Another station has a distinct amount and must never fill an HKO gap."""
    return {
        "obsTime": time,
        "hourlyRainfall": [
            {"automaticWeatherStation": "Lau Fau Shan",
             "automaticWeatherStationID": "RF001", "value": "9", "unit": "mm"},
            {"automaticWeatherStation": "Hong Kong Observatory",
             "automaticWeatherStationID": "RF023", "value": value, "unit": "mm"},
        ],
    }


def response_metadata(raw, url):
    """Match the downloader contract while keeping the test entirely offline."""
    return {
        "requested_url": url,
        "received_url": url,
        "snapshotUTC": NOW.astimezone(dt.timezone.utc).isoformat(),
        "content_type": "application/json",
        "last_modified": None,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def model_download(url, **kwargs):
    """Answer the actual requested source dates without touching an external API."""
    query = parse_qs(urlparse(url).query)
    raw = raw_json(model_fixture(query["start_date"][0], query["end_date"][0]))
    return raw, response_metadata(raw, url)


def observation_download(value="0", time="2026-10-03T02:00:00+08:00"):
    """Return a fresh mocked reply; the application decides how to store it."""
    raw = raw_json(observation_fixture(time, value))
    return lambda url, **kwargs: (raw, response_metadata(raw, url))


# ---------------------------------------------------------------------------
# Model values stay estimated and are aligned to the hour they actually cover.
# ---------------------------------------------------------------------------

class ModelParserTests(unittest.TestCase):
    def parse(self, fixture, now=NOW):
        return parse_model_response(raw_json(fixture), "2026-06-15", "2026-06-15",
                                    now=now, source_url=ARCHIVE)

    def test_end_times_map_to_the_preceding_hour_including_midnight(self):
        fixture = model_fixture()
        fixture["hourly"]["rain"][0] = 99.0
        fixture["hourly"]["rain"][1] = 0.5
        fixture["hourly"]["rain"][24] = 7.0
        days = self.parse(fixture)
        self.assertEqual(set(days), {"2026-06-15"})
        day = days["2026-06-15"]
        self.assertEqual(day["kind"], "model")
        self.assertEqual(day["completeHours"], 24)
        self.assertEqual([hour["hour"] for hour in day["hours"]], list(range(24)))
        self.assertEqual(day["hours"][0]["mm"], 0.5)
        self.assertEqual(day["hours"][23]["mm"], 7.0)
        self.assertEqual(day["hours"][0]["observationTime"], "2026-06-15T01:00:00+08:00")
        self.assertEqual(day["hours"][23]["observationTime"], "2026-06-16T00:00:00+08:00")
        self.assertTrue(all(hour["status"] == "estimated" for hour in day["hours"]))

    def test_zero_estimate_and_missing_value_have_different_statuses(self):
        fixture = model_fixture()
        fixture["hourly"]["rain"][1] = 0.0
        fixture["hourly"]["rain"][2] = None
        day = self.parse(fixture)["2026-06-15"]
        self.assertEqual(day["hours"][0]["mm"], 0.0)
        self.assertEqual(day["hours"][0]["status"], "estimated")
        self.assertIsNone(day["hours"][1]["mm"])
        self.assertEqual(day["hours"][1]["status"], "missing")
        self.assertEqual(day["completeHours"], 23)

    def test_wrong_units_timezone_and_offset_are_rejected(self):
        changes = [
            ("rain unit", lambda item: item["hourly_units"].update(rain="cm")),
            ("time unit", lambda item: item["hourly_units"].update(time="unixtime")),
            ("timezone", lambda item: item.update(timezone="UTC")),
            ("offset", lambda item: item.update(utc_offset_seconds=0)),
            ("coordinate", lambda item: item.update(latitude=float("inf"))),
        ]
        for label, change in changes:
            with self.subTest(label=label):
                fixture = model_fixture()
                change(fixture)
                with self.assertRaises(ValueError):
                    self.parse(fixture)

    def test_wrong_lengths_duplicate_hours_and_wrong_order_are_rejected(self):
        changes = [
            ("short values", lambda item: item["hourly"]["rain"].pop()),
            ("short days", lambda item: (item["hourly"]["rain"].pop(),
                                        item["hourly"]["time"].pop())),
            ("duplicate", lambda item: item["hourly"]["time"].__setitem__(
                6, item["hourly"]["time"][5])),
            ("wrong hour", lambda item: item["hourly"]["time"].__setitem__(
                6, "2026-06-15T06:30")),
            ("wrong order", lambda item: item["hourly"]["time"].__setitem__(
                slice(5, 7), list(reversed(item["hourly"]["time"][5:7])))),
        ]
        for label, change in changes:
            with self.subTest(label=label):
                fixture = model_fixture()
                change(fixture)
                with self.assertRaises(ValueError):
                    self.parse(fixture)

    def test_nonfinite_and_negative_rain_are_rejected(self):
        for value in (-0.1, float("nan"), float("inf")):
            with self.subTest(value=value):
                fixture = model_fixture()
                fixture["hourly"]["rain"][1] = value
                with self.assertRaises(ValueError):
                    self.parse(fixture)

    def test_unfinished_intervals_do_not_count_as_completed_estimates(self):
        now = dt.datetime(2026, 6, 15, 10, 30, tzinfo=HKT)
        day = self.parse(model_fixture(), now=now)["2026-06-15"]
        self.assertEqual(day["completeHours"], 10)
        self.assertEqual(day["hours"][9]["status"], "estimated")
        self.assertTrue(all(hour["status"] == "missing" and hour["mm"] is None
                            for hour in day["hours"][10:]))

    def test_html_and_wrong_date_coverage_do_not_become_a_weather_day(self):
        with self.assertRaises(ValueError):
            parse_model_response(b"<html>Gateway error</html>", "2026-06-15", "2026-06-15",
                                 now=NOW, source_url=ARCHIVE)
        with self.assertRaises(ValueError):
            self.parse(model_fixture("2026-06-16", "2026-06-17"))


# ---------------------------------------------------------------------------
# Real observations use RF023 only; four rolling updates are never added up.
# ---------------------------------------------------------------------------

class ObservationParserTests(unittest.TestCase):
    def parse(self, fixture):
        return parse_observation(raw_json(fixture), now=NOW)

    def test_midnight_is_the_previous_days_last_interval(self):
        days = self.parse(observation_fixture("2026-10-03T00:00:00+08:00", "3"))
        self.assertEqual(set(days), {"2026-10-02"})
        day = days["2026-10-02"]
        self.assertEqual(day["kind"], "observed")
        self.assertEqual(day["completeHours"], 1)
        self.assertEqual(day["hours"][23]["mm"], 3.0)
        self.assertEqual(day["hours"][23]["status"], "observed")
        self.assertEqual(day["hours"][23]["observationTime"], "2026-10-03T00:00:00+08:00")
        self.assertTrue(all(hour["mm"] is None for hour in day["hours"][:23]))

    def test_quarter_hour_windows_do_not_fill_nonoverlapping_hour_slots(self):
        for time in ("2026-10-03T01:15:00+08:00", "2026-10-03T01:30:00+08:00",
                     "2026-10-03T01:45:00+08:00"):
            with self.subTest(time=time):
                self.assertEqual(self.parse(observation_fixture(time, "8")), {})

    def test_measured_zero_is_observed_and_maintenance_stays_missing(self):
        zero = self.parse(observation_fixture(value="0"))["2026-10-03"]
        missing = self.parse(observation_fixture(value="M"))["2026-10-03"]
        self.assertEqual(zero["hours"][1]["mm"], 0.0)
        self.assertEqual(zero["hours"][1]["status"], "observed")
        self.assertEqual(zero["completeHours"], 1)
        self.assertIsNone(missing["hours"][1]["mm"])
        self.assertEqual(missing["hours"][1]["status"], "missing")
        self.assertEqual(missing["completeHours"], 0)

    def test_another_station_does_not_replace_a_missing_hko_station(self):
        fixture = observation_fixture()
        fixture["hourlyRainfall"] = fixture["hourlyRainfall"][:1]
        self.assertEqual(self.parse(fixture), {})

    def test_future_source_times_and_invalid_rain_are_rejected(self):
        with self.assertRaises(ValueError):
            self.parse(observation_fixture("2026-10-03T04:00:00+08:00", "1"))
        for value in ("-1", "NaN", "Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.parse(observation_fixture(value=value))


# ---------------------------------------------------------------------------
# Mocked public requests exercise storage, offline reuse, and failure fallback.
# ---------------------------------------------------------------------------

class HourlyCacheTests(unittest.TestCase):
    def setUp(self):
        # Use a new, isolated directory and retain it instead of deleting files.
        TEST_WORK.mkdir(parents=True, exist_ok=True)
        self.cache = Path(tempfile.mkdtemp(prefix="hourly-", dir=TEST_WORK))

    def manifest(self):
        return json.loads((self.cache / "manifest.json").read_text(encoding="utf-8"))

    def saved_bytes(self):
        return {entry["raw_file"]: (self.cache / entry["raw_file"]).read_bytes()
                for entry in self.manifest()["snapshots"]}

    def cache_model(self):
        with patch("hourly.download", side_effect=model_download):
            refresh_models("2026-06-15", "2026-06-15", data_dir=self.cache, now=NOW)

    def test_offline_empty_cache_makes_no_request_or_fake_day(self):
        with patch("hourly.download", side_effect=AssertionError("Offline mode requested weather")):
            result = get_day("2026-06-15", mode="model", offline=True,
                             data_dir=self.cache, now=NOW)
        self.assertIsNone(result["day"])
        self.assertEqual(result["query"]["status"], "unqueried")

    def test_two_dates_reuse_one_month_and_complete_cache_stays_offline(self):
        with patch("hourly.download", side_effect=model_download) as request:
            first = get_day("2026-06-15", mode="model", data_dir=self.cache, now=NOW)
            second = get_day("2026-06-16", mode="model", data_dir=self.cache, now=NOW)
            forced = get_day("2026-06-15", mode="model", force=True,
                             data_dir=self.cache, now=NOW)
        self.assertEqual(request.call_count, 1)
        for result in (first, second, forced):
            self.assertEqual(result["day"]["kind"], "model")
            self.assertEqual(result["day"]["completeHours"], 24)
            self.assertTrue(all(hour["status"] == "estimated"
                                for hour in result["day"]["hours"]))
        with patch("hourly.download", side_effect=AssertionError("Cache read requested weather")):
            cached = read_hourly(data_dir=self.cache, now=NOW)
            offline = get_day("2026-06-15", mode="model", offline=True,
                              data_dir=self.cache, now=NOW)
        self.assertEqual(cached["observed"], {})
        self.assertEqual(offline["day"], first["day"])

    def test_today_model_is_unavailable_and_never_calls_a_forecast(self):
        with patch("hourly.download", side_effect=AssertionError("Today's model requested weather")):
            result = get_day("2026-10-03", mode="model", data_dir=self.cache, now=NOW)
        self.assertIsNone(result["day"])
        self.assertEqual(result["query"]["status"], "unavailable")

    def test_invalid_dates_modes_and_future_dates_are_rejected_before_requests(self):
        cases = [("not-a-date", "model"), ("2026-02-30", "model"),
                 ("2026-10-04", "model"), ("2026-06-15", "forecast")]
        with patch("hourly.download", side_effect=AssertionError("Invalid input requested weather")):
            for date, mode in cases:
                with self.subTest(date=date, mode=mode):
                    with self.assertRaises(ValueError):
                        get_day(date, mode=mode, data_dir=self.cache, now=NOW)

    def test_original_bytes_match_their_checksum_and_tampering_is_rejected(self):
        self.cache_model()
        entry = self.manifest()["snapshots"][0]
        target = self.cache / entry["raw_file"]
        raw = target.read_bytes()
        self.assertEqual(len(raw), entry["bytes"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])
        # This deliberate corruption affects only a newly created test fixture.
        target.write_bytes(raw + b" ")
        with self.assertRaises(ValueError):
            read_hourly(data_dir=self.cache, now=NOW)

    def test_manifest_paths_cannot_escape_the_hourly_cache(self):
        self.cache_model()
        manifest = self.manifest()
        manifest["snapshots"][0]["raw_file"] = "../outside.json"
        (self.cache / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError):
            read_hourly(data_dir=self.cache, now=NOW)

    def test_duplicate_observations_are_not_added_and_raw_bytes_stay_unchanged(self):
        with patch("hourly.download", side_effect=observation_download("2")):
            capture_observation(data_dir=self.cache, now=NOW)
            before = self.saved_bytes()
            capture_observation(data_dir=self.cache, now=NOW)
        self.assertEqual(self.saved_bytes(), before)
        cache = read_hourly(data_dir=self.cache, now=NOW)
        day = cache["observed"]["2026-10-03"]
        self.assertEqual(day["completeHours"], 1)
        self.assertEqual(day["hours"][1]["mm"], 2.0)
        self.assertEqual(cache["model"], {})

    def test_conflicting_observation_keeps_the_first_reading_and_raw_file(self):
        with patch("hourly.download", side_effect=observation_download("2")):
            capture_observation(data_dir=self.cache, now=NOW)
        before = self.saved_bytes()
        with patch("hourly.download", side_effect=observation_download("5")):
            capture_observation(data_dir=self.cache, now=NOW)
        cache = read_hourly(data_dir=self.cache, now=NOW)
        self.assertEqual(cache["observed"]["2026-10-03"]["hours"][1]["mm"], 2.0)
        self.assertEqual(cache["queries"]["observed:2026-10-03"]["status"], "failed")
        for file, raw in before.items():
            self.assertEqual((self.cache / file).read_bytes(), raw)

    def test_failed_observation_refresh_keeps_saved_values_and_exposes_failure(self):
        with patch("hourly.download", side_effect=observation_download("0")):
            capture_observation(data_dir=self.cache, now=NOW)
        before = self.saved_bytes()
        with patch("hourly.download", side_effect=OSError("Fixture network unavailable")):
            capture_observation(data_dir=self.cache, now=NOW)
        cache = read_hourly(data_dir=self.cache, now=NOW)
        self.assertEqual(cache["observed"]["2026-10-03"]["hours"][1]["mm"], 0.0)
        query = cache["queries"]["observed:2026-10-03"]
        self.assertEqual(query["status"], "failed")
        self.assertTrue(query["message"])
        self.assertEqual(self.saved_bytes(), before)


if __name__ == "__main__":
    unittest.main()
