# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Read and check the saved rainfall numbers before drawing anything.

Run: uv run number.py
Source: the unchanged Observatory CSV in data/daily_HKO_RF_ALL.csv.
Prints the coverage, totals, and quality flags for 2025 and 2026. No internet.
"""

import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

# ---------------------------------------------------------------------------
# The knobs. Dates come from the snapshot, never from the computer's clock.
# ---------------------------------------------------------------------------

YEAR = 2026
PREVIOUS_YEAR = 2025
RAINY_DAY_MM = 1.0          # the threshold used in this project's rainy-day count
TRACE_LIMIT_MM = 0.05      # the upper limit stated in the publisher's footnote
HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "daily_HKO_RF_ALL.csv"
NOTES = HERE / "data" / "source.json"

# ---------------------------------------------------------------------------
# Reading the numbers. Keep missing, incomplete, and trace readings distinct.
# ---------------------------------------------------------------------------


def parse_rows(reader):
    """Return daily records and an explicit audit of invalid missing-date placeholders."""
    next(reader)                              # the Chinese title
    title = next(reader)
    if "Daily Total Rainfall (mm)" not in ",".join(title):
        raise ValueError("Expected the Observatory's daily rainfall file, in millimetres.")
    header = next(reader)
    columns = [name.split("/")[-1].strip().lower() for name in header]
    if columns != ["year", "month", "day", "value", "data completeness"]:
        raise ValueError(f"Unexpected rainfall columns: {header}")

    records = {}
    excluded = []
    previous = None
    footer = False
    for line, row in enumerate(reader, start=4):
        if not row or not any(cell.strip() for cell in row):
            continue
        if not row[0].strip().isdigit():
            note = " ".join(row).lower()
            if any(text in note for text in (
                "unavailable", "data incomplete", "trace means rainfall", "data complete"
            )):
                footer = True
                continue
            raise ValueError(f"Line {line}: unexpected text inside the data: {row}")
        if footer or len(row) != 5:
            raise ValueError(f"Line {line}: expected five daily fields before the footnotes.")

        value, flag = row[3].strip(), row[4].strip()
        try:
            when = dt.date(*(int(cell) for cell in row[:3]))
        except ValueError as problem:
            # The raw file contains 1900-02-29, a nonexistent date marked unavailable.
            # Preserve it in the CSV and disclose its exclusion from calendar calculations.
            if value == "***" and flag == "":
                excluded.append({"line": line, "date_fields": row[:3],
                                 "reason": "Invalid calendar date with an unavailable value."})
                continue
            raise ValueError(f"Line {line}: invalid calendar date {row[:3]}.") from problem
        if previous is not None and when <= previous:
            raise ValueError(f"Line {line}: duplicate or out-of-order date {when}.")
        trace = value.casefold() == "trace"
        mm = None if value == "***" else 0.0 if trace else float(value)
        if mm is not None and (not math.isfinite(mm) or mm < 0):
            raise ValueError(f"Line {line}: invalid rainfall amount {value}.")
        if flag not in ("C", "#", ""):
            raise ValueError(f"Line {line}: unknown data-completeness flag {flag!r}.")
        records[when] = {"mm": mm, "flag": flag, "trace": trace}
        previous = when
    if not records or not footer:
        raise ValueError("The file has no daily records or is missing its explanatory footnotes.")
    return records, excluded


def read_records():
    """Verify the raw snapshot's checksum, then parse its original CSV rows."""
    if not RAW.is_file() or not NOTES.is_file():
        raise FileNotFoundError("Missing rainfall snapshot; run uv run fetch.py once.")
    notes = json.loads(NOTES.read_text(encoding="utf-8"))
    if hashlib.sha256(RAW.read_bytes()).hexdigest() != notes["sha256"]:
        raise ValueError("The raw CSV differs from the downloaded snapshot; inspect it first.")
    with RAW.open(encoding="utf-8-sig", newline="") as handle:
        return parse_rows(csv.reader(handle))


def is_complete(record):
    """Only a numeric, publisher-marked complete reading may enter a total."""
    return record is not None and record["flag"] == "C" and record["mm"] is not None


def coverage_end(records, year):
    """Find the last published date, including any unavailable daily record."""
    dates = [when for when in records if when.year == year]
    if not dates:
        raise ValueError(f"The snapshot does not contain {year}; choose a published year.")
    return max(dates)


def days_to(end):
    """List every calendar day from New Year's Day to an inclusive cutoff."""
    start = dt.date(end.year, 1, 1)
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def summarise(records, end):
    """Count and sum complete days; disclose every omitted or trace reading."""
    total = 0.0
    rainy = complete = missing = traces = 0
    peak_day, peak_mm = None, -1.0
    for when in days_to(end):
        record = records.get(when)
        if not is_complete(record):
            missing += 1
            continue
        mm = record["mm"]
        total += mm
        complete += 1
        rainy += mm >= RAINY_DAY_MM
        traces += record["trace"]
        if mm > peak_mm:
            peak_day, peak_mm = when, mm
    if not complete:
        raise ValueError(f"No complete readings in {end.year} through {end:%d %b}.")
    return {
        "total": total, "rainy": rainy, "complete": complete, "missing": missing,
        "traces": traces, "peak_day": peak_day, "peak_mm": peak_mm,
    }


def comparison_end(records, current_end, previous_year=PREVIOUS_YEAR):
    """Compare equal month-and-day windows, never a partial year with a full year."""
    previous_end = coverage_end(records, previous_year)
    month, day = min((current_end.month, current_end.day),
                     (previous_end.month, previous_end.day))
    # A leap day has no counterpart in a non-leap year. End both on 28 February.
    if (month, day) == (2, 29):
        try:
            dt.date(previous_year, month, day)
            dt.date(current_end.year, month, day)
        except ValueError:
            day = 28
    return dt.date(current_end.year, month, day), dt.date(previous_year, month, day)


def cumulative(records, end):
    """Return daily totals, stopping at the first gap rather than inventing rain."""
    dates, totals = [], []
    total = 0.0
    for when in days_to(end):
        record = records.get(when)
        if not is_complete(record):
            break
        total += record["mm"]
        dates.append(when)
        totals.append(total)
    return dates, totals

# ---------------------------------------------------------------------------
# A small audit. This also runs on its own, before the plotting library is used.
# ---------------------------------------------------------------------------


def main():
    """Print the source's actual date coverage and the two equal-period totals."""
    records, excluded = read_records()
    end = coverage_end(records, YEAR)
    current_end, previous_end = comparison_end(records, end)
    print(f"{len(records) + len(excluded):,} raw daily rows; {len(records):,} valid dates: "
          f"{min(records)} to {max(records)}")
    for item in excluded:
        print(f"  excluded missing-date placeholder on line {item['line']}: {item['date_fields']}")
    for cutoff in (current_end, previous_end):
        stats = summarise(records, cutoff)
        print(f"{cutoff.year} through {cutoff:%d %b}: {stats['total']:,.1f} mm; "
              f"{stats['complete']} complete days; {stats['missing']} missing/incomplete; "
              f"{stats['traces']} trace readings; {stats['rainy']} days >= {RAINY_DAY_MM:g} mm")
        print(f"  wettest day: {stats['peak_day']} — {stats['peak_mm']:g} mm")


if __name__ == "__main__":
    main()
