# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Explore the saved rainfall observations in a small, offline browser instrument.

Run: uv run explore.py
Build without opening a browser: uv run explore.py --build-only
Reads data/ and assets/. Writes the self-contained site/index.html.
The browser has no libraries to download and makes no requests for rainfall.
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

from number import (
    NOTES, PREVIOUS_YEAR, RAINY_DAY_MM, TRACE_LIMIT_MM, YEAR,
    coverage_end, is_complete, read_records,
)

# ---------------------------------------------------------------------------
# The knobs. The saved publisher's dates, rather than today's date, set coverage.
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


def prepare_year(records, year):
    """Create one entry per calendar day and honest prefixes for every playback step."""
    end = coverage_end(records, year)
    first = dt.date(year, 1, 1)
    length = 366 if calendar.isleap(year) else 365
    total = 0.0
    complete = rainy = traces = missing = 0
    peak_index = None
    peak_mm = -1.0
    gap = False
    days = []
    for index in range(length):
        when = first + dt.timedelta(days=index)
        record = records.get(when)
        published = when <= end
        status = describe_day(record, published)
        if published:
            if is_complete(record):
                mm = record["mm"]
                total += mm
                complete += 1
                rainy += mm >= RAINY_DAY_MM
                traces += record["trace"]
                if mm > peak_mm or (mm == peak_mm == 0 and record["trace"]
                                    and not days[peak_index]["trace"]):
                    peak_mm, peak_index = mm, index
            else:
                missing += 1
                gap = True
        days.append({
            "date": when.isoformat(), "month": when.month, "day": when.day,
            "index": index, "status": status,
            "mm": record["mm"] if published and record else None,
            "flag": record["flag"] if published and record else "",
            "trace": bool(published and record and record["trace"]),
            "cumulative": round(total, 4) if published and not gap else None,
            "stats": {"total": round(total, 4), "complete": complete,
                      "rainy": rainy, "traces": traces, "missing": missing,
                      "peakIndex": peak_index},
        })
    return {"year": year, "coverageEnd": end.isoformat(),
            "observedCount": (end - first).days + 1, "days": days}


def build_payload(records, excluded):
    """Package both years with one shared scale and a month/day comparison limit."""
    notes = json.loads(NOTES.read_text(encoding="utf-8"))
    years = {str(year): prepare_year(records, year) for year in YEARS}
    ends = [coverage_end(records, year) for year in YEARS]
    matched_month, matched_day = min((end.month, end.day) for end in ends)
    # This project uses two non-leap years; retain a safe rule if the knobs change.
    if (matched_month, matched_day) == (2, 29) and not all(
        calendar.isleap(year) for year in YEARS
    ):
        matched_day = 28
    peak = max(day["mm"] for series in years.values() for day in series["days"]
               if day["status"] in ("rain", "dry", "trace"))
    for series in years.values():
        series["matchedCount"] = next(day["index"] + 1 for day in series["days"]
                                      if (day["month"], day["day"]) ==
                                      (matched_month, matched_day))
        other_year = next(year for year in YEARS if year != series["year"])
        counterpart = {(day["month"], day["day"]): day["index"]
                       for day in years[str(other_year)]["days"]}
        for day in series["days"]:
            day["counterpart"] = counterpart.get((day["month"], day["day"]))
    return {
        "defaultYear": YEAR, "years": years,
        "rainyThreshold": RAINY_DAY_MM, "traceLimit": TRACE_LIMIT_MM,
        "scaleMax": max(50, math.ceil(peak / 50) * 50),
        "source": {"station": notes["station"], "url": notes["source_page"],
                   "snapshotUTC": notes["downloaded_at_utc"],
                   "sha256": notes["sha256"], "excludedRows": len(excluded)},
    }

# ---------------------------------------------------------------------------
# One page, no network dependencies. The editable assets stay in the repository.
# ---------------------------------------------------------------------------


def build_page(records, excluded):
    """Embed the cached numbers, CSS, and JavaScript into one portable HTML file."""
    payload = json.dumps(build_payload(records, excluded), ensure_ascii=False,
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
    """Build from the verified snapshot, then open the viewer unless told otherwise."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-only", action="store_true",
                        help="Write the offline HTML without opening a browser.")
    args = parser.parse_args()
    records, excluded = read_records()
    page = build_page(records, excluded)
    if not args.build_only:
        serve_page(page)


if __name__ == "__main__":
    main()
