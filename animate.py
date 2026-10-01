# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib", "pillow"]
# ///

"""
A year arriving in rain: a moving calendar and two growing rainfall curves.

Run: uv run animate.py
Reads the unchanged observations in data/. Writes out/rainfall-2026.gif and
out/rainfall-animation-preview.png. No internet connection or display is needed.

Most frames advance two days; the wettest day and final date are always included.
The 2025 curve follows the same month and day as the moving 2026 calendar.
"""

import calendar
import datetime as dt
import math
import os
from bisect import bisect_right
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(HERE / ".mpl-cache"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.colors import LinearSegmentedColormap, PowerNorm
from matplotlib.patches import Rectangle

from rainfall import (
    PREVIOUS_YEAR, TRACE_LIMIT_MM, YEAR, comparison_end, coverage_end,
    cumulative, days_to, is_complete, read_records, summarise,
)

# ---------------------------------------------------------------------------
# The knobs. Rainfall is in millimetres; playback is not real elapsed time.
# ---------------------------------------------------------------------------

FPS = 12
STEP = 2                    # ordinary frames advance two observation dates
FIRST_HOLD = 2              # extra frames at the beginning
FINAL_HOLD = 12             # one second to read the final observation
FIGSIZE = (11, 7.4)
DPI = 96

PAPER = "#f7f5ef"
INK = "#20363a"
MUTED = "#62777b"
GRID = "#d9e1dc"
WATER = "#147a78"
PREVIOUS = "#9a718e"
MARK = "#c46a34"
DRY = "#ffffff"
WAITING = "#edf0e9"          # a published observation not reached by playback
UNPUBLISHED = "#d7dbd4"      # no observation published in the saved snapshot
MISSING = "#f4dfce"
TRACE = "#cbe9e2"
OUT = HERE / "out"

# ---------------------------------------------------------------------------
# Prepare the numbers once. No totals are recalculated while a frame is drawn.
# ---------------------------------------------------------------------------


def prefix_totals(records, dates):
    """Return complete-reading lower bounds and gap counts for each playback date."""
    totals, gaps = [], []
    total = 0.0
    missing = 0
    for when in dates:
        record = records.get(when)
        if is_complete(record):
            total += record["mm"]
        else:
            missing += 1
        totals.append(total)
        gaps.append(missing)
    return totals, gaps


def animation_frames(dates, peak_day):
    """Sample the calendar while retaining the first, wettest, and final dates."""
    if not dates:
        raise ValueError("The animation needs at least one observation date.")
    indices = set(range(0, len(dates), STEP))
    indices.update((0, len(dates) - 1))
    if peak_day in dates:
        indices.add(dates.index(peak_day))
    return [0] * FIRST_HOLD + sorted(indices) + [len(dates) - 1] * FINAL_HOLD


def reading_label(record):
    """Name trace, dry, and incomplete readings without turning gaps into zeros."""
    if not is_complete(record):
        return "unavailable", "Missing or incomplete reading"
    if record["trace"]:
        return f"< {TRACE_LIMIT_MM:g}", "mm / trace rainfall"
    return f"{record['mm']:g}", "mm / dry day" if record["mm"] == 0 else "mm / observed rain"


def make_animation(records):
    """Build the fixed page and return its reusable artists and frame function."""
    published_end = coverage_end(records, YEAR)
    current_end, previous_end = comparison_end(records, published_end)
    dates = days_to(current_end)
    previous_dates = [dt.date(PREVIOUS_YEAR, when.month, when.day) for when in dates]
    current_totals, current_gaps = prefix_totals(records, dates)
    previous_totals, previous_gaps = prefix_totals(records, previous_dates)
    current_curve_dates, current_curve = cumulative(records, current_end)
    previous_curve_dates, previous_curve = cumulative(records, previous_end)
    previous_points = [dt.date(YEAR, when.month, when.day) for when in previous_curve_dates
                       if (when.month, when.day) != (2, 29) or calendar.isleap(YEAR)]
    previous_curve = [value for when, value in zip(previous_curve_dates, previous_curve)
                      if (when.month, when.day) != (2, 29) or calendar.isleap(YEAR)]
    previous_counts = [bisect_right(previous_points, when) for when in dates]
    stats = summarise(records, current_end)

    figure = plt.figure(figsize=FIGSIZE, facecolor=PAPER)
    figure.text(0.065, 0.948, "HONG KONG / AN OBSERVATION IN MOTION", fontsize=9,
                color=WATER, weight="bold")
    figure.text(0.065, 0.901, "A year, arriving in rain.", fontsize=27,
                color=INK, weight="bold")
    figure.text(0.935, 0.948, f"{YEAR}", fontsize=14, ha="right", color=WATER, weight="bold")
    figure.text(0.065, 0.875,
                f"Hong Kong Observatory station / saved observations through {published_end:%d %b %Y}",
                fontsize=9, color=MUTED)
    figure.add_artist(plt.Line2D([0.065, 0.935], [0.854, 0.854],
                                 transform=figure.transFigure, color=GRID, linewidth=1))

    values, notes = [], []
    for x, label, colour in (
        (0.065, "DATE / PLAYHEAD", INK),
        (0.290, "DAILY RAIN", WATER),
        (0.520, f"{YEAR} TO THIS DATE", WATER),
        (0.750, f"{PREVIOUS_YEAR} / SAME DATE", PREVIOUS),
    ):
        figure.text(x, 0.828, label, fontsize=8, color=MUTED)
        values.append(figure.text(x, 0.785, "", fontsize=24, color=colour, weight="bold"))
        notes.append(figure.text(x, 0.760, "", fontsize=8, color=MUTED))

    figure.text(0.095, 0.727, "01 / EACH DAY LEAVES A MARK", fontsize=9,
                color=INK, weight="bold")
    figure.text(0.935, 0.727, "ORANGE OUTLINE = PLAYHEAD", fontsize=7.5,
                color=MARK, ha="right")

    # Every calendar square is made once. Playback changes only its fill and hatch.
    axes = figure.add_axes([0.095, 0.354, 0.840, 0.340])
    axes.set_facecolor(PAPER)
    colours = LinearSegmentedColormap.from_list(
        "moving_rain", [TRACE, "#72bcb5", "#268f8b", "#105d64", "#083842"]
    )
    limit = max(50, math.ceil(stats["peak_mm"] / 50) * 50)
    scale = PowerNorm(gamma=0.5, vmin=0, vmax=limit)
    squares, fills, hatches = {}, {}, {}
    for month in range(1, 13):
        for day in range(1, calendar.monthrange(YEAR, month)[1] + 1):
            when = dt.date(YEAR, month, day)
            record = records.get(when)
            if when > published_end:
                colour, hatch = UNPUBLISHED, ".."
            else:
                colour, hatch = WAITING, None
            square = Rectangle((day - 1 + 0.09, month - 1 + 0.10), 0.82, 0.80,
                               facecolor=colour, edgecolor=GRID, linewidth=0.5, hatch=hatch)
            axes.add_patch(square)
            squares[when] = square
            if not is_complete(record):
                fills[when], hatches[when] = MISSING, "////"
            elif record["trace"]:
                fills[when], hatches[when] = TRACE, None
            elif record["mm"] == 0:
                fills[when], hatches[when] = DRY, None
            else:
                fills[when], hatches[when] = colours(scale(record["mm"])), None

    axes.set_xlim(0, 31)
    axes.set_ylim(12, 0)
    axes.set_xticks([day - 0.5 for day in (1, 5, 10, 15, 20, 25, 31)])
    axes.set_xticklabels(["01", "05", "10", "15", "20", "25", "31"])
    axes.xaxis.tick_top()
    axes.set_yticks([month - 0.5 for month in range(1, 13)])
    axes.set_yticklabels([calendar.month_abbr[month].upper() for month in range(1, 13)])
    axes.tick_params(axis="both", length=0, pad=7, colors=MUTED, labelsize=8)
    for spine in axes.spines.values():
        spine.set_visible(False)
    cursor = Rectangle((0.03, 0.04), 0.94, 0.92, fill=False,
                       edgecolor=MARK, linewidth=1.8, zorder=5)
    axes.add_patch(cursor)

    # The legend keeps four kinds of empty-looking cells separate from measured rain.
    bar_axes = figure.add_axes([0.095, 0.303, 0.270, 0.012])
    bar = figure.colorbar(matplotlib.cm.ScalarMappable(norm=scale, cmap=colours),
                          cax=bar_axes, orientation="horizontal")
    ticks = {tick for tick in (0, 10, 50, 100, 200, 300, 400, 500) if tick <= limit}
    bar.set_ticks(sorted(ticks | {limit}))
    bar.ax.tick_params(labelsize=7, colors=MUTED, length=2, pad=3)
    bar.outline.set_visible(False)
    figure.text(0.095, 0.324, "DAILY RAIN / mm / square-root colour scale", fontsize=7,
                color=MUTED)
    for x, y, colour, label, hatch in (
        (0.425, 0.315, WAITING, "Not revealed yet", None),
        (0.625, 0.315, UNPUBLISHED, "Not published", ".."),
        (0.810, 0.315, DRY, "Dry day", None),
        (0.425, 0.292, TRACE, "Trace < 0.05 mm", None),
        (0.625, 0.292, MISSING, "Missing / incomplete", "////"),
    ):
        figure.add_artist(Rectangle((x, y), 0.010, 0.010, transform=figure.transFigure,
                                    facecolor=colour, edgecolor=GRID, linewidth=0.6, hatch=hatch))
        figure.text(x + 0.016, y, label, fontsize=7.3, color=MUTED, va="bottom")

    figure.text(0.095, 0.261, "02 / WATCH THE TOTALS GROW", fontsize=9,
                color=INK, weight="bold")
    difference = figure.text(0.935, 0.261, "", fontsize=8, color=MUTED, ha="right")
    curve_axes = figure.add_axes([0.095, 0.109, 0.840, 0.130])
    curve_axes.set_facecolor(PAPER)
    current_line, = curve_axes.plot([], [], color=WATER, linewidth=2.3, label=str(YEAR))
    previous_line, = curve_axes.plot([], [], color=PREVIOUS, linewidth=1.8,
                                      label=str(PREVIOUS_YEAR))
    current_dot, = curve_axes.plot([], [], "o", color=WATER, markersize=4)
    previous_dot, = curve_axes.plot([], [], "o", color=PREVIOUS, markersize=4)
    moving_line = curve_axes.axvline(dates[0], color=MARK, alpha=0.65, linewidth=0.8)
    curve_axes.set_xlim(dates[0], dates[-1] + dt.timedelta(days=4))
    highest = max(current_curve + previous_curve + [1.0])
    curve_axes.set_ylim(0, max(500, math.ceil(highest / 500) * 500))
    ticks = [dt.date(YEAR, month, 1) for month in range(1, current_end.month + 1)]
    curve_axes.set_xticks(ticks)
    curve_axes.set_xticklabels([calendar.month_abbr[when.month] for when in ticks])
    curve_axes.tick_params(colors=MUTED, labelsize=8, length=0, pad=5)
    curve_axes.set_ylabel("Cumulative / mm", fontsize=7.5, color=MUTED, labelpad=7)
    curve_axes.grid(axis="y", color=GRID, linewidth=0.7)
    curve_axes.set_axisbelow(True)
    for side in ("top", "right", "left"):
        curve_axes.spines[side].set_visible(False)
    curve_axes.spines["bottom"].set_color(GRID)
    curve_axes.legend(loc="upper left", frameon=False, fontsize=8, ncol=2, labelcolor=INK)

    figure.text(0.095, 0.058,
                "Trace < 0.05 mm stays visible; totals use 0 as a lower bound. Curves stop at any gap.",
                fontsize=7.5, color=MUTED)
    figure.text(0.095, 0.036,
                "Source: Hong Kong Observatory / one station, not a citywide average. "
                "Normally 2 days per frame; wettest day included.", fontsize=7.3, color=MUTED)
    drawn_through = -1

    def frame(index):
        """Reveal one sampled date and move the existing squares, lines, and labels."""
        nonlocal drawn_through
        when = dates[index]
        if index < drawn_through:
            for date in dates:
                squares[date].set_facecolor(WAITING)
                squares[date].set_hatch(None)
            drawn_through = -1
        for date in dates[drawn_through + 1:index + 1]:
            squares[date].set_facecolor(fills[date])
            squares[date].set_hatch(hatches[date])
        drawn_through = index
        cursor.set_xy((when.day - 1 + 0.03, when.month - 1 + 0.04))

        values[0].set_text(f"{when:%d %b}".upper())
        notes[0].set_text(f"Day {index + 1:03d} / {len(dates)} published dates in this window")
        amount, note = reading_label(records.get(when))
        values[1].set_text(amount)
        notes[1].set_text(note)
        values[2].set_text(f"{current_totals[index]:,.1f}")
        notes[2].set_text("mm / complete readings, lower bound")
        values[3].set_text(f"{previous_totals[index]:,.1f}")
        notes[3].set_text(f"mm / 01 Jan - {when:%d %b}")

        current_count = min(index + 1, len(current_curve))
        previous_count = previous_counts[index]
        current_line.set_data(current_curve_dates[:current_count], current_curve[:current_count])
        previous_line.set_data(previous_points[:previous_count], previous_curve[:previous_count])
        if current_count:
            current_dot.set_data([current_curve_dates[current_count - 1]],
                                 [current_curve[current_count - 1]])
        if previous_count:
            previous_dot.set_data([previous_points[previous_count - 1]],
                                  [previous_curve[previous_count - 1]])
        moving_line.set_xdata([when, when])
        if current_gaps[index] or previous_gaps[index]:
            difference.set_text("Incomplete readings / comparison withheld")
        elif previous_totals[index] > 0:
            change = (current_totals[index] / previous_totals[index] - 1) * 100
            difference.set_text(f"{change:+.1f}% / same month-and-day window")
        else:
            difference.set_text("No percentage until the 2025 total is above zero")
        return (cursor, current_line, previous_line, current_dot, previous_dot, moving_line,
                difference, *values, *notes)

    frames = animation_frames(dates, stats["peak_day"])
    frame(0)
    return figure, frame, frames, dates

# ---------------------------------------------------------------------------
# Saving. The animation and its still are both reproducible from the raw cache.
# ---------------------------------------------------------------------------


def save_animation(records, excluded):
    """Save the moving calendar and a final-frame still, returning both file paths."""
    figure, frame, frames, dates = make_animation(records)
    OUT.mkdir(exist_ok=True)
    target = OUT / f"rainfall-{YEAR}.gif"
    preview = OUT / "rainfall-animation-preview.png"
    print(f"Rendering {len(frames)} animation steps / {len(dates)} dates / "
          f"{FIGSIZE[0] * DPI:g} x {int(FIGSIZE[1] * DPI)} pixels ...", flush=True)
    try:
        frame(len(dates) - 1)
        figure.savefig(preview, dpi=DPI, facecolor=PAPER)
        movie = FuncAnimation(figure, frame, frames=frames, interval=1000 / FPS,
                              blit=False, repeat=True, cache_frame_data=False)
        movie.save(target, writer=PillowWriter(fps=FPS), dpi=DPI)
    finally:
        plt.close(figure)
    print(f"wrote {target.relative_to(HERE)} / {target.stat().st_size / 1024**2:.2f} MB")
    print(f"wrote {preview.relative_to(HERE)} / final observation: {dates[-1]}")
    if excluded:
        print(f"Raw-data audit: {len(excluded)} invalid missing-date placeholder excluded.")
    return target, preview


def main():
    """Read the frozen observations and render the GIF without a live data request."""
    records, excluded = read_records()
    save_animation(records, excluded)


if __name__ == "__main__":
    main()
