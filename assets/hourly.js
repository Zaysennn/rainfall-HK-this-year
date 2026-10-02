"use strict";

// ---------------------------------------------------------------------------
// One hourly client is shared by the station viewer and the water preview.
// Requests stay on the local Python server; portable pages use saved data only.
// ---------------------------------------------------------------------------

window.HourlyData = (() => {
  let data = {};
  let offline = false;
  const requests = new Map();
  const controllers = new Set();
  const queryStates = new Map();
  const VALID_MODES = ["model", "observed"];
  const FRESH_MS = 5 * 60000;

  const service = () => data.hourlyService || {};
  const keyFor = (date, mode) => `${mode}:${date}`;
  const fieldFor = mode => mode === "model" ? "hourlyModel" : "hourly";
  const countHours = (day, mode) => (day?.hours || []).filter(hour =>
    hour.status === (mode === "model" ? "estimated" : "observed") &&
    Number.isFinite(hour.mm) && hour.mm >= 0).length;

  function validDate(date) {
    return typeof date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(date) &&
      Number.isFinite(Date.parse(`${date}T00:00:00Z`)) &&
      new Date(`${date}T00:00:00Z`).toISOString().slice(0, 10) === date;
  }

  function hongKongDate() {
    return new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10);
  }

  function configure(snapshot) {
    data = snapshot;
    queryStates.clear();
    return api;
  }

  // A static host must never accidentally call a nonexistent local API.
  function canRequest(row = null) {
    const location = window.location;
    const local = location && ["http:", "https:"].includes(location.protocol) &&
      ["localhost", "127.0.0.1", "[::1]", "::1"].includes(location.hostname);
    if (!local || offline || service().enabled !== true || service().path !== "/api/hourly") return false;
    return !row || validDate(row.date) && row.date <= hongKongDate() &&
      (service().supportedYears || []).includes(Number(row.date.slice(0, 4)));
  }

  function snapshot(row, mode) {
    const day = row[fieldFor(mode)] || null;
    const key = keyFor(row.date, mode);
    const saved = queryStates.get(key) || service().queries?.[key];
    return {date: row.date, mode, day, query: saved || {
      status: countHours(day, mode) ? "cached" : "unqueried",
      message: "", checkedAt: null, completeHours: countHours(day, mode),
    }};
  }

  // Even a model forecast is withheld until its full hourly interval has ended.
  function slots(row, mode) {
    const day = row[fieldFor(mode)];
    const supplied = new Map((day?.hours || []).filter(hour =>
      Number.isInteger(hour.hour) && hour.hour >= 0 && hour.hour < 24).map(hour => [hour.hour, hour]));
    const start = Date.parse(`${row.date}T00:00:00+08:00`);
    const expected = mode === "model" ? "estimated" : "observed";
    return Array.from({length: 24}, (_, hour) => {
      const item = supplied.get(hour), end = start + (hour + 1) * 3600000;
      const pending = end > Date.now();
      const sourceMatches = mode === "model" ? day?.kind === "model" :
        day?.kind !== "model" && day?.source !== "ecmwf_ifs";
      const usable = !pending && sourceMatches &&
        item?.status === expected && Number.isFinite(item.mm) && item.mm >= 0;
      return {hour, mm: usable ? item.mm : null,
              status: usable ? expected : pending ? "pending" : "missing",
              observationTime: usable ? item.observationTime || null : null};
    });
  }

  function needsRequest(row, mode, force = false) {
    if (!VALID_MODES.includes(mode) || !canRequest(row)) return false;
    if (force) return true;
    const saved = snapshot(row, mode);
    if (slots(row, mode).filter(hour => hour.mm !== null).length === 24) return false;
    const checked = Date.parse(saved.query.checkedAt || "");
    return !Number.isFinite(checked) || Date.now() - checked >= FRESH_MS;
  }

  // Check the response contract before it can replace any embedded hourly data.
  function validateDay(day, date, mode) {
    if (day === null) return null;
    if (!day || !Array.isArray(day.hours) || day.hours.length !== 24) throw new Error("Invalid 24-hour response");
    if (mode === "model") {
      if (day.kind !== "model" || day.source !== "ecmwf_ifs" || day.model !== "ECMWF IFS" ||
          !Number.isFinite(day.grid?.latitude) || Math.abs(day.grid.latitude) > 90 ||
          !Number.isFinite(day.grid?.longitude) || Math.abs(day.grid.longitude) > 180) {
        throw new Error("Invalid ECMWF model source");
      }
    } else if (day.kind === "model" || day.source === "ecmwf_ifs" ||
               day.station !== "Hong Kong Observatory" ||
               day.stationID != null && day.stationID !== "RF023") {
      throw new Error("Invalid hourly station or source type");
    }
    const expected = mode === "model" ? "estimated" : "observed";
    const first = Date.parse(`${date}T00:00:00+08:00`), seen = new Set();
    const hours = day.hours.map(hour => {
      if (!Number.isInteger(hour.hour) || hour.hour < 0 || hour.hour > 23 || seen.has(hour.hour)) {
        throw new Error("Invalid or repeated hourly slot");
      }
      seen.add(hour.hour);
      if (hour.status === "missing") {
        if (hour.mm !== null) throw new Error("A missing interval cannot contain a rainfall amount");
        return {...hour, mm: null};
      }
      if (hour.status !== expected || !Number.isFinite(hour.mm) || hour.mm < 0 ||
          typeof hour.observationTime !== "string" ||
          !/(?:Z|[+-]\d{2}:\d{2})$/.test(hour.observationTime) ||
          Date.parse(hour.observationTime) !== first + (hour.hour + 1) * 3600000) {
        throw new Error("Invalid rainfall value or hourly interval");
      }
      return {...hour};
    }).sort((a, b) => a.hour - b.hour);
    return {...day, hours, completeHours: hours.filter(hour => hour.status === expected).length};
  }

  // Station slots can fill one another's gaps; conflicting readings stay untouched.
  // Model responses are kept as whole snapshots, never assembled from different runs.
  function mergeHourlyDay(previous, incoming, date, mode) {
    if (!previous) return incoming;
    if (mode === "model") {
      return countHours(previous, mode) > countHours(incoming, mode) ? previous : incoming;
    }
    if (previous.station !== incoming.station || previous.kind === "model" ||
        previous.source === "ecmwf_ifs") return incoming;
    const saved = validateDay(previous, date, mode);
    const hours = incoming.hours.map(hour => {
      const old = saved.hours[hour.hour];
      if (hour.status === "observed" && old.status === "observed" &&
          Date.parse(hour.observationTime) === Date.parse(old.observationTime) &&
          hour.mm !== old.mm) {
        throw new Error("Conflicting station rainfall for the same hourly interval");
      }
      return hour.status === "missing" && old.status === "observed" ? old : hour;
    });
    return {...incoming, hours, completeHours: hours.filter(hour => hour.status === "observed").length};
  }

  async function load(row, mode, options = {}) {
    if (!validDate(row.date) || !VALID_MODES.includes(mode)) throw new Error("Invalid hourly request");
    const key = keyFor(row.date, mode);
    if (requests.has(key)) return requests.get(key);
    if (!needsRequest(row, mode, options.force === true)) return snapshot(row, mode);
    const operation = (async () => {
      const controller = new AbortController();
      controllers.add(controller);
      const timeout = setTimeout(() => controller.abort(), 45000);
      try {
        const url = new URL(service().path, window.location.href);
        url.searchParams.set("date", row.date);
        url.searchParams.set("mode", mode);
        if (options.force === true) url.searchParams.set("force", "1");
        const response = await fetch(url.href, {method: "GET", credentials: "same-origin",
          cache: "no-store", signal: controller.signal});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        if (body?.date !== row.date || body.mode !== mode ||
            !["cached", "partial", "unavailable", "failed", "unqueried"].includes(body.query?.status)) {
          throw new Error("The response does not match this date and mode");
        }
        const day = validateDay(body.day, row.date, mode);
        if (day) row[fieldFor(mode)] = mergeHourlyDay(row[fieldFor(mode)], day, row.date, mode);
        const query = {status: body.query.status,
          message: typeof body.query.message === "string" ? body.query.message : "",
          checkedAt: body.query.checkedAt || new Date().toISOString(),
          completeHours: countHours(row[fieldFor(mode)], mode)};
        queryStates.set(key, query);
        return snapshot(row, mode);
      } catch (error) {
        queryStates.set(key, {status: "failed", checkedAt: new Date().toISOString(),
          completeHours: countHours(row[fieldFor(mode)], mode),
          message: error.name === "AbortError" ? "The request stopped or timed out. Saved readings remain available." :
            "This date could not be loaded safely. Saved readings remain available; try again."});
        return snapshot(row, mode);
      } finally {
        clearTimeout(timeout);
        controllers.delete(controller);
      }
    })();
    requests.set(key, operation);
    try { return await operation; }
    finally { requests.delete(key); }
  }

  function setOffline(enabled) {
    offline = Boolean(enabled);
    if (offline) for (const controller of controllers) controller.abort();
  }

  const api = Object.freeze({configure, canRequest, snapshot, slots, needsRequest, load, setOffline});
  return api;
})();