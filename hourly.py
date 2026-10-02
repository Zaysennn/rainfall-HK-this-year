# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Read or fetch separate observed and modelled hourly rainfall.

Run: uv run hourly.py --date 2026-06-15 --mode model
Read saved responses only: uv run hourly.py --date 2026-06-15 --offline
Model estimates never fill a missing gauge observation or change HKO daily totals.
"""

import argparse
import calendar
import datetime as dt
import hashlib
import json
import math
import os
import tempfile
import threading
import urllib.parse
from pathlib import Path

from fetch_weather import archive_time, archive_versions, download
from weather import parse_hourly_snapshots

# ---------------------------------------------------------------------------
# The knobs. These are independent sources, even when their clocks agree.
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "hourly"
HKT = dt.timezone(dt.timedelta(hours=8))
YEARS = (2025, 2026)
LATITUDE, LONGITUDE = 22.302, 114.174
MODEL = "ecmwf_ifs"
STATION = "Hong Kong Observatory"
STATION_ID = "RF023"
RAIN_URL = "https://data.weather.gov.hk/weatherAPI/opendata/hourlyRainfall.php?lang=en"
ARCHIVE = "https://api.data.gov.hk/v1/historical-archive/"
MODEL_URLS = {
    "archive": "https://archive-api.open-meteo.com/v1/archive",
    "historicalForecast": "https://historical-forecast-api.open-meteo.com/v1/forecast",
    "recentForecast": "https://api.open-meteo.com/v1/forecast",
}
MODEL_TITLES = {
    "archive": "Open-Meteo ECMWF IFS historical model estimate",
    "historicalForecast": "Open-Meteo ECMWF IFS historical forecast model estimate",
    "recentForecast": "Open-Meteo ECMWF IFS recent forecast model estimate",
}
LOCK = threading.RLock()
MONTH_LOCKS = {}


# ---------------------------------------------------------------------------
# Parse source values before saving anything. Missing rain never becomes zero.
# ---------------------------------------------------------------------------


def hong_kong_now(now=None):
    """Use an aware Hong Kong clock rather than the machine's local calendar."""
    clock = now if now is not None else dt.datetime.now(dt.timezone.utc)
    if not isinstance(clock, dt.datetime) or clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("The hourly clock must be timezone-aware.")
    return clock.astimezone(HKT)


def calendar_date(value):
    """Accept explicit ISO dates and datetime.date objects."""
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    raise ValueError("Expected an ISO calendar date.")


def project_date(value, clock):
    """Keep requests within the configured years and never request a future date."""
    date = calendar_date(value)
    if date.year not in YEARS or date > clock.date():
        raise ValueError("Hourly dates must be in 2025 or 2026 and must not be in the future.")
    return date


def json_object(raw):
    """Accept original UTF-8 bytes or a decoded JSON object."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict) or raw.get("error") is True:
        raise ValueError("Expected a successful hourly JSON object.")
    return raw


def finite_number(value, name, minimum=None, maximum=None):
    """Reject invalid values instead of silently turning them into plausible rainfall."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"Invalid {name}.")
    try:
        number = float(value)
    except (ValueError, TypeError) as problem:
        raise ValueError(f"Invalid {name}.") from problem
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite.")
    if minimum is not None and number < minimum or maximum is not None and number > maximum:
        raise ValueError(f"{name} is outside its valid range.")
    return number


def source_type(url):
    """Name a forecast response explicitly; an archive label is never borrowed for it."""
    if "historical-forecast-api.open-meteo.com" in url:
        return "historicalForecast"
    if "api.open-meteo.com" in url and "archive-api.open-meteo.com" not in url:
        return "recentForecast"
    return "archive"


def parse_model_response(raw, start_date, end_date, now=None, source_url="", source_title=""):
    """Map preceding-hour model amounts to actual 00:00-24:00 Hong Kong day windows."""
    clock = hong_kong_now(now)
    start = project_date(start_date, clock)
    end = project_date(end_date, clock)
    if end < start:
        raise ValueError("The hourly period ends before it starts.")
    body = json_object(raw)
    if body.get("timezone") != "Asia/Hong_Kong" or body.get("utc_offset_seconds") != 28800:
        raise ValueError("Model responses must use Asia/Hong_Kong and UTC+08:00.")
    units = body.get("hourly_units", {})
    if units.get("time") != "iso8601" or units.get("rain") != "mm":
        raise ValueError("Expected ISO timestamps and model rain in millimetres.")
    latitude = finite_number(body.get("latitude"), "grid latitude", -90, 90)
    longitude = finite_number(body.get("longitude"), "grid longitude", -180, 180)
    if abs(latitude - LATITUDE) > .5 or abs(longitude - LONGITUDE) > .5:
        raise ValueError("The returned model grid is not near the requested Hong Kong location.")
    hourly = body.get("hourly", {})
    times, values = hourly.get("time"), hourly.get("rain")
    expected_count = ((end - start).days + 2) * 24
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != expected_count or len(values) != len(times):
        raise ValueError("The model response has the wrong number of hourly timestamps or values.")
    origin = dt.datetime.combine(start, dt.time(), HKT)
    selected = {}
    finish = dt.datetime.combine(end + dt.timedelta(days=1), dt.time(), HKT)
    kind = source_type(source_url)
    for index, (stamp, value) in enumerate(zip(times, values)):
        if not isinstance(stamp, str):
            raise ValueError("Invalid model timestamp.")
        try:
            when = dt.datetime.fromisoformat(stamp)
        except ValueError as problem:
            raise ValueError("Invalid model timestamp.") from problem
        when = when.replace(tzinfo=HKT) if when.tzinfo is None else when.astimezone(HKT)
        if when != origin + dt.timedelta(hours=index):
            raise ValueError("Model timestamps are duplicated, missing, or out of order.")
        mm = None if value is None else finite_number(value, "model rain", 0)
        # The first midnight refers to the previous day. The final useful midnight
        # closes the target day's 23:00-24:00 window, rather than starting a new slot.
        if origin < when <= finish:
            beginning = when - dt.timedelta(hours=1)
            date = beginning.date().isoformat()
            if date not in selected:
                selected[date] = {
                    "kind": "model", "source": MODEL, "model": "ECMWF IFS",
                    "sourceType": kind, "grid": {"latitude": latitude, "longitude": longitude},
                    "sourceURL": source_url, "sourceTitle": source_title or MODEL_TITLES[kind],
                    "hours": [], "completeHours": 0,
                }
            ended = when <= clock
            selected[date]["hours"].append({
                "hour": beginning.hour, "mm": mm if ended else None,
                "status": "estimated" if ended and mm is not None else "missing",
                "observationTime": when.isoformat(),
            })
    for day in selected.values():
        day["completeHours"] = sum(hour["status"] == "estimated" for hour in day["hours"])
    return selected


def parse_observation(raw, now=None):
    """Read only the named RF023 gauge; quarter-hour rolling windows are not added."""
    clock = hong_kong_now(now)
    body = json_object(raw)
    try:
        when = dt.datetime.fromisoformat(body["obsTime"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError, AttributeError) as problem:
        raise ValueError("The rain response needs a valid observation timestamp.") from problem
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("The rain observation must include its timezone.")
    when = when.astimezone(HKT)
    if when > clock:
        raise ValueError("A future rain interval cannot be a completed observation.")
    stations = body.get("hourlyRainfall")
    if not isinstance(stations, list):
        raise ValueError("Expected an hourlyRainfall station list.")
    matches = [item for item in stations if isinstance(item, dict) and item.get("automaticWeatherStationID") == STATION_ID]
    if not matches:
        return {}
    if len(matches) != 1:
        raise ValueError("Expected exactly one RF023 rain gauge.")
    station = matches[0]
    if station.get("automaticWeatherStation") != STATION or station.get("unit") != "mm":
        raise ValueError("The rain gauge's name or unit differs from the expected source.")
    if station.get("value") != "M":
        finite_number(station.get("value"), "observed rain", 0)
    grouped = parse_hourly_snapshots([body], station_id=STATION_ID)
    for day in grouped.values():
        day.update({"kind": "observed", "source": "currentRain", "stationID": STATION_ID,
                    "sourceURL": RAIN_URL, "sourceTitle": "Provisional rainfall at the HKO RF023 AWS gauge"})
    return grouped


# ---------------------------------------------------------------------------
# A small index selects immutable raw responses. Reading never creates a folder.
# ---------------------------------------------------------------------------


def empty_manifest():
    return {"version": 1, "timezone": "Asia/Hong_Kong", "snapshots": [], "model": {}, "queries": {}}


def load_manifest(data_dir):
    target = Path(data_dir) / "manifest.json"
    if not target.is_file():
        return empty_manifest()
    result = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("version") != 1 or result.get("timezone") != "Asia/Hong_Kong":
        raise ValueError("Unsupported hourly cache manifest.")
    return result


def checked_sources(data_dir, manifest):
    """Check every saved original response, including versions no longer selected."""
    root = Path(data_dir).resolve()
    raw_files, entries = {}, {}
    for entry in manifest.get("snapshots", []):
        name = entry["raw_file"]
        target = (root / name).resolve()
        if not target.is_relative_to(root) or name in entries:
            raise ValueError("Invalid or duplicate hourly cache path.")
        raw = target.read_bytes()
        if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError(f"Hourly snapshot checksum mismatch: {name}")
        raw_files[name], entries[name] = raw, entry
    return raw_files, entries


def read_hourly(now=None, data_dir=None):
    """Read two independent data collections, verifying all raw bytes without networking."""
    clock = hong_kong_now(now)
    data_dir = Path(data_dir) if data_dir is not None else DATA
    with LOCK:
        manifest = load_manifest(data_dir)
        raw_files, entries = checked_sources(data_dir, manifest)
        model, parsed_models, observed_versions = {}, {}, []
        for date, name in manifest.get("model", {}).items():
            if name not in entries or entries[name].get("mode") != "model":
                raise ValueError("A model date points to a different or missing source.")
            entry = entries[name]
            if name not in parsed_models:
                parsed_models[name] = parse_model_response(
                    raw_files[name], entry["startDate"], entry["endDate"], now=clock,
                    source_url=entry.get("requested_url", ""), source_title=entry.get("sourceTitle", ""),
                )
            if date not in parsed_models[name]:
                raise ValueError("The selected model response does not contain its indexed date.")
            model[date] = parsed_models[name][date]
        for entry in manifest.get("snapshots", []):
            if entry.get("mode") == "observed":
                raw = raw_files[entry["raw_file"]]
                parse_observation(raw, now=clock)
                observed_versions.append(json_object(raw))
        observed = parse_hourly_snapshots(observed_versions, station_id=STATION_ID)
        for day in observed.values():
            day.update({"kind": "observed", "source": "currentRain", "stationID": STATION_ID,
                        "sourceURL": RAIN_URL, "sourceTitle": "Provisional rainfall at the HKO RF023 AWS gauge"})
        return {"observed": observed, "model": model, "queries": dict(manifest.get("queries", {}))}


def save_manifest(data_dir, manifest):
    """Commit the generated index atomically; immutable response files remain recoverable."""
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", prefix=".manifest-",
                                     suffix=".json", dir=data_dir, delete=False) as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = handle.name
    os.replace(temporary, data_dir / "manifest.json")


def save_response(data_dir, manifest, mode, raw, metadata):
    """Preserve source bytes and provenance; identical already-saved responses are reused."""
    if not isinstance(raw, bytes):
        raise ValueError("A download must return its original bytes.")
    digest = hashlib.sha256(raw).hexdigest()
    previous = next((entry for entry in manifest["snapshots"]
                     if entry["mode"] == mode and entry["sha256"] == digest
                     and entry.get("requested_url") == metadata.get("requested_url")), None)
    if previous is not None:
        return previous["raw_file"]
    captured = metadata.get("snapshotUTC") or dt.datetime.now(dt.timezone.utc).isoformat()
    timestamp = dt.datetime.fromisoformat(captured.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("A snapshot capture time must include its timezone.")
    stamp = timestamp.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    name = f"{mode}/{stamp}_{digest[:16]}.json"
    target = data_dir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(raw)
    entry = dict(metadata)
    entry.update({"mode": mode, "raw_file": name, "bytes": len(raw), "sha256": digest, "snapshotUTC": captured})
    manifest["snapshots"].append(entry)
    return name


def query_record(status, message, clock, complete=0):
    return {"status": status, "message": message, "checkedAt": clock.astimezone(dt.timezone.utc).isoformat(),
            "completeHours": complete}


def note_query(data_dir, key, status, message, clock, complete=0):
    """Persist failures independently of usable previous responses."""
    with LOCK:
        manifest = load_manifest(data_dir)
        manifest["queries"][key] = query_record(status, message, clock, complete)
        save_manifest(data_dir, manifest)


def month_lock(data_dir, date):
    """Coalesce simultaneous requests for different dates in the same month."""
    key = (str(Path(data_dir).resolve()), date.year, date.month)
    with LOCK:
        return MONTH_LOCKS.setdefault(key, threading.RLock())


# ---------------------------------------------------------------------------
# Model requests are monthly. The recent forecast route retains its own label.
# ---------------------------------------------------------------------------


def model_url(kind, start, end):
    params = {"latitude": LATITUDE, "longitude": LONGITUDE,
              "start_date": start.isoformat(), "end_date": end.isoformat(),
              "hourly": "rain", "models": MODEL, "timezone": "Asia/Hong_Kong"}
    return MODEL_URLS[kind] + "?" + urllib.parse.urlencode(params)


def refresh_models(start_date, end_date, data_dir=None, now=None):
    """Cache ended days by month, keeping earlier valid data if an independent request fails."""
    clock = hong_kong_now(now)
    start, requested_end = project_date(start_date, clock), project_date(end_date, clock)
    if requested_end < start:
        raise ValueError("The model period ends before it starts.")
    end = min(requested_end, clock.date() - dt.timedelta(days=1))
    data_dir = Path(data_dir) if data_dir is not None else DATA
    # Read first so corrupted bytes stop an update before any file changes.
    read_hourly(now=clock, data_dir=data_dir)
    cursor = start.replace(day=1)
    while cursor <= end:
        month_end = cursor.replace(day=calendar.monthrange(cursor.year, cursor.month)[1])
        target_end = min(month_end, clock.date() - dt.timedelta(days=1))
        dates = [(cursor + dt.timedelta(days=index)).isoformat() for index in range((target_end - cursor).days + 1)]
        with month_lock(data_dir, cursor):
            cached = read_hourly(now=clock, data_dir=data_dir)
            if all(cached["model"].get(date, {}).get("completeHours") == 24 for date in dates):
                cursor = (month_end + dt.timedelta(days=1)).replace(day=1)
                continue
            source_end = target_end + dt.timedelta(days=1)
            recent = source_end > clock.date() - dt.timedelta(days=1)
            kinds = ("historicalForecast", "recentForecast") if recent else ("archive", "historicalForecast")
            errors, success = [], False
            for kind in kinds:
                url = model_url(kind, cursor, source_end)
                try:
                    raw, metadata = download(url)
                    parsed = parse_model_response(raw, cursor, target_end, now=clock,
                                                  source_url=url, source_title=MODEL_TITLES[kind])
                    metadata = {**metadata, "requested_url": url, "sourceTitle": MODEL_TITLES[kind],
                                "sourceType": kind, "model": MODEL,
                                "startDate": cursor.isoformat(), "endDate": target_end.isoformat(),
                                "grid": next(iter(parsed.values()))["grid"]}
                    with LOCK:
                        manifest = load_manifest(data_dir)
                        name = save_response(data_dir, manifest, "model", raw, metadata)
                        for date, day in parsed.items():
                            # A partial new response never displaces a more complete saved day.
                            previous = cached["model"].get(date, {})
                            if day["completeHours"] >= previous.get("completeHours", 0):
                                manifest["model"][date] = name
                            count = max(day["completeHours"], previous.get("completeHours", 0))
                            manifest["queries"]["model:" + date] = query_record(
                                "cached" if count == 24 else "partial",
                                "24 hourly model estimates are cached." if count == 24 else
                                f"{count} of 24 model estimates are available; missing values are not filled.",
                                clock, count,
                            )
                        save_manifest(data_dir, manifest)
                    success = True
                    break
                except Exception as problem:
                    errors.append(f"{kind}: {type(problem).__name__}: {problem}")
            if not success:
                for date in dates:
                    count = cached["model"].get(date, {}).get("completeHours", 0)
                    note_query(data_dir, "model:" + date, "failed", " | ".join(errors)[:1000], clock, count)
        cursor = (month_end + dt.timedelta(days=1)).replace(day=1)
    return read_hourly(now=clock, data_dir=data_dir)


# ---------------------------------------------------------------------------
# Observed responses stay separate. A retained rolling hour is not a daily total.
# ---------------------------------------------------------------------------


def store_observation(raw, metadata, data_dir, clock):
    """Reject conflicting versions of a gauge hour while retaining every accepted original."""
    parsed = parse_observation(raw, now=clock)
    with LOCK:
        manifest = load_manifest(data_dir)
        raw_files, _ = checked_sources(data_dir, manifest)
        previous = [json_object(raw_files[entry["raw_file"]]) for entry in manifest["snapshots"]
                    if entry["mode"] == "observed"]
        parse_hourly_snapshots(previous + [json_object(raw)], station_id=STATION_ID)
        save_response(data_dir, manifest, "observed", raw,
                      {**metadata, "station": STATION, "stationID": STATION_ID, "unit": "mm"})
        for date, day in parsed.items():
            # The derived collection may already contain other hours from earlier captures.
            grouped = parse_hourly_snapshots(previous + [json_object(raw)], station_id=STATION_ID)
            count = grouped[date]["completeHours"]
            manifest["queries"]["observed:" + date] = query_record(
                "cached" if count == 24 else "partial",
                f"{count} of 24 genuine RF023 hourly observations are cached.", clock, count,
            )
        save_manifest(data_dir, manifest)
    return parsed


def capture_observation(data_dir=None, now=None):
    """Save the current public gauge response, suitable for a server's periodic collector."""
    clock = hong_kong_now(now)
    data_dir = Path(data_dir) if data_dir is not None else DATA
    previous = read_hourly(now=clock, data_dir=data_dir)
    date = clock.date().isoformat()
    try:
        raw, metadata = download(RAIN_URL)
        parsed = store_observation(raw, {**metadata, "requested_url": RAIN_URL}, data_dir, clock)
        if not parsed:
            count = previous["observed"].get(date, {}).get("completeHours", 0)
            note_query(data_dir, "observed:" + date, "partial",
                       "A rolling-hour response was saved; only whole-hour endings fill calendar slots.",
                       clock, count)
    except Exception as problem:
        count = previous["observed"].get(date, {}).get("completeHours", 0)
        note_query(data_dir, "observed:" + date, "failed", f"{type(problem).__name__}: {problem}"[:1000], clock, count)
    return read_hourly(now=clock, data_dir=data_dir)


def fetch_observed_date(date, data_dir, clock):
    """Try exact official archive keys without mistaking dictionary dates for rain files."""
    index_url = ARCHIVE + "list-file-versions?" + urllib.parse.urlencode({
        "url": RAIN_URL, "start": date.strftime("%Y%m%d"),
        "end": (date + dt.timedelta(days=1)).strftime("%Y%m%d"),
    })
    cached = read_hourly(now=clock, data_dir=data_dir)
    key = "observed:" + date.isoformat()
    try:
        raw, _ = download(index_url)
        versions = archive_versions(json_object(raw))
        if not versions:
            count = cached["observed"].get(date.isoformat(), {}).get("completeHours", 0)
            note_query(data_dir, key, "unavailable",
                       "The official archive returned no rainfall file versions for this date; existing observations are retained.",
                       clock, count)
            return
        candidates = []
        for hour in range(1, 25):
            ending = dt.datetime.combine(date, dt.time(), HKT) + dt.timedelta(hours=hour)
            stamps = sorted((stamp for stamp in versions
                             if ending <= archive_time(stamp) < ending + dt.timedelta(minutes=40)),
                            key=archive_time)
            candidates.extend(stamps[:2])
        errors = []
        for stamp in dict.fromkeys(candidates):
            url = ARCHIVE + "get-file?" + urllib.parse.urlencode({"url": RAIN_URL, "time": stamp})
            try:
                content, metadata = download(url)
                parsed = parse_observation(content, now=clock)
                if date.isoformat() not in parsed:
                    continue
                store_observation(content, {**metadata, "requested_url": url,
                                            "archiveVersion": stamp, "archiveIndexURL": index_url},
                                  data_dir, clock)
            except Exception as problem:
                errors.append(f"{type(problem).__name__}: {problem}")
        saved = read_hourly(now=clock, data_dir=data_dir)["observed"].get(date.isoformat())
        count = saved["completeHours"] if saved else 0
        note_query(data_dir, key, "cached" if count == 24 else "partial" if count else
                   "failed" if errors else "unavailable",
                   f"{count} of 24 genuine gauge hours are cached." +
                   (" " + errors[0][:700] if errors else ""), clock, count)
    except Exception as problem:
        count = cached["observed"].get(date.isoformat(), {}).get("completeHours", 0)
        note_query(data_dir, key, "failed", f"{type(problem).__name__}: {problem}"[:1000], clock, count)


def get_day(date_text, mode="model", offline=False, data_dir=None, now=None, force=False):
    """Load one date on demand; successful whole model months are reused across requests."""
    clock = hong_kong_now(now)
    date = project_date(date_text, clock)
    mode = "observed" if mode == "obs" else mode
    if mode not in ("model", "observed"):
        raise ValueError("Hourly mode must be model or observed.")
    data_dir = Path(data_dir) if data_dir is not None else DATA
    date_text = date.isoformat()
    key = mode + ":" + date_text

    def result():
        collection = read_hourly(now=clock, data_dir=data_dir)
        day = collection[mode].get(date_text)
        query = collection["queries"].get(key, {
            "status": "unqueried", "message": "No response has been cached for this date and mode.",
            "checkedAt": None, "completeHours": day["completeHours"] if day else 0,
        })
        return {"date": date_text, "mode": mode, "day": day, "query": query}

    saved = result()
    if offline or saved["day"] and saved["day"]["completeHours"] == 24:
        return saved
    if mode == "model" and date == clock.date():
        saved["query"] = {"status": "unavailable", "message": "Model history is shown for ended days only.",
                          "checkedAt": None, "completeHours": 0}
        return saved
    query = saved["query"]
    if not force and query["checkedAt"]:
        checked = dt.datetime.fromisoformat(query["checkedAt"].replace("Z", "+00:00"))
        if clock - checked < dt.timedelta(minutes=15):
            return saved
    if mode == "model":
        refresh_models(date, date, data_dir=data_dir, now=clock)
    elif date == clock.date():
        capture_observation(data_dir=data_dir, now=clock)
    else:
        fetch_observed_date(date, data_dir, clock)
    return result()


def main():
    """Request a date explicitly, or inspect the saved collections without the internet."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Inspect one date, as YYYY-MM-DD.")
    parser.add_argument("--mode", choices=("observed", "model"), default="model")
    parser.add_argument("--offline", action="store_true", help="Read saved data only.")
    args = parser.parse_args()
    if args.date:
        result = get_day(args.date, mode=args.mode, offline=args.offline)
        print(f"{result['date']} / {result['mode']}: {result['query']['completeHours']} of 24 hours")
        print(result["query"]["message"])
    else:
        saved = read_hourly()
        print(f"Observed dates cached: {len(saved['observed'])}")
        print(f"Model dates cached: {len(saved['model'])}")


if __name__ == "__main__":
    main()

