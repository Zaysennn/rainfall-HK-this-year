# A year, in rain

An **animated GIF and interactive explorer** of daily rainfall at the Hong Kong
Observatory, with **2026** as the main subject and **2025** as a comparison.
Rainfall changes both the feel of the city and the rhythm of an ordinary day.
Watch small wet days and larger bursts build a year's total, then change the
view and inspect the individual days behind the pattern.

![Animated rainfall calendar with a moving date cursor and synchronized cumulative rain for 2026 and the same period in 2025.](out/rainfall-2026.gif)

![Still preview of the rainfall animation at the final published date.](out/rainfall-animation-preview.png)

The animation is the portable preview. Run the project to open the interactive
version, where the same data can be explored in four visual modes. The original
[full-page still](out/rainfall-2026.png) and [vector version](out/rainfall-2026.svg)
are also included for reading or printing.

## Run and explore

```bash
uv run plot.py
```

This builds the GIF and stills, generates `site/index.html`, and opens the explorer
in a browser. Keep the terminal open while using the local viewer; press **Ctrl+C**
when finished. The page contains its data and assets, so it can also be opened
directly from `site/index.html` without a server or internet connection.

- Switch between **Calendar**, **Daily bars**, **Rain wheel**, and **Cumulative**
  to see the same numbers encoded as colour, height, radius, or accumulated rain.
- Choose **2026** or **2025**, play or pause, change speed, and drag the day slider.
  Seeking backwards also moves the totals and visible observations backwards.
- Hover, focus, or select a day to inspect its date, rain amount, quality status,
  and cumulative amount. A selected detail stays available while you examine it.
- Keep **same-period comparison** enabled to compare equal month-and-day windows.
  Disable it to explore the full 2025 calendar on its own. The unfinished 2026
  record is never compared with an entire 2025 total.

The scripts use their own dependency blocks and read only the saved data.
After uv has installed or cached Python and the declared plotting dependencies,
they work offline. A verified GIF is reused when its source data and animation
code are unchanged, so opening the project again does not render every frame.

For a quick visit without exporting the animation again:

```bash
uv run explore.py
```

For headless generation, such as on a build machine:

```bash
uv run plot.py --export
```

## The numbers

The source is the Hong Kong Observatory's [daily total rainfall dataset](https://data.gov.hk/en-data/dataset/hk-hko-rss-daily-total-rainfall).
The [original CSV endpoint](https://data.weather.gov.hk/weatherAPI/cis/csvfile/HKO/ALL/daily_HKO_RF_ALL.csv)
is saved unchanged as `data/daily_HKO_RF_ALL.csv`. The separate `data/source.json`
records the download time, source URL, response size, and SHA-256 checksum.
The raw CSV is also excluded from Git's line-ending conversion in `.gitattributes`.

The file contains **49,492 published daily rows**, spanning March 1884 to August
2026. Each row gives a year, month, day, rainfall amount in **millimetres**, and
the publisher's data-completeness flag. One historical row is an unavailable
placeholder for the nonexistent date **1900-02-29**. It remains in the raw file;
the parser explicitly reports its exclusion, leaving 49,491 valid dated records.
The two title lines, column headings, and explanatory footnotes are also preserved.

This snapshot has **365 complete records for 2025**, and **243 complete records for
2026, from 1 January through 31 August**. There are no missing or incomplete days
in either January-August comparison window. Publication is monthly: the absence
of September-December 2026 in this snapshot does not mean those months were dry.

## Reading the views

Every calendar square is one valid day. The animation progressively reveals
published readings, moves a date cursor, and grows both cumulative lines in sync.
The explorer keeps measured zero, trace rain, missing or incomplete readings,
unpublished dates, and observations not yet revealed by playback distinct.
The shared colour scale expands small rain amounts with a square-root mapping;
the labels remain in millimetres. The wettest observed day in 2026 is **15 June,
with 122.6 mm**.

The rain wheel places the day of the year around a circle, with the rainfall
amount controlling radius. It is a seasonal view inspired by the course's
`tide_clock.py`, not a map. Bars make individual rain events easier to compare;
the cumulative view shows how those events add up. Switching modes keeps the
playback date and revealed numbers. Cumulative inspection stays within the
published exploration window. The wheel's small status dots do not encode rain
amounts; bars use a one-pixel visibility floor for tiny readings and zero.

The cumulative lines compare **1 January-31 August in both years**. Recorded rain
over that window is **2,357.6 mm in 2026** and **1,985.3 mm in 2025**, about **18.8%
more in 2026**. A rainy day here means at least 1 mm: 85 such days in 2026, compared
with 73 in the same 2025 window. These are two years of observations, not evidence
of a long-term climate trend.

The picture hides variation within each day and across Hong Kong: this is one
station, not a citywide average. The publisher's `Trace` means less than 0.05 mm.
Traces are pale marks in the calendar and contribute zero as a **lower bound** to
totals, not as a claim that no rain fell. There are 30 trace readings in the 2026
window and 36 in the 2025 window, so the uncounted trace amounts are less than
1.5 mm and 1.8 mm respectively. Missing or incomplete records never enter totals;
a cumulative line stops at the first such gap rather than silently bridging it.

## Inspect or fetch

```bash
uv run rainfall.py
uv run test_rainfall.py
uv run fetch.py
```

The first two commands audit the numbers and run focused data-handling checks.
The fetch script is optional when the snapshot is present: it verifies the
existing checksum and makes no request. It never replaces a saved CSV.

## Optional web publication

Editable HTML, CSS, and JavaScript live in `assets/`; `explore.py` embeds them
and the checked data into the self-contained generated page. `site/` is ignored.
The supplied `.github/workflows/pages.yml`, adapted from the course workflow,
builds the page with `uv run explore.py --build-only` on GitHub. To publish later,
commit and push the project, then select **GitHub Actions** under the repository's
Pages settings. No live page is claimed until that deployment actually succeeds.

## Assignment status

This local draft includes the raw data, animated and interactive views, still
preview, process note, and course workflows. The new files still need to be committed and pushed by
the author. The assignment also requires a real history across more than one
day; that history must come from actual work, not fabricated timestamps.
