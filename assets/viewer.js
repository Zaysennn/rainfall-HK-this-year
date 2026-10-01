"use strict";

// ---------------------------------------------------------------------------
// The numbers arrive inside this page. No library, request, or live feed is used.
// ---------------------------------------------------------------------------

const DATA = JSON.parse(document.getElementById("rain-data").textContent);
const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const COLOURS = {teal: "#147a78", purple: "#9a718e", ink: "#20363a", orange: "#c46a34", grid: "#d9e1dc"};
const state = {year: DATA.defaultYear, mode: "calendar", compare: true, cutoff: 1,
               selected: 0, pinned: false, playing: false, speed: 1, hover: null};
let animation = null;
let lastFrame = 0;
const byId = id => document.getElementById(id);
const fmt = value => Number(value).toLocaleString("en-GB", {minimumFractionDigits: 1, maximumFractionDigits: 1});
// Singular day labels follow the displayed count without changing the observations.
const dayUnit = count => count === 1 ? "day" : "days";
const series = () => DATA.years[String(state.year)];
const other = () => Object.values(DATA.years).find(item => item.year !== state.year);

// Read precomputed prefixes rather than rescanning the historical source on input.
function limit() {
  return state.compare ? Math.min(series().observedCount, series().matchedCount) : series().observedCount;
}

// Keyboard inspection stays within the dates actually drawn by the active chart.
function inspectionLimit() {
  return state.mode === "cumulative" ? limit() : series().days.length;
}

// Match calendar dates, not row offsets, so changing a year does not shift the season.
function counterpart(row) {
  return row.counterpart === null ? null : other().days[row.counterpart];
}

// A revealed date has a public reading; a later published date stays hidden in playback.
function visibleStatus(row) {
  return row.status === "unpublished" ? "unpublished" : row.index >= state.cutoff ? "unrevealed" : row.status;
}

// Use a calendar-only label; parsing local midnight would introduce timezone shifts.
function dateLabel(row, includeYear = true) {
  return `${String(row.day).padStart(2, "0")} ${MONTHS[row.month - 1]}${includeYear ? ` ${row.date.slice(0, 4)}` : ""}`;
}

// Keep trace and incomplete values distinct from a measured zero in every view.
function reading(row, status = visibleStatus(row)) {
  if (status === "trace") return "<0.05";
  if (status === "rain" || status === "dry") return fmt(row.mm);
  if (status === "incomplete" && row.mm !== null) return fmt(row.mm);
  return "—";
}

// Human-readable states explain why a grey or hatched day has no numeric total.
function statusLabel(status) {
  return ({rain: "COMPLETE OBSERVATION", dry: "MEASURED ZERO", trace: "TRACE RAINFALL",
           missing: "MISSING OBSERVATION", incomplete: "INCOMPLETE OBSERVATION",
           unpublished: "NOT YET PUBLISHED", unrevealed: "NOT REVEALED YET"})[status];
}

// Share one square-root colour scale across both years; geometry remains linear in mm.
function rainColour(mm, palette = "teal") {
  const stops = palette === "purple" ? [[235,226,234],[184,154,177],[139,100,132],[96,63,92],[59,36,58]] :
    [[203,233,226],[114,188,181],[38,143,139],[16,93,100],[8,56,66]];
  const position = Math.sqrt(Math.max(0, Math.min(DATA.scaleMax, mm)) / DATA.scaleMax) * (stops.length - 1);
  const low = Math.min(stops.length - 2, Math.floor(position));
  const fraction = position - low;
  return `rgb(${stops[low].map((value, index) => Math.round(value + (stops[low + 1][index] - value) * fraction)).join(",")})`;
}

// Pattern fills remain meaningful when the observation is unavailable or not revealed.
function dayFill(row) {
  const status = visibleStatus(row);
  if (status === "unpublished") return "#e5e8e3";
  if (status === "unrevealed") return "url(#unrevealed-pattern)";
  if (status === "missing" || status === "incomplete") return "url(#missing-pattern)";
  if (status === "dry") return "#ffffff";
  return rainColour(Math.max(row.mm, DATA.traceLimit));
}

// Each mark can be inspected with a pointer or a roving keyboard focus.
function markAttributes(row) {
  const status = visibleStatus(row);
  const numeric = ["rain", "dry", "trace", "incomplete"].includes(status) ? `${reading(row, status)} millimetres` : "";
  return `data-index="${row.index}" tabindex="${row.index === state.selected ? 0 : -1}" role="button" aria-label="${dateLabel(row)}: ${statusLabel(status).toLowerCase()}, ${numeric}"`;
}

// Reusable SVG patterns make data quality visible rather than silently drawing zeros.
function definitions() {
  return `<defs><pattern id="missing-pattern" width="6" height="6" patternUnits="userSpaceOnUse"><rect width="6" height="6" fill="#f4dfce"/><path d="M-1,1 L1,-1 M0,6 L6,0 M5,7 L7,5" stroke="#cda484" stroke-width="1"/></pattern><pattern id="unrevealed-pattern" width="5" height="5" patternUnits="userSpaceOnUse"><rect width="5" height="5" fill="#eef3ef"/><circle cx="2" cy="2" r=".45" fill="#a6bbb1"/></pattern></defs>`;
}

// Transform the same daily amounts into a month-by-day calendar.
function calendarView() {
  const left = 50, top = 38, width = 27.2, height = 29.8;
  let drawing = definitions();
  for (let day = 1; day <= 31; day++) {
    if ([1, 5, 10, 15, 20, 25, 31].includes(day)) drawing += `<text x="${left + (day - .5) * width}" y="18" text-anchor="middle">${String(day).padStart(2, "0")}</text>`;
  }
  MONTHS.forEach((month, index) => { drawing += `<text x="34" y="${top + (index + .5) * height + 3}" text-anchor="end">${month}</text>`; });
  for (const row of series().days) {
    const x = left + (row.day - 1) * width, y = top + (row.month - 1) * height;
    const stroke = row.index === state.selected ? COLOURS.orange : row.index === state.cutoff - 1 ? COLOURS.teal : COLOURS.grid;
    drawing += `<rect ${markAttributes(row)} x="${x + 1.6}" y="${y + 1.5}" width="${width - 3.2}" height="${height - 3}" rx="2" fill="${dayFill(row)}" stroke="${stroke}" stroke-width="${row.index === state.selected ? 2 : .7}"/>`;
    if (visibleStatus(row) === "trace") drawing += `<circle cx="${x + width / 2}" cy="${y + height / 2}" r="1.4" fill="${COLOURS.teal}" pointer-events="none"/>`;
  }
  drawing += `<text x="50" y="429" class="axis-label">One square = one day · dates run left to right, months top to bottom</text>`;
  return drawing;
}

// Draw a linear ruler shared by all daily views; tiny hit areas still span the chart.
function dailyAxes(top, bottom, left, right) {
  let drawing = "";
  for (let tick = 0; tick <= 4; tick++) {
    const amount = DATA.scaleMax * tick / 4;
    const y = bottom - tick / 4 * (bottom - top);
    drawing += `<line x1="${left}" x2="${right}" y1="${y}" y2="${y}" stroke="${COLOURS.grid}" stroke-width=".7"/><text x="${left - 10}" y="${y + 3}" text-anchor="end">${amount}</text>`;
  }
  return drawing;
}

// Daily bars preserve linear heights, while paired bars share identical calendar dates.
function barsView() {
  const left = 50, right = 902, top = 32, bottom = 388;
  const step = (right - left) / series().days.length;
  let drawing = definitions() + dailyAxes(top, bottom, left, right);
  for (const row of series().days) {
    const x = left + row.index * step, status = visibleStatus(row);
    const complete = ["rain", "dry", "trace"].includes(status);
    const height = complete ? (row.mm / DATA.scaleMax) * (bottom - top) : 0;
    const paired = state.compare ? counterpart(row) : null;
    const pairedComplete = paired && row.index < state.cutoff && ["rain", "dry", "trace"].includes(paired.status);
    const barWidth = step * (state.compare ? .49 : .8);
    if (complete) drawing += `<rect x="${x}" y="${bottom - Math.max(height, 1)}" width="${barWidth}" height="${Math.max(height, 1)}" fill="${status === "dry" ? "#ffffff" : dayFill(row)}" stroke="${status === "dry" ? COLOURS.grid : "none"}" stroke-width=".5"/>`;
    else drawing += `<rect x="${x}" y="${bottom - 5}" width="${step * .8}" height="5" fill="${dayFill(row)}"/>`;
    if (pairedComplete) {
      const otherHeight = paired.mm / DATA.scaleMax * (bottom - top);
      drawing += `<rect x="${x + step * .51}" y="${bottom - Math.max(otherHeight, 1)}" width="${step * .4}" height="${Math.max(otherHeight, 1)}" fill="${COLOURS.purple}" opacity=".72"/>`;
    }
    drawing += `<rect ${markAttributes(row)} x="${x}" y="${top}" width="${step}" height="${bottom - top + 10}" fill="transparent"/>`;
    if (row.day === 1) drawing += `<text x="${x}" y="412" text-anchor="start">${MONTHS[row.month - 1]}</text>`;
  }
  const cursorX = left + (state.cutoff - .5) * step;
  drawing += `<line x1="${cursorX}" x2="${cursorX}" y1="${top}" y2="${bottom}" stroke="${COLOURS.orange}" stroke-width="1" pointer-events="none"/><text x="50" y="439" class="axis-label">Daily rain / mm${state.compare ? ` · ${state.year} teal, ${other().year} purple` : ""}</text>`;
  return drawing;
}

// Polar to Cartesian: January begins at the top and the year turns clockwise.
function polar(angle, radius) {
  return [460 + Math.sin(angle) * radius, 221 - Math.cos(angle) * radius];
}

// The rain wheel is the daily bar chart bent into a full turn, with a linear radius.
function wheelView() {
  const baseline = 103, reach = 90, count = series().days.length;
  let drawing = definitions();
  for (let tick = 0; tick <= 3; tick++) {
    const radius = baseline + reach * tick / 3;
    drawing += `<circle cx="460" cy="221" r="${radius}" fill="none" stroke="${COLOURS.grid}" stroke-width=".7"/>`;
    if (tick > 0) drawing += `<text x="${460 + radius + 6}" y="225">${Math.round(DATA.scaleMax * tick / 3)} mm</text>`;
  }
  for (const row of series().days) {
    const angle = row.index / count * Math.PI * 2;
    const status = visibleStatus(row), complete = ["rain", "dry", "trace"].includes(status);
    const start = polar(angle, baseline), tip = polar(angle, baseline + (complete ? row.mm / DATA.scaleMax * reach : 0));
    const paired = state.compare ? counterpart(row) : null;
    if (paired && row.index < state.cutoff && ["rain", "dry", "trace"].includes(paired.status)) {
      const pairedAngle = angle + .006;
      const otherStart = polar(pairedAngle, baseline), otherTip = polar(pairedAngle, baseline + paired.mm / DATA.scaleMax * reach);
      drawing += `<line x1="${otherStart[0]}" y1="${otherStart[1]}" x2="${otherTip[0]}" y2="${otherTip[1]}" stroke="${COLOURS.purple}" stroke-width="1" opacity=".72"/>`;
      if (paired.status === "trace" || paired.status === "dry") drawing += `<circle cx="${otherStart[0]}" cy="${otherStart[1]}" r="${paired.status === "trace" ? 1 : .7}" fill="${paired.status === "trace" ? COLOURS.purple : "#ffffff"}" stroke="${COLOURS.purple}" stroke-width=".5" pointer-events="none"/>`;
    }
    const stroke = complete ? status === "dry" ? "#bbc9bf" : dayFill(row) : status === "unpublished" ? "#d4d9d2" : status === "unrevealed" ? "#adc2b6" : "#cda484";
    if (complete && row.mm > 0) drawing += `<line x1="${start[0]}" y1="${start[1]}" x2="${tip[0]}" y2="${tip[1]}" stroke="${stroke}" stroke-width="${row.index === state.selected ? 2.2 : 1.6}"/>`;
    else drawing += `<circle cx="${start[0]}" cy="${start[1]}" r="${status === "trace" ? 1.3 : 1}" fill="${dayFill(row)}" stroke="${status === "trace" ? COLOURS.teal : stroke}" stroke-width=".5" pointer-events="none"/>`;
    const hitStart = polar(angle, baseline - 9), hitTip = polar(angle, baseline + reach + 4);
    drawing += `<line ${markAttributes(row)} x1="${hitStart[0]}" y1="${hitStart[1]}" x2="${hitTip[0]}" y2="${hitTip[1]}" stroke="transparent" stroke-width="4"/>`;
    if (row.day === 1) {
      const label = polar(angle, 213);
      drawing += `<text x="${label[0]}" y="${label[1] + 3}" text-anchor="middle">${MONTHS[row.month - 1]}</text>`;
    }
  }
  const cursorAngle = (state.cutoff - 1) / count * Math.PI * 2;
  const pointer = polar(cursorAngle, baseline - 17), outer = polar(cursorAngle, baseline + reach + 9);
  drawing += `<line x1="${pointer[0]}" y1="${pointer[1]}" x2="${outer[0]}" y2="${outer[1]}" stroke="${COLOURS.orange}" stroke-width="1" pointer-events="none"/><text x="460" y="209" text-anchor="middle" class="wheel-title">${state.year}</text><text x="460" y="234" text-anchor="middle">${dateLabel(series().days[state.cutoff - 1], false)}</text><text x="460" y="255" text-anchor="middle">ONE TURN = ONE YEAR</text><text x="50" y="442" class="axis-label">Distance from the inner ring = daily rain / mm${state.compare ? ` · paired ${other().year} spokes in purple` : ""}</text>`;
  return drawing;
}

// Build a line only while the publisher's complete observations remain uninterrupted.
function cumulativePath(days, coordinates, cutoff, matched = false) {
  let path = "";
  for (const row of series().days.slice(0, cutoff)) {
    const value = matched ? counterpart(row) : days[row.index];
    if (!value || value.cumulative === null) break;
    const [x, y] = coordinates(row.index, value.cumulative);
    path += `${path ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)} `;
  }
  return path;
}

// Shared cumulative geometry keeps totals aligned to the same month-and-day exposure.
function lineView(mini = false) {
  const left = 54, right = 900, top = 16, bottom = mini ? 158 : 388;
  const horizon = limit();
  const current = series().days[state.cutoff - 1];
  const paired = state.compare ? counterpart(current) : null;
  const endpoint = series().days[horizon - 1];
  const pairedEndpoint = state.compare ? counterpart(endpoint) : null;
  const highest = Math.max(endpoint.stats.total, pairedEndpoint ? pairedEndpoint.stats.total : 0, 1);
  const axisStep = Math.max(10, Math.pow(10, Math.floor(Math.log10(highest))) / 2);
  const maximum = Math.ceil(highest / axisStep) * axisStep;
  const coordinates = (index, mm) => [left + index / Math.max(1, horizon - 1) * (right - left), bottom - mm / maximum * (bottom - top)];
  let drawing = mini ? "" : definitions();
  for (let tick = 0; tick <= 4; tick++) {
    const amount = maximum * tick / 4, y = bottom - tick / 4 * (bottom - top);
    drawing += `<line x1="${left}" x2="${right}" y1="${y}" y2="${y}" stroke="${COLOURS.grid}" stroke-width=".7"/><text x="${left - 10}" y="${y + 3}" text-anchor="end">${Math.round(amount).toLocaleString("en-GB")}</text>`;
  }
  for (const row of series().days.slice(0, horizon)) {
    const x = coordinates(row.index, 0)[0];
    if (row.day === 1) drawing += `<text x="${x}" y="${bottom + 20}">${MONTHS[row.month - 1]}</text>`;
    if (!mini) drawing += `<rect ${markAttributes(row)} x="${x - (right - left) / horizon / 2}" y="${top}" width="${(right - left) / horizon}" height="${bottom - top}" fill="transparent"/>`;
  }
  if (state.compare) drawing += `<path d="${cumulativePath(other().days, coordinates, state.cutoff, true)}" fill="none" stroke="${COLOURS.purple}" stroke-width="2" pointer-events="none"/>`;
  drawing += `<path d="${cumulativePath(series().days, coordinates, state.cutoff)}" fill="none" stroke="${COLOURS.teal}" stroke-width="${mini ? 2.3 : 3}" pointer-events="none"/>`;
  const cursorX = coordinates(state.cutoff - 1, 0)[0];
  drawing += `<line x1="${cursorX}" x2="${cursorX}" y1="${top}" y2="${bottom}" stroke="${COLOURS.orange}" stroke-width="1" stroke-dasharray="3 4" pointer-events="none"/>`;
  if (current.cumulative !== null) drawing += `<circle cx="${cursorX}" cy="${coordinates(current.index, current.cumulative)[1]}" r="3" fill="${COLOURS.teal}" pointer-events="none"/>`;
  if (paired && paired.cumulative !== null) drawing += `<circle cx="${cursorX}" cy="${coordinates(current.index, paired.cumulative)[1]}" r="3" fill="${COLOURS.purple}" pointer-events="none"/>`;
  drawing += `<text x="54" y="${mini ? 193 : 439}" class="axis-label">Accumulated complete rain / mm · 01 JAN–${dateLabel(current, false)}</text>`;
  return drawing;
}

// Prefix statistics always describe the revealed window, including when seeking backwards.
function renderStats() {
  const row = series().days[state.cutoff - 1], stats = row.stats;
  byId("total-label").textContent = `${state.year} · ${stats.missing ? "KNOWN COMPLETE TOTAL" : "RECORDED TOTAL"}`;
  byId("total").textContent = fmt(stats.total);
  byId("total-note").textContent = `01 JAN–${dateLabel(row, false)} · ${stats.complete} complete ${dayUnit(stats.complete)}`;
  byId("rainy").textContent = stats.rainy;
  byId("rainy").nextElementSibling.textContent = dayUnit(stats.rainy);
  byId("rainy-note").textContent = `At least ${DATA.rainyThreshold} mm · ${stats.traces} trace ${dayUnit(stats.traces)}`;
  const peak = stats.peakIndex === null ? null : series().days[stats.peakIndex];
  byId("peak").textContent = peak ? reading(peak, peak.status) : "—";
  byId("peak-note").textContent = peak ? dateLabel(peak) : "No complete readings";
  if (state.compare) {
    const paired = counterpart(row), prior = paired.stats;
    byId("comparison-title").textContent = `${other().year} · SAME PERIOD`;
    byId("comparison-total").textContent = fmt(prior.total);
    byId("comparison-unit").textContent = "mm";
    const gap = stats.missing || prior.missing;
    const delta = stats.total - prior.total;
    byId("comparison-note").textContent = gap ? "Quality gaps: known totals are not equal coverage" :
      prior.total === 0 ? `Same dates · difference ${delta >= 0 ? "+" : ""}${fmt(delta)} mm` :
      `${delta >= 0 ? "+" : ""}${(delta / prior.total * 100).toFixed(1)}% in ${state.year} · same dates`;
  } else {
    byId("comparison-title").textContent = "COMPLETE READINGS";
    byId("comparison-total").textContent = stats.complete;
    byId("comparison-unit").textContent = dayUnit(stats.complete);
    byId("comparison-note").textContent = `${stats.missing} missing / incomplete ${dayUnit(stats.missing)} · comparison off`;
  }
  byId("quality-note").textContent = `${stats.missing} missing or incomplete ${dayUnit(stats.missing)} in the revealed ${state.year} window. Only publisher-marked complete observations enter totals. A cumulative line stops at its first gap instead of inventing values.`;
}

// The pinned panel tells exact values and limits without exposing unrevealed future readings.
function renderDetail(index = state.hover === null ? state.selected : state.hover) {
  const row = series().days[index], status = visibleStatus(row);
  byId("detail-date").textContent = dateLabel(row);
  byId("detail-value").textContent = reading(row, status);
  byId("detail-unit").textContent = ["rain", "dry", "trace", "incomplete"].includes(status) ? "mm" : "";
  byId("detail-status").textContent = statusLabel(status);
  byId("detail-status").dataset.status = status;
  const explanations = {
    rain: "A complete observed daily total. This amount contributes to the revealed total.",
    dry: "The station measured zero rainfall. This is an observation, not a missing day.",
    trace: "The station recorded a trace: less than 0.05 mm. It contributes a 0.0 mm lower bound, not a measured zero.",
    missing: "No usable daily observation is available. It contributes nothing to the known total; the cumulative line stops at this gap.",
    incomplete: "The publisher marks this reading incomplete. Its reported amount is shown for inspection but excluded from all totals.",
    unpublished: "This date is beyond the saved publisher’s coverage. No rainfall value is inferred, even if the calendar date has passed.",
    unrevealed: state.compare && index >= limit() ? "This published day is outside the matched comparison window. Turn comparison off to reveal this published day." : "The snapshot contains this day, but playback has not reached it. Reveal through this date to inspect the observation.",
  };
  byId("detail-explanation").textContent = explanations[status];
  byId("detail-flag").textContent = status === "unrevealed" || status === "unpublished" ? "Not shown" : row.flag === "C" ? "C · complete" : row.flag === "#" ? "# · incomplete" : "No completeness flag";
  const paired = counterpart(row);
  const mayCompare = state.compare && row.index < state.cutoff && row.index < series().matchedCount;
  byId("detail-other").textContent = !state.compare ? "Comparison is off" : !mayCompare ? "Outside the revealed comparison window" :
    paired ? `${other().year}: ${reading(paired, paired.status)}${paired.mm !== null ? " mm" : ""} · ${statusLabel(paired.status).toLowerCase()}` : "No matching calendar date";
  byId("detail-cumulative").textContent = status === "unrevealed" || status === "unpublished" ? "Not shown" : row.cumulative === null ? "Stopped at a quality gap" : `${fmt(row.cumulative)} mm`;
  const revealable = status === "unrevealed" && index < limit();
  byId("reveal-day").hidden = !revealable;
  byId("previous-day").disabled = index === 0;
  byId("next-day").disabled = index === inspectionLimit() - 1;
}

// One render keeps every encoding, annotation, and summary on the same playback date.
function render() {
  state.selected = Math.min(state.selected, inspectionLimit() - 1);
  const row = series().days[state.cutoff - 1];
  const views = {
    calendar: ["A calendar of rain", "Each square holds one day. Read the wet season across months, then inspect an individual date.", calendarView, "01"],
    bars: ["The height of a wet day", (state.compare ? "Bar height is daily rainfall in millimetres. Paired purple bars use the same dates in the other year." : `Bar height is daily rainfall in millimetres, using only ${state.year} observations.`) + " A one-pixel visibility floor marks tiny readings, zero, and Trace; it is not extra rain.", barsView, "02"],
    wheel: ["A year, bent into a circle", "January starts at twelve o’clock. The year turns clockwise; rain extends linearly from the inner ring. Inner-ring dots mark zero, Trace, and data states; dot size does not encode rain.", wheelView, "03"],
    cumulative: ["How the year accumulates", state.compare ? "Each complete day adds to the line. Both years use the same month-and-day window; a quality gap stops the line." : `Each complete day in ${state.year} adds to the line. A quality gap stops the line instead of inventing an observation.`, lineView, "04"],
  };
  const [title, description, draw, number] = views[state.mode];
  byId("view-title").textContent = title;
  byId("view-description").textContent = description;
  byId("view-number").textContent = `${number} / 04`;
  document.querySelectorAll("[data-mode]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.mode === state.mode)));
  byId("chart").innerHTML = draw();
  byId("chart").setAttribute("aria-label", `${title}, ${state.year}, revealed through ${dateLabel(row)}. Use arrow keys on a date to inspect nearby days.`);
  byId("seek").max = limit();
  byId("seek").value = state.cutoff;
  byId("seek").setAttribute("aria-valuetext", `Revealed through ${dateLabel(row)}`);
  byId("cursor-date").textContent = dateLabel(row);
  byId("cursor-count").textContent = `DAY ${state.cutoff} / ${limit()}`;
  byId("range-end").textContent = dateLabel(series().days[limit() - 1], false);
  byId("coverage-note").textContent = `${state.year} · ${series().observedCount} calendar ${dayUnit(series().observedCount)} published\nThrough ${dateLabel(series().days[series().observedCount - 1])}`;
  byId("compare-label").textContent = `${state.year} vs ${other().year} · matched dates only`;
  byId("selected-year-key").textContent = state.year;
  byId("other-year-key").textContent = other().year;
  byId("comparison-chart-wrap").hidden = !state.compare || state.mode === "cumulative";
  if (state.compare && state.mode !== "cumulative") byId("comparison-chart").innerHTML = lineView(true);
  byId("matched-note").textContent = `Both lines cover 01 JAN–${dateLabel(row, false)}. Comparison is capped at ${dateLabel(series().days[series().matchedCount - 1], false)}, the latest month/day available in both years. Turn comparison off to explore a longer published year.`;
  renderStats();
  renderDetail();
}

// Seeking backward is a fresh prefix, never an accumulation on the previous frame.
function setCutoff(value) {
  state.cutoff = Math.max(1, Math.min(limit(), Math.round(Number(value))));
  if (!state.pinned) state.selected = state.cutoff - 1;
  state.hover = null;
  byId("tooltip").hidden = true;
  render();
}

// Pause the animation without changing the inspected day or the selected chart mode.
function pause() {
  state.playing = false;
  if (animation !== null) cancelAnimationFrame(animation);
  animation = null;
  byId("play-label").textContent = "Play";
  byId("play").setAttribute("aria-label", "Play rainfall timeline");
  byId("play").firstElementChild.textContent = "▶";
}

// Advance from elapsed time at a bounded rate; changing a view keeps the same cursor.
function tick(timestamp) {
  if (!state.playing) return;
  const interval = 1000 / (12 * state.speed);
  if (timestamp - lastFrame >= interval) {
    const steps = Math.min(4, Math.floor((timestamp - lastFrame) / interval));
    lastFrame = timestamp;
    setCutoff(state.cutoff + steps);
    if (state.cutoff >= limit()) { pause(); return; }
  }
  animation = requestAnimationFrame(tick);
}

// A completed year restarts on January 1; starting halfway through resumes in place.
function play() {
  if (state.playing) { pause(); return; }
  if (state.cutoff >= limit()) { state.pinned = false; setCutoff(1); }
  state.playing = true;
  lastFrame = performance.now();
  byId("play-label").textContent = "Pause";
  byId("play").setAttribute("aria-label", "Pause rainfall timeline");
  byId("play").firstElementChild.textContent = "Ⅱ";
  animation = requestAnimationFrame(tick);
}

// Pin an inspection independently of playback; keyboard arrows use the same action.
function selectDay(index, focus = false) {
  state.selected = Math.max(0, Math.min(inspectionLimit() - 1, index));
  state.pinned = true;
  state.hover = null;
  render();
  if (focus) byId("chart").querySelector(`[data-index="${state.selected}"]`)?.focus();
}

// Position an exact-value tooltip within the chart, including on a narrow screen.
function showTooltip(event, index) {
  const row = series().days[index], status = visibleStatus(row);
  const tooltip = byId("tooltip"), frame = byId("main-chart").getBoundingClientRect();
  const numeric = ["rain", "dry", "trace", "incomplete"].includes(status);
  tooltip.innerHTML = `<strong>${dateLabel(row)}</strong><br>${numeric ? `${reading(row, status)} mm · ` : ""}${statusLabel(status).toLowerCase()}`;
  tooltip.hidden = false;
  const mark = event.target.getBoundingClientRect();
  const clientX = Number.isFinite(event.clientX) ? event.clientX : mark.x + mark.width / 2;
  const clientY = Number.isFinite(event.clientY) ? event.clientY : mark.y;
  tooltip.style.left = `${Math.max(0, Math.min(frame.width - tooltip.offsetWidth, clientX - frame.x + 14))}px`;
  tooltip.style.top = `${Math.max(0, Math.min(frame.height - tooltip.offsetHeight, clientY - frame.y - tooltip.offsetHeight - 10))}px`;
  state.hover = index;
  renderDetail(index);
}

// Year switching keeps the calendar date where possible and never extends comparison exposure.
function setYear(year) {
  const prior = series().days[state.cutoff - 1];
  state.year = Number(year);
  byId("year").value = state.year;
  const match = series().days.find(row => row.month === prior.month && row.day === prior.day);
  state.pinned = false;
  setCutoff(match ? match.index + 1 : state.cutoff);
}

// Turning comparison on caps both years at the common published month and day.
function setCompare(enabled) {
  state.compare = Boolean(enabled);
  byId("compare").checked = state.compare;
  setCutoff(state.cutoff);
}

// Chart transformations change geometry without resetting the timeline or its totals.
function setMode(mode) {
  if (!["calendar", "bars", "wheel", "cumulative"].includes(mode)) return;
  state.mode = mode;
  byId("tooltip").hidden = true;
  state.hover = null;
  render();
}

// Bind controls once; chart events are delegated because the SVG marks are redrawn.
function connectControls() {
  byId("play").addEventListener("click", play);
  byId("seek").addEventListener("input", event => { pause(); setCutoff(event.target.value); });
  byId("year").addEventListener("change", event => setYear(event.target.value));
  byId("compare").addEventListener("change", event => setCompare(event.target.checked));
  byId("speed").addEventListener("change", event => { state.speed = Number(event.target.value); });
  document.querySelectorAll("[data-mode]").forEach(button => button.addEventListener("click", () => setMode(button.dataset.mode)));
  byId("previous-day").addEventListener("click", () => selectDay(state.selected - 1));
  byId("next-day").addEventListener("click", () => selectDay(state.selected + 1));
  byId("reveal-day").addEventListener("click", () => { pause(); setCutoff(state.selected + 1); });
  byId("chart").addEventListener("click", event => {
    const mark = event.target.closest("[data-index]");
    if (mark) selectDay(Number(mark.dataset.index));
  });
  byId("chart").addEventListener("pointermove", event => {
    const mark = event.target.closest("[data-index]");
    if (mark) showTooltip(event, Number(mark.dataset.index));
    else { state.hover = null; byId("tooltip").hidden = true; renderDetail(); }
  });
  byId("chart").addEventListener("pointerleave", () => { state.hover = null; byId("tooltip").hidden = true; renderDetail(); });
  byId("chart").addEventListener("focusin", event => {
    const mark = event.target.closest("[data-index]");
    if (mark) showTooltip(event, Number(mark.dataset.index));
  });
  byId("chart").addEventListener("focusout", () => { state.hover = null; byId("tooltip").hidden = true; renderDetail(); });
  byId("chart").addEventListener("keydown", event => {
    const mark = event.target.closest("[data-index]");
    if (!mark) return;
    const index = Number(mark.dataset.index);
    const movement = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -1, ArrowDown: 1};
    if (Object.hasOwn(movement, event.key)) { event.preventDefault(); selectDay(index + movement[event.key], true); }
    else if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectDay(index, true); }
    else if (event.key === "Home") { event.preventDefault(); selectDay(0, true); }
    else if (event.key === "End") { event.preventDefault(); selectDay(inspectionLimit() - 1, true); }
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) pause(); });
}

// Fill source and scale notes from the snapshot, then draw the initial published window.
function initialise() {
  state.cutoff = limit();
  state.selected = state.cutoff - 1;
  byId("year").value = state.year;
  byId("scale-max").textContent = DATA.scaleMax;
  byId("scale-quarter").textContent = DATA.scaleMax / 4;
  byId("source-link").href = DATA.source.url;
  byId("snapshot-note").textContent = `Saved ${DATA.source.snapshotUTC.slice(0, 10)} UTC · ${DATA.source.excludedRows} invalid historical date placeholder excluded · verified SHA-256 ${DATA.source.sha256.slice(0, 12)}…`;
  connectControls();
  render();
}

initialise();

// A small read-only inspection hook makes automated checks independent of presentation.
window.rainfallExplorer = Object.freeze({getState: () => ({...state, limit: limit()})});
