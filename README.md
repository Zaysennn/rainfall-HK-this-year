# Rainfall in HK 2025/2026.

A little record of Hong Kong’s wet and dry days. Follow **2026**, compare
it with **2025**, and pause on any day that catches your eye.

![Rainfall animation](out/rainfall-2026.gif)

Still previews: [PNG](out/rainfall-2026.png) ·
[SVG](out/rainfall-2026.svg) ·
[Animation frame](out/rainfall-animation-preview.png)

## Get started

Run this from the project folder with **uv** installed:

```bash
uv run rainfall_main.py
```

This updates recent weather, prepares the hourly cache, creates or reuses the
GIF, and opens the explorer. Keep the terminal open; **Ctrl+C** stops the server.
The first online run also downloads hourly model data for the two project years;
later runs reuse saved historical data.

The first run may need internet access for Python and dependencies.

| What you want | Command |
|---|---|
| Open the explorer without exporting images | `uv run explore.py` |
| Export everything without opening a browser | `uv run rainfall_main.py --export` |
| Open using saved weather | `uv run rainfall_main.py --offline` |
| Export using saved weather | `uv run rainfall_main.py --export --offline` |
| Build a cached web page | `uv run explore.py --build-only --offline` |
| Render the GIF again | `uv run animate.py` |
| Update the live cache only | `uv run live.py` |

**Parameters**

- `--export`: save outputs without opening the viewer.
- `--build-only`: generate `site/index.html` without starting the viewer.
- `--offline`: use saved weather and start the page with refresh disabled.

`--export` and `--build-only` still update weather unless `--offline` is added.
To also stop uv from downloading dependencies, use the following command
with Python and dependencies already cached:

```bash
uv run --offline rainfall_main.py --offline
```

## Have a look around

- Try **Calendar**, **Daily bars**, **Rain wheel**, or **Cumulative**.
- Choose a year, press **Play**, change speed, or drag the date slider.
- Zoom **Daily bars**, **Rain wheel**, and **Cumulative** with the mouse wheel,
  a two-finger pinch, or **+ / -** (1-16 times). Drag the enlarged chart to look
  around; **Reset** brings back the full view. Each chart remembers its position.
- Hover or focus a day for a quick reading.
- Click a Calendar square—or press **Enter / Space**—for **Day weather**.
- Use previous/next to browse dates; **Escape** closes the weather panel.
- **Same-period comparison** matches completed dates in both years.

The daily panel shows available rain, maximum/minimum temperature,
mean humidity, and mean cloud cover. Missing values stay blank.

The **Current weather** section keeps today’s temperature, humidity,
and rolling one-hour rain separate, each with its own observation time.

### Inside the day

Choose an hourly view:

- **Model estimate:** hourly rainfall near Hong Kong from ECMWF IFS through
  Open-Meteo. These are grid estimates, not Observatory gauge measurements.
- **Station observations:** genuine saved Observatory AWS readings. A full
  24-hour record is not guaranteed.

Model history is for ended dates. For today, choose station observations;
unfinished intervals stay pending.

Click a bar, drag the slider, or press **Play hours** to follow the day.
Change speed, switch source, or retry a failed request. The panel labels its
source, coverage, and missing intervals; estimated hours are never called observed.

The daily calendar, totals, and year comparison always use Observatory daily
records. Hourly model estimates do not change those numbers. Both sources use
Hong Kong time and intervals 00-01 through 23-24, with the midnight reading
assigned to the preceding day. Missing values are never filled with zero.

## Live updates and offline use

The viewing date follows **Hong Kong time (UTC+08:00)** within the
configured years. Complete daily totals require an ended day and a
published report; today stays out of completed-day statistics.

- The visible page checks official weather sources about every **15 minutes**.
- While the online local server runs, station rain responses are saved every
  **5 minutes**. Only genuine whole-hour windows fill the station chart.
- **Refresh weather** requests an update sooner.
- **Offline snapshot** freezes browser updates; unchecking it refreshes the page data.
  The terminal collector continues until **Ctrl+C**; **--offline** disables it.
- Failed requests keep available readings and show a warning.

The local hourly service saves raw responses in **data/hourly/**; restarting
with **--offline** reuses them. A generated page also embeds its saved hours,
so the chart and playback work without a server or internet.

Browser-only daily/current-weather updates stay in memory. Rebuild the page
to embed them. Static pages can inspect their saved hours; new project cache
files are saved by the local Python server. Closing a page does not stop the
terminal's collector; **Ctrl+C** does.

`live.py` saves the raw cache but does not rebuild HTML. The generated
`site/index.html` can also be opened directly using its embedded snapshot.

## About the numbers

Observations come from the **Hong Kong Observatory station**, not a
citywide average. Daily rain is measured in **millimetres**.

Sources: [Daily rainfall](https://data.gov.hk/en-data/dataset/hk-hko-rss-daily-total-rainfall) ·
[Daily weather reports](https://data.gov.hk/en-data/dataset/hk-hko-rss-weather-and-radiation-level-report/resource/9551ffed-5ce2-469f-b9e6-38a938febee9) ·
[Current weather](https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=en) ·
[Past-hour rainfall](https://data.weather.gov.hk/weatherAPI/opendata/hourlyRainfall.php?lang=en) ·
[Hourly model data](https://open-meteo.com/en/docs/historical-weather-api) ·
[Recent model data](https://open-meteo.com/en/docs/historical-forecast-api)

- **Verified snapshot:** January–August 2026, 243 complete days,
  **2,357.6 mm**. The GIF and stills use this snapshot.
- **Recent reports:** provisional daily readings extend the explorer.
- **Rainy day:** at least **1 mm**.
- **Trace:** below **0.05 mm**, counted as zero only as a lower bound.
- **Missing / incomplete:** excluded from totals; cumulative lines stop at gaps.

Mean humidity and cloud cover are daily values. Current readings do not
replace them, and overlapping rolling-hour rain is never added together
or used to invent a daily total.

Raw responses are preserved unchanged. Their manifests record source URLs,
download times, and **SHA-256** checksums.

## Files and helpers

| Location | Contents |
|---|---|
| `data/` | Raw station and model responses, with source times and checksums |
| `assets/` | Editable viewer HTML, CSS, and JavaScript |
| `out/` | GIF and PNG/SVG previews |
| `site/index.html` | Generated, self-contained explorer |

For a closer look at the saved data:

```bash
uv run number.py
uv run weather.py
uv run live.py --offline
```