# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Read cached Observatory weather without making a network request.

Run: uv run weather.py
Raw CSV and hourly JSON responses belong in data/weather/. Their checksums,
sources, dates, and download times are recorded separately in manifest.json.
"""

import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

# ---------------------------------------------------------------------------
# The knobs. Daily climate readings and hourly AWS readings have different sources.
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "weather"
TIMEZONE = dt.timezone(dt.timedelta(hours=8))
STATION = "Hong Kong Observatory"
METRICS = {
    "maxTemp": {"title": "Daily maximum temperature", "expected": "Daily Maximum Temperature",
                "unit": "degrees Celsius", "code": "CLMMAXT",
                "page": "https://data.gov.hk/en-data/dataset/hk-hko-rss-daily-temperature-info-hko"},
    "minTemp": {"title": "Daily minimum temperature", "expected": "Daily Minimum Temperature",
                "unit": "degrees Celsius", "code": "CLMMINT",
                "page": "https://data.gov.hk/en-data/dataset/hk-hko-rss-daily-temperature-info-hko"},
    "humidity": {"title": "Daily mean relative humidity", "expected": "Daily Mean Relative Humidity",
                 "unit": "%", "code": "RH",
                 "page": "https://data.gov.hk/en-data/dataset/hk-hko-rss-daily-mean-relative-humidity"},
    "cloud": {"title": "Daily mean cloud amount", "expected": "Daily Mean Amount of Cloud",
              "unit": "%", "code": "CLD",
              "page": "https://data.gov.hk/en-data/dataset/hk-hko-rss-daily-mean-amount-of-cloud"},
}
HOURLY_URL = "https://data.weather.gov.hk/weatherAPI/opendata/hourlyRainfall.php?lang=en"
HOURLY_PAGE = "https://data.gov.hk/en-data/dataset/hk-hko-rss-rainfall-in-the-past-hour"


# ---------------------------------------------------------------------------
# Daily CSV. Publisher flags decide whether a value is complete, not its size.
# ---------------------------------------------------------------------------


def parse_daily(reader, metric, source=None):
    """Parse the publisher's two titles, five columns, dated rows, and footnotes."""
    if metric not in METRICS:
        raise ValueError(f"Unknown weather metric: {metric}")
    rows = iter(reader)
    try:
        title = " ".join(" ".join(next(rows)) for _ in range(2))
        header = next(rows)
    except StopIteration as problem:
        raise ValueError("The weather CSV is missing its titles or header.") from problem
    if METRICS[metric]["expected"].casefold() not in title.casefold():
        raise ValueError(f"Expected {METRICS[metric]['expected']} in the weather CSV.")
    if STATION.casefold() not in title.casefold():
        raise ValueError("Expected the Hong Kong Observatory station in the weather CSV.")
    columns = [name.split("/")[-1].strip().lower() for name in header]
    if columns != ["year", "month", "day", "value", "data completeness"]:
        raise ValueError(f"Unexpected weather columns: {header}")

    records = {}
    previous = None
    footer = False
    for line, row in enumerate(rows, start=4):
        if not row or not any(cell.strip() for cell in row):
            continue
        if not row[0].strip().isdigit():
            note = " ".join(row).lower()
            if any(word in note for word in ("unavailable", "data incomplete", "data complete")):
                footer = True
                continue
            raise ValueError(f"Line {line}: unexpected weather text: {row}")
        if footer or len(row) != 5:
            raise ValueError(f"Line {line}: expected five weather fields before the footnotes.")
        try:
            when = dt.date(*(int(cell.strip()) for cell in row[:3]))
        except ValueError as problem:
            raise ValueError(f"Line {line}: invalid calendar date {row[:3]}.") from problem
        if previous is not None and when <= previous:
            raise ValueError(f"Line {line}: duplicate or out-of-order date {when}.")
        raw_value, flag = row[3].strip(), row[4].strip()
        if flag not in ("C", "#", ""):
            raise ValueError(f"Line {line}: unknown data-completeness flag {flag!r}.")
        value = None if raw_value == "***" else float(raw_value)
        if value is not None and not math.isfinite(value):
            raise ValueError(f"Line {line}: non-finite weather value.")
        if metric in ("humidity", "cloud") and value is not None and not 0 <= value <= 100:
            raise ValueError(f"Line {line}: percentage outside 0 to 100.")
        status = "missing" if value is None else "complete" if flag == "C" else "incomplete"
        records[when.isoformat()] = {
            "value": value, "status": status, "flag": flag, "source": source or metric,
        }
        previous = when
    if not records or not footer:
        raise ValueError("The weather CSV has no records or is missing its footnotes.")
    return records


# ---------------------------------------------------------------------------
# Hourly JSON. Keep only whole-hour windows, never overlapping quarter-hour reports.
# ---------------------------------------------------------------------------


def parse_hourly_snapshots(snapshots, station_id=None):
    """Group real AWS snapshots into 24 windows from 00:00 to 24:00 Hong Kong time."""
    readings = {}
    selected_id = station_id
    for snapshot in snapshots:
        try:
            observation = dt.datetime.fromisoformat(snapshot["obsTime"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError) as problem:
            raise ValueError("Hourly JSON needs a valid obsTime.") from problem
        if observation.tzinfo is None or observation.utcoffset() is None:
            raise ValueError("Hourly observation time must include its timezone.")
        observation = observation.astimezone(TIMEZONE)
        if observation.minute != 0 or observation.second != 0 or observation.microsecond != 0:
            continue
        stations = snapshot.get("hourlyRainfall")
        if not isinstance(stations, list):
            raise ValueError("Hourly JSON needs an hourlyRainfall list.")
        if selected_id is None:
            station = next((item for item in stations
                            if item.get("automaticWeatherStation") == STATION), None)
            if station is None:
                continue
            selected_id = station.get("automaticWeatherStationID")
            if not selected_id:
                raise ValueError("The hourly station is missing its ID.")
        station = next((item for item in stations
                        if item.get("automaticWeatherStationID") == selected_id), None)
        if station is None:
            continue
        if station.get("automaticWeatherStation") != STATION:
            raise ValueError("The selected hourly station is not Hong Kong Observatory.")
        if station.get("unit") != "mm":
            raise ValueError("Expected hourly rainfall in millimetres.")
        raw_value = station.get("value")
        if raw_value == "M":
            mm = None
        else:
            if isinstance(raw_value, bool) or raw_value is None:
                raise ValueError("Invalid hourly rainfall value.")
            try:
                mm = float(raw_value)
            except (TypeError, ValueError) as problem:
                raise ValueError("Invalid hourly rainfall value.") from problem
            if not math.isfinite(mm) or mm < 0:
                raise ValueError("Hourly rainfall must be finite and non-negative.")
        timestamp = observation.isoformat()
        if timestamp in readings and readings[timestamp]["mm"] != mm:
            raise ValueError(f"Conflicting hourly snapshots for {timestamp}.")
        readings[timestamp] = {"mm": mm, "time": observation}

    grouped = {}
    for timestamp, reading in sorted(readings.items()):
        # The reading ending at midnight belongs to the previous day's 23:00 window.
        start = reading["time"] - dt.timedelta(hours=1)
        when = start.date().isoformat()
        if when not in grouped:
            grouped[when] = {
                "hours": [{"hour": hour, "mm": None, "status": "missing",
                           "observationTime": None} for hour in range(24)],
                "completeHours": 0, "station": STATION, "source": "hourly",
            }
        grouped[when]["hours"][start.hour] = {
            "hour": start.hour, "mm": reading["mm"],
            "status": "observed" if reading["mm"] is not None else "missing",
            "observationTime": timestamp,
        }
    for day in grouped.values():
        day["completeHours"] = sum(hour["status"] == "observed" for hour in day["hours"])
    return grouped


# ---------------------------------------------------------------------------
# The saved snapshot. Read bytes, verify checksums, then join by calendar date.
# ---------------------------------------------------------------------------


def snapshot_bytes(data_dir, entry):
    """Reject changed bytes and paths outside this weather cache before parsing."""
    root = Path(data_dir).resolve()
    target = (root / entry["raw_file"]).resolve()
    if not target.is_relative_to(root):
        raise ValueError("A weather snapshot path leaves the weather cache.")
    raw = target.read_bytes()
    if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError(f"Weather snapshot checksum mismatch: {entry['raw_file']}")
    return raw


def read_weather(data_dir=None):
    """Return available weather and honest empty states without accessing the internet."""
    data_dir = Path(data_dir) if data_dir is not None else DATA
    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    daily = {}
    sources = {metric: {"title": info["title"], "station": STATION, "url": info["page"],
                        "coverageStart": "", "coverageEnd": "", "snapshotUTC": "",
                        "unit": info["unit"]} for metric, info in METRICS.items()}
    for entry in manifest.get("dailyFiles", []):
        metric = entry["metric"]
        raw = snapshot_bytes(data_dir, entry)
        records = parse_daily(csv.reader(raw.decode("utf-8-sig").splitlines()), metric)
        for when, value in records.items():
            if metric in daily.setdefault(when, {}):
                raise ValueError(f"Duplicate cached weather metric for {when}: {metric}")
            daily[when][metric] = value
        source = sources[metric]
        source["coverageStart"] = min(filter(None, (source["coverageStart"], min(records))))
        source["coverageEnd"] = max(source["coverageEnd"], max(records))
        source["snapshotUTC"] = max(source["snapshotUTC"], entry["snapshotUTC"])
    for when, values in daily.items():
        low, high = values.get("minTemp"), values.get("maxTemp")
        if low and high and low["status"] == high["status"] == "complete":
            if low["value"] > high["value"]:
                raise ValueError(f"Minimum temperature exceeds maximum on {when}.")

    snapshots = [json.loads(snapshot_bytes(data_dir, entry).decode("utf-8-sig"))
                 for entry in manifest.get("hourlyFiles", [])]
    hourly = parse_hourly_snapshots(snapshots)
    sources["hourly"] = {
        "title": "Rainfall in the past hour from automatic weather stations",
        "station": STATION, "url": HOURLY_PAGE, "coverageStart": min(hourly, default=""),
        "coverageEnd": max(hourly, default=""),
        "snapshotUTC": max((entry["snapshotUTC"] for entry in manifest.get("hourlyFiles", [])),
                           default=""), "unit": "mm",
    }
    note = ("Hourly bars use cached, provisional AWS observations in Hong Kong time. "
            "This rainfall source differs from the official daily total. "
            "Dates without snapshots have not been cached by this project.")
    if not hourly:
        note = ("No hourly observations are cached by this project. "
                "Missing bars do not mean zero rain or that the Observatory has no records.")
        if any(query.get("status") == "failed"
               for query in manifest.get("hourlyQueries", {}).values()):
            note += " The last attempt to query the official archive failed."
    return {"daily": daily, "hourly": hourly, "sources": sources, "hourlyNote": note,
            "timezone": "Asia/Hong_Kong", "hourlyQueries": manifest.get("hourlyQueries", {}),
            "dailyQueries": manifest.get("dailyQueries", {})}


def main():
    """Report what can be displayed from the existing weather cache."""
    weather = read_weather()
    for metric in METRICS:
        source = weather["sources"][metric]
        print(f"{source['title']}: {source['coverageStart'] or 'not cached'}"
              f" to {source['coverageEnd'] or 'not cached'}")
    print(f"Hourly dates cached: {len(weather['hourly'])}")
    print(weather["hourlyNote"])


if __name__ == "__main__":
    main()

