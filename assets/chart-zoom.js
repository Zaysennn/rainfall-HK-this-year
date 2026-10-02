"use strict";

// Keep each chart's viewport independent while its marks are redrawn for playback.
window.ChartZoom = (() => {
  const WIDTH = 920, HEIGHT = 450, MAX_SCALE = 16;
  const MODES = new Set(["bars", "wheel", "cumulative"]);
  const instances = new WeakMap();
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const baseView = () => ({x: 0, y: 0, width: WIDTH, height: HEIGHT, scale: 1});

  function attach(chart, {toolbar, onGesture = () => {}} = {}) {
    if (instances.has(chart)) return instances.get(chart);
    const views = new Map([...MODES].map(mode => [mode, baseView()]));
    const pointers = new Map();
    const buttons = Object.fromEntries(["in", "out", "reset"].map(name =>
      [name, toolbar?.querySelector(`[data-zoom="${name}"]`)]));
    const output = toolbar?.querySelector("[data-zoom-status]");
    let mode = "calendar", drag = null, pinch = null, interacting = false;
    let hoverBlockedUntil = 0, blockedClick = null;
    const enabled = () => MODES.has(mode);
    const view = () => enabled() ? views.get(mode) : baseView();

    // Invert the SVG transform so letterboxing and responsive layouts do not move anchors.
    function screenFrame() {
      try {
        const matrix = chart.getScreenCTM()?.inverse();
        if (matrix && [matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f].every(Number.isFinite)) {
          return matrix;
        }
      } catch (_) {
        // A detached SVG has no screen transform; the measured viewport is a useful fallback.
      }
      const box = chart.getBoundingClientRect();
      const current = view();
      const ratio = Math.min(box.width / current.width, box.height / current.height) || 1;
      const left = box.left + (box.width - current.width * ratio) / 2;
      const top = box.top + (box.height - current.height * ratio) / 2;
      return {a: 1 / ratio, b: 0, c: 0, d: 1 / ratio,
              e: current.x - left / ratio, f: current.y - top / ratio};
    }

    function localPoint(x, y, frame = screenFrame()) {
      return {x: frame.a * x + frame.c * y + frame.e,
              y: frame.b * x + frame.d * y + frame.f};
    }

    // Clamp the viewport to the original drawing, leaving Calendar's geometry unchanged.
    function apply(next, notify = true) {
      if (!enabled()) return;
      const scale = clamp(Number.isFinite(next.scale) ? next.scale : 1, 1, MAX_SCALE);
      const current = {scale, width: WIDTH / scale, height: HEIGHT / scale,
                       x: 0, y: 0};
      current.x = clamp(next.x, 0, WIDTH - current.width);
      current.y = clamp(next.y, 0, HEIGHT - current.height);
      const before = view();
      const changed = current.scale !== before.scale || current.x !== before.x || current.y !== before.y;
      views.set(mode, current);
      chart.setAttribute("viewBox", `${current.x} ${current.y} ${current.width} ${current.height}`);
      chart.dataset.zoomEnabled = "true";
      chart.dataset.zoomed = String(scale > 1);
      chart.dataset.zoomDragging = String(interacting);
      chart.querySelectorAll("[data-zoom-cursor]").forEach(circle => circle.setAttribute("r", String(3 / scale)));
      if (output) output.textContent = `${Math.round(scale * 100)}%`;
      if (buttons.in) buttons.in.disabled = scale >= MAX_SCALE - 1e-9;
      if (buttons.out) buttons.out.disabled = scale <= 1 + 1e-9;
      if (buttons.reset) buttons.reset.disabled = scale <= 1 + 1e-9;
      if (changed && notify) onGesture();
    }

    function zoomAt(scale, point) {
      const current = view();
      const fractionX = clamp((point.x - current.x) / current.width, 0, 1);
      const fractionY = clamp((point.y - current.y) / current.height, 0, 1);
      const nextScale = clamp(scale, 1, MAX_SCALE);
      apply({scale: nextScale, x: point.x - fractionX * WIDTH / nextScale,
             y: point.y - fractionY * HEIGHT / nextScale});
    }

    function capture(id) {
      try { chart.setPointerCapture?.(id); } catch (_) { /* The pointer may already have ended. */ }
    }

    function release(id) {
      try {
        if (!chart.hasPointerCapture || chart.hasPointerCapture(id)) chart.releasePointerCapture?.(id);
      } catch (_) { /* Capture is already released when a pointer is cancelled. */ }
    }

    function startGesture() {
      if (!interacting) {
        interacting = true;
        chart.dataset.zoomDragging = "true";
        onGesture();
      }
    }

    // Suppress only the click produced at the end of a drag, preserving keyboard activation.
    function rememberClick(pointer, id) {
      if (!pointer) return;
      blockedClick = {x: pointer.x, y: pointer.y, id, until: Date.now() + 400};
      hoverBlockedUntil = Date.now() + 120;
    }

    function clearPointers(block = false) {
      const entries = [...pointers];
      const wasInteracting = interacting;
      pointers.clear();
      drag = null;
      pinch = null;
      interacting = false;
      chart.dataset.zoomDragging = "false";
      if (block && wasInteracting && entries.length) rememberClick(entries[entries.length - 1][1], entries[entries.length - 1][0]);
      entries.forEach(([id]) => release(id));
    }

    function prepareDrag(id, alreadyMoving = false) {
      const pointer = pointers.get(id);
      if (!pointer) return;
      drag = {id, start: {...pointer}, origin: {...view()}, frame: screenFrame(), moved: alreadyMoving};
      pinch = null;
    }

    // Pinch distances change scale; the original midpoint stays under the fingers as they move.
    function preparePinch() {
      const pair = [...pointers].slice(0, 2);
      if (pair.length < 2) return;
      const [first, second] = pair.map(item => item[1]);
      const distance = Math.hypot(second.x - first.x, second.y - first.y);
      if (distance < 2) return;
      pinch = {ids: pair.map(item => item[0]), distance, scale: view().scale,
               anchor: localPoint((first.x + second.x) / 2, (first.y + second.y) / 2)};
      drag = null;
      startGesture();
      pinch.ids.forEach(capture);
    }

    function stopEvent(event) {
      event.preventDefault();
      event.stopPropagation();
    }

    function pointerDown(event) {
      // A fresh press is a new click sequence, even at the previous drag's endpoint.
      blockedClick = null;
      hoverBlockedUntil = 0;
      if (!enabled() || (event.pointerType !== "touch" && event.button !== 0)) return;
      pointers.set(event.pointerId, {x: event.clientX, y: event.clientY, type: event.pointerType});
      if (pointers.size >= 2) {
        if (!pinch) preparePinch();
        if (pinch) stopEvent(event);
      } else {
        prepareDrag(event.pointerId);
      }
    }

    function pointerMove(event) {
      if (!enabled() || !pointers.has(event.pointerId)) return;
      // Re-entering after a release outside the browser must not resume an old drag.
      if (event.pointerType !== "touch" && event.buttons === 0) {
        pointerEnd(event);
        return;
      }
      pointers.set(event.pointerId, {x: event.clientX, y: event.clientY, type: event.pointerType});
      if (pointers.size >= 2 && !pinch) preparePinch();
      if (pinch) {
        const [first, second] = pinch.ids.map(id => pointers.get(id));
        if (!first || !second) return;
        const distance = Math.hypot(second.x - first.x, second.y - first.y);
        const midpoint = localPoint((first.x + second.x) / 2, (first.y + second.y) / 2);
        const current = view();
        const fractionX = (midpoint.x - current.x) / current.width;
        const fractionY = (midpoint.y - current.y) / current.height;
        const scale = clamp(pinch.scale * distance / pinch.distance, 1, MAX_SCALE);
        apply({scale, x: pinch.anchor.x - fractionX * WIDTH / scale,
               y: pinch.anchor.y - fractionY * HEIGHT / scale});
        stopEvent(event);
        return;
      }
      if (!drag || drag.id !== event.pointerId || view().scale <= 1) return;
      const dx = event.clientX - drag.start.x, dy = event.clientY - drag.start.y;
      if (!drag.moved && Math.hypot(dx, dy) <= 5) return;
      if (!drag.moved) {
        drag.moved = true;
        startGesture();
        capture(event.pointerId);
      }
      apply({scale: drag.origin.scale,
             x: drag.origin.x - drag.frame.a * dx - drag.frame.c * dy,
             y: drag.origin.y - drag.frame.b * dx - drag.frame.d * dy});
      stopEvent(event);
    }

    // Re-anchor the remaining finger after a pinch, and finish cleanly on cancellation.
    function pointerEnd(event) {
      if (!pointers.has(event.pointerId)) return;
      const last = {x: event.clientX ?? pointers.get(event.pointerId).x,
                    y: event.clientY ?? pointers.get(event.pointerId).y};
      const wasInteracting = interacting;
      pointers.delete(event.pointerId);
      release(event.pointerId);
      if (wasInteracting) rememberClick(last, event.pointerId);
      if (pointers.size >= 2) {
        if (!pinch || pinch.ids.includes(event.pointerId)) preparePinch();
      } else if (pointers.size === 1) {
        prepareDrag(pointers.keys().next().value, wasInteracting);
      } else {
        drag = null;
        pinch = null;
        interacting = false;
        chart.dataset.zoomDragging = "false";
      }
      if (wasInteracting) stopEvent(event);
    }

    function wheel(event) {
      if (!enabled() || !Number.isFinite(event.deltaY) || event.deltaY === 0) return;
      // Wheel input replaces a pointer gesture so its saved transform cannot become stale.
      clearPointers(true);
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? chart.getBoundingClientRect().height : 1);
      zoomAt(view().scale * Math.exp(-clamp(delta, -400, 400) * 0.002),
             localPoint(event.clientX, event.clientY));
      event.preventDefault();
    }

    function click(event) {
      if (!blockedClick || Date.now() > blockedClick.until || event.detail === 0) return;
      const samePointer = event.pointerId === undefined || event.pointerId === blockedClick.id;
      const nearEnd = Math.hypot(event.clientX - blockedClick.x, event.clientY - blockedClick.y) < 12;
      if (samePointer && nearEnd) {
        blockedClick = null;
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }

    function activate(nextMode) {
      if (nextMode !== mode) clearPointers(true);
      mode = nextMode;
      if (toolbar) toolbar.hidden = !enabled();
      if (enabled()) {
        apply(view(), false);
      } else {
        chart.setAttribute("viewBox", `0 0 ${WIDTH} ${HEIGHT}`);
        chart.dataset.zoomEnabled = "false";
        chart.dataset.zoomed = "false";
        chart.dataset.zoomDragging = "false";
      }
    }

    // Keyboard focus pans only as far as necessary; tall hit areas keep their visible overlap.
    function reveal(mark) {
      if (!enabled() || view().scale <= 1 || !mark?.getBBox) return;
      let box;
      try { box = mark.getBBox(); } catch (_) { return; }
      if (![box.x, box.y, box.width, box.height].every(Number.isFinite)) return;
      const current = view();
      function revealAxis(position, extent, start, length) {
        const padding = extent * 0.04;
        if (length >= extent - 2 * padding) {
          if (start + length < position + padding) return start + length - padding;
          if (start > position + extent - padding) return start - extent + padding;
          return position;
        }
        if (start < position + padding) return start - padding;
        if (start + length > position + extent - padding) return start + length - extent + padding;
        return position;
      }
      apply({scale: current.scale,
             x: revealAxis(current.x, current.width, box.x, box.width),
             y: revealAxis(current.y, current.height, box.y, box.height)});
    }

    // Bind once to the stable root, rather than to the marks replaced during rendering.
    chart.addEventListener("wheel", wheel, {passive: false, capture: true});
    chart.addEventListener("pointerdown", pointerDown, true);
    chart.addEventListener("pointermove", pointerMove, true);
    chart.addEventListener("pointerup", pointerEnd, true);
    chart.addEventListener("pointercancel", pointerEnd, true);
    chart.addEventListener("lostpointercapture", pointerEnd, true);
    chart.addEventListener("click", click, true);
    chart.addEventListener("mousemove", event => {
      if (interacting || Date.now() < hoverBlockedUntil) event.stopImmediatePropagation();
    }, true);
    // A short press can end outside the SVG before drag capture begins.
    document.addEventListener("pointerup", pointerEnd, true);
    document.addEventListener("pointercancel", pointerEnd, true);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) clearPointers(true);
    });
    ["in", "out"].forEach(name => buttons[name]?.addEventListener("click", () => {
      if (!enabled()) return;
      clearPointers(true);
      const current = view();
      zoomAt(current.scale * (name === "in" ? 1.5 : 1 / 1.5),
             {x: current.x + current.width / 2, y: current.y + current.height / 2});
    }));
    buttons.reset?.addEventListener("click", () => {
      if (!enabled()) return;
      clearPointers(true);
      apply(baseView());
    });

    const api = {
      activate, reveal,
      getState: () => {
        const current = view();
        return {mode, enabled: enabled(), scale: current.scale,
                viewBox: {x: current.x, y: current.y, width: current.width, height: current.height},
                interacting: interacting || Date.now() < hoverBlockedUntil};
      },
      isInteracting: () => interacting || Date.now() < hoverBlockedUntil
    };
    instances.set(chart, api);
    activate(mode);
    return api;
  }

  return Object.freeze({attach});
})();
