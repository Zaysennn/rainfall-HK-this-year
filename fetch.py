# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Fetch the Observatory's daily rainfall file once, without changing its bytes.

Source: https://data.gov.hk/en-data/dataset/hk-hko-rss-daily-total-rainfall
Run: uv run fetch.py

The snapshot and its source notes live in data/. An existing snapshot is kept:
running this script again checks its checksum and makes no network request.
"""

import datetime as dt
import hashlib
import json
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# The knobs. Keep one published file, including its titles and footnotes.
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RAW = DATA / "daily_HKO_RF_ALL.csv"
NOTES = DATA / "source.json"
URL = "https://data.weather.gov.hk/weatherAPI/cis/csvfile/HKO/ALL/daily_HKO_RF_ALL.csv"
SOURCE_PAGE = "https://data.gov.hk/en-data/dataset/hk-hko-rss-daily-total-rainfall"

# ---------------------------------------------------------------------------
# The download. Binary writes preserve the publisher's original response.
# ---------------------------------------------------------------------------


def check_snapshot():
    """Check the saved bytes against the checksum recorded at download time."""
    if not NOTES.is_file():
        raise ValueError("The raw file exists without source.json; inspect it before continuing.")
    notes = json.loads(NOTES.read_text(encoding="utf-8"))
    digest = hashlib.sha256(RAW.read_bytes()).hexdigest()
    if digest != notes["sha256"]:
        raise ValueError("The saved CSV no longer matches its original SHA-256 checksum.")
    print(f"kept {RAW.relative_to(HERE)} — SHA-256 verified; no request made")


def main():
    """Save one snapshot and a separate record of where and when it arrived."""
    if RAW.exists():
        check_snapshot()
        return
    if NOTES.exists():
        raise ValueError("source.json exists without the CSV; inspect this partial snapshot first.")

    request = urllib.request.Request(URL, headers={"User-Agent": "rainfall-HK-this-year/1.0"})
    with urllib.request.urlopen(request, timeout=60) as reply:
        raw = reply.read()
        received_url = reply.geturl()
        modified = reply.headers.get("Last-Modified")
        content_type = reply.headers.get("Content-Type")

    # A successful HTTP response can still be an error page. Check before saving.
    title = raw.decode("utf-8-sig").splitlines()
    if len(title) < 4 or "Daily Total Rainfall (mm)" not in title[1]:
        raise ValueError("The reply is not the expected Observatory rainfall CSV.")

    notes = {
        "publisher": "Hong Kong Observatory",
        "station": "Hong Kong Observatory",
        "source_page": SOURCE_PAGE,
        "requested_url": URL,
        "received_url": received_url,
        "downloaded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "last_modified": modified,
        "content_type": content_type,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "raw_file": RAW.name,
        "units": "mm per calendar day",
        "note": "This JSON is project metadata; the neighbouring CSV is the unchanged response.",
    }
    DATA.mkdir(exist_ok=True)
    with RAW.open("xb") as handle:
        handle.write(raw)
    with NOTES.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(notes, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"saved {RAW.relative_to(HERE)} — {len(raw):,} original bytes")
    print("now run: uv run number.py")


if __name__ == "__main__":
    main()
