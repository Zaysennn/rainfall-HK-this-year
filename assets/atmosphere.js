// Daily observations shape this harbour scene; its light and wet glass are artwork.
(function (global) {
  "use strict";

  const COMPLETE = new Set(["dry", "rain", "trace"]);
  const QUALITY = new Set(["verified", "provisional"]);
  const PROFILES = {
    neutral: {density: 0, rain: 0, label: "neutral light"},
    dry: {density: 0, rain: 0, label: "golden daylight"},
    trace: {density: .08, rain: 2, label: "a little mist"},
    light: {density: .15, rain: 12, label: "a passing shower"},
    moderate: {density: .5, rain: 120, label: "mist and wet glass"},
    heavy: {density: .9, rain: 300, label: "a blue city rainstorm"},
    storm: {density: .9, rain: 420, label: "a blue city rainstorm"}
  };
  const FRAME_INTERVAL = 1000 / 30;
  const MAX_CANVAS_PIXELS = 4000000;

  // Only an ended, usable daily record can supply the scene's rainfall band.
  function validDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const [year, month, day] = value.split("-").map(Number);
    if (year < 1 || month < 1 || month > 12 || day < 1) return false;
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    return day <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
  }

  function hongKongToday() {
    return new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10);
  }

  function classify(row, status, today) {
    if (!row || !validDate(row.date) || !validDate(today) || row.date >= today ||
        !COMPLETE.has(status) || !COMPLETE.has(row.status) ||
        !QUALITY.has(row.quality == null ? "verified" : row.quality) ||
        !Number.isFinite(row.mm) || row.mm < 0) return "neutral";
    if (row.status === "trace" || status === "trace") return "trace";
    if (row.mm === 0) return "dry";
    if (row.mm < 10) return "light";
    if (row.mm < 50) return "moderate";
    if (row.mm < 100) return "heavy";
    return "storm";
  }

  function attach({root, control = null, note = null, images = {}}) {
    if (!root || !root.ownerDocument) throw new Error("The harbour scene needs a document root.");
    const doc = root.ownerDocument;
    const media = typeof global.matchMedia === "function" ?
      global.matchMedia("(prefers-reduced-motion: reduce)") : null;
    const rainCanvas = doc.getElementById("atmosphere-rain");
    const glassCanvas = doc.getElementById("atmosphere-glass");
    const cache = doc.createElement("canvas");
    function context(canvas) {
      try { return canvas && typeof canvas.getContext === "function" ? canvas.getContext("2d") : null; }
      catch (_) { return null; }
    }
    const rainContext = context(rainCanvas);
    const glassContext = context(glassCanvas);
    const cacheContext = context(cache);
    const sceneCanvas = doc.createElement("canvas"), sceneContext = context(sceneCanvas);
    const photoCanvas = doc.createElement("canvas"), photoContext = context(photoCanvas);
    const nightPhoto = root.querySelector('[data-harbour="night"]');
    const harbour = doc.getElementById("atmosphere-harbour");
    const rainStamps = [];
    const imageReady = {sun: false, mist: false, night: false, glass: false};
    const imageFailed = {sun: false, mist: false, night: false, glass: false};
    const imageListeners = [];
    const controlTitle = control && typeof control.title === "string" ? control.title : "";
    let reduced = !!(media && media.matches);
    let hidden = !!doc.hidden || doc.visibilityState === "hidden";
    let requestedMotion = !reduced;
    let manuallyChosen = false;
    let destroyed = false;
    let profile = "neutral", date = null, mm = null, status = "missing", provisional = false;
    let width = 1, height = 1, dpr = 1, maxDrops = 80, plannedDrops = 0, rainCount = 0;
    let raf = null, lastFrame = null, motionTime = 0;
    let lightningTimer = null, lightningOffTimer = null, lightning = false, bolt = "left";
    let cacheDirty = true, dirtyGlass = [];
    let lastNote = "", frameCount = 0, totalDrawMs = 0, maxDrawMs = 0;
    const atlas = typeof global.Image === "function" ? new global.Image() : doc.createElement("img");
    let sceneDirty = true, sceneCacheReady = false, sceneScale = 1;
    let sceneTop = 66, sceneHeight = 1, sceneSampleFilter = "none", sceneBuilds = 0;
    let sceneBuildMs = 0, glassCacheBuildMs = 0, glassCacheBuilds = 0;
    let microCount = 0, lensCount = 0, largeCount = 0, runnerCount = 0, microCapacity = 0;
    let nightLastTime = 0, runnerSideWidth = 0, runnerTravelPx = 0;
    let nightMinRainSpeed = 0, nightMaxRainSpeed = 0, nightMinRainLength = 0, nightMaxRainLength = 0;

    // Fixed positions keep adjacent dates from making the wet window jump or restart.
    const drops = Array.from({length: 80}, (_, index) => ({
      x: (index * .61803398875 + .09) % 1,
      y: (index * .41421356237 + .07) % 1,
      scale: .62 + (index * 7 % 13) / 24,
      speed: 4 + index % 5 * 1.4,
      tile: index * 7 % 16,
      moving: index % 6 === 0
    }));
    const rain = Array.from({length: 420}, (_, index) => ({
      x: (index * .61803398875 + .03) % 1,
      y: (index * .73205080757 + .11) % 1,
      near: index % 3 === 0,
      speed: 250 + index % 11 * 24,
      length: 14 + index % 14 * 2
    }));

    // A repeatable random field has clusters and gaps without jumping between dates.
    let wetSeed = 0x5eeda117;
    function wetRandom() {
      wetSeed = (Math.imul(wetSeed, 1664525) + 1013904223) >>> 0;
      return wetSeed / 4294967296;
    }
    function wetDrop(kind) {
      const small = kind === "micro", large = kind === "large";
      return {x: wetRandom(), y: wetRandom(),
        radius: small ? .65 + Math.pow(wetRandom(), 1.7) * 1.55 :
          large ? 7 + wetRandom() * 4 : 2.6 + wetRandom() * 3.2,
        aspect: .78 + wetRandom() * .48, skew: (wetRandom() - .5) * .68,
        lens: 1.6 + wetRandom() * 1.1, opacity: .57 + wetRandom() * .23,
        phase: wetRandom() * 10, cycle: 5 + wetRandom() * 5,
        speed: 3 + wetRandom() * 9, offset: 0, small};
    }
    const microDrops = Array.from({length: 2700}, () => wetDrop("micro"));
    const lensDrops = Array.from({length: 50}, () => wetDrop("lens"));
    const largeDrops = Array.from({length: 3}, () => wetDrop("large"));
    // A few larger beads carry the motion while most of the wet texture stays still.
    function makeRunner(index) {
      const drop = wetDrop("lens"), size = (drop.radius - 2.6) / 3.2;
      drop.radius = index % 7 === 0 ? 7 + size * 2 : 4 + size * 3;
      drop.speed = 14 + (drop.speed - 3) / 9 * 19;
      drop.cycle = 3.5 + (drop.cycle - 5) / 5 * 2.5;
      drop.band = index % 4;
      drop.track = index % 3 !== 1;
      return drop;
    }
    const runners = Array.from({length: 26}, (_, index) => makeRunner(index));
    function makeDistantRain() {
      return {x: wetRandom(), y: wetRandom(), speed: 220 + wetRandom() * 200,
        length: 16 + wetRandom() * 22, slant: -.1 - wetRandom() * .16,
        alpha: .62 + wetRandom() * .32, stamp: wetRandom() < .35 ? 1 : 0};
    }
    const distantRain = Array.from({length: 220}, makeDistantRain);
    // Keep the established window pattern, then add the denser downpour around it.
    while (microDrops.length < 4500) microDrops.push(wetDrop("micro"));
    while (lensDrops.length < 100) lensDrops.push(wetDrop("lens"));
    while (runners.length < 44) runners.push(makeRunner(runners.length));
    while (distantRain.length < 1000) distantRain.push(makeDistantRain());
    for (const drop of distantRain) {
      const speed = (drop.speed - 220) / 200, length = (drop.length - 16) / 22;
      // Near rain has a longer exposure streak; the farther layer stays finer.
      drop.speed = drop.stamp ? 780 + speed * 270 : 540 + speed * 240;
      drop.length = drop.stamp ? 42 + length * 28 : 24 + length * 20;
    }

    function wetWindow() { return profile === "heavy" || profile === "storm"; }

    function motionAllowed() {
      return requestedMotion && !reduced && !hidden && !destroyed;
    }

    function nightAllowed() {
      return (profile === "heavy" || profile === "storm") && motionAllowed();
    }

    function now() {
      return global.performance && typeof global.performance.now === "function" ?
        global.performance.now() : Date.now();
    }

    function clearCanvas(canvas, ctx) {
      if (ctx && canvas) ctx.clearRect(0, 0, canvas.width / dpr, canvas.height / dpr);
    }

    // Limit both resolution and work; even a large desktop uses a bounded pixel budget.
    function resizeCanvases() {
      const rect = typeof root.getBoundingClientRect === "function" ? root.getBoundingClientRect() : {};
      const nextWidth = Math.max(1, Math.round(rect.width || global.innerWidth || 1));
      const nextHeight = Math.max(1, Math.round(rect.height || global.innerHeight || 1));
      const nextDpr = Math.min(1.5, Math.max(1, Number(global.devicePixelRatio) || 1),
        Math.sqrt(MAX_CANVAS_PIXELS / (nextWidth * nextHeight)));
      if (width === nextWidth && height === nextHeight && dpr === nextDpr && !cacheDirty) return false;
      width = nextWidth;
      height = nextHeight;
      dpr = nextDpr;
      maxDrops = width <= 800 ? 36 : 80;
      for (const [canvas, ctx] of [[rainCanvas, rainContext], [glassCanvas, glassContext], [cache, cacheContext]]) {
        if (!canvas || !ctx) continue;
        canvas.width = Math.max(1, Math.floor(width * dpr));
        canvas.height = Math.max(1, Math.floor(height * dpr));
        if (canvas.style) {
          canvas.style.width = width + "px";
          canvas.style.height = height + "px";
        }
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = "high";
      }
      cacheDirty = true;
      sceneDirty = true;
      sceneCacheReady = false;
      dirtyGlass = [];
      return true;
    }

    function planScene() {
      const nextDrops = Math.round(PROFILES[profile].density * maxDrops);
      if (nextDrops !== plannedDrops) cacheDirty = true;
      plannedDrops = nextDrops;
      const area = Math.min(1, Math.max(.35, width * height / 1049088));
      if (wetWindow()) {
        const mobile = width <= 800;
        microCapacity = Math.round((mobile ? 960 : 3520) * Math.max(mobile ? .8 : .95,
          Math.min(1.2, width * height / (mobile ? 329160 : 1440000))));
        microCount = Math.round(microCapacity * PROFILES[profile].density);
        lensCount = Math.round((mobile ? 40 : 100) * PROFILES[profile].density);
        largeCount = mobile ? 2 : 3;
        runnerCount = Math.round((mobile ? 20 : 42) * PROFILES[profile].density);
        rainCount = Math.round((profile === "storm" ? 1000 : 650) * area);
        // These ranges are inspected only when planning, never in the frame loop.
        nightMinRainSpeed = nightMinRainLength = Infinity;
        nightMaxRainSpeed = nightMaxRainLength = 0;
        for (let i = 0; i < rainCount; i++) {
          nightMinRainSpeed = Math.min(nightMinRainSpeed, distantRain[i].speed);
          nightMaxRainSpeed = Math.max(nightMaxRainSpeed, distantRain[i].speed);
          nightMinRainLength = Math.min(nightMinRainLength, distantRain[i].length);
          nightMaxRainLength = Math.max(nightMaxRainLength, distantRain[i].length);
        }
      } else {
        microCount = lensCount = largeCount = runnerCount = 0;
        nightMinRainSpeed = nightMaxRainSpeed = nightMinRainLength = nightMaxRainLength = 0;
        rainCount = Math.round(PROFILES[profile].rain * area);
      }
    }

    // Each drop is cropped from one photographic 4 by 4 atlas, never a drawn bubble.
    function drawDrop(ctx, drop, moving) {
      const cellWidth = (atlas.naturalWidth || atlas.width) / 4;
      const cellHeight = (atlas.naturalHeight || atlas.height) / 4;
      const baseSize = maxDrops === 36 ? 28 : 42;
      const size = baseSize * drop.scale;
      const stretched = moving ? 1.22 : 1;
      const drawHeight = size * cellHeight / cellWidth * stretched;
      const x = drop.x * Math.max(0, width - size);
      const travel = height + drawHeight;
      const y = moving ?
        ((drop.y * travel + motionTime * drop.speed) % travel) - drawHeight :
        drop.y * Math.max(0, height - drawHeight);
      ctx.globalAlpha = .78 + (drop.tile % 4) * .06;
      ctx.drawImage(atlas, (drop.tile % 4) * cellWidth, Math.floor(drop.tile / 4) * cellHeight,
        cellWidth, cellHeight, x, y, size, drawHeight);
      return {x: Math.max(0, x - 2), y: Math.max(0, y - 2),
        width: Math.min(width, x + size + 2) - Math.max(0, x - 2),
        height: Math.min(height, y + drawHeight + 2) - Math.max(0, y - 2)};
    }

    // The photograph is sampled once at page coordinates, including its soft edges.
    // This small buffer never includes UI and never reads full-screen pixels back.
    function rebuildScene() {
      if (!sceneDirty) return sceneCacheReady;
      sceneCacheReady = false;
      if (!sceneContext || !photoContext || !nightPhoto || !imageReady.night) return false;
      const started = now();
      const bounds = typeof harbour?.getBoundingClientRect === "function" ? harbour.getBoundingClientRect() : {};
      const rootBounds = typeof root.getBoundingClientRect === "function" ? root.getBoundingClientRect() : {};
      sceneTop = Number.isFinite(bounds.top) ? bounds.top - (rootBounds.top || 0) :
        width <= 580 ? 152 : width <= 800 ? 108 : 66;
      sceneHeight = bounds.height > 0 ? bounds.height : width / 3;
      sceneScale = Math.min(1, 900 / width, 600 / height);
      sceneCanvas.width = Math.max(1, Math.ceil(width * sceneScale));
      sceneCanvas.height = Math.max(1, Math.ceil(height * sceneScale));
      sceneContext.setTransform(sceneScale, 0, 0, sceneScale, 0, 0);
      sceneContext.fillStyle = profile === "storm" ? "#102c46" : "#193650";
      sceneContext.fillRect(0, 0, width, height);
      let filter = "blur(" + Math.max(1.6, Math.min(5, width * .0028)) + "px)";
      let opacity = profile === "storm" ? .96 : .9;
      if (typeof global.getComputedStyle === "function") {
        const style = global.getComputedStyle(nightPhoto);
        if (style && typeof style.filter === "string" && style.filter !== "none") filter = style.filter;
        // The profile's target opacity is stable even during the CSS crossfade.
        const rootStyle = global.getComputedStyle(root);
        const target = rootStyle && typeof rootStyle.getPropertyValue === "function" ?
          parseFloat(rootStyle.getPropertyValue("--night-opacity")) : NaN;
        if (Number.isFinite(target)) opacity = target;
      }
      sceneSampleFilter = filter;
      photoCanvas.width = sceneCanvas.width;
      photoCanvas.height = Math.max(1, Math.ceil(sceneHeight * sceneScale));
      photoContext.setTransform(1, 0, 0, 1, 0, 0);
      // Filtering is done only while building the tiny photograph cache.
      photoContext.filter = filter.replace(/([\d.]+)px/g, (_, value) => Number(value) * sceneScale + "px");
      photoContext.drawImage(nightPhoto, 0, 0, photoCanvas.width, photoCanvas.height);
      photoContext.filter = "none";
      const mask = photoContext.createLinearGradient(0, 0, 0, photoCanvas.height);
      mask.addColorStop(0, "rgba(0,0,0,0)");
      mask.addColorStop(.08, "#000"); mask.addColorStop(.83, "#000");
      mask.addColorStop(1, "rgba(0,0,0,0)");
      photoContext.globalCompositeOperation = "destination-in";
      photoContext.fillStyle = mask;
      photoContext.fillRect(0, 0, photoCanvas.width, photoCanvas.height);
      photoContext.globalCompositeOperation = "source-over";
      sceneContext.globalAlpha = opacity;
      sceneContext.drawImage(photoCanvas, 0, sceneTop, width, sceneHeight);
      sceneContext.globalAlpha = 1;
      sceneDirty = false; sceneCacheReady = true; sceneBuilds++;
      sceneBuildMs = Math.round(Math.max(0, now() - started) * 100) / 100;
      return true;
    }

    function lensPath(ctx, x, y, rx, ry, skew) {
      ctx.beginPath();
      ctx.moveTo(x + rx * skew, y - ry);
      ctx.bezierCurveTo(x + rx * (.55 + skew), y - ry * .91,
        x + rx * (.97 - skew * .35), y - ry * .3, x + rx, y + ry * (.12 + skew));
      ctx.bezierCurveTo(x + rx * (.92 - skew), y + ry * .88,
        x + rx * (.35 + skew), y + ry * 1.04, x - rx * (.12 - skew), y + ry);
      ctx.bezierCurveTo(x - rx * .86, y + ry * (.8 + skew),
        x - rx * 1.02, y + ry * .3, x - rx, y - ry * (.06 + skew * .4));
      ctx.bezierCurveTo(x - rx * (.91 + skew * .18), y - ry * .57,
        x - rx * (.46 - skew), y - ry * .99, x + rx * skew, y - ry);
      ctx.closePath();
    }

    // A bead is a small lens onto this part of the harbour, not a silver sprite.
    function drawLens(ctx, drop, moving = false) {
      const rx = drop.radius * (width <= 800 ? .85 : 1);
      const ry = rx * drop.aspect * (moving ? 1.38 : 1);
      let x = rx + drop.x * Math.max(0, width - rx * 2);
      if (moving) {
        // Side margins and the photographed upper page keep some movement in view.
        if (runnerSideWidth >= 24 && drop.band < 2) {
          x = rx + drop.x * Math.max(0, runnerSideWidth - rx * 2);
          if (drop.band === 1) x = width - x;
        }
        x += Math.sin(motionTime * .3 + drop.phase) * .45;
      }
      const travel = height + ry * 2;
      const start = sceneTop + sceneHeight * .08 + drop.y * Math.min(sceneHeight * .72, height * .25);
      let y = moving ? (start + drop.offset) % travel - ry : ry + drop.y * Math.max(0, height - ry * 2);
      const trail = moving && drop.track ? 22 + rx * 4 + (drop.phase % 1) * 8 : 0;
      let fade = 1;
      if (moving && (drop.band >= 2 || (width <= 800 && drop.band !== 0))) {
        // The photographed area keeps receiving beads after the first few seconds.
        // Slightly different fade boundaries make their return quiet and irregular.
        const bandTop = Math.max(0, sceneTop + sceneHeight * (.04 + drop.x * .04));
        const bandHeight = Math.max(30, Math.min(sceneHeight * (.7 + drop.skew * .1), height * .33));
        const bandTravel = bandHeight + ry * 2 + trail;
        const position = (drop.y * bandTravel + drop.offset) % bandTravel;
        y = bandTop - ry + position;
        fade = Math.max(0, Math.min(1, position / (ry * 2 + 1),
          (bandTravel - position) / (trail + ry * 2 + 1)));
      }
      const box = {x: Math.max(0, x - rx - 2), y: Math.max(0, y - ry - trail - 2),
        width: Math.max(0, Math.min(width, x + rx + 2) - Math.max(0, x - rx - 2)),
        height: Math.max(0, Math.min(height, y + ry + 2) - Math.max(0, y - ry - trail - 2))};
      if (y + ry < 0 || y - ry > height) return box;
      if (moving) { ctx.save(); ctx.globalAlpha = fade; }
      if (trail > 0) {
        const film = ctx.createLinearGradient(0, y - ry - trail, 0, y);
        film.addColorStop(0, "rgba(96,140,167,0)"); film.addColorStop(1, "rgba(112,158,180,.11)");
        ctx.strokeStyle = film; ctx.lineWidth = .55 + rx * .05;
        ctx.beginPath(); ctx.moveTo(x - .25, y - ry - trail);
        ctx.bezierCurveTo(x + .5, y - ry - trail * .66, x - .4, y - ry - trail * .3, x, y);
        ctx.stroke();
      }
      // The curved bead gathers nearby light as well as the point directly behind it.
      const sw = Math.min(sceneCanvas.width, Math.max(1, rx * 2 * drop.lens * sceneScale));
      const sh = Math.min(sceneCanvas.height, Math.max(1, ry * 2 * drop.lens * sceneScale));
      const sx = Math.max(0, Math.min(sceneCanvas.width - sw,
        (x + rx * drop.skew * 1.8) * sceneScale - sw / 2));
      const sy = Math.max(0, Math.min(sceneCanvas.height - sh,
        (y - ry * .18) * sceneScale - sh / 2));
      ctx.save(); lensPath(ctx, x, y, rx, ry, drop.skew); ctx.clip();
      ctx.translate(x, y); ctx.scale(1, -1);
      ctx.globalAlpha = drop.opacity * fade;
      ctx.drawImage(sceneCanvas, sx, sy, sw, sh, -rx, -ry, rx * 2, ry * 2);
      ctx.restore();
      // Partial edge shadows leave an irregular wet boundary, rather than a dark ring.
      ctx.strokeStyle = drop.small ? "rgba(3,12,22,.26)" : "rgba(3,12,22,.3)";
      ctx.lineWidth = drop.small ? .34 : .5;
      ctx.beginPath(); ctx.moveTo(x + rx * .96, y - ry * .02);
      ctx.bezierCurveTo(x + rx * (.91 - drop.skew), y + ry * .7,
        x + rx * .35, y + ry * 1.02, x - rx * .17, y + ry * .95);
      ctx.stroke();
      // A short, sharp glint picks up warm city light or the cooler surrounding sky.
      const cityBand = (y - sceneTop) / sceneHeight;
      ctx.strokeStyle = cityBand > .45 && cityBand < .78 ?
        "rgba(233,198,141,.42)" : "rgba(157,198,218,.38)";
      ctx.lineWidth = drop.small ? .34 + rx * .11 : .58 + rx * .016;
      ctx.beginPath(); ctx.moveTo(x - rx * .7, y - ry * .16);
      ctx.bezierCurveTo(x - rx * .67, y - ry * .64, x - rx * (.28 - drop.skew * .3),
        y - ry * .88, x + rx * (.1 + drop.skew * .25), y - ry * .86);
      ctx.stroke();
      if (moving) ctx.restore();
      return box;
    }

    function rebuildNightGlass() {
      if (!cacheContext || !rebuildScene() || !cacheDirty) return;
      const started = now();
      // Read the page geometry once, never while animating each bead.
      runnerSideWidth = 0;
      const page = typeof doc.querySelector === "function" ? doc.querySelector(".page") : null;
      if (width > 800 && page && typeof page.getBoundingClientRect === "function") {
        const bounds = page.getBoundingClientRect();
        const rootBounds = typeof root.getBoundingClientRect === "function" ? root.getBoundingClientRect() : {};
        const style = typeof global.getComputedStyle === "function" ? global.getComputedStyle(page) : null;
        const leftPadding = parseFloat(style && style.paddingLeft) || 0;
        const rightPadding = parseFloat(style && style.paddingRight) || 0;
        const left = bounds.left - (rootBounds.left || 0) + leftPadding;
        const right = width - (bounds.right - (rootBounds.left || 0) - rightPadding);
        runnerSideWidth = Math.max(0, Math.min(width * .18, left - 8, right - 8));
      }
      clearCanvas(cache, cacheContext);
      for (let i = 0; i < microCount; i++) drawLens(cacheContext, microDrops[i]);
      for (let i = 0; i < lensCount; i++) drawLens(cacheContext, lensDrops[i]);
      for (let i = 0; i < largeCount; i++) drawLens(cacheContext, largeDrops[i]);
      cacheContext.globalAlpha = 1;
      cacheDirty = false;
      glassCacheBuilds++;
      glassCacheBuildMs = Math.round(Math.max(0, now() - started) * 100) / 100;
    }

    function paintNightGlass(full) {
      if (!glassContext || !cacheContext) return;
      if (sceneDirty || cacheDirty) { rebuildNightGlass(); full = true; }
      if (!sceneCacheReady) { clearCanvas(glassCanvas, glassContext); dirtyGlass = []; return; }
      glassContext.globalAlpha = 1;
      if (full) {
        clearCanvas(glassCanvas, glassContext);
        glassContext.drawImage(cache, 0, 0, width, height);
      } else {
        for (const box of dirtyGlass) {
          if (box.width <= 0 || box.height <= 0) continue;
          glassContext.clearRect(box.x, box.y, box.width, box.height);
          glassContext.drawImage(cache, box.x * dpr, box.y * dpr, box.width * dpr, box.height * dpr,
            box.x, box.y, box.width, box.height);
        }
      }
      const elapsed = motionAllowed() ? Math.max(0, Math.min(.12, motionTime - nightLastTime)) : 0;
      nightLastTime = motionTime;
      dirtyGlass = [];
      for (let i = 0; i < runnerCount; i++) {
        const drop = runners[i];
        // Surface tension slows each bead briefly; a gentle drift is always visible.
        const phase = (motionTime + drop.phase) % drop.cycle / drop.cycle;
        const flow = phase < .12 ? .18 : .18 + .82 * Math.pow((phase - .12) / .88, .9);
        const distance = elapsed * drop.speed * flow;
        drop.offset += distance;
        runnerTravelPx += distance;
        dirtyGlass.push(drawLens(glassContext, drop, true));
      }
      glassContext.globalAlpha = 1;
    }

    // Soft distant rain is baked into two tiny stamps; no screen-sized blur per frame.
    function buildRainStamps() {
      if (rainStamps.length) return true;
      for (let i = 0; i < 2; i++) {
        const stamp = doc.createElement("canvas"), ctx = context(stamp);
        if (!ctx) { rainStamps.length = 0; return false; }
        stamp.width = 10; stamp.height = 36;
        const gradient = ctx.createLinearGradient(0, 2, 0, 34);
        gradient.addColorStop(0, "rgba(150,184,207,0)");
        gradient.addColorStop(.35, i ? "rgba(157,190,211,.32)" : "rgba(144,179,205,.26)");
        gradient.addColorStop(1, "rgba(150,184,207,0)");
        ctx.strokeStyle = gradient; ctx.lineWidth = i ? 2.1 : 1.6;
        ctx.filter = i ? "blur(.9px)" : "blur(.55px)";
        ctx.beginPath(); ctx.moveTo(7, 4); ctx.lineTo(3, 32); ctx.stroke();
        ctx.filter = "none";
        rainStamps.push(stamp);
      }
      return true;
    }

    function paintNightRain() {
      if (!buildRainStamps()) return;
      for (let i = 0; i < rainCount; i++) {
        const drop = distantRain[i];
        const y = (drop.y * (height + drop.length) + motionTime * drop.speed) % (height + drop.length) - drop.length;
        const x = (drop.x * width + y * drop.slant + width) % width;
        rainContext.globalAlpha = drop.alpha;
        // Preserve enough of the baked stroke's width to see its continuous fall.
        rainContext.drawImage(rainStamps[drop.stamp], x, y, drop.stamp ? 9 : 7, drop.length);
      }
      rainContext.globalAlpha = 1;
    }

    function rebuildGlassCache() {
      if (!cacheContext || !imageReady.glass || !cacheDirty) return;
      clearCanvas(cache, cacheContext);
      for (let index = 0; index < plannedDrops; index++) {
        if (!drops[index].moving) drawDrop(cacheContext, drops[index], false);
      }
      cacheContext.globalAlpha = 1;
      cacheDirty = false;
    }

    // Most glass stays cached. Moving drops restore only their previous small rectangles.
    function paintGlass(full = false) {
      if (wetWindow()) { paintNightGlass(full); return; }
      if (!glassContext || !cacheContext) return;
      if (!imageReady.glass) {
        clearCanvas(glassCanvas, glassContext);
        dirtyGlass = [];
        return;
      }
      if (cacheDirty) { rebuildGlassCache(); full = true; }
      glassContext.globalAlpha = 1;
      if (full) {
        clearCanvas(glassCanvas, glassContext);
        glassContext.drawImage(cache, 0, 0, width, height);
      } else {
        for (const box of dirtyGlass) {
          if (box.width <= 0 || box.height <= 0) continue;
          glassContext.clearRect(box.x, box.y, box.width, box.height);
          glassContext.drawImage(cache, box.x * dpr, box.y * dpr, box.width * dpr, box.height * dpr,
            box.x, box.y, box.width, box.height);
        }
      }
      dirtyGlass = [];
      for (let index = 0; index < plannedDrops; index++) {
        if (drops[index].moving) dirtyGlass.push(drawDrop(glassContext, drops[index], true));
      }
      glassContext.globalAlpha = 1;
    }

    // Two depths of thin rain share two strokes, rather than hundreds of DOM animations.
    function paintRain() {
      if (!rainContext) return;
      clearCanvas(rainCanvas, rainContext);
      if (!motionAllowed() || rainCount === 0) return;
      if (wetWindow()) { paintNightRain(); return; }
      const night = profile === "heavy" || profile === "storm";
      const speed = profile === "storm" ? 1.35 : profile === "heavy" ? 1.15 : .8;
      const slant = profile === "storm" ? -.3 : profile === "heavy" ? -.24 : -.18;
      for (const near of [false, true]) {
        rainContext.beginPath();
        for (let index = 0; index < rainCount; index++) {
          const drop = rain[index];
          if (drop.near !== near) continue;
          const length = drop.length * (near ? 1 : .48);
          const y = (drop.y * (height + length) + motionTime * drop.speed * speed) % (height + length) - length;
          const x = (drop.x * width + y * slant + width) % width;
          rainContext.moveTo(x, y);
          rainContext.lineTo(x + length * slant, y + length);
        }
        rainContext.strokeStyle = night ? (near ? "#cee8fbcc" : "#a4c8eab3") :
          (near ? "#476978c0" : "#d2e0eab3");
        rainContext.lineWidth = near ? 1.1 : .7;
        rainContext.stroke();
      }
    }

    function movingCount() {
      if (wetWindow()) return sceneCacheReady && glassContext && cacheContext ? runnerCount : 0;
      if (!imageReady.glass || !glassContext || !cacheContext) return 0;
      let count = 0;
      for (let index = 0; index < plannedDrops; index++) if (drops[index].moving) count++;
      return count;
    }

    function hasCanvasMotion() {
      return !!((rainContext && rainCount > 0) || movingCount() > 0);
    }

    function stopFrames() {
      if (raf !== null && typeof global.cancelAnimationFrame === "function") global.cancelAnimationFrame(raf);
      raf = null;
      lastFrame = null;
    }

    // A single frame loop runs at most 30 times a second and stops in hidden tabs.
    function scheduleFrame() {
      if (raf !== null || !motionAllowed() || !hasCanvasMotion() ||
          typeof global.requestAnimationFrame !== "function") return;
      raf = global.requestAnimationFrame(frame);
    }

    function frame(timestamp) {
      raf = null;
      if (!motionAllowed() || !hasCanvasMotion()) return;
      if (lastFrame !== null && timestamp - lastFrame < FRAME_INTERVAL - .1) {
        scheduleFrame();
        return;
      }
      const elapsed = lastFrame === null ? FRAME_INTERVAL : Math.min(120, Math.max(0, timestamp - lastFrame));
      lastFrame = timestamp;
      motionTime += elapsed / 1000;
      const started = now();
      paintRain();
      paintGlass();
      const cost = Math.max(0, now() - started);
      totalDrawMs += cost;
      maxDrawMs = Math.max(maxDrawMs, cost);
      frameCount++;
      scheduleFrame();
    }

    // Violet light stays in the harbour's sky; the page never becomes a white flash.
    function stopLightning() {
      if (lightningTimer !== null) global.clearTimeout(lightningTimer);
      if (lightningOffTimer !== null) global.clearTimeout(lightningOffTimer);
      lightningTimer = null;
      lightningOffTimer = null;
      lightning = false;
      root.dataset.lightning = "off";
    }

    function scheduleLightning(delay = 2000) {
      if (!nightAllowed() || lightningTimer !== null || lightningOffTimer !== null) return;
      lightningTimer = global.setTimeout(function () {
        lightningTimer = null;
        if (!nightAllowed()) return;
        bolt = bolt === "left" ? "right" : "left";
        lightning = true;
        root.dataset.bolt = bolt;
        root.dataset.lightning = "on";
        lightningOffTimer = global.setTimeout(function () {
          lightningOffTimer = null;
          lightning = false;
          root.dataset.lightning = "off";
          scheduleLightning(4100 + Math.random() * 3000);
        }, 900);
      }, delay);
    }

    function syncMotion() {
      root.dataset.motion = motionAllowed() ? "on" : "off";
      if (control) {
        control.checked = requestedMotion && !reduced;
        control.disabled = reduced;
        control.title = reduced ?
          "Your system's reduced-motion setting keeps the harbour still." : controlTitle;
      }
      if (motionAllowed()) scheduleFrame();
      else { stopFrames(); clearCanvas(rainCanvas, rainContext); }
      if (nightAllowed()) scheduleLightning();
      else stopLightning();
    }

    function caption() {
      let reading;
      if (profile === "neutral") {
        reading = status === "ongoing" ? "day still in progress" :
          status === "unrevealed" || status === "unpublished" ? "daily reading not shown" :
          "no completed daily reading";
      } else {
        reading = profile === "trace" ? "<0.05 mm (trace)" : String(mm) + " mm";
        if (provisional) reading += " (provisional)";
      }
      let text = (date ? date + " · " : "") + reading + " · Rain-inspired " + PROFILES[profile].label + ".";
      if (PROFILES[profile].density > 0) {
        text += " " + Math.round(PROFILES[profile].density * 100) + "% artistic wet-window density.";
        const texture = wetWindow() ? "night" : "glass";
        if (imageFailed[texture]) text += " Water texture unavailable.";
        else if (!imageReady[texture]) text += " Loading the water texture.";
      }
      if (note && text !== lastNote) { note.textContent = text; lastNote = text; }
    }

    // An observation can change a caption without rebuilding the scene or resetting time.
    function updateDay(row, options = {}) {
      if (destroyed) return;
      const nextStatus = options.status == null ? (row && row.status) || "missing" : options.status;
      const nextProfile = classify(row, nextStatus, options.today || hongKongToday());
      const changed = nextProfile !== profile;
      date = row && validDate(row.date) ? row.date : null;
      status = nextStatus;
      mm = nextProfile === "neutral" ? null : row.mm;
      provisional = !!(row && row.quality === "provisional");
      if (changed) {
        if (wetWindow() || nextProfile === "heavy" || nextProfile === "storm") {
          sceneDirty = true; cacheDirty = true; nightLastTime = motionTime;
        }
        profile = nextProfile;
        root.dataset.atmosphere = profile;
        if (doc.body) doc.body.dataset.atmosphere = profile;
        planScene();
        paintGlass(true);
        paintRain();
        syncMotion();
      }
      caption();
    }

    function motionChanged() {
      if (!reduced) {
        manuallyChosen = true;
        requestedMotion = !!control.checked;
      }
      syncMotion();
    }

    function visibilityChanged() {
      hidden = !!doc.hidden || doc.visibilityState === "hidden";
      syncMotion();
    }

    function preferenceChanged() {
      reduced = !!media.matches;
      if (!manuallyChosen) requestedMotion = !reduced;
      syncMotion();
    }

    function resized() {
      if (destroyed) return;
      if (resizeCanvases()) {
        planScene();
        paintGlass(true);
        paintRain();
        syncMotion();
      }
    }

    // Decode one atlas for all sprites. A failed texture stays absent, with a clear note.
    function atlasLoaded() {
      if (destroyed || imageReady.glass) return;
      const w = atlas.naturalWidth || atlas.width, h = atlas.naturalHeight || atlas.height;
      if (!(w >= 4 && h >= 4)) { atlasFailed(); return; }
      imageReady.glass = true;
      imageFailed.glass = false;
      cacheDirty = true;
      paintGlass(true);
      syncMotion();
      caption();
    }

    function atlasFailed() {
      if (destroyed || imageReady.glass) return;
      imageFailed.glass = true;
      caption();
    }

    for (const key of ["sun", "mist", "night"]) {
      const image = root.querySelector('[data-harbour="' + key + '"]');
      if (!image || typeof images[key] !== "string" || !images[key]) { imageFailed[key] = true; continue; }
      const loaded = function () {
        if (destroyed) return;
        imageReady[key] = !!image.naturalWidth;
        imageFailed[key] = !imageReady[key];
        if (key === "night") {
          sceneDirty = true; cacheDirty = true;
          if (wetWindow()) { paintGlass(true); syncMotion(); caption(); }
        }
      };
      const failed = function () {
        if (!destroyed) {
          imageReady[key] = false; imageFailed[key] = true;
          if (key === "night") {
            sceneCacheReady = false; sceneDirty = true;
            if (wetWindow()) { paintGlass(true); syncMotion(); caption(); }
          }
        }
      };
      image.addEventListener("load", loaded);
      image.addEventListener("error", failed);
      imageListeners.push({image, loaded, failed});
      image.src = images[key];
      if (image.complete) loaded();
    }

    root.dataset.atmosphere = "neutral";
    root.dataset.motion = "off";
    root.dataset.lightning = "off";
    root.dataset.bolt = bolt;
    if (doc.body) doc.body.dataset.atmosphere = "neutral";
    resizeCanvases();
    planScene();
    if (control) control.addEventListener("change", motionChanged);
    doc.addEventListener("visibilitychange", visibilityChanged);
    if (typeof global.addEventListener === "function") global.addEventListener("resize", resized);
    if (media) {
      if (typeof media.addEventListener === "function") media.addEventListener("change", preferenceChanged);
      else if (typeof media.addListener === "function") media.addListener(preferenceChanged);
    }
    atlas.onload = atlasLoaded;
    atlas.onerror = atlasFailed;
    if (typeof images.glass === "string" && images.glass) {
      atlas.src = images.glass;
      if (typeof atlas.decode === "function") atlas.decode().then(atlasLoaded, atlasFailed);
      else if (atlas.complete) atlasLoaded();
    } else atlasFailed();
    syncMotion();
    updateDay(null);

    // Copies expose useful checks without exposing the renderer or any daily data object.
    function getState() {
      const available = !destroyed && (wetWindow() ? sceneCacheReady : imageReady.glass) && !!glassContext && !!cacheContext;
      const nightPlanned = microCount + lensCount + largeCount + runnerCount;
      return {
        profile, date, mm, status, density: PROFILES[profile].density,
        maxDrops: wetWindow() ? microCapacity + (width <= 800 ? 40 + 2 + 20 : 100 + 3 + 42) : maxDrops,
        plannedDrops: wetWindow() ? nightPlanned : plannedDrops,
        dropCount: available ? (wetWindow() ? nightPlanned : plannedDrops) : 0,
        glassRenderer: wetWindow() ? "scene-refraction" : "photographic-atlas",
        staticMicroDrops: available && wetWindow() ? microCount : 0,
        staticLensDrops: available && wetWindow() ? lensCount + largeCount : 0,
        nightMovingDrops: available && wetWindow() ? runnerCount : 0,
        sceneCacheReady: !destroyed && sceneCacheReady,
        sceneCacheWidth: sceneCanvas.width, sceneCacheHeight: sceneCanvas.height,
        sceneTop, sceneHeight, sceneSampleFilter, sceneBuilds,
        sceneBuildMs, glassCacheBuildMs, glassCacheBuilds,
        runnerSideWidth, runnerTravelPx: Math.round(runnerTravelPx * 10) / 10,
        runnerSamples: wetWindow() ? runners.slice(0, Math.min(5, runnerCount)).map(drop => ({
          offset: Math.round(drop.offset * 10) / 10, radius: Math.round(drop.radius * 10) / 10,
          speed: Math.round(drop.speed * 10) / 10})) : [],
        rainRenderer: wetWindow() ? "soft-distant-rain" : "original-strokes",
        rainSpeedRange: {min: Math.round(nightMinRainSpeed), max: Math.round(nightMaxRainSpeed)},
        rainLengthRange: {min: Math.round(nightMinRainLength), max: Math.round(nightMaxRainLength)},
        rainSamples: wetWindow() ? distantRain.slice(0, Math.min(5, rainCount)).map(drop => ({
          speed: Math.round(drop.speed), length: Math.round(drop.length), depth: drop.stamp ? "near" : "far"})) : [],
        movingDrops: motionAllowed() ? movingCount() : 0,
        rainCount, motion: motionAllowed(), requestedMotion, reduced, hidden, destroyed,
        lightning, bolt, timers: {lightning: lightningTimer !== null, lightningOff: lightningOffTimer !== null},
        rafPending: raf !== null, imageReady: {...imageReady}, imageFailed: {...imageFailed},
        assetLoading: wetWindow() ? !imageReady.night && !imageFailed.night : !imageReady.glass && !imageFailed.glass,
        canvasReady: {rain: !!rainContext, glass: !!glassContext && !!cacheContext},
        fpsLimit: 30, dpr, width, height, maxCanvasPixels: MAX_CANVAS_PIXELS, frameCount,
        averageDrawMs: frameCount ? Math.round(totalDrawMs / frameCount * 100) / 100 : 0,
        maxDrawMs: Math.round(maxDrawMs * 100) / 100
      };
    }

    function destroy() {
      if (destroyed) return;
      destroyed = true;
      sceneCacheReady = false;
      stopFrames();
      stopLightning();
      root.dataset.motion = "off";
      clearCanvas(rainCanvas, rainContext);
      clearCanvas(glassCanvas, glassContext);
      if (control) {
        control.removeEventListener("change", motionChanged);
        control.checked = false;
        control.disabled = true;
      }
      doc.removeEventListener("visibilitychange", visibilityChanged);
      if (typeof global.removeEventListener === "function") global.removeEventListener("resize", resized);
      if (media) {
        if (typeof media.removeEventListener === "function") media.removeEventListener("change", preferenceChanged);
        else if (typeof media.removeListener === "function") media.removeListener(preferenceChanged);
      }
      for (const {image, loaded, failed} of imageListeners) {
        image.removeEventListener("load", loaded);
        image.removeEventListener("error", failed);
      }
      atlas.onload = null;
      atlas.onerror = null;
    }

    return {updateDay, getState, destroy};
  }

  global.RainAtmosphere = Object.freeze({attach});
})(window);
