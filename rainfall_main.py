# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib", "pillow"]
# ///

"""
A year in rain: an animated calendar and an interactive rainfall explorer.

Run: uv run rainfall_main.py
Refreshes recent official reports, then saves a GIF, PNG/SVG previews and the
interactive page. Use --export to build without opening a browser, and --offline
to keep network requests off. The GIF uses the verified monthly climate snapshot;
the explorer also shows clearly labelled provisional reports and current readings.
"""

import argparse
import calendar
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(HERE / ".mpl-cache"))

import matplotlib

matplotlib.use("Agg")                      # save pictures on laptops and headless machines alike
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, PowerNorm
from matplotlib.patches import Rectangle

from animate import save_animation
from explore import build_page, load_latest, serve_page
from number import (
    PREVIOUS_YEAR, RAINY_DAY_MM, TRACE_LIMIT_MM, YEAR, comparison_end,
    coverage_end, cumulative, is_complete, read_records, summarise,
)

# ---------------------------------------------------------------------------
# The knobs. All rainfall amounts are millimetres per calendar day.
# ---------------------------------------------------------------------------

PAPER = "#f7f5ef"
INK = "#20363a"
MUTED = "#62777b"
GRID = "#d9e1dc"
WATER = "#147a78"
PREVIOUS = "#9a718e"
MARK = "#c46a34"
DRY = "#ffffff"
PENDING = "#e5e8e3"
MISSING = "#f4dfce"
FIGSIZE = (12.8, 13.6)
DPI = 160
OUT = HERE / "out"

# ---------------------------------------------------------------------------
# The calendar. Missing days and unpublished dates never become zero rain.
# ---------------------------------------------------------------------------


def draw_calendar(figure, records, end, stats):
    """Draw one square per valid calendar date, using a shared rainfall scale."""
    axes = figure.add_axes([0.11, 0.345, 0.80, 0.295])
    axes.set_facecolor(PAPER)
    limit = max(50, math.ceil(stats["peak_mm"] / 50) * 50)
    colours = LinearSegmentedColormap.from_list(
        "rain", ["#cbe9e2", "#72bcb5", "#268f8b", "#105d64", "#083842"]
    )
    scale = PowerNorm(gamma=0.5, vmin=0, vmax=limit)

    for month in range(1, 13):
        for day in range(1, calendar.monthrange(YEAR, month)[1] + 1):
            when = dt.date(YEAR, month, day)
            record = records.get(when)
            hatch = None
            if when > end:
                colour = PENDING
            elif not is_complete(record):
                colour, hatch = MISSING, "////"
            elif record["mm"] == 0 and not record["trace"]:
                colour = DRY
            else:
                # Give a trace a visible pale mark without changing its numeric lower bound.
                colour = colours(scale(max(record["mm"], TRACE_LIMIT_MM)))
            square = Rectangle((day - 1 + 0.09, month - 1 + 0.10), 0.82, 0.80,
                               facecolor=colour, edgecolor=GRID, linewidth=0.5, hatch=hatch)
            axes.add_patch(square)
            if when == stats["peak_day"]:
                axes.add_patch(Rectangle((day - 1 + 0.02, month - 1 + 0.03), 0.96, 0.94,
                                         fill=False, edgecolor=MARK, linewidth=1.8))

    axes.set_xlim(0, 31)
    axes.set_ylim(12, 0)
    axes.set_xticks([day - 0.5 for day in (1, 5, 10, 15, 20, 25, 31)])
    axes.set_xticklabels(["01", "05", "10", "15", "20", "25", "31"])
    axes.xaxis.tick_top()
    axes.set_yticks([month - 0.5 for month in range(1, 13)])
    axes.set_yticklabels([calendar.month_abbr[month].upper() for month in range(1, 13)])
    axes.tick_params(axis="both", length=0, pad=10, colors=MUTED, labelsize=9)
    for spine in axes.spines.values():
        spine.set_visible(False)

    bar_axes = figure.add_axes([0.11, 0.298, 0.34, 0.012])
    bar = figure.colorbar(matplotlib.cm.ScalarMappable(norm=scale, cmap=colours),
                          cax=bar_axes, orientation="horizontal")
    ticks = {tick for tick in (0, 1, 10, 50, 100, 200, 300, 400, 500) if tick <= limit}
    bar.set_ticks(sorted(ticks | {limit}))       # label the darkest end of the scale too
    bar.ax.tick_params(labelsize=8, colors=MUTED, length=2, pad=4)
    bar.outline.set_visible(False)
    figure.text(0.11, 0.32, "DAILY RAINFALL / mm", color=MUTED, fontsize=8)

    # These keys explain white and grey cells separately from the colour scale.
    for x, colour, label, hatch in (
        (0.50, DRY, "Dry day", None),
        (0.63, MISSING, "Missing / incomplete", "////"),
        (0.82, PENDING, "Not yet published", None),
    ):
        figure.add_artist(Rectangle((x, 0.300), 0.010, 0.009, transform=figure.transFigure,
                                    facecolor=colour, edgecolor=GRID, linewidth=0.6, hatch=hatch))
        figure.text(x + 0.014, 0.300, label, fontsize=7.5, color=MUTED, va="bottom")


def draw_comparison(figure, records, end):
    """Overlay cumulative rain only through the same published month and day."""
    current_end, previous_end = comparison_end(records, end)
    axes = figure.add_axes([0.11, 0.096, 0.80, 0.12])
    axes.set_facecolor(PAPER)
    series = []
    for cutoff, colour, width in ((previous_end, PREVIOUS, 1.8), (current_end, WATER, 2.4)):
        dates, totals = cumulative(records, cutoff)
        # Use the current year's calendar for both series, preserving month/day alignment.
        points = [dt.date(YEAR, when.month, when.day) for when in dates
                  if (when.month, when.day) != (2, 29) or calendar.isleap(YEAR)]
        amounts = [amount for when, amount in zip(dates, totals)
                   if (when.month, when.day) != (2, 29) or calendar.isleap(YEAR)]
        if points:
            axes.plot(points, amounts, color=colour, linewidth=width, label=str(cutoff.year))
            axes.plot(points[-1], amounts[-1], "o", color=colour, markersize=4)
            series.append({"year": cutoff.year, "points": len(points), "last_day": dates[-1].isoformat()})

    first = dt.date(YEAR, 1, 1)
    axes.set_xlim(first, current_end + dt.timedelta(days=4))
    axes.set_ylim(bottom=0)
    ticks = [dt.date(YEAR, month, 1) for month in range(1, current_end.month + 1)]
    axes.set_xticks(ticks)
    axes.set_xticklabels([calendar.month_abbr[when.month] for when in ticks])
    axes.set_ylabel("Accumulated rain / mm", fontsize=8, color=MUTED, labelpad=9)
    axes.tick_params(colors=MUTED, labelsize=8, length=0, pad=6)
    axes.grid(axis="y", color=GRID, linewidth=0.7)
    axes.set_axisbelow(True)
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)
    axes.spines["bottom"].set_color(GRID)
    axes.legend(loc="upper left", frameon=False, fontsize=9, ncol=2, labelcolor=INK)

    current = summarise(records, current_end)
    previous = summarise(records, previous_end)
    if not current["missing"] and not previous["missing"] and previous["total"] > 0:
        difference = (current["total"] / previous["total"] - 1) * 100
        detail = (f"{difference:+.1f}% against {PREVIOUS_YEAR}  /  "
                  f"both years: 01 Jan - {current_end:%d %b}")
    else:
        detail = "Incomplete readings: curves stop at their first gap; no percentage comparison."
    figure.text(0.11, 0.249, "02  /  THE SAME WINDOW, TWO YEARS", fontsize=10, color=INK, weight="bold")
    figure.text(0.11, 0.231, detail, fontsize=9, color=MUTED)
    return current_end, previous_end, current, previous, series

# ---------------------------------------------------------------------------
# The still. A readable preview accompanies the animated and interactive views.
# ---------------------------------------------------------------------------


def make_picture(records, excluded):
    """Compose the poster and return a machine-readable audit of its numbers."""
    end = coverage_end(records, YEAR)
    stats = summarise(records, end)
    figure = plt.figure(figsize=FIGSIZE, facecolor=PAPER)
    figure.text(0.08, 0.957, "HONG KONG  /  A RAINFALL STUDY", fontsize=10, color=WATER, weight="bold")
    figure.text(0.08, 0.910, "A year, in rain.", fontsize=37, color=INK, weight="bold")
    figure.text(0.08, 0.879, f"{YEAR} at the Hong Kong Observatory", fontsize=15, color=INK)
    figure.text(0.08, 0.853,
                f"Published observations: 01 Jan - {end:%d %b %Y}. Later dates are unfilled, not dry.",
                fontsize=10, color=MUTED)
    figure.add_artist(plt.Line2D([0.08, 0.92], [0.830, 0.830], transform=figure.transFigure,
                                 color=GRID, linewidth=1))

    metrics = (
        (0.08, "RECORDED RAIN", f"{stats['total']:,.1f}", "mm across complete daily readings", WATER),
        (0.40, "RAINY DAYS", str(stats["rainy"]),
         f"of {stats['complete']} complete days  /  at least {RAINY_DAY_MM:g} mm", INK),
        (0.72, "WETTEST DAY", f"{stats['peak_mm']:g}",
         f"mm on {stats['peak_day']:%d %b}  /  outlined below", MARK),
    )
    for x, label, value, note, colour in metrics:
        figure.text(x, 0.790, label, fontsize=9, color=MUTED)
        figure.text(x, 0.752, value, fontsize=29, color=colour, weight="bold")
        figure.text(x, 0.728, note, fontsize=8.5, color=MUTED)
    figure.text(0.11, 0.670, "01  /  EVERY DAY LEAVES A MARK", fontsize=10, color=INK, weight="bold")
    figure.text(0.91, 0.670, f"{YEAR}", fontsize=12, color=WATER, ha="right", weight="bold")

    draw_calendar(figure, records, end, stats)
    current_end, previous_end, current, previous, series = draw_comparison(figure, records, end)
    figure.text(0.11, 0.057,
                f"One station, not a citywide average. {stats['missing']} missing/incomplete days in the shown period.",
                fontsize=8, color=MUTED)
    figure.text(0.11, 0.041,
                "Source: Hong Kong Observatory. Colour uses a square-root scale; all amounts remain in mm.",
                fontsize=8, color=MUTED)
    figure.text(0.11, 0.025,
                f"Trace (< {TRACE_LIMIT_MM:g} mm) is a pale mark and contributes 0 mm as a lower bound to totals.",
                fontsize=8, color=MUTED)

    def serialise(numbers):
        """Convert the peak date to text for JSON without altering any rain values."""
        return {key: value.isoformat() if isinstance(value, dt.date) else value
                for key, value in numbers.items()}

    notes = {
        "station": "Hong Kong Observatory", "units": "mm",
        "raw_rows": len(records) + len(excluded), "valid_daily_rows": len(records),
        "excluded_missing_date_placeholders": excluded,
        "raw_first_date": min(records).isoformat(), "raw_last_date": max(records).isoformat(),
        "year": YEAR, "coverage_end": end.isoformat(), "rainy_day_threshold_mm": RAINY_DAY_MM,
        "trace_upper_limit_mm": TRACE_LIMIT_MM, "trace_total_convention": "zero, a lower bound",
        "shown_year": serialise(stats),
        "comparison": {
            str(YEAR): {"end": current_end.isoformat(), **serialise(current)},
            str(PREVIOUS_YEAR): {"end": previous_end.isoformat(), **serialise(previous)},
        },
        "cumulative_series": series,
    }
    return figure, notes


def export_animation(records, excluded):
    """Reuse a verified GIF when its data and animation code have not changed."""
    inputs = (HERE / "animate.py").read_bytes() + (HERE / "number.py").read_bytes()
    inputs += (HERE / "data" / "source.json").read_bytes()
    fingerprint = hashlib.sha256(inputs).hexdigest()
    cache = OUT / "animation-build.json"
    gif = OUT / f"rainfall-{YEAR}.gif"
    preview = OUT / "rainfall-animation-preview.png"
    if cache.is_file() and gif.is_file() and preview.is_file():
        notes = json.loads(cache.read_text(encoding="utf-8"))
        hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (gif, preview)}
        if notes.get("inputs_sha256") == fingerprint and notes.get("outputs_sha256") == hashes:
            print(f"kept {gif.relative_to(HERE)} — data, code and output checksums match")
            return gif, preview
    gif, preview = save_animation(records, excluded)
    notes = {"inputs_sha256": fingerprint,
             "outputs_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in (gif, preview)}}
    cache.write_text(json.dumps(notes, indent=2) + "\n", encoding="utf-8")
    return gif, preview


def main():
    """Build the full project, then open its interactive explorer by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true",
                        help="Save all outputs without starting the browser viewer.")
    parser.add_argument("--offline", action="store_true",
                        help="Use saved sources only and disable automatic browser updates.")
    options = parser.parse_args()
    records, excluded = read_records()
    live = load_latest(records, options.offline)
    figure, notes = make_picture(records, excluded)
    OUT.mkdir(exist_ok=True)
    for extension in ("png", "svg"):
        target = OUT / f"rainfall-{YEAR}.{extension}"
        metadata = {"Date": None} if extension == "svg" else None
        figure.savefig(target, dpi=DPI, facecolor=PAPER, metadata=metadata)
        print(f"wrote {target.relative_to(HERE)}")
    plt.close(figure)
    (OUT / "summary.json").write_text(json.dumps(notes, indent=2) + "\n", encoding="utf-8")
    print(f"{YEAR}: {notes['shown_year']['total']:,.1f} mm through {notes['coverage_end']}")
    export_animation(records, excluded)
    page = build_page(records, excluded, live=live)
    if not options.export:
        serve_page(page)


if __name__ == "__main__":
    main()
