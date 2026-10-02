# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Explore saved rainfall and recent observations in a small browser instrument.

Run: uv run explore.py
Build without opening a browser: uv run explore.py --build-only
Reads data/ and assets/. Writes the self-contained site/index.html.
The browser needs no external libraries. Live updates are optional; use --offline
to build from the checked local cache and disable automatic browser requests.
"""

import argparse
import calendar
import datetime as dt
import functools
import http.server
import json
import math
import re
import threading
import urllib.parse
import webbrowser
from pathlib import Path

from weather import read_weather
from hourly import capture_observation, get_day, read_hourly, refresh_models
from live import read_live, refresh_live

from number import (
    NOTES, PREVIOUS_YEAR, RAINY_DAY_MM, TRACE_LIMIT_MM, YEAR,
    coverage_end, is_complete, read_records,
)

# ---------------------------------------------------------------------------
# The knobs. Keep complete daily coverage separate from the live viewing date.
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
SITE = HERE / "site"
YEARS = (PREVIOUS_YEAR, YEAR)

# ---------------------------------------------------------------------------
# A compact calendar. Precompute running values once, before the browser opens.
# ---------------------------------------------------------------------------


def describe_day(record, published):
    """Give zero, trace, incomplete, missing, and unpublished days separate names."""
    if not published:
        return "unpublished"
    if record is None or record["mm"] is None:
        return "missing"
    if not is_complete(record):
        return "incomplete"
    if record["trace"]:
        return "trace"
    return "dry" if record["mm"] == 0 else "rain"


def prepare_year(records, year, live=None):
    """Keep verified and provisional days separate; never total an unfinished day."""
    live = live or {}
    recent = live.get("daily", {})
    official_end = coverage_end(records, year)
    first = dt.date(year, 1, 1)
    last = dt.date(year, 12, 31)
    today = dt.date.fromisoformat(live["today"]) if live.get("today") else None
    recent = {key: report for key, report in recent.items()
              if today is None or dt.date.fromisoformat(key) < today}
    recent_dates = [dt.date.fromisoformat(key) for key in recent
                    if key.startswith(f"{year}-") and
                    dt.date.fromisoformat(key) > official_end]
    end = max([official_end, *recent_dates])
    # The clock extends inspection, not the period with published daily rain.
    display_end = max(end, today) if today and today.year == year else end
    display_end = min(display_end, last)
    length = (last - first).days + 1
    total = 0.0
    complete = verified = provisional = rainy = traces = missing = 0
    peak_index = None
    peak_mm = -1.0
    gap = False
    days = []
    for index in range(length):
        when = first + dt.timedelta(days=index)
        record = records.get(when)
        report = recent.get(when.isoformat()) if when > official_end else None
        published = when <= end
        ongoing = when == today and when > end
        quality = "unpublished"
        valid = False
        mm = None
        trace = False
        flag = ""
        if when <= official_end:
            status = describe_day(record, published)
            mm = record["mm"] if published and record else None
            flag = record["flag"] if published and record else ""
            trace = bool(published and record and record["trace"])
            valid = is_complete(record)
            quality = "verified" if valid else status
        elif report is not None:
            mm, trace = report.get("mm"), bool(report.get("trace", False))
            valid = mm is not None
            status = ("trace" if trace else "dry" if mm == 0 else "rain") if valid else "missing"
            quality = "provisional" if valid else "missing"
        else:
            status = "ongoing" if ongoing else "missing" if published else "unpublished"
            quality = status
        if published:
            if valid:
                total += mm
                complete += 1
                verified += quality == "verified"
                provisional += quality == "provisional"
                rainy += mm >= RAINY_DAY_MM
                traces += trace
                if mm > peak_mm or (mm == peak_mm == 0 and trace and
                                    peak_index is not None and not days[peak_index]["trace"]):
                    peak_mm, peak_index = mm, index
            else:
                missing += 1
                gap = True
        days.append({
            "date": when.isoformat(), "month": when.month, "day": when.day,
            "index": index, "status": status, "quality": quality,
            "mm": mm, "flag": flag, "trace": trace,
            "recentDaily": report,
            "currentObservation": live.get("current") if
                live.get("current", {}).get("date") == when.isoformat() else None,
            "cumulative": round(total, 4) if published and not gap else None,
            "stats": {"total": round(total, 4), "complete": complete,
                      "verified": verified, "provisional": provisional,
                      "rainy": rainy, "traces": traces, "missing": missing,
                      "peakIndex": peak_index},
        })
    return {"year": year, "coverageEnd": end.isoformat(),
            "officialCoverageEnd": official_end.isoformat(),
            "displayCoverageEnd": display_end.isoformat(),
            "observedCount": (end - first).days + 1,
            "displayCount": (display_end - first).days + 1, "days": days}



def merge_observed_days(*days):
    """Combine saved station windows without putting model estimates into observations."""
    available = [day for day in days if day]
    if not available:
        return None
    merged = dict(available[-1])
    hours = [{"hour": hour, "mm": None, "status": "missing", "observationTime": None}
             for hour in range(24)]
    for day in available:
        for item in day.get("hours", []):
            hour, value = item.get("hour"), item.get("mm")
            if (isinstance(hour, int) and not isinstance(hour, bool) and 0 <= hour < 24
                    and item.get("status") == "observed" and isinstance(value, (int, float))
                    and not isinstance(value, bool) and math.isfinite(value) and value >= 0):
                previous = hours[hour]
                if (previous["status"] == "observed"
                        and previous.get("observationTime") == item.get("observationTime")
                        and previous["mm"] != value):
                    raise ValueError("Saved station sources disagree on the same hourly window.")
                hours[hour] = dict(item)
    merged["hours"] = hours
    merged["completeHours"] = sum(item["status"] == "observed" for item in hours)
    return merged

def build_payload(records, excluded, weather=None, live=None, hourly=None):
    """Join cached sources by date and retain their distinct quality and time scales."""
    weather = read_weather() if weather is None else weather
    # No hidden live-cache input in this pure builder; callers choose their snapshot.
    live = live or {"daily": {}, "current": {}, "sources": {}, "errors": [],
                    "enabled": False, "refreshMinutes": 15, "timezone": "Asia/Hong_Kong"}
    hourly = hourly or {"observed": {}, "model": {}, "queries": {}}
    notes = json.loads(NOTES.read_text(encoding="utf-8"))
    years = {str(year): prepare_year(records, year, live) for year in YEARS}
    matched = min((dt.date.fromisoformat(series["coverageEnd"]).month,
                   dt.date.fromisoformat(series["coverageEnd"]).day)
                  for series in years.values())
    display_match = min((dt.date.fromisoformat(series["displayCoverageEnd"]).month,
                         dt.date.fromisoformat(series["displayCoverageEnd"]).day)
                        for series in years.values())
    # A leap day has no counterpart in a non-leap comparison year.
    if not all(calendar.isleap(year) for year in YEARS):
        matched = (2, 28) if matched == (2, 29) else matched
        display_match = (2, 28) if display_match == (2, 29) else display_match
    peak = max(day["mm"] for series in years.values() for day in series["days"]
               if day["status"] in ("rain", "dry", "trace"))
    for series in years.values():
        series["matchedCount"] = next(day["index"] + 1 for day in series["days"]
                                      if (day["month"], day["day"]) == matched)
        series["matchedDisplayCount"] = next(day["index"] + 1 for day in series["days"]
                                             if (day["month"], day["day"]) == display_match)
        other_year = next(year for year in YEARS if year != series["year"])
        counterpart = {(day["month"], day["day"]): day["index"]
                       for day in years[str(other_year)]["days"]}
        for day in series["days"]:
            day["counterpart"] = counterpart.get((day["month"], day["day"]))
            day["weather"] = dict(weather["daily"].get(day["date"], {}))
            report = day["recentDaily"]
            if report:
                for metric in ("maxTemp", "minTemp"):
                    saved = day["weather"].get(metric, {})
                    if saved.get("value") is None and report.get(metric) is not None:
                        day["weather"][metric] = {"value": report[metric],
                                                   "status": "provisional", "source": "recentDaily"}
            day["hourly"] = merge_observed_days(
                weather["hourly"].get(day["date"]), live.get("hourly", {}).get(day["date"]),
                hourly.get("observed", {}).get(day["date"]))
            day["hourlyModel"] = hourly.get("model", {}).get(day["date"])
    return {
        "defaultYear": YEAR, "years": years, "live": live,
        "hourlyService": {"path": "/api/hourly", "enabled": live.get("enabled", False),
                          "queries": hourly.get("queries", {}), "supportedYears": list(YEARS)},
        "weather": {"sources": {**weather["sources"], **live.get("sources", {})},
                    "hourlyNote": "Station hours come from saved, dated Observatory AWS records. Missing hours are not zero rain.",
                    "timezone": weather["timezone"]},
        "rainyThreshold": RAINY_DAY_MM, "traceLimit": TRACE_LIMIT_MM,
        "scaleMax": max(50, math.ceil(peak / 50) * 50),
        "source": {"station": notes["station"], "url": notes["source_page"],
                   "snapshotUTC": notes["downloaded_at_utc"],
                   "sha256": notes["sha256"], "excludedRows": len(excluded)},
    }


def load_latest(records, offline=False):
    """Refresh the raw cache at startup, or keep all network access explicitly off."""
    result = read_live() if offline else refresh_live(coverage_end(records, YEAR))
    result["enabled"] = not offline
    if not offline:
        yesterday = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date() - dt.timedelta(days=1)
        for year in YEARS:
            first, last = dt.date(year, 1, 1), min(dt.date(year, 12, 31), yesterday)
            if last >= first:
                refresh_models(first.isoformat(), last.isoformat())
    for error in result.get("errors", []):
        print(f"Live update notice: {error}")
    return result

# ---------------------------------------------------------------------------
# One portable page. Its saved data remains readable when a live request fails.
# ---------------------------------------------------------------------------


def build_page(records, excluded, live=None):
    """Embed the cached numbers, CSS, and JavaScript into one portable HTML file."""
    live = read_live() if live is None else live
    model = build_payload(records, excluded, live=live, hourly=read_hourly())
    payload = json.dumps(model, ensure_ascii=False,
                         separators=(",", ":")).replace("<", "\\u003c")
    page = (ASSETS / "viewer.html").read_text(encoding="utf-8")
    replacements = {
        "<!-- INLINE_STYLE -->": "<style>" + (ASSETS / "viewer.css").read_text(
            encoding="utf-8") + "</style>",
        "<!-- INLINE_DATA -->": '<script id="rain-data" type="application/json">' +
                                payload + "</script>",
        "<!-- INLINE_HOURLY -->": "<script>" + (ASSETS / "hourly.js").read_text(
            encoding="utf-8") + "</script>",
        "<!-- INLINE_ZOOM -->": "<script>" + (ASSETS / "chart-zoom.js").read_text(
            encoding="utf-8") + "</script>",
        "<!-- INLINE_SCRIPT -->": "<script>" + (ASSETS / "viewer.js").read_text(
            encoding="utf-8") + "</script>",
    }
    for marker, content in replacements.items():
        if page.count(marker) != 1:
            raise ValueError(f"Expected exactly one {marker} in the page template.")
        page = page.replace(marker, content)
    SITE.mkdir(exist_ok=True)
    target = SITE / "index.html"
    target.write_text(page, encoding="utf-8")
    current = model["years"][str(YEAR)]
    print(f"Explorer daily reports through {current['coverageEnd']}; "
          f"viewing date {current['displayCoverageEnd']}. The current day is excluded from totals.")
    print(f"Interactive page: {target.relative_to(HERE)} (works offline)")
    return target


class HourlyRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Serve the page and its same-origin hourly API, with no arbitrary download URLs."""

    hourly_enabled = False

    def send_hourly_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        if path.path != "/api/hourly":
            return super().do_GET()
        try:
            options = urllib.parse.parse_qs(path.query, keep_blank_values=True)
            if (set(options) - {"date", "mode", "force"}
                    or any(len(items) != 1 for items in options.values())):
                raise ValueError("Use one date, one mode and an optional retry flag.")
            date = options.get("date", [""])[0]
            mode = options.get("mode", ["model"])[0]
            if options.get("force", ["0"])[0] not in {"0", "1"}:
                raise ValueError("The retry flag must be 0 or 1.")
            hosts = {f"127.0.0.1:{self.server.server_port}",
                     f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            if (self.headers.get("Host") not in hosts
                    or origin and origin not in {"http://" + host for host in hosts}
                    or self.headers.get("Sec-Fetch-Site") == "cross-site"):
                return self.send_hourly_json({"error": "Use the local explorer origin."}, 403)
            result = get_day(date, mode=mode, offline=not self.hourly_enabled,
                             force=options.get("force", ["0"])[0] == "1")
            if mode == "observed":
                result["day"] = merge_observed_days(
                    read_weather()["hourly"].get(date), read_live().get("hourly", {}).get(date),
                    result.get("day"))
                count = (result["day"] or {}).get("completeHours", 0)
                result["query"]["completeHours"] = count
                if count and result["query"]["status"] != "failed":
                    result["query"]["status"] = "cached" if count == 24 else "partial"
                    result["query"]["message"] = f"{count} of 24 station windows are saved."
            self.send_hourly_json(result)
        except ValueError as problem:
            self.send_hourly_json({"error": str(problem)}, 400)
        except Exception:
            self.send_hourly_json({"error": "Hourly data could not be refreshed; keep the saved readings."}, 503)

    def log_message(self, format, *args):
        # Hourly polling stays quiet; the application reports availability in the sheet.
        if args and str(args[1] if len(args) > 1 else "") not in {"200", "304"}:
            super().log_message(format, *args)


def collect_station_hours(stop):
    """Keep new station responses while the local viewer runs; closing it stops collection."""
    while not stop.is_set():
        try:
            capture_observation()
        except Exception as problem:
            print(f"Hourly station notice: {problem}", flush=True)
        stop.wait(5 * 60)


def serve_page(page=None):
    """Open the local viewer; its hourly API stores real responses for later offline use."""
    page = Path(page) if page is not None else SITE / "index.html"
    if not page.is_file():
        raise FileNotFoundError("Build the page first with uv run explore.py --build-only.")
    contents = page.read_text(encoding="utf-8")
    embedded = re.search(r'<script[^>]*id="rain-data"[^>]*>(.*?)</script>', contents, re.S)
    if not embedded:
        raise ValueError("The page has no saved rainfall snapshot.")
    enabled = json.loads(embedded.group(1)).get("hourlyService", {}).get("enabled", False)
    handler_type = type("ConfiguredHourlyHandler", (HourlyRequestHandler,),
                        {"hourly_enabled": enabled})
    handler = functools.partial(handler_type, directory=str(page.parent))
    stop = threading.Event()
    collector = None
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        server.daemon_threads = False
        if enabled:
            collector = threading.Thread(target=collect_station_hours, args=(stop,), daemon=True)
            collector.start()
        url = f"http://127.0.0.1:{server.server_port}/{page.name}"
        print(f"Explore: {url}\nKeep this terminal open. Press Ctrl-C to stop.", flush=True)
        webbrowser.open(url, new=2)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nViewer stopped; the saved page remains in site/.")
        finally:
            stop.set()
    if collector is not None:
        collector.join(timeout=45)



def main():
    """Update recent sources, build the page, and optionally open the local viewer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-only", action="store_true",
                        help="Write the offline HTML without opening a browser.")
    parser.add_argument("--offline", action="store_true",
                        help="Use saved sources only and disable automatic browser updates.")
    args = parser.parse_args()
    records, excluded = read_records()
    page = build_page(records, excluded, live=load_latest(records, args.offline))
    if not args.build_only:
        serve_page(page)


if __name__ == "__main__":
    main()
