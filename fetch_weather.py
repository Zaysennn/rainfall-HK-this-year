# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Fetch real daily weather and, optionally, archived hourly rain into data/weather/.

Run: uv run fetch_weather.py
One historical day: uv run fetch_weather.py --hourly-date 2026-06-15
An existing HTTP proxy may be passed with --proxy http://127.0.0.1:PORT.
No proxy is hard-coded and certificate verification is always enabled.
Existing raw responses are kept unchanged; network failures are recorded as failures.
"""

import argparse
import base64
import concurrent.futures
import csv
import datetime as dt
import hashlib
import io
import os
import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from weather import (
    DATA, HOURLY_PAGE, HOURLY_URL, METRICS, STATION, TIMEZONE,
    parse_daily, parse_hourly_snapshots, read_weather, snapshot_bytes,
)

# ---------------------------------------------------------------------------
# The knobs. Small yearly CSV files and selected dates, never a whole-year hourly crawl.
# ---------------------------------------------------------------------------

YEARS = (2025, 2026)
ARCHIVE = "https://api.data.gov.hk/v1/historical-archive/"
MAX_BYTES = 5_000_000


def daily_url(metric, year):
    """Use the publisher's climate API for temperatures and original CSVs for percentages."""
    code = METRICS[metric]["code"]
    if metric in ("maxTemp", "minTemp"):
        return ("https://data.weather.gov.hk/weatherAPI/opendata/opendata.php?"
                + urllib.parse.urlencode({"dataType": code, "year": year,
                                          "rformat": "csv", "station": "HKO"}))
    return f"https://data.weather.gov.hk/weatherAPI/cis/csvfile/HKO/{year}/daily_HKO_{code}_{year}.csv"


def download_windows(url, proxy=None):
    """Use Windows' HTTPS client with TLS 1.2 and normal certificate verification."""
    script = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Net.Http
$handler = [System.Net.Http.HttpClientHandler]::new()
$handler.SslProtocols = [System.Security.Authentication.SslProtocols]::Tls12
$handler.UseProxy = $false
PROXY_PLACEHOLDER
$client = [System.Net.Http.HttpClient]::new($handler)
$client.Timeout = [TimeSpan]::FromSeconds(30)
$client.MaxResponseContentBufferSize = 5000001
$client.DefaultRequestHeaders.UserAgent.ParseAdd('rainfall-HK-this-year/1.0')
try {
    $reply = $client.GetAsync(URL_PLACEHOLDER).GetAwaiter().GetResult()
    $bytes = $reply.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
    $record = @{
        status = [int]$reply.StatusCode
        raw = [Convert]::ToBase64String($bytes)
        received_url = $reply.RequestMessage.RequestUri.AbsoluteUri
        last_modified = [string]$reply.Content.Headers.LastModified
        content_type = [string]$reply.Content.Headers.ContentType
    }
    $record | ConvertTo-Json -Compress
} finally {
    $client.Dispose()
    $handler.Dispose()
}
"""
    quote = lambda value: "'" + value.replace("'", "''") + "'"
    proxy_code = ("$handler.Proxy = [System.Net.WebProxy]::new(" + quote(proxy) + ")\n"
                  "$handler.UseProxy = $true") if proxy else ""
    script = script.replace("URL_PLACEHOLDER", quote(url)).replace("PROXY_PLACEHOLDER", proxy_code)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, encoding="utf-8", timeout=45, check=False,
    )
    if result.returncode:
        raise OSError("Windows HTTPS request failed: " + result.stderr.strip()[:900])
    response = json.loads(result.stdout.lstrip("\ufeff"))
    raw = base64.b64decode(response.pop("raw"), validate=True)
    status = response.pop("status")
    if not 200 <= status < 300:
        raise urllib.error.HTTPError(url, status, f"Server returned HTTP {status}",
                                     None, io.BytesIO(raw))
    return raw, response


def download(url, proxy=None):
    """Read HTTPS with certificate checks, using a compatible native client on Windows."""
    if os.name == "nt":
        raw, response = download_windows(url, proxy)
    else:
        handlers = [urllib.request.ProxyHandler({"https": proxy, "http": proxy})] if proxy else []
        opener = urllib.request.build_opener(*handlers)
        request = urllib.request.Request(url, headers={"User-Agent": "rainfall-HK-this-year/1.0"})
        with opener.open(request, timeout=30) as reply:
            raw = reply.read(MAX_BYTES + 1)
            response = {"received_url": reply.geturl(),
                        "last_modified": reply.headers.get("Last-Modified"),
                        "content_type": reply.headers.get("Content-Type")}
    if len(raw) > MAX_BYTES:
        raise ValueError("The weather response exceeds the expected download size.")
    response.update({
        "requested_url": url, "snapshotUTC": dt.datetime.now(dt.timezone.utc).isoformat(),
        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
    })
    return raw, response

def save_raw(raw, entry):
    """Create new raw files exclusively; an existing file must match its recorded checksum."""
    target = DATA / entry["raw_file"]
    if target.exists():
        snapshot_bytes(DATA, entry)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(raw)


def save_manifest(manifest):
    """Save separate provenance only; the publisher's raw files are never rewritten."""
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "manifest.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def fetch_daily(manifest, proxy=None):
    """Download only missing yearly metrics, validating titles, flags, dates, and ranges first."""
    existing = {(entry["metric"], entry["year"]): entry
                for entry in manifest["dailyFiles"]}
    jobs = [(metric, year) for year in YEARS for metric in METRICS
            if (metric, year) not in existing]
    for entry in existing.values():
        snapshot_bytes(DATA, entry)

    def receive(job):
        metric, year = job
        try:
            raw, entry = download(daily_url(metric, year), proxy)
            records = parse_daily(csv.reader(io.StringIO(raw.decode("utf-8-sig"))), metric)
            if any(dt.date.fromisoformat(when).year != year for when in records):
                raise ValueError("The weather reply contains a different year.")
            entry.update({
                "raw_file": f"daily_HKO_{METRICS[metric]['code']}_{year}.csv",
                "metric": metric, "year": year, "station": STATION,
                "unit": METRICS[metric]["unit"], "source_page": METRICS[metric]["page"],
                "coverageStart": min(records), "coverageEnd": max(records),
            })
            return metric, year, raw, entry, None
        except Exception as problem:
            return metric, year, None, None, f"{type(problem).__name__}: {problem}"

    # The requests are independent. Writes remain sequential after validation succeeds.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for metric, year, raw, entry, error in pool.map(receive, jobs):
            key = f"{metric}_{year}"
            if error:
                manifest["dailyQueries"][key] = {"status": "failed", "message": error}
                print(f"{key}: download failed; no raw file saved ({error})")
            else:
                save_raw(raw, entry)
                manifest["dailyFiles"].append(entry)
                manifest["dailyQueries"][key] = {"status": "cached", "message": "Original CSV saved."}
                print(f"{key}: saved {entry['coverageStart']} to {entry['coverageEnd']}")
            save_manifest(manifest)


def archive_versions(result):
    """Extract supplied archive timestamps without inventing observation times."""
    versions = set()

    def visit(value):
        if isinstance(value, str) and re.fullmatch(r"\d{14}|\d{8}-\d{4}", value):
            versions.add(value)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if re.fullmatch(r"\d{14}|\d{8}-\d{4}", str(key)):
                    versions.add(str(key))
                visit(item)

    visit(result)
    return sorted(versions)


def archive_time(stamp):
    """Read the publisher's capture time while preserving its original download key."""
    pattern = "%Y%m%d-%H%M" if "-" in stamp else "%Y%m%d%H%M%S"
    return dt.datetime.strptime(stamp, pattern).replace(tzinfo=TIMEZONE)


def fetch_hourly(manifest, date_text, proxy=None):
    """Try genuine archive versions for a selected day's non-overlapping hourly windows."""
    when = dt.date.fromisoformat(date_text)
    existing = read_weather()["hourly"].get(date_text)
    if existing and existing["completeHours"] == 24:
        print(f"{date_text}: 24 original hourly observations already cached; no request.")
        return
    tomorrow = when + dt.timedelta(days=1)
    index_url = ARCHIVE + "list-file-versions?" + urllib.parse.urlencode({
        "url": HOURLY_URL, "start": when.strftime("%Y%m%d"),
        "end": tomorrow.strftime("%Y%m%d"),
    })
    try:
        raw, _ = download(index_url, proxy)
        result = json.loads(raw.decode("utf-8-sig"))
        versions = archive_versions(result)
        if not versions:
            manifest["hourlyQueries"][date_text] = {
                "status": "unavailable",
                "message": "The official archive returned no usable version timestamps.",
            }
            save_manifest(manifest)
            print(f"{date_text}: archive returned no usable version timestamps.")
            return

        # Archive capture time and obsTime differ. Inspect the returned obsTime in every file.
        # At most two captures per target hour are tried, keeping this optional fetch small.
        candidates = []
        for hour in range(1, 25):
            end = dt.datetime.combine(when, dt.time(), TIMEZONE) + dt.timedelta(hours=hour)
            upper = end + dt.timedelta(minutes=40)
            candidates.extend([stamp for stamp in versions
                               if end <= archive_time(stamp) < upper][:2])
        errors = []
        for stamp in dict.fromkeys(candidates):
            url = ARCHIVE + "get-file?" + urllib.parse.urlencode({"url": HOURLY_URL, "time": stamp})
            try:
                content, entry = download(url, proxy)
                snapshot = json.loads(content.decode("utf-8-sig"))
                grouped = parse_hourly_snapshots([snapshot])
                if date_text not in grouped:
                    continue
                observation = dt.datetime.fromisoformat(snapshot["obsTime"].replace("Z", "+00:00"))
                observation = observation.astimezone(TIMEZONE)
                entry.update({
                    "raw_file": "hourly/" + observation.strftime("%Y%m%dT%H%M%S") + ".json",
                    "station": STATION, "unit": "mm", "source_page": HOURLY_PAGE,
                    "observationTime": observation.isoformat(), "archiveVersion": stamp,
                    "archiveIndexURL": index_url,
                })
                previous = next((item for item in manifest["hourlyFiles"]
                                 if item["raw_file"] == entry["raw_file"]), None)
                if previous:
                    saved = json.loads(snapshot_bytes(DATA, previous).decode("utf-8-sig"))
                    parse_hourly_snapshots([saved, snapshot])
                else:
                    save_raw(content, entry)
                    manifest["hourlyFiles"].append(entry)
                    save_manifest(manifest)
            except Exception as problem:
                errors.append(f"{type(problem).__name__}: {problem}")
        cached = read_weather()["hourly"].get(date_text)
        complete = cached["completeHours"] if cached else 0
        manifest["hourlyQueries"][date_text] = {
            "status": "cached" if complete == 24 else "partial" if complete else
                      "failed" if errors else "unavailable",
            "message": f"{complete} of 24 observed hourly windows cached.",
            "completeHours": complete,
            "errors": errors[:3],
        }
        save_manifest(manifest)
        print(f"{date_text}: {complete} of 24 hourly observations cached.")
    except Exception as problem:
        missing_archive = isinstance(problem, urllib.error.HTTPError) and problem.code == 404
        message = ("The official archive has no versions available for this file and date query."
                   if missing_archive else f"{type(problem).__name__}: {problem}")
        manifest["hourlyQueries"][date_text] = {
            "status": "unavailable" if missing_archive else "failed", "message": message,
        }
        save_manifest(manifest)
        print(f"{date_text}: archive request failed; no invented hourly values ({message})")


def main():
    """Fetch the optional sources explicitly; normal viewer startup stays offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy", help="Optional existing HTTP proxy for this run only.")
    parser.add_argument("--hourly-date", action="append", default=[], metavar="YYYY-MM-DD",
                        help="Try to cache one selected historical day; may be repeated.")
    parser.add_argument("--hourly-only", action="store_true",
                        help="Skip daily CSV requests and query only the selected hourly dates.")
    args = parser.parse_args()
    for text in args.hourly_date:
        dt.date.fromisoformat(text)
    if args.proxy and urllib.parse.urlparse(args.proxy).scheme not in ("http", "https"):
        parser.error("--proxy must name an existing HTTP or HTTPS proxy.")
    manifest_path = DATA / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {
        "version": 1, "publisher": STATION, "timezone": "Asia/Hong_Kong",
        "dailyFiles": [], "hourlyFiles": [], "dailyQueries": {}, "hourlyQueries": {},
    }
    # Verify saved responses before any request or metadata update.
    read_weather()
    if not args.hourly_only:
        fetch_daily(manifest, args.proxy)
    for text in args.hourly_date:
        fetch_hourly(manifest, text, args.proxy)
    if not manifest_path.exists():
        save_manifest(manifest)
    print("Weather cache checked. Run: uv run explore.py --build-only")


if __name__ == "__main__":
    main()

