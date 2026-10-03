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
      dirtyGlass = [];
      return true;
    }

    function planScene() {
      const nextDrops = Math.round(PROFILES[profile].density * maxDrops);
      if (nextDrops !== plannedDrops) cacheDirty = true;
      plannedDrops = nextDrops;
      rainCount = Math.round(PROFILES[profile].rain * Math.min(1, Math.max(.35, width * height / 1049088)));
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
        if (imageFailed.glass) text += " Water texture unavailable.";
        else if (!imageReady.glass) text += " Loading the water texture.";
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
      };
      const failed = function () {
        if (!destroyed) { imageReady[key] = false; imageFailed[key] = true; }
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
      const available = !destroyed && imageReady.glass && !!glassContext && !!cacheContext;
      return {
        profile, date, mm, status, density: PROFILES[profile].density,
        maxDrops, plannedDrops, dropCount: available ? plannedDrops : 0,
        movingDrops: motionAllowed() ? movingCount() : 0,
        rainCount, motion: motionAllowed(), requestedMotion, reduced, hidden, destroyed,
        lightning, bolt, timers: {lightning: lightningTimer !== null, lightningOff: lightningOffTimer !== null},
        rafPending: raf !== null, imageReady: {...imageReady}, imageFailed: {...imageFailed},
        assetLoading: !imageReady.glass && !imageFailed.glass,
        canvasReady: {rain: !!rainContext, glass: !!glassContext && !!cacheContext},
        fpsLimit: 30, dpr, width, height, maxCanvasPixels: MAX_CANVAS_PIXELS, frameCount,
        averageDrawMs: frameCount ? Math.round(totalDrawMs / frameCount * 100) / 100 : 0,
        maxDrawMs: Math.round(maxDrawMs * 100) / 100
      };
    }

    function destroy() {
      if (destroyed) return;
      destroyed = true;
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
