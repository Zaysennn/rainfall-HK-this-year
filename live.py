# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Update recent Observatory reports while keeping every downloaded response intact.

Run: uv run live.py
Read saved data without the internet: uv run live.py --offline
The final daily CSV remains the historical reference. Recent daily reports are
provisional; today's temperature and past-hour AWS rain are separate observations.
"""

import argparse
import concurrent.futures
import csv
import datetime as dt
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

from fetch_weather import download
from weather import parse_hourly_snapshots

# ---------------------------------------------------------------------------
# The knobs. The Hong Kong calendar, rather than the machine's locale, sets today.
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "live"
HKT = dt.timezone(dt.timedelta(hours=8))
STATION = "Hong Kong Observatory"
STATION_ID = "RF023"
REFRESH_MINUTES = 15
RECENT_URL = "https://data.weather.gov.hk/weatherAPI/opendata/opendata.php?dataType=RYES&lang=en"
WEATHER_URL = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=en"
RAIN_URL = "https://data.weather.gov.hk/weatherAPI/opendata/hourlyRainfall.php?lang=en"
SOURCES = {
    "recentDaily": {
        "title": "Provisional daily weather and radiation report at the Observatory",
        "url": "https://data.gov.hk/en-data/dataset/hk-hko-rss-weather-and-radiation-level-report",
    },
    "currentWeather": {
        "title": "Current weather observations at the Hong Kong Observatory",
        "url": "https://data.gov.hk/en-data/dataset/hk-hko-rss-current-weather-report",
    },
    "currentRain": {
        "title": "Provisional past-hour rainfall at the Hong Kong Observatory AWS",
        "url": "https://data.gov.hk/en-data/dataset/hk-hko-rss-rainfall-in-the-past-hour",
    },
}


# ---------------------------------------------------------------------------
# Small parsing helpers. Zero, Trace, missing data, and timestamps stay distinct.
# ---------------------------------------------------------------------------


def hong_kong_now(now=None):
    """Interpret an explicit aware clock in Hong Kong time; never assume a local timezone."""
    clock = now if now is not None else dt.datetime.now(dt.timezone.utc)
    if not isinstance(clock, dt.datetime) or clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("The live clock must be a timezone-aware datetime.")
    return clock.astimezone(HKT)


def json_object(raw):
    """Accept original bytes or a decoded object, and reject HTML error responses."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError("Expected a JSON weather object.")
    return raw


def number(value, name, minimum=None, maximum=None):
    """Read finite numeric values without converting an unavailable reading into zero."""
    if value is None or (isinstance(value, str) and
                         value.strip().casefold() in ("", "***", "m", "n/a", "//", "--")):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a numeric reading.")
    try:
        result = float(value)
    except (ValueError, TypeError) as problem:
        raise ValueError(f"Invalid {name}: {value!r}") from problem
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite.")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} is below its valid range.")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} is above its valid range.")
    return result


def calendar_date(value):
    """Accept the API's YYYYMMDD strings or explicit ISO calendar dates."""
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, str) and len(value) == 8 and value.isdigit():
        return dt.datetime.strptime(value, "%Y%m%d").date()
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    raise ValueError("Expected a calendar date.")


def observation_time(value):
    """Require an explicit source timezone and convert the observation to Hong Kong time."""
    if not isinstance(value, str):
        raise ValueError("Missing observation timestamp.")
    try:
        when = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as problem:
        raise ValueError("Invalid observation timestamp.") from problem
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("Observation timestamps must include their timezone.")
    return when.astimezone(HKT)


def parse_daily_report(raw, expected_date=None):
    """Read a full previous day's provisional HKO report, including its actual publication."""
    report = json_object(raw)
    when = calendar_date(report.get("ReportTimeInfoDate"))
    if expected_date is not None and when != calendar_date(expected_date):
        raise ValueError("The daily report date differs from the requested date.")
    published_date = calendar_date(report.get("BulletinDate"))
    published_clock = report.get("BulletinTime")
    if not isinstance(published_clock, str) or len(published_clock) != 4 or not published_clock.isdigit():
        raise ValueError("Expected the bulletin time in HHmm format.")
    published = dt.datetime.combine(
        published_date, dt.time(int(published_clock[:2]), int(published_clock[2:])), HKT,
    )
    if published_date <= when:
        raise ValueError("A full daily report must be published after the observation day.")

    rain = report.get("HKOReadingsRainfall")
    trace = isinstance(rain, str) and rain.strip().casefold() == "trace"
    mm = 0.0 if trace else number(rain, "daily rainfall", 0)
    high = number(report.get("HKOReadingsMaxTemp"), "maximum temperature", -90, 60)
    low = number(report.get("HKOReadingsMinTemp"), "minimum temperature", -90, 60)
    maximum_rh = number(report.get("HKOReadingsMaxRH"), "maximum humidity", 0, 100)
    minimum_rh = number(report.get("HKOReadingsMinRH"), "minimum humidity", 0, 100)
    if high is not None and low is not None and low > high:
        raise ValueError("The daily minimum temperature exceeds the maximum.")
    if maximum_rh is not None and minimum_rh is not None and minimum_rh > maximum_rh:
        raise ValueError("The daily minimum humidity exceeds the maximum.")
    return {
        "date": when.isoformat(), "mm": mm, "trace": trace,
        "maxTemp": high, "minTemp": low, "minHumidity": minimum_rh,
        "maxHumidity": maximum_rh,
        "annualRain": number(report.get("HKOReadingsAccumRainfall"), "annual rainfall", 0),
        "status": "provisional", "source": "recentDaily",
        "publicationTime": published.isoformat(),
    }


def station_reading(report, field, minimum, maximum):
    """Pick the named Observatory reading, retaining that field's own observation time."""
    block = report.get(field)
    if block is None or block == "":
        return None
    if not isinstance(block, dict) or not isinstance(block.get("data"), list):
        raise ValueError(f"Unexpected current {field} structure.")
    stations = [item for item in block["data"] if item.get("place") == STATION]
    if len(stations) > 1:
        raise ValueError(f"Duplicate Observatory {field} readings.")
    if not stations:
        return None
    reading = stations[0]
    units = ("C",) if field == "temperature" else ("percent", "%")
    if reading.get("unit") not in units:
        raise ValueError(f"Unexpected current {field} unit.")
    when = observation_time(block.get("recordTime"))
    return {"value": number(reading.get("value"), field, minimum, maximum),
            "observationTime": when.isoformat()}


def parse_current_weather(raw):
    """Read current HKO temperature and humidity without using district rainfall as a total."""
    report = json_object(raw)
    updated = observation_time(report.get("updateTime"))
    return {
        "date": updated.date().isoformat(),
        "temperature": station_reading(report, "temperature", -90, 60),
        "humidity": station_reading(report, "humidity", 0, 100),
        "updateTime": updated.isoformat(),
    }


def parse_current_rain(raw):
    """Read the RF023 AWS gauge's rolling hour, never a full calendar-day total."""
    report = json_object(raw)
    when = observation_time(report.get("obsTime"))
    stations = report.get("hourlyRainfall")
    if not isinstance(stations, list):
        raise ValueError("Expected an hourlyRainfall list.")
    matches = [item for item in stations if item.get("automaticWeatherStationID") == STATION_ID]
    if len(matches) > 1:
        raise ValueError("Duplicate RF023 rainfall readings.")
    rainfall = None
    if matches:
        reading = matches[0]
        if reading.get("automaticWeatherStation") != STATION or reading.get("unit") != "mm":
            raise ValueError("The rain gauge's station or unit differs from the expected source.")
        rainfall = {
            "value": number(reading.get("value"), "past-hour rainfall", 0),
            "observationTime": when.isoformat(),
            "intervalStart": (when - dt.timedelta(hours=1)).isoformat(),
            "intervalEnd": when.isoformat(), "station": STATION, "stationID": STATION_ID,
        }
    return {"date": when.date().isoformat(), "rainfall": rainfall}


# ---------------------------------------------------------------------------
# Immutable responses. The manifest selects versions but never rewrites their bytes.
# ---------------------------------------------------------------------------


def empty_manifest():
    """Keep a small, explicit index for reports, current feeds, and refresh failures."""
    return {"version": 1, "timezone": "Asia/Hong_Kong", "snapshots": [],
            "daily": {}, "current": {}, "checkedAt": None, "lastSuccessAt": None,
            "errors": []}


def load_manifest(data_dir):
    """Read only the index; all selected and historical responses are verified separately."""
    target = Path(data_dir) / "manifest.json"
    if not target.is_file():
        return empty_manifest()
    result = json.loads(target.read_text(encoding="utf-8"))
    if result.get("version") != 1:
        raise ValueError("Unsupported live manifest version.")
    return result


def checked_snapshots(data_dir, manifest):
    """Verify original bytes and reject duplicate entries or paths outside the live cache."""
    root = Path(data_dir).resolve()
    raw_files = {}
    entries = {}
    for entry in manifest.get("snapshots", []):
        target = (root / entry["raw_file"]).resolve()
        if not target.is_relative_to(root):
            raise ValueError("A live snapshot path leaves the live cache.")
        if entry["raw_file"] in entries:
            raise ValueError("Duplicate live snapshot path in the manifest.")
        raw = target.read_bytes()
        if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError(f"Live snapshot checksum mismatch: {entry['raw_file']}")
        raw_files[entry["raw_file"]] = raw
        entries[entry["raw_file"]] = entry
    return raw_files, entries


def read_live(now=None, data_dir=None):
    """Return saved observations with their source times; this function never requests data."""
    clock = hong_kong_now(now)
    data_dir = Path(data_dir) if data_dir is not None else DATA
    manifest = load_manifest(data_dir)
    raw_files, entries = checked_snapshots(data_dir, manifest)
    daily = {}
    for date, name in manifest.get("daily", {}).items():
        if name not in entries or entries[name]["feed"] != "recentDaily":
            raise ValueError("A daily live index points to a different or missing feed.")
        daily[date] = parse_daily_report(raw_files[name], expected_date=date)

    current = {"date": clock.date().isoformat(), "temperature": None, "humidity": None,
               "rainfall": None}
    actual_times = []
    # Search valid previous versions for a field missing from the latest successful response.
    # Its old observation time remains visible, so a fallback cannot appear freshly measured.
    weather_entries = [entry for entry in manifest.get("snapshots", [])
                       if entry["feed"] == "currentWeather"]
    for entry in reversed(weather_entries):
        report = parse_current_weather(raw_files[entry["raw_file"]])
        for field in ("temperature", "humidity"):
            reading = report[field]
            if current[field] is None and reading is not None and reading["value"] is not None:
                current[field] = reading
                actual_times.append(observation_time(reading["observationTime"]))
        if current["temperature"] is not None and current["humidity"] is not None:
            break
    rain_entries = [entry for entry in manifest.get("snapshots", []) if entry["feed"] == "currentRain"]
    for entry in reversed(rain_entries):
        report = parse_current_rain(raw_files[entry["raw_file"]])
        if report["rainfall"] is not None:
            current["rainfall"] = report["rainfall"]
            actual_times.append(observation_time(report["rainfall"]["observationTime"]))
            break
    if actual_times:
        current["date"] = max(actual_times).date().isoformat()

    # Only reports ending on a whole hour can become non-overlapping hourly bars.
    # Later publisher revisions of the same observation take precedence in the derived view.
    hourly_versions = {}
    for entry in rain_entries:
        snapshot = json_object(raw_files[entry["raw_file"]])
        parsed = parse_current_rain(snapshot)
        if parsed["rainfall"] is not None:
            when = observation_time(snapshot["obsTime"])
            hourly_versions[when.isoformat()] = snapshot
    hourly = parse_hourly_snapshots(list(hourly_versions.values()), station_id=STATION_ID)
    for day in hourly.values():
        day["source"] = "currentRain"
    # Source notes describe the saved raw coverage, independently of browser polling.
    sources = {key: {**notes, "station": STATION} for key, notes in SOURCES.items()}
    for feed, source in sources.items():
        saved = [entry for entry in manifest.get("snapshots", []) if entry["feed"] == feed]
        dates = sorted({entry["date"] for entry in saved})
        captured = sorted(entry["snapshotUTC"] for entry in saved if entry.get("snapshotUTC"))
        if dates:
            source.update(coverageStart=dates[0], coverageEnd=dates[-1])
        if captured:
            source["snapshotUTC"] = captured[-1]
    return {
        "daily": daily, "current": current, "today": clock.date().isoformat(),
        "sources": sources, "checkedAt": manifest.get("checkedAt"),
        "lastSuccessAt": manifest.get("lastSuccessAt"), "errors": manifest.get("errors", []),
        "timezone": "Asia/Hong_Kong", "refreshMinutes": REFRESH_MINUTES, "hourly": hourly,
    }


def save_manifest(data_dir, manifest):
    """Replace the generated index atomically; every raw response remains independently recoverable."""
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                     prefix=".manifest-", suffix=".json",
                                     dir=data_dir, delete=False) as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temporary = handle.name
    os.replace(temporary, data_dir / "manifest.json")


def save_response(data_dir, manifest, feed, date, raw, metadata):
    """Add an unchanged response and source record, reusing identical already-saved bytes."""
    if not isinstance(raw, bytes):
        raise ValueError("A download must return its original bytes.")
    digest = hashlib.sha256(raw).hexdigest()
    existing = next((entry for entry in manifest["snapshots"]
                     if entry["feed"] == feed and entry["date"] == date
                     and entry["sha256"] == digest), None)
    if existing is not None:
        return existing["raw_file"]
    captured = metadata.get("snapshotUTC") or dt.datetime.now(dt.timezone.utc).isoformat()
    stamp = observation_time(captured).astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    name = f"raw/{feed}/{date}/{stamp}_{digest[:16]}.json"
    target = data_dir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(raw)
    entry = dict(metadata)
    entry.update({"raw_file": name, "feed": feed, "date": date, "sha256": digest,
                  "bytes": len(raw), "snapshotUTC": captured,
                  "station": STATION, "source_page": SOURCES[feed]["url"]})
    manifest["snapshots"].append(entry)
    return name


# ---------------------------------------------------------------------------
# Explicit refresh. Fill the historical gap, revisit seven days, then poll live feeds.
# ---------------------------------------------------------------------------


def refresh_live(coverage_end, now=None, data_dir=None):
    """Update supported days and preserve previous valid responses if any request fails."""
    clock = hong_kong_now(now)
    data_dir = Path(data_dir) if data_dir is not None else DATA
    # Integrity failures stop the update before it changes the cache.
    cached = read_live(now=clock, data_dir=data_dir)
    manifest = load_manifest(data_dir)
    first = calendar_date(coverage_end) + dt.timedelta(days=1)
    yesterday = clock.date() - dt.timedelta(days=1)
    recent_start = yesterday - dt.timedelta(days=6)
    dates = []
    when = first
    while when <= yesterday:
        if when.isoformat() not in cached["daily"] or when >= recent_start:
            dates.append(when)
        when += dt.timedelta(days=1)

    jobs = [("recentDaily", when.isoformat(), RECENT_URL + "&date=" + when.strftime("%Y%m%d"))
            for when in dates]
    jobs.extend((("currentWeather", None, WEATHER_URL), ("currentRain", None, RAIN_URL)))

    def receive(job):
        feed, requested_date, url = job
        try:
            raw, metadata = download(url)
            if feed == "recentDaily":
                parsed = parse_daily_report(raw, expected_date=requested_date)
            elif feed == "currentWeather":
                parsed = parse_current_weather(raw)
            else:
                parsed = parse_current_rain(raw)
            metadata = dict(metadata)
            metadata.setdefault("requested_url", url)
            metadata.setdefault("received_url", url)
            return feed, requested_date or parsed["date"], raw, metadata, None
        except Exception as problem:
            # Do not store an error page as observations or replace a usable previous version.
            return feed, requested_date, None, None, {
                "source": feed, "date": requested_date, "url": url,
                "message": f"{type(problem).__name__}: {problem}"[:1200],
            }

    errors = []
    succeeded = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for feed, date, raw, metadata, error in pool.map(receive, jobs):
            if error is not None:
                errors.append(error)
                continue
            try:
                name = save_response(data_dir, manifest, feed, date, raw, metadata)
                if feed == "recentDaily":
                    manifest["daily"][date] = name
                else:
                    manifest["current"]["weather" if feed == "currentWeather" else "rain"] = name
                succeeded += 1
            except Exception as problem:
                errors.append({"source": feed, "date": date,
                               "message": f"{type(problem).__name__}: {problem}"[:1200]})
    checked = clock.astimezone(dt.timezone.utc).isoformat()
    manifest["checkedAt"] = checked
    if succeeded:
        manifest["lastSuccessAt"] = checked
    manifest["errors"] = errors
    manifest["coverageEnd"] = calendar_date(coverage_end).isoformat()
    save_manifest(data_dir, manifest)
    return read_live(now=clock, data_dir=data_dir)


def monthly_cutoff():
    """Find the original saved monthly CSV's end without using the provisional extension."""
    from number import NOTES, RAW, parse_rows
    notes = json.loads(NOTES.read_text(encoding="utf-8"))
    raw = RAW.read_bytes()
    if hashlib.sha256(raw).hexdigest() != notes["sha256"]:
        raise ValueError("The monthly rainfall snapshot's checksum changed.")
    records, _ = parse_rows(csv.reader(raw.decode("utf-8-sig").splitlines()))
    return max(records)


def main():
    """Refresh explicitly, or inspect the latest saved source times entirely offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Read the cache without any request.")
    parser.add_argument("--coverage-end", help="Original monthly rainfall cutoff, as YYYY-MM-DD.")
    args = parser.parse_args()
    result = read_live() if args.offline else refresh_live(
        calendar_date(args.coverage_end) if args.coverage_end else monthly_cutoff(),
    )
    print(f"Recent provisional days cached: {len(result['daily'])}")
    print(f"Latest daily report: {max(result['daily'], default='not cached')}")
    print(f"Live observation date: {result['current']['date']}; today: {result['today']}")
    print(f"Last successful refresh (UTC): {result['lastSuccessAt'] or 'not refreshed'}")
    for error in result["errors"]:
        print(f"{error['source']} {error.get('date') or ''}: {error['message']}")


if __name__ == "__main__":
    main()

