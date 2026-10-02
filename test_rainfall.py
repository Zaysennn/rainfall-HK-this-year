# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Check the decisions that could change the meaning of a rainfall picture.

Run: uv run test_rainfall.py
The small fixtures below are test cases, not data used by the artwork.
"""

import csv
import datetime as dt
import io
import unittest

from number import comparison_end, cumulative, parse_rows, read_records, summarise
from explore import build_payload, describe_day, prepare_year

# ---------------------------------------------------------------------------
# Tiny fixtures. Real output always comes from the unchanged file in data/.
# ---------------------------------------------------------------------------


def fixture(rows):
    """Wrap test records in the publisher's titles, columns, and footnotes."""
    text = (
        "Daily rainfall test fixture\n"
        "Daily Total Rainfall (mm) at the Hong Kong Observatory\n"
        "Year,Month,Day,Value,data Completeness\n"
        + "\n".join(rows)
        + "\n\n*** unavailable\n# data incomplete\n"
        "Trace means rainfall less than 0.05 mm\nC data Complete\n"
    )
    return parse_rows(csv.reader(io.StringIO(text)))

# ---------------------------------------------------------------------------
# Checks for missingness, quality, calendar validity, and equal time windows.
# ---------------------------------------------------------------------------


class RainfallTests(unittest.TestCase):
    """Catch plausible data errors that would otherwise produce a convincing chart."""

    def test_missing_and_incomplete_are_not_dry_days(self):
        """Only complete numeric days contribute to a total or a rainy-day count."""
        records, _ = fixture([
            "2026,1,1,0.0,C", "2026,1,2,Trace,C", "2026,1,3,1.0,C",
            "2026,1,4,***,", "2026,1,5,12.5,#",
        ])
        stats = summarise(records, dt.date(2026, 1, 6))
        self.assertEqual((stats["complete"], stats["missing"], stats["traces"]), (3, 3, 1))
        self.assertEqual((stats["total"], stats["rainy"]), (1.0, 1))
        self.assertEqual(stats["peak_day"], dt.date(2026, 1, 3))
        dates, amounts = cumulative(records, dt.date(2026, 1, 6))
        self.assertEqual(dates[-1], dt.date(2026, 1, 3))
        self.assertEqual(amounts, [0.0, 0.0, 1.0])

    def test_invalid_missing_date_is_disclosed(self):
        """An unavailable non-date is audited, while an observed non-date is rejected."""
        records, excluded = fixture([
            "1900,2,28,0.0,C", "1900,2,29,***,", "1900,3,1,2.0,C",
        ])
        self.assertEqual(len(records), 2)
        self.assertEqual(excluded[0]["date_fields"], ["1900", "2", "29"])
        with self.assertRaisesRegex(ValueError, "invalid calendar date"):
            fixture(["1900,2,29,2.0,C"])

    def test_duplicates_and_bad_numbers_fail_loudly(self):
        """Do not replace duplicates or draw negative and non-finite rainfall."""
        with self.assertRaisesRegex(ValueError, "duplicate"):
            fixture(["2026,1,1,1.0,C", "2026,1,1,2.0,C"])
        for value in ("-1", "nan", "inf", "not a number"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fixture([f"2026,1,1,{value},C"])
        with self.assertRaisesRegex(ValueError, "unknown"):
            fixture(["2026,1,1,1.0,NEW-FLAG"])

    def test_comparison_uses_the_shorter_published_window(self):
        """A full previous year must not be compared with an unfinished current year."""
        records, _ = fixture([
            "2025,12,31,0.0,C", "2026,8,31,0.0,C",
        ])
        current, previous = comparison_end(records, dt.date(2026, 8, 31))
        self.assertEqual((current, previous), (dt.date(2026, 8, 31), dt.date(2025, 8, 31)))
        records, _ = fixture(["2025,7,31,0.0,C", "2026,8,31,0.0,C"])
        current, previous = comparison_end(records, dt.date(2026, 8, 31))
        self.assertEqual((current.month, current.day), (7, 31))
        self.assertEqual((previous.month, previous.day), (7, 31))

    def test_leap_day_has_a_valid_comparison_cutoff(self):
        """End both windows on 28 February when a leap day has no counterpart."""
        records, _ = fixture(["2025,12,31,0.0,C", "2028,2,29,0.0,C"])
        current, previous = comparison_end(records, dt.date(2028, 2, 29))
        self.assertEqual((current.day, previous.day), (28, 28))

    def test_real_snapshot_coverage_and_published_extremes(self):
        """Verify the downloaded years independently of the drawing's layout."""
        records, excluded = read_records()
        self.assertEqual(len(records) + len(excluded), 49492)
        self.assertEqual(max(records), dt.date(2026, 8, 31))
        stats = summarise(records, dt.date(2026, 8, 31))
        # The source has 243 complete daily values; future months must not add zeros.
        self.assertEqual((stats["complete"], stats["missing"]), (243, 0))
        self.assertAlmostEqual(stats["total"], 2357.6, places=6)
        self.assertEqual(stats["peak_day"], dt.date(2026, 6, 15))
        self.assertAlmostEqual(stats["peak_mm"], 122.6, places=6)
        prior = summarise(records, dt.date(2025, 8, 31))
        self.assertAlmostEqual(prior["total"], 1985.3, places=6)


# ---------------------------------------------------------------------------
# Explorer checks. Each mode and playback step starts with these same values.
# ---------------------------------------------------------------------------


class ExplorerTests(unittest.TestCase):
    """Verify exported playback prefixes, daily states, and matched-year limits."""

    def test_daily_states_do_not_confuse_rain_with_missing_data(self):
        """Distinguish measured zero, trace, missing, incomplete, and unpublished."""
        self.assertEqual(describe_day({"mm": 0.0, "flag": "C", "trace": False}, True), "dry")
        self.assertEqual(describe_day({"mm": 0.0, "flag": "C", "trace": True}, True), "trace")
        self.assertEqual(describe_day(None, True), "missing")
        self.assertEqual(describe_day({"mm": 2.0, "flag": "#", "trace": False}, True), "incomplete")
        self.assertEqual(describe_day(None, False), "unpublished")

    def test_prefix_statistics_only_use_the_selected_date(self):
        """Later observed rainfall must not enter an earlier playback total."""
        records, _ = fixture([
            "2026,1,1,0.0,C", "2026,1,2,Trace,C", "2026,1,3,***,",
            "2026,1,4,2.0,#", "2026,1,5,7.0,C",
        ])
        series = prepare_year(records, 2026)
        days = series["days"]
        self.assertEqual(days[1]["stats"]["total"], 0.0)
        self.assertEqual(days[1]["stats"]["traces"], 1)
        self.assertEqual(days[1]["stats"]["peakIndex"], 1)
        self.assertEqual(days[4]["stats"]["total"], 7.0)
        self.assertEqual(days[4]["stats"]["missing"], 2)
        self.assertIsNone(days[2]["cumulative"])
        self.assertIsNone(days[4]["cumulative"])
        self.assertEqual(days[5]["status"], "unpublished")
        self.assertIsNone(days[5]["mm"])
        self.assertIsNone(days[5]["cumulative"])

    def test_exported_years_share_an_honest_comparison_window(self):
        """The full 2025 record stays available without extending its paired window."""
        records, excluded = read_records()
        payload = build_payload(records, excluded)
        current = payload["years"]["2026"]
        previous = payload["years"]["2025"]
        self.assertEqual((current["observedCount"], previous["observedCount"]), (243, 365))
        self.assertEqual((current["matchedCount"], previous["matchedCount"]), (243, 243))
        self.assertEqual(len(current["days"]), 365)
        self.assertEqual(current["days"][243]["status"], "unpublished")
        self.assertEqual(current["days"][242]["counterpart"], 242)
        self.assertEqual(current["days"][242]["stats"]["complete"], 243)
        self.assertAlmostEqual(current["days"][242]["cumulative"], 2357.6)
        self.assertAlmostEqual(previous["days"][242]["cumulative"], 1985.3)
        self.assertGreaterEqual(payload["scaleMax"], 368.9)


if __name__ == "__main__":
    unittest.main()
