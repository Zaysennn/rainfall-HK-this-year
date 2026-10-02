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
import webbrowser
from pathlib import Path

from weather import read_weather
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


def build_payload(records, excluded, weather=None, live=None):
    """Join cached sources by date and retain their distinct quality and time scales."""
    weather = read_weather() if weather is None else weather
    # No hidden live-cache input in this pure builder; callers choose their snapshot.
    live = live or {"daily": {}, "current": {}, "sources": {}, "errors": [],
                    "enabled": False, "refreshMinutes": 15, "timezone": "Asia/Hong_Kong"}
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
            day["hourly"] = weather["hourly"].get(day["date"]) or live.get("hourly", {}).get(day["date"])
    return {
        "defaultYear": YEAR, "years": years, "live": live,
        "weather": {"sources": {**weather["sources"], **live.get("sources", {})},
                    "hourlyNote": weather["hourlyNote"], "timezone": weather["timezone"]},
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
    for error in result.get("errors", []):
        print(f"Live update notice: {error}")
    return result

# ---------------------------------------------------------------------------
# One portable page. Its saved data remains readable when a live request fails.
# ---------------------------------------------------------------------------


def build_page(records, excluded, live=None):
    """Embed the cached numbers, CSS, and JavaScript into one portable HTML file."""
    live = read_live() if live is None else live
    model = build_payload(records, excluded, live=live)
    payload = json.dumps(model, ensure_ascii=False,
                         separators=(",", ":")).replace("<", "\\u003c")
    page = (ASSETS / "viewer.html").read_text(encoding="utf-8")
    replacements = {
        "<!-- INLINE_STYLE -->": "<style>" + (ASSETS / "viewer.css").read_text(
            encoding="utf-8") + "</style>",
        "<!-- INLINE_DATA -->": '<script id="rain-data" type="application/json">' +
                                payload + "</script>",
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


def serve_page(page=None):
    """Open the local viewer and serve only its folder until Ctrl-C is pressed."""
    page = Path(page) if page is not None else SITE / "index.html"
    if not page.is_file():
        raise FileNotFoundError("Build the page first with uv run explore.py --build-only.")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(page.parent))
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        server.daemon_threads = True
        url = f"http://127.0.0.1:{server.server_port}/{page.name}"
        print(f"Explore: {url}\nKeep this terminal open. Press Ctrl-C to stop.", flush=True)
        webbrowser.open(url, new=2)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nViewer stopped; the saved page remains in site/.")


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
