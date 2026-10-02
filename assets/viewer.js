"use strict";

// ---------------------------------------------------------------------------
// The saved records are embedded here; optional official requests refresh this page in memory.
// ---------------------------------------------------------------------------

const DATA = JSON.parse(document.getElementById("rain-data").textContent);
const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const COLOURS = {teal: "#147a78", purple: "#9a718e", ink: "#20363a", orange: "#c46a34", grid: "#d9e1dc"};
const state = {year: DATA.defaultYear, mode: "calendar", compare: true, cutoff: 1,
               selected: 0, pinned: false, playing: false, speed: 1, hover: null};
// Daily inspection and hourly playback are independent of the yearly timeline.
const weatherView = {year: DATA.defaultYear, index: null, hour: 23, hours: [],
                     playing: false, speed: 1, returnFocus: true};
let hourlyAnimation = null;
let lastHourFrame = 0;
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
  const shown = series().displayCount ?? series().observedCount;
  return state.compare ? Math.min(shown, series().matchedDisplayCount ?? series().matchedCount) : shown;
}

// A day in progress can be inspected but cannot extend a completed-day comparison.
function completedLimit() {
  return state.compare ? Math.min(series().observedCount, series().matchedCount) : series().observedCount;
}

function completedCutoff() {
  return Math.max(1, Math.min(state.cutoff, completedLimit()));
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
           ongoing: "DAY IN PROGRESS", unpublished: "NOT YET PUBLISHED", unrevealed: "NOT REVEALED YET"})[status] || "OBSERVATION UNAVAILABLE";
}

function dayStatusLabel(row, status = visibleStatus(row)) {
  return row.quality === "provisional" && ["rain", "dry", "trace"].includes(status) ? "PROVISIONAL DAILY REPORT" : statusLabel(status);
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
  if (status === "ongoing") return "url(#ongoing-pattern)";
  if (status === "dry") return "#ffffff";
  return rainColour(Math.max(row.mm, DATA.traceLimit));
}

// Each mark can be inspected with a pointer or a roving keyboard focus.
function markAttributes(row) {
  const status = visibleStatus(row);
  const numeric = ["rain", "dry", "trace", "incomplete"].includes(status) ? `${reading(row, status)} millimetres` : "";
  return `data-index="${row.index}" data-quality="${row.quality || "verified"}" data-status="${status}" tabindex="${row.index === state.selected ? 0 : -1}" role="button" aria-label="${dateLabel(row)}: ${dayStatusLabel(row, status).toLowerCase()}, ${numeric}"`;
}

// Reusable SVG patterns make data quality visible rather than silently drawing zeros.
function definitions() {
  return `<defs><pattern id="ongoing-pattern" width="6" height="6" patternUnits="userSpaceOnUse"><rect width="6" height="6" fill="#eee2c9"/><path d="M0,6 L6,0" stroke="#c9aa73" stroke-width=".8"/></pattern><pattern id="missing-pattern" width="6" height="6" patternUnits="userSpaceOnUse"><rect width="6" height="6" fill="#f4dfce"/><path d="M-1,1 L1,-1 M0,6 L6,0 M5,7 L7,5" stroke="#cda484" stroke-width="1"/></pattern><pattern id="unrevealed-pattern" width="5" height="5" patternUnits="userSpaceOnUse"><rect width="5" height="5" fill="#eef3ef"/><circle cx="2" cy="2" r=".45" fill="#a6bbb1"/></pattern></defs>`;
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
    drawing += `<rect ${markAttributes(row)} x="${x + 1.6}" y="${y + 1.5}" width="${width - 3.2}" height="${height - 3}" rx="2" fill="${dayFill(row)}" stroke="${stroke}" stroke-width="${row.index === state.selected ? 2 : .7}" stroke-dasharray="${row.quality === "provisional" ? "2 2" : "none"}"/>`;
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
    const pairedComplete = paired && row.index < series().matchedCount && row.index < state.cutoff && ["rain", "dry", "trace"].includes(paired.status);
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
    if (paired && row.index < series().matchedCount && row.index < state.cutoff && ["rain", "dry", "trace"].includes(paired.status)) {
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
  const horizon = limit(), cutoff = completedCutoff();
  const current = series().days[cutoff - 1], paired = state.compare ? counterpart(current) : null;
  const endpoint = series().days[Math.max(0, Math.min(horizon, completedLimit()) - 1)];
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
  if (state.compare) drawing += `<path d="${cumulativePath(other().days, coordinates, cutoff, true)}" fill="none" stroke="${COLOURS.purple}" stroke-width="2" pointer-events="none"/>`;
  drawing += `<path d="${cumulativePath(series().days, coordinates, cutoff)}" fill="none" stroke="${COLOURS.teal}" stroke-width="${mini ? 2.3 : 3}" pointer-events="none"/>`;
  const cursorX = coordinates(cutoff - 1, 0)[0];
  drawing += `<line x1="${cursorX}" x2="${cursorX}" y1="${top}" y2="${bottom}" stroke="${COLOURS.orange}" stroke-width="1" stroke-dasharray="3 4" pointer-events="none"/>`;
  if (current.cumulative !== null) drawing += `<circle cx="${cursorX}" cy="${coordinates(current.index, current.cumulative)[1]}" r="3" fill="${COLOURS.teal}" pointer-events="none"/>`;
  if (paired && paired.cumulative !== null) drawing += `<circle cx="${cursorX}" cy="${coordinates(current.index, paired.cumulative)[1]}" r="3" fill="${COLOURS.purple}" pointer-events="none"/>`;
  drawing += `<text x="54" y="${mini ? 193 : 439}" class="axis-label">Accumulated completed-day rain / mm · 01 JAN–${dateLabel(current, false)}${state.cutoff > cutoff ? " · day in progress excluded" : ""}</text>`;
  return drawing;
}

// Prefix statistics always describe the revealed window, including when seeking backwards.
function renderStats() {
  const row = series().days[completedCutoff() - 1], stats = row.stats;
  const provisional = stats.provisional || 0, verified = stats.verified ?? stats.complete - provisional;
  byId("total-label").textContent = `${state.year} · ${provisional || stats.missing ? "KNOWN DAILY TOTAL" : "RECORDED DAILY TOTAL"}`;
  byId("total").textContent = fmt(stats.total);
  byId("total-note").textContent = `01 JAN–${dateLabel(row, false)} · ${verified} verified / ${provisional} provisional ${dayUnit(stats.complete)}${state.cutoff > completedCutoff() ? " · current day excluded" : ""}`;
  byId("rainy").textContent = stats.rainy;
  byId("rainy").nextElementSibling.textContent = dayUnit(stats.rainy);
  byId("rainy-note").textContent = `At least ${DATA.rainyThreshold} mm · ${stats.traces} trace ${dayUnit(stats.traces)}`;
  const peak = stats.peakIndex === null ? null : series().days[stats.peakIndex];
  byId("peak").textContent = peak ? reading(peak, peak.status) : "—";
  byId("peak-note").textContent = peak ? `${dateLabel(peak)}${peak.quality === "provisional" ? " · provisional" : ""}` : "No completed daily readings";
  if (state.compare) {
    const paired = counterpart(row), prior = paired.stats;
    byId("comparison-title").textContent = `${other().year} · SAME PERIOD`;
    byId("comparison-total").textContent = fmt(prior.total);
    byId("comparison-unit").textContent = "mm";
    const gap = stats.missing || prior.missing, delta = stats.total - prior.total;
    byId("comparison-note").textContent = gap ? "Quality gaps: known totals are not equal coverage" :
      `${prior.total === 0 ? `Difference ${delta >= 0 ? "+" : ""}${fmt(delta)} mm` : `${delta >= 0 ? "+" : ""}${(delta / prior.total * 100).toFixed(1)}% in ${state.year}`} · through ${dateLabel(row, false)}${provisional || prior.provisional ? " · provisional reports included" : ""}`;
  } else {
    byId("comparison-title").textContent = "COMPLETED DAILY READINGS";
    byId("comparison-total").textContent = stats.complete;
    byId("comparison-unit").textContent = dayUnit(stats.complete);
    byId("comparison-note").textContent = `${stats.missing} missing / incomplete ${dayUnit(stats.missing)} · comparison off`;
  }
  byId("quality-note").textContent = `${verified} verified climate readings and ${provisional} provisional reports contribute to the revealed ${state.year} daily total. ${stats.missing} missing or incomplete ${dayUnit(stats.missing)} are excluded. Provisional reports may be revised. The day in progress and rolling one-hour observations never enter completed-day totals. A cumulative line stops at its first quality gap.`;
}

// The pinned panel tells exact values and limits without exposing unrevealed future readings.
function renderDetail(index = state.hover === null ? state.selected : state.hover) {
  const row = series().days[index], status = visibleStatus(row);
  byId("detail-date").textContent = dateLabel(row);
  byId("detail-value").textContent = reading(row, status);
  byId("detail-unit").textContent = ["rain", "dry", "trace", "incomplete"].includes(status) ? "mm" : "";
  byId("detail-status").textContent = dayStatusLabel(row, status);
  byId("detail-status").dataset.quality = row.quality || "verified";
  byId("detail-status").dataset.status = status;
  const explanations = {
    rain: "A complete observed daily total. This amount contributes to the revealed total.",
    dry: "The station measured zero rainfall. This is an observation, not a missing day.",
    trace: "The station recorded a trace: less than 0.05 mm. It contributes a 0.0 mm lower bound, not a measured zero.",
    missing: "No usable daily observation is available. It contributes nothing to the known total; the cumulative line stops at this gap.",
    incomplete: "The publisher marks this reading incomplete. Its reported amount is shown for inspection but excluded from all totals.",
    ongoing: "This Hong Kong calendar day is in progress. Open Day weather for timestamped observations; no whole-day rain total is inferred or included in daily statistics.",
    unpublished: "This date is beyond the saved publisher’s coverage. No rainfall value is inferred, even if the calendar date has passed.",
    unrevealed: state.compare && index >= limit() ? "This published day is outside the matched comparison window. Turn comparison off to reveal this published day." : "The snapshot contains this day, but playback has not reached it. Reveal through this date to inspect the observation.",
  };
  byId("detail-explanation").textContent = row.quality === "provisional" && ["rain", "dry", "trace"].includes(status) ? "A provisional daily weather report for an ended day. It contributes to the known daily total separately from verified monthly climate records and may be revised." : explanations[status];
  byId("detail-flag").textContent = status === "unrevealed" || status === "unpublished" ? "Not shown" : row.quality === "provisional" ? "Provisional daily report · no monthly C flag" : row.flag === "C" ? "C · complete" : row.flag === "#" ? "# · incomplete" : "No completeness flag";
  const paired = counterpart(row);
  const mayCompare = state.compare && row.index < state.cutoff && row.index < series().matchedCount;
  byId("detail-other").textContent = !state.compare ? "Comparison is off" : !mayCompare ? "Outside the revealed comparison window" :
    paired ? `${other().year}: ${reading(paired, paired.status)}${paired.mm !== null ? " mm" : ""} · ${statusLabel(paired.status).toLowerCase()}` : "No matching calendar date";
  byId("detail-cumulative").textContent = status === "ongoing" ? "Not a completed day" : status === "unrevealed" || status === "unpublished" ? "Not shown" : row.cumulative === null ? "Stopped at a quality gap" : `${fmt(row.cumulative)} mm`;
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
    calendar: ["A calendar of rain", "Each square holds one day. Click a square, or press Enter on a focused date, to inspect daily weather and any saved hourly rainfall.", calendarView, "01"],
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
  byId("coverage-note").textContent = `${state.year} · daily readings through ${dateLabel(series().days[series().observedCount - 1])}\n${(series().displayCount ?? series().observedCount) > series().observedCount ? `Current date ${dateLabel(series().days[(series().displayCount ?? series().observedCount) - 1])} · in progress` : "Verified and labelled provisional records"}`;
  byId("compare-label").textContent = `${state.year} vs ${other().year} · matched dates only`;
  byId("selected-year-key").textContent = state.year;
  byId("other-year-key").textContent = other().year;
  byId("comparison-chart-wrap").hidden = !state.compare || state.mode === "cumulative";
  if (state.compare && state.mode !== "cumulative") byId("comparison-chart").innerHTML = lineView(true);
  byId("matched-note").textContent = `Both completed-day lines cover 01 JAN–${dateLabel(series().days[completedCutoff() - 1], false)}. The matched daily window ends at ${dateLabel(series().days[series().matchedCount - 1], false)}; current-day observations are excluded. Provisional reports remain labelled and may be revised.`;
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
  tooltip.innerHTML = `<strong>${dateLabel(row)}</strong><br>${numeric ? `${reading(row, status)} mm · ` : ""}${dayStatusLabel(row, status).toLowerCase()}`;
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
  closeWeather(false);
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

// ---------------------------------------------------------------------------
// A selected date stays fixed in its sheet, even when the chart is hovered.
// ---------------------------------------------------------------------------

function weatherRow() {
  return weatherView.index === null ? null : DATA.years[String(weatherView.year)].days[weatherView.index];
}

// Keep a slot for every hour. An absent or invalid reading never becomes zero.
function hourlySlots(row) {
  const supplied = new Map((row.hourly?.hours || []).filter(item =>
    Number.isInteger(item.hour) && item.hour >= 0 && item.hour < 24).map(item => [item.hour, item]));
  const dayStart = Date.parse(`${row.date}T00:00:00+08:00`);
  return Array.from({length: 24}, (_, hour) => {
    const item = supplied.get(hour);
    const observed = item?.status === "observed" && Number.isFinite(item.mm) && item.mm >= 0;
    const pending = !observed && dayStart + (hour + 1) * 3600000 > Date.now();
    return {hour, mm: observed ? item.mm : null, status: observed ? "observed" : pending ? "pending" : "missing",
            observationTime: observed ? item.observationTime : null};
  });
}

const hourLabel = hour => `${String(hour).padStart(2, "0")}–${String(hour + 1).padStart(2, "0")} HKT`;
const observedHours = () => weatherView.hours.filter(item => item.status === "observed").length;

// Source notes are built as text nodes, so publisher labels cannot become markup.
function renderWeatherSources(row) {
  const list = byId("weather-sources");
  list.replaceChildren();
  const rainSource = {...DATA.source, title: "Daily total rainfall",
    coverageStart: `${weatherView.year}-01-01`, coverageEnd: DATA.years[String(weatherView.year)].officialCoverageEnd || DATA.years[String(weatherView.year)].coverageEnd};
  const keys = new Set(["maxTemp", "minTemp", "humidity", "cloud"].map(key => row.weather?.[key]?.source || key).filter(key => !["recentDaily", "currentWeather", "currentRain"].includes(key)));
  const sources = [rainSource, ...Array.from(keys, key => DATA.weather?.sources?.[key]).filter(Boolean)];
  // An hourly record keeps its own link, coverage, and observation source.
  const hourlySource = DATA.weather?.sources?.[row.hourly?.source];
  if (hourlySource) sources.push(hourlySource);
  for (const key of ["recentDaily", "currentWeather", "currentRain"]) {
    const source = DATA.live?.sources?.[key];
    if (source && (key === "recentDaily" ? row.recentDaily : row.currentObservation)) {
      sources.push({...source, station: "Hong Kong Observatory", coverageStart: row.date, coverageEnd: row.date,
        snapshotUTC: DATA.live.lastSuccessAt || DATA.live.checkedAt || "",
        url: key === "recentDaily" ? LIVE_URLS.recentDaily + row.date.replaceAll("-", "") : source.url});
    }
  }
  for (const source of Array.from(new Map(sources.map(item => [`${item.title}|${item.url}`, item])).values())) {
    const item = document.createElement("li"), title = document.createElement("a");
    title.textContent = source.title || "Official weather data";
    try {
      const url = new URL(source.url);
      if (["https:", "http:"].includes(url.protocol)) {
        title.href = url.href;
        title.target = "_blank";
        title.rel = "noreferrer";
      }
    } catch { /* An unavailable source link still has a readable label. */ }
    item.append(title);
    item.append(document.createTextNode(` · ${source.station || "Station not specified"} · saved coverage ${source.coverageStart || "unknown"} to ${source.coverageEnd || "unknown"} · snapshot ${(source.snapshotUTC || "unknown").slice(0, 10)} UTC`));
    list.append(item);
  }
}

// Show the selected day's stored values without moving the paused yearly cursor.
function renderWeather() {
  const row = weatherRow();
  if (!row) return;
  byId("weather-date").textContent = dateLabel(row);
  byId("weather-day-position").textContent = `DAY ${row.index + 1} / ${DATA.years[String(weatherView.year)].days.length}`;
  byId("weather-previous").disabled = row.index === 0;
  byId("weather-next").disabled = row.index === DATA.years[String(weatherView.year)].days.length - 1;
  byId("weather-rain").textContent = reading(row, row.status);
  byId("weather-rain-unit").textContent = ["rain", "dry", "trace", "incomplete"].includes(row.status) ? "mm" : "";
  byId("weather-rain-status").textContent = `${dayStatusLabel(row, row.status).toLowerCase()} · ${DATA.source.station}`;
  byId("weather-rain-status").dataset.status = row.status;
  for (const key of ["maxTemp", "minTemp", "humidity", "cloud"]) {
    const item = row.weather?.[key], source = DATA.weather?.sources?.[item?.source || key];
    const available = Number.isFinite(item?.value) && ["complete", "incomplete", "provisional"].includes(item.status);
    byId(`weather-${key}`).textContent = available ?
      (key.endsWith("Temp") ? fmt(item.value) : item.value.toLocaleString("en-GB", {maximumFractionDigits: 1})) : "—";
    const note = byId(`weather-${key}-status`);
    note.dataset.status = available ? item.status : "missing";
    note.textContent = available ? `${item.status === "complete" ? "Complete" : item.status === "provisional" ? "Provisional daily report" : "Incomplete"}${item.flag ? ` · ${item.flag}` : ""} · ${source?.station || (item.source === "recentDaily" ? "Hong Kong Observatory" : "Station not specified")}` : "No saved observation for this date";
  }
  byId("weather-daily-note").textContent = row.status === "ongoing" ? "This day is still in progress. Completed daily rain and temperature extremes are not yet reported here. The separate observation-time panel shows actual instantaneous readings; they are not daily means or totals." : row.quality === "provisional" ? "This ended day has a provisional daily report. Its daily rainfall and temperature extremes may be revised. Mean humidity and cloud cover remain missing until genuine daily climate observations are available." : "These are dated daily observations, independently of the paused yearly playback. Missing values are not estimates. Incomplete readings are shown for inspection only.";
  renderCurrentObservation(row);
  const count = observedHours();
  // A shortcut leads to genuinely cached hourly dates in the inspected year.
  const savedDates = DATA.years[String(weatherView.year)].days.filter(day => day.hourly?.completeHours > 0);
  byId("hourly-saved-dates").hidden = savedDates.length === 0;
  const dateSelect = byId("hourly-saved-date"), prompt = document.createElement("option");
  prompt.value = "";
  prompt.textContent = "Choose a date with saved hourly readings";
  prompt.disabled = true;
  dateSelect.replaceChildren(prompt);
  for (const day of savedDates) {
    const option = document.createElement("option");
    option.value = day.index;
    option.textContent = `${dateLabel(day)} · ${day.hourly.completeHours} / 24 observed hours`;
    dateSelect.append(option);
  }
  dateSelect.value = savedDates.some(day => day.index === row.index) ? String(row.index) : "";
  byId("hourly-coverage").textContent = `${count} / 24 observed hours`;
  byId("hourly-availability").dataset.empty = String(count === 0);
  const pending = weatherView.hours.filter(item => item.status === "pending").length;
  byId("hourly-availability").textContent = count === 0 ?
    `No observed hourly readings are saved for this date. ${pending ? `${24 - pending} finished intervals have no saved record; ${pending} intervals have not finished yet.` : "All 24 intervals are missing, not zero rainfall."} ${DATA.weather?.hourlyNote || "Historical hourly readings are not reconstructed from daily totals."}` :
    `${count} of 24 intervals have observed station readings; ${24 - count - pending} are missing${pending ? ` and ${pending} have not finished` : ""}. Click a bar or use the slider to inspect an exact amount. Play hours to reveal saved observations in order.`;

  const station = row.hourly?.station;
  const hourlyTitle = DATA.weather?.sources?.[row.hourly?.source]?.title || row.hourly?.source;
  byId("hourly-source").textContent = station ? `Hourly station: ${station}. ${hourlyTitle ? `Source: ${hourlyTitle}.` : ""}` : "No hourly station record is saved for this date.";
  renderWeatherSources(row);
  renderHours();
}

// Bars share a linear millimetre scale; missing slots use a separate hatched mark.
function hourlyChart() {
  const left = 45, right = 707, top = 26, bottom = 198, step = (right - left) / 24;
  const peak = Math.max(0, ...weatherView.hours.filter(item => item.mm !== null).map(item => item.mm));
  const maximum = Math.max(1, Math.ceil(peak * 1.1));
  let drawing = '<defs><pattern id="hourly-missing-pattern" width="6" height="6" patternUnits="userSpaceOnUse"><rect width="6" height="6" fill="#f4dfce"/><path d="M-1,1 L1,-1 M0,6 L6,0 M5,7 L7,5" stroke="#cda484" stroke-width="1"/></pattern></defs>';
  drawing += `<rect x="${left + weatherView.hour * step}" y="${top}" width="${step}" height="${bottom - top + 12}" fill="#e6ede4"/>`;
  for (let tick = 0; tick <= 4; tick++) {
    const mm = maximum * tick / 4, y = bottom - tick / 4 * (bottom - top);
    drawing += `<line x1="${left}" x2="${right}" y1="${y}" y2="${y}" stroke="${COLOURS.grid}" stroke-width=".7"/><text x="${left - 8}" y="${y + 3}" text-anchor="end">${mm.toLocaleString("en-GB", {maximumFractionDigits: 2})}</text>`;
  }
  for (const item of weatherView.hours) {
    const x = left + item.hour * step, width = step - 6, shown = item.hour <= weatherView.hour;
    const label = item.status === "pending" ? "interval not finished" : item.status === "missing" ? "missing observation" : item.mm === 0 ? "0.0 millimetres, measured zero" : `${fmt(item.mm)} millimetres`;
    drawing += `<g data-hour="${item.hour}" tabindex="${item.hour === weatherView.hour ? 0 : -1}" role="button" aria-label="${hourLabel(item.hour)}: ${label}">`;
    if (item.status === "pending") drawing += `<rect x="${x + 3}" y="${bottom - 10}" width="${width}" height="10" fill="#eee2c9" stroke="#c9aa73" stroke-width=".7" stroke-dasharray="2 2"/>`; else if (item.status === "missing") drawing += `<rect x="${x + 3}" y="${bottom - 10}" width="${width}" height="10" fill="url(#hourly-missing-pattern)"/>`;
    else if (!shown) drawing += `<line x1="${x + 3}" x2="${x + step - 3}" y1="${bottom - 2}" y2="${bottom - 2}" stroke="#aebeb4" stroke-width="2" stroke-dasharray="3 2"/>`;
    else if (item.mm === 0) drawing += `<rect x="${x + 3}" y="${bottom - 2}" width="${width}" height="2" fill="#ffffff" stroke="#8da59a" stroke-width=".8"/>`;
    else {
      const height = item.mm / maximum * (bottom - top);
      drawing += `<rect x="${x + 3}" y="${bottom - height}" width="${width}" height="${height}" fill="${COLOURS.teal}"/>`;
    }
    drawing += `<rect class="hour-hit" x="${x + 1}" y="${top - 3}" width="${step - 2}" height="${bottom - top + 16}" rx="2" fill="transparent" stroke="${item.hour === weatherView.hour ? COLOURS.orange : "none"}" stroke-width="1.4"/></g>`;
    if (item.hour % 3 === 0) drawing += `<text x="${x}" y="225">${String(item.hour).padStart(2, "0")}</text>`;
  }
  drawing += `<text x="${right}" y="225" text-anchor="end">24</text><text x="${left}" y="249" class="axis-label">Hourly rain / mm · interval start–end in HKT (UTC+08:00)</text>`;
  return drawing;
}

// Every seek rebuilds the visible prefix, rather than accumulating old frames.
function renderHours() {
  const row = weatherRow();
  if (!row) return;
  const item = weatherView.hours[weatherView.hour], count = observedHours();
  byId("hourly-chart").innerHTML = hourlyChart();
  byId("hourly-chart").setAttribute("aria-label", `Hourly rainfall for ${dateLabel(row)}, ${count} of 24 hours observed. Use arrow keys to inspect adjacent hourly intervals.`);
  byId("hourly-seek").value = weatherView.hour;
  byId("hourly-seek").setAttribute("aria-valuetext", `${hourLabel(item.hour)}: ${item.status === "pending" ? "interval not finished" : item.mm === null ? "missing observation" : `${fmt(item.mm)} millimetres`}`);
  byId("hourly-play").disabled = count === 0;
  byId("hourly-speed").disabled = count === 0;
  byId("hourly-play-label").textContent = weatherView.playing ? "Pause hours" : "Play hours";
  byId("hourly-play").setAttribute("aria-label", weatherView.playing ? "Pause hourly rainfall" : "Play hourly rainfall");
  byId("hourly-play").firstElementChild.textContent = weatherView.playing ? "Ⅱ" : "▶";
  byId("hourly-interval").textContent = hourLabel(item.hour);
  byId("hourly-value").textContent = item.mm === null ? "—" : fmt(item.mm);
  byId("hourly-unit").textContent = item.mm === null ? "" : "mm";
  byId("hourly-detail").textContent = item.status === "pending" ? "This interval has not finished. No complete one-hour amount can be shown yet." : item.mm === null ? "No observed amount is saved for this interval. This gap does not mean a dry hour." :
    `${item.mm === 0 ? "The station measured zero rain." : "Observed rainfall in this one-hour interval."}${item.observationTime ? ` Observation ending ${item.observationTime}.` : ""}`;
  const shown = weatherView.hours.slice(0, weatherView.hour + 1), valid = shown.filter(hour => hour.status === "observed");
  const missing = shown.filter(hour => hour.status === "missing").length, pending = shown.filter(hour => hour.status === "pending").length;
  byId("hourly-progress").textContent = `${weatherView.hour + 1} / 24 slots shown · ${valid.length} observed · ${missing} missing · ${pending} pending. ${valid.length ? `${fmt(valid.reduce((total, hour) => total + hour.mm, 0))} mm across observed intervals only${valid.length === shown.length ? "." : "; this is not a complete period total."}` : "No hourly total can be calculated."}`;
}

// Closing, changing dates, or hiding the page always stops the hourly animation.
function pauseHourly() {
  weatherView.playing = false;
  if (hourlyAnimation !== null) cancelAnimationFrame(hourlyAnimation);
  hourlyAnimation = null;
  byId("hourly-play-label").textContent = "Play hours";
  byId("hourly-play").setAttribute("aria-label", "Play hourly rainfall");
  byId("hourly-play").firstElementChild.textContent = "▶";
}

function seekHour(value, focus = false) {
  weatherView.hour = Math.max(0, Math.min(23, Math.round(Number(value))));
  renderHours();
  if (focus) byId("hourly-chart").querySelector(`[data-hour="${weatherView.hour}"]`)?.focus({preventScroll: true});
}

function tickHourly(timestamp) {
  if (!weatherView.playing || !byId("weather-dialog").open) return;
  const interval = 1000 / (2 * weatherView.speed);
  if (timestamp - lastHourFrame >= interval) {
    const steps = Math.min(4, Math.floor((timestamp - lastHourFrame) / interval));
    lastHourFrame = timestamp;
    seekHour(weatherView.hour + steps);
    if (weatherView.hour === 23) { pauseHourly(); return; }
  }
  hourlyAnimation = requestAnimationFrame(tickHourly);
}

function playHourly() {
  if (!byId("weather-dialog").open || observedHours() === 0) return;
  if (weatherView.playing) { pauseHourly(); return; }
  if (weatherView.hour === 23) seekHour(0);
  weatherView.playing = true;
  lastHourFrame = performance.now();
  renderHours();
  hourlyAnimation = requestAnimationFrame(tickHourly);
}

function openWeather(index) {
  pause();
  pauseHourly();
  selectDay(index);
  weatherView.year = state.year;
  weatherView.index = state.selected;
  weatherView.hour = 23;
  weatherView.returnFocus = true;
  weatherView.hours = hourlySlots(weatherRow());
  byId("tooltip").hidden = true;
  renderWeather();
  if (!byId("weather-dialog").open) byId("weather-dialog").showModal();
  document.body.classList.add("weather-open");
}

function changeWeatherDay(direction) {
  const row = weatherRow();
  if (!row) return;
  pauseHourly();
  weatherView.index = Math.max(0, Math.min(DATA.years[String(weatherView.year)].days.length - 1, row.index + direction));
  weatherView.hour = 23;
  weatherView.hours = hourlySlots(weatherRow());
  selectDay(weatherView.index);
  renderWeather();
}

function closeWeather(restoreFocus = true) {
  pauseHourly();
  weatherView.returnFocus = restoreFocus;
  if (byId("weather-dialog").open) byId("weather-dialog").close();
}

// The native dialog traps focus and handles Escape; restore the redrawn date mark.
function connectWeatherControls() {
  byId("open-weather").addEventListener("click", () => openWeather(state.selected));
  byId("weather-close").addEventListener("click", () => closeWeather());
  byId("weather-dialog").addEventListener("close", () => {
    pauseHourly();
    document.body.classList.remove("weather-open");
    weatherView.index = null;
    weatherView.hours = [];
    if (weatherView.returnFocus) byId("chart").querySelector(`[data-index="${state.selected}"]`)?.focus({preventScroll: true});
  });
  byId("weather-previous").addEventListener("click", () => changeWeatherDay(-1));
  byId("weather-next").addEventListener("click", () => changeWeatherDay(1));
  byId("hourly-saved-date").addEventListener("change", event => {
    if (event.target.value !== "") changeWeatherDay(Number(event.target.value) - weatherView.index);
  });
  byId("hourly-play").addEventListener("click", playHourly);
  byId("hourly-seek").addEventListener("input", event => { pauseHourly(); seekHour(event.target.value); });
  byId("hourly-speed").addEventListener("change", event => { weatherView.speed = Number(event.target.value); });
  byId("hourly-chart").addEventListener("click", event => {
    const mark = event.target.closest("[data-hour]");
    if (mark) { pauseHourly(); seekHour(Number(mark.dataset.hour), true); }
  });
  byId("hourly-chart").addEventListener("keydown", event => {
    const mark = event.target.closest("[data-hour]");
    if (!mark) return;
    const direction = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -1, ArrowDown: 1};
    if (Object.hasOwn(direction, event.key) || ["Home", "End", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      pauseHourly();
      const index = Number(mark.dataset.hour);
      seekHour(event.key === "Home" ? 0 : event.key === "End" ? 23 : index + (direction[event.key] || 0), true);
    }
  });
}

// ---------------------------------------------------------------------------
// Official live requests update this page in memory; the embedded cache is kept.
// ---------------------------------------------------------------------------

const LIVE_URLS = {
  recentDaily: "https://data.weather.gov.hk/weatherAPI/opendata/opendata.php?dataType=RYES&lang=en&date=",
  currentWeather: "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=en",
  currentRain: "https://data.weather.gov.hk/weatherAPI/opendata/hourlyRainfall.php?lang=en",
};
const liveState = {enabled: DATA.live?.enabled === true, refreshing: false, status: "saved",
                   lastAttempt: DATA.live?.checkedAt || "", lastSuccess: DATA.live?.lastSuccessAt || "",
                   errors: [...(DATA.live?.errors || [])]};
const liveRequests = new Set();
let liveTimer = null;

// Calendar dates always use Hong Kong time, regardless of the reader's time zone.
function hongKongDate(value = new Date()) {
  const parts = new Intl.DateTimeFormat("en-GB", {timeZone: "Asia/Hong_Kong", year: "numeric", month: "2-digit", day: "2-digit"}).formatToParts(value);
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function observedTime(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return "Time not reported";
  return `${new Intl.DateTimeFormat("en-GB", {timeZone: "Asia/Hong_Kong", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23"}).format(new Date(value))} HKT`;
}

function shiftDate(value, days) {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function checkedTimestamp(value) {
  const match = typeof value === "string" && value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})$/);
  const calendar = match && new Date(`${match[1]}T00:00:00Z`);
  if (!match || !Number.isFinite(calendar.getTime()) || calendar.toISOString().slice(0, 10) !== match[1] || Number(match[2]) > 23 || Number(match[3]) > 59 || Number(match[4] || 0) > 59) throw new Error("Invalid observation date or clock time");
  if (typeof value !== "string" || !/(Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) throw new Error("Missing observation time zone");
  if (Date.parse(value) > Date.now() + 5 * 60000) throw new Error("Observation time is in the future");
  return value;
}

function observedNumber(value, minimum, maximum) {
  if (!["string", "number"].includes(typeof value) || String(value).trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= minimum && number <= maximum ? number : null;
}

// The daily report is a provisional ended-day record, never a forecast or average.
function parseRecentReport(body, date) {
  if (!body || String(body.ReportTimeInfoDate) !== date.replaceAll("-", "")) throw new Error("The daily report date does not match the request");
  const rawRain = body.HKOReadingsRainfall;
  const trace = typeof rawRain === "string" && rawRain.trim().toLowerCase() === "trace";
  const mm = trace ? 0 : observedNumber(rawRain, 0, 5000);
  if (mm === null) throw new Error("No daily rainfall observation in this report");
  const publicationDate = String(body.BulletinDate || ""), publicationClock = String(body.BulletinTime || "");
  const publicationTime = /^\d{8}$/.test(publicationDate) && /^\d{4}$/.test(publicationClock) ?
    `${publicationDate.slice(0, 4)}-${publicationDate.slice(4, 6)}-${publicationDate.slice(6, 8)}T${publicationClock.slice(0, 2)}:${publicationClock.slice(2)}:00+08:00` : null;
  if (!publicationTime || !Number.isFinite(Date.parse(publicationTime)) || Number(publicationClock.slice(0, 2)) > 23 || Number(publicationClock.slice(2)) > 59 ||
      hongKongDate(new Date(publicationTime)) !== `${publicationDate.slice(0, 4)}-${publicationDate.slice(4, 6)}-${publicationDate.slice(6, 8)}` ||
      Date.parse(publicationTime) < Date.parse(`${shiftDate(date, 1)}T00:00:00+08:00`) || Date.parse(publicationTime) > Date.now() + 5 * 60000) throw new Error("Invalid daily report publication time");
  const minHumidity = observedNumber(body.HKOReadingsMinRH, 0, 100), maxHumidity = observedNumber(body.HKOReadingsMaxRH, 0, 100);
  if (minHumidity !== null && maxHumidity !== null && minHumidity > maxHumidity) throw new Error("Invalid daily humidity extremes");
  const high = observedNumber(body.HKOReadingsMaxTemp, -90, 60), low = observedNumber(body.HKOReadingsMinTemp, -90, 60);
  if (high !== null && low !== null && low > high) throw new Error("Invalid daily temperature extremes");
  return {mm, trace, maxTemp: high, minTemp: low,
          minHumidity, maxHumidity,
          annualRain: observedNumber(body.HKOReadingsAccumRainfall, 0, 50000),
          status: "provisional", source: "recentDaily", publicationTime};
}

function parseCurrentWeather(body) {
  const read = (group, unit, minimum, maximum) => {
    if (!group) return null;
    if (!Array.isArray(group.data)) throw new Error("Invalid station weather array");
    const matches = group.data.filter(item => item?.place === "Hong Kong Observatory");
    if (matches.length > 1) throw new Error("Duplicate Observatory weather readings");
    const record = matches[0];
    if (!record || record.unit !== unit) return null;
    const value = observedNumber(record.value, minimum, maximum);
    return value === null ? null : {value, observationTime: checkedTimestamp(group.recordTime)};
  };
  const temperature = read(body?.temperature, "C", -90, 60), humidity = read(body?.humidity, "percent", 0, 100);
  if (!temperature && !humidity) throw new Error("No Observatory weather readings in this response");
  return {temperature, humidity};
}

function parseCurrentRain(body) {
  if (!Array.isArray(body?.hourlyRainfall)) throw new Error("Invalid hourly station array");
  const matches = body.hourlyRainfall.filter(item => item?.automaticWeatherStationID === "RF023");
  if (matches.length !== 1 || body.hourlyRainfall.filter(item => item?.automaticWeatherStation === "Hong Kong Observatory").length > 1) throw new Error("Ambiguous Observatory hourly station");
  const station = matches[0];
  if (station.automaticWeatherStation !== "Hong Kong Observatory" || station.unit !== "mm") throw new Error("No matching Observatory hourly station");
  const value = station.value === "M" ? null : observedNumber(station.value, 0, 5000);
  if (value === null && station.value !== "M") throw new Error("Invalid hourly rainfall reading");
  const observationTime = checkedTimestamp(body.obsTime);
  return {value, observationTime, intervalStart: new Date(Date.parse(observationTime) - 3600000).toISOString(),
          intervalEnd: observationTime, station: "Hong Kong Observatory", stationID: "RF023"};
}

// Fixed public GET requests need no credentials or custom preflight headers.
async function requestLiveJSON(url) {
  const controller = new AbortController();
  liveRequests.add(controller);
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(url, {method: "GET", mode: "cors", credentials: "omit", cache: "no-store", signal: controller.signal});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timeout);
    liveRequests.delete(controller);
  }
}

// A partial failure preserves prior readings; older responses cannot replace newer ones.
function mergeCurrentReadings(previous, readings) {
  const merged = {...(previous || {})};
  for (const [key, item] of Object.entries(readings)) {
    if (item && (!merged[key] || Date.parse(item.observationTime) >= Date.parse(merged[key].observationTime))) merged[key] = item;
  }
  const times = [merged.temperature, merged.humidity, merged.rainfall].filter(Boolean).map(item => Date.parse(item.observationTime));
  if (!times.length) return previous || null;
  merged.date = hongKongDate(new Date(Math.max(...times)));
  // A newer date has its own readings; a previous day's humidity is not a new-day mean.
  for (const key of ["temperature", "humidity", "rainfall"]) {
    if (merged[key] && hongKongDate(new Date(merged[key].observationTime)) !== merged.date) merged[key] = null;
  }
  return merged;
}

// Only a validated whole-hour RF023 observation may fill a non-overlapping slot.
function keepWholeHourReading(current) {
  const rain = current?.rainfall;
  if (!rain || rain.stationID !== "RF023" || rain.station !== "Hong Kong Observatory") return;
  const end = new Date(rain.observationTime);
  if (end.getUTCMinutes() !== 0 || end.getUTCSeconds() !== 0 || end.getUTCMilliseconds() !== 0) return;
  const start = new Date(end.getTime() - 3600000), date = hongKongDate(start);
  const year = DATA.years[date.slice(0, 4)], row = year?.days.find(day => day.date === date);
  if (!row || row.hourly && row.hourly.source !== "currentRain") return;
  if (!row.hourly) row.hourly = {hours: Array.from({length: 24}, (_, hour) => ({hour, mm: null, status: "missing", observationTime: null})), completeHours: 0, station: rain.station, source: "currentRain"};
  const hour = Number(new Intl.DateTimeFormat("en-GB", {timeZone: "Asia/Hong_Kong", hour: "2-digit", hourCycle: "h23"}).format(start));
  row.hourly.hours[hour] = {hour, mm: Number.isFinite(rain.value) ? rain.value : null, status: Number.isFinite(rain.value) ? "observed" : "missing", observationTime: rain.observationTime};
  row.hourly.completeHours = row.hourly.hours.filter(item => item.status === "observed").length;
}

// Rebuild one compact prefix per year when actual published records change.
function rebuildLiveCalendar() {
  const today = hongKongDate(), live = DATA.live || {};
  for (const item of Object.values(DATA.years)) {
    const oldCoverage = item.coverageEnd;
    for (const row of item.days) {
      row.weather ||= {};
      const recent = live.daily?.[row.date];
      const verified = row.quality === "verified" || row.flag === "C";
      if (recent && row.date < today && !verified) {
        row.recentDaily = recent;
        row.mm = recent.mm;
        row.trace = recent.trace;
        row.flag = "";
        row.status = recent.trace ? "trace" : recent.mm === 0 ? "dry" : "rain";
        row.quality = "provisional";
        for (const key of ["maxTemp", "minTemp"]) {
          if (Number.isFinite(recent[key]) && (!Number.isFinite(row.weather[key]?.value) || row.weather[key]?.source === "recentDaily")) row.weather[key] = {value: recent[key], status: "provisional", flag: "", source: "recentDaily"};
        }
      } else if (row.status === "ongoing" && row.date !== today) {
        row.mm = null;
        row.trace = false;
        row.flag = "";
        row.status = "unpublished";
        row.quality = "missing";
      }
      if (row.date === today) {
        row.status = "ongoing";
        row.quality = "ongoing";
        row.mm = null;
        row.trace = false;
        row.flag = "";
      }
      if (live.current?.date === row.date) row.currentObservation = live.current;
    }
    const published = item.days.filter(row => row.date < today && (row.date <= oldCoverage || ["rain", "dry", "trace", "incomplete"].includes(row.status)));
    const end = published.at(-1);
    item.observedCount = end ? end.index + 1 : 0;
    item.coverageEnd = end?.date || "";
    const ongoing = item.days.find(row => row.date === today);
    item.displayCount = Math.max(item.observedCount, ongoing ? ongoing.index + 1 : 0);
    item.displayCoverageEnd = item.days[Math.max(0, item.displayCount - 1)]?.date || "";
    let total = 0, complete = 0, verified = 0, provisional = 0, rainy = 0, traces = 0, missing = 0, peakIndex = null, gap = false;
    for (const row of item.days) {
      const completeDay = row.index < item.observedCount && ["rain", "dry", "trace"].includes(row.status) && Number.isFinite(row.mm);
      if (completeDay) {
        total += row.mm;
        complete++;
        if (row.quality === "provisional") provisional++; else verified++;
        rainy += row.mm >= DATA.rainyThreshold;
        traces += row.trace ? 1 : 0;
        if (peakIndex === null || row.mm > item.days[peakIndex].mm || row.mm === item.days[peakIndex].mm && row.trace && !item.days[peakIndex].trace) peakIndex = row.index;
      } else if (row.index < item.observedCount) { missing++; gap = true; }
      row.cumulative = completeDay && !gap ? Math.round(total * 10000) / 10000 : null;
      row.stats = {total: Math.round(total * 10000) / 10000, complete, verified, provisional, rainy, traces, missing, peakIndex};
    }
  }
  const years = Object.values(DATA.years), completedEnd = years.map(item => item.coverageEnd.slice(5)).sort()[0], displayEnd = years.map(item => item.displayCoverageEnd.slice(5)).sort()[0];
  for (const item of years) {
    const paired = years.find(year => year.year !== item.year), pairs = new Map(paired.days.map(day => [day.date.slice(5), day.index]));
    item.matchedCount = (item.days.find(day => day.date.slice(5) === completedEnd)?.index ?? item.days.find(day => day.date.slice(5) === "02-28")?.index ?? 0) + 1;
    item.matchedDisplayCount = (item.days.find(day => day.date.slice(5) === displayEnd)?.index ?? item.matchedCount - 1) + 1;
    for (const row of item.days) row.counterpart = pairs.get(row.date.slice(5)) ?? null;
  }
  const peak = Math.max(0, ...years.flatMap(item => item.days.filter(row => ["rain", "dry", "trace"].includes(row.status)).map(row => row.mm)));
  DATA.scaleMax = Math.max(50, Math.ceil(peak / 50) * 50);
  byId("scale-max").textContent = DATA.scaleMax;
  byId("scale-quarter").textContent = DATA.scaleMax / 4;
}

function renderCurrentObservation(row) {
  const current = row.currentObservation || (DATA.live?.current?.date === row.date ? DATA.live.current : null);
  byId("weather-current").hidden = !current;
  if (!current) return;
  byId("weather-current-heading").textContent = row.date === hongKongDate() ? "Current weather" : "Dated weather observation";
  const readings = [current.temperature, current.humidity, current.rainfall].filter(Boolean);
  const latest = readings.length ? readings.reduce((first, item) => Date.parse(item.observationTime) > Date.parse(first.observationTime) ? item : first) : null;
  byId("weather-current-time").textContent = latest ? observedTime(latest.observationTime) : "No current station reading";
  for (const key of ["temperature", "humidity", "rainfall"]) {
    const item = current[key];
    byId(`current-${key}`).textContent = Number.isFinite(item?.value) ? (key === "humidity" ? String(item.value) : fmt(item.value)) : "—";
    byId(`current-${key}-time`).textContent = !item ? "No saved station observation" : key === "rainfall" ? `${observedTime(item.intervalStart)} to ${observedTime(item.intervalEnd)}` : observedTime(item.observationTime);
  }
}

function renderLiveStatus() {
  byId("live-refresh").disabled = !liveState.enabled || liveState.refreshing;
  byId("live-offline").checked = !liveState.enabled;
  byId("live-indicator").dataset.state = !liveState.enabled ? "offline" : liveState.status;
  const labels = {saved: "Showing saved observations · automatic checks every 15 minutes", refreshing: "Checking official weather sources…", success: "Official observations updated · automatic checks every 15 minutes", checked: "Official sources checked · observations unchanged", partial: "Some sources refreshed · unavailable sources retain their last observations", failed: "Refresh unavailable · the last saved observations are retained"};
  byId("live-status").textContent = liveState.enabled ? labels[liveState.status] || labels.saved : "Offline snapshot · automatic weather requests are disabled";
  const current = DATA.live?.current, readings = [current?.temperature, current?.humidity, current?.rainfall].filter(Boolean);
  const latest = readings.length ? readings.reduce((first, item) => Date.parse(item.observationTime) > Date.parse(first.observationTime) ? item : first) : null;
  const stale = latest && Date.now() - Date.parse(latest.observationTime) > 45 * 60000;
  byId("live-observation-time").textContent = `${latest ? `Latest observation ${observedTime(latest.observationTime)}${stale ? " · more than 45 minutes old" : ""}` : "No dated current observation is available"}${liveState.lastAttempt ? ` · last source check ${observedTime(liveState.lastAttempt)}` : ""}. Current observations do not enter completed-day rain totals.${liveState.errors.length ? " Some sources could not be reached; missing observations are not filled in." : ""}`;
}

function scheduleLiveRefresh() {
  if (liveTimer !== null) clearTimeout(liveTimer);
  liveTimer = null;
  if (liveState.enabled) liveTimer = setTimeout(() => { if (document.hidden) scheduleLiveRefresh(); else refreshLive(); }, 15 * 60000);
}

// Recent reports are fetched one at a time; the two current feeds are independent.
async function refreshLive() {
  if (!liveState.enabled || liveState.refreshing) return;
  liveState.refreshing = true;
  liveState.status = "refreshing";
  liveState.lastAttempt = new Date().toISOString();
  liveState.errors = [];
  renderLiveStatus();
  const today = hongKongDate(), oldLimit = limit(), wasAtEnd = state.cutoff === oldLimit;
  const before = JSON.stringify({daily: DATA.live?.daily || {}, current: DATA.live?.current || null});
  const daily = {...(DATA.live?.daily || {})}, readings = {};
  let successes = 0;
  const currentResults = Promise.allSettled([
    requestLiveJSON(LIVE_URLS.currentWeather).then(parseCurrentWeather),
    requestLiveJSON(LIVE_URLS.currentRain).then(parseCurrentRain),
  ]);
  try {
    // Fill uncached dates after the archived climate coverage, then recheck recent reports.
    const requested = new Set();
    for (const item of Object.values(DATA.years)) {
      const coverage = item.officialCoverageEnd || item.coverageEnd;
      for (const row of item.days) {
        if (row.date > coverage && row.date < today && row.quality !== "verified" && row.flag !== "C" && !Number.isFinite(daily[row.date]?.mm)) requested.add(row.date);
      }
    }
    for (let offset = 7; offset >= 1; offset--) {
      const date = shiftDate(today, -offset), row = DATA.years[date.slice(0, 4)]?.days.find(day => day.date === date);
      if (row && row.quality !== "verified" && row.flag !== "C") requested.add(date);
    }
    for (const date of Array.from(requested).sort()) {
      if (!liveState.enabled) break;

      try {
        daily[date] = parseRecentReport(await requestLiveJSON(LIVE_URLS.recentDaily + date.replaceAll("-", "")), date);
        successes++;
      } catch (problem) {
        liveState.errors.push(`The provisional daily report for ${date} could not be refreshed.`);
        if (problem.name === "AbortError" || problem instanceof TypeError) break;
      }
    }
    const results = await currentResults;
    if (!liveState.enabled) return;
    if (results[0].status === "fulfilled") { Object.assign(readings, results[0].value); successes++; }
    else liveState.errors.push("Current temperature and humidity could not be refreshed.");
    if (results[1].status === "fulfilled") { readings.rainfall = results[1].value; successes++; }
    else liveState.errors.push("The rolling one-hour rainfall could not be refreshed.");
    DATA.live ||= {sources: {}, timezone: "Asia/Hong_Kong", refreshMinutes: 15};
    DATA.live.daily = daily;
    DATA.live.current = mergeCurrentReadings(DATA.live.current, readings);
    DATA.live.checkedAt = liveState.lastAttempt;
    DATA.live.errors = [...liveState.errors];
    if (successes) DATA.live.lastSuccessAt = liveState.lastSuccess = new Date().toISOString();
    keepWholeHourReading(DATA.live.current);
    rebuildLiveCalendar();
    if (wasAtEnd && !state.playing) state.cutoff = limit(); else state.cutoff = Math.min(state.cutoff, limit());
    if (!state.pinned) state.selected = state.cutoff - 1;
    const changed = before !== JSON.stringify({daily: DATA.live.daily, current: DATA.live.current});
    liveState.status = !successes ? "failed" : liveState.errors.length ? "partial" : changed ? "success" : "checked";
    render();
    if (byId("weather-dialog").open) { pauseHourly(); weatherView.hours = hourlySlots(weatherRow()); renderWeather(); }
  } catch {
    liveState.status = "failed";
    liveState.errors.push("The response could not be safely applied; the previous observations remain available.");
  } finally {
    liveState.refreshing = false;
    renderLiveStatus();
    scheduleLiveRefresh();
  }
}

function connectLiveControls() {
  byId("live-refresh").addEventListener("click", refreshLive);
  byId("live-offline").addEventListener("change", event => {
    liveState.enabled = !event.target.checked;
    if (DATA.live) DATA.live.enabled = liveState.enabled;
    if (!liveState.enabled) { for (const request of liveRequests) request.abort(); scheduleLiveRefresh(); renderLiveStatus(); }
    else refreshLive();
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && liveState.enabled && Date.now() - Date.parse(liveState.lastAttempt || 0) >= 15 * 60000) refreshLive();
  });
  renderLiveStatus();
  if (liveState.enabled && (!liveState.lastSuccess || Date.now() - Date.parse(liveState.lastSuccess) > 15 * 60000)) refreshLive();
  else scheduleLiveRefresh();
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
    if (mark) state.mode === "calendar" ? openWeather(Number(mark.dataset.index)) : selectDay(Number(mark.dataset.index));
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
    else if (event.key === "Enter" || event.key === " ") { event.preventDefault(); state.mode === "calendar" ? openWeather(index) : selectDay(index, true); }
    else if (event.key === "Home") { event.preventDefault(); selectDay(0, true); }
    else if (event.key === "End") { event.preventDefault(); selectDay(inspectionLimit() - 1, true); }
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) { pause(); pauseHourly(); } });
}

// Fill source and scale notes from the snapshot, then draw the initial published window.
function initialise() {
  if (DATA.live && (Object.keys(DATA.live.daily || {}).length || DATA.live.current)) rebuildLiveCalendar();
  state.cutoff = limit();
  state.selected = state.cutoff - 1;
  byId("year").value = state.year;
  byId("scale-max").textContent = DATA.scaleMax;
  byId("scale-quarter").textContent = DATA.scaleMax / 4;
  byId("source-link").href = DATA.source.url;
  byId("snapshot-note").textContent = `Verified climate snapshot saved ${DATA.source.snapshotUTC.slice(0, 10)} UTC · ${DATA.source.excludedRows} invalid historical date placeholder excluded · verified SHA-256 ${DATA.source.sha256.slice(0, 12)}…`;
  connectControls();
  connectWeatherControls();
  connectLiveControls();
  render();
}

initialise();

// A small read-only inspection hook makes automated checks independent of presentation.
window.rainfallExplorer = Object.freeze({
  getState: () => ({...state, limit: limit()}),
  getLiveState: () => ({...liveState, errors: [...liveState.errors], currentDate: hongKongDate()}),
  refreshLive,
  getWeatherState: () => ({open: byId("weather-dialog").open, year: weatherView.year,
    index: weatherView.index, date: weatherRow()?.date || null, hour: weatherView.hour,
    playing: weatherView.playing, speed: weatherView.speed, observedHours: observedHours()}),
});
