"use client";

import { useEffect, useRef, useState } from "react";
import type { IChartApi, ISeriesApi, Logical, Time } from "lightweight-charts";

export type Tool = "none" | "rect" | "fib" | "trendline" | "hline";

export interface Drawing {
  id: string;
  kind: "rect" | "fib" | "trendline" | "hline";
  t1: number;   // unix seconds - primary anchor when drawing sits over data
  p1: number;
  t2: number;   // for hline we reuse t1/t2 = extents but draw full-width
  p2: number;
  /** Logical-index fallback anchors. Captured on create and used when the
   *  drawing extends into the "future" empty area where timeToCoordinate
   *  would return null (there is no candle at that time yet). Logical
   *  indices are stable across pan/zoom and work beyond the last candle. */
  l1?: number;
  l2?: number;
}

export interface FibLevel {
  ratio: number;
  color: string;
  enabled: boolean;
}

export const DEFAULT_FIB_LEVELS: FibLevel[] = [
  { ratio: 0,     color: "#c6c6c7", enabled: true },
  { ratio: 0.236, color: "#60a5fa", enabled: true },
  { ratio: 0.382, color: "#60a5fa", enabled: true },
  { ratio: 0.5,   color: "#c6c6c7", enabled: true },
  { ratio: 0.618, color: "#c6c6c7", enabled: true },
  { ratio: 0.786, color: "#f87171", enabled: true },
  { ratio: 1,     color: "#c6c6c7", enabled: true },
  { ratio: 1.272, color: "#a78bfa", enabled: false },
  { ratio: 1.618, color: "#a78bfa", enabled: false },
  { ratio: 2.618, color: "#ec4899", enabled: false },
];

export interface ZoneOverlay {
  price_low: number;
  price_high: number;
  tier: string;
  zone_type?: string;
  score?: number;
}

interface Props {
  chart: IChartApi | null;
  priceSeries: ISeriesApi<"Candlestick"> | null;
  tool: Tool;
  setTool?: (t: Tool) => void;
  drawings: Drawing[];
  setDrawings: React.Dispatch<React.SetStateAction<Drawing[]>>;
  fibLevels?: FibLevel[];
  zones?: ZoneOverlay[];
}

const TIER_COLOR: Record<string, { fill: string; stroke: string }> = {
  platinum: { fill: "rgba(224,224,255,0.10)", stroke: "rgba(224,224,255,0.55)" },
  golden:   { fill: "rgba(255,176,0,0.10)",   stroke: "rgba(255,176,0,0.55)" },
  silver:   { fill: "rgba(184,184,200,0.08)", stroke: "rgba(184,184,200,0.45)" },
  bronze:   { fill: "rgba(139,90,43,0.07)",   stroke: "rgba(139,90,43,0.40)" },
};

// Handle hit-box in pixels
const HANDLE = 7;

type HandleName = "nw" | "ne" | "sw" | "se" | "n" | "s" | "e" | "w" | "body" | null;

interface Interaction {
  mode: "create" | "move" | "resize";
  id: string | null;       // for move/resize
  handle: HandleName;
  startX: number;
  startY: number;
  startT1: number;
  startP1: number;
  startT2: number;
  startP2: number;
  /** Logical-index anchors captured at drag start. These are the canonical
   *  positions used for move/resize math because they remain valid even in
   *  the future-area beyond the last candle. */
  startL1: number;
  startL2: number;
}

/**
 * Canvas overlay for chart drawings with selection + resize + delete.
 *
 * Modes:
 *   - tool="none": selection mode. Click a drawing to select; drag body to move;
 *     drag a corner/edge handle to resize; press Delete/Backspace to remove.
 *   - tool="rect"|"fib": create mode. Click-drag to place a new drawing.
 *     Tool stays armed; click the same button again or press Esc to disarm.
 */
export default function DrawingLayer({
  chart,
  priceSeries,
  tool,
  drawings,
  setDrawings,
  fibLevels = DEFAULT_FIB_LEVELS,
  zones = [],
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [dragging, setDragging] = useState<Drawing | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoverCursor, setHoverCursor] = useState<string>("default");
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  const interactionRef = useRef<Interaction | null>(null);
  const dragRef = useRef<Drawing | null>(null);
  useEffect(() => { dragRef.current = dragging; }, [dragging]);

  // Keep latest drawings accessible to event handlers without re-subscribing.
  const drawingsRef = useRef<Drawing[]>(drawings);
  useEffect(() => { drawingsRef.current = drawings; }, [drawings]);

  // --- keep canvas pixel size in sync with container ---
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const parent = c.parentElement;
    if (!parent) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width;
        const h = entry.contentRect.height;
        setSize({ w, h });
        const dpr = window.devicePixelRatio || 1;
        c.width = Math.floor(w * dpr);
        c.height = Math.floor(h * dpr);
        c.style.width = w + "px";
        c.style.height = h + "px";
      }
    });
    ro.observe(parent);
    return () => ro.disconnect();
  }, []);

  // --- coordinate helpers ---
  const priceFromY = (y: number): number | null => {
    const s = priceSeries;
    if (!s) return null;
    const p = s.coordinateToPrice(y);
    return typeof p === "number" ? p : null;
  };
  const timeFromX = (x: number): number | null => {
    const c = chart;
    if (!c) return null;
    const t = c.timeScale().coordinateToTime(x);
    return typeof t === "number" ? t : null;
  };
  const logicalFromX = (x: number): number | null => {
    const c = chart;
    if (!c) return null;
    const l = c.timeScale().coordinateToLogical(x);
    return typeof l === "number" && Number.isFinite(l) ? l : null;
  };
  /** Resolve x-coordinate for a drawing anchor. Prefers logical (works even
   *  in the future-area beyond the last candle); falls back to time-based
   *  conversion for drawings saved before the logical fallback existed. */
  const xFromAnchor = (t: number, l: number | undefined): number | null => {
    const c = chart;
    if (!c) return null;
    const ts = c.timeScale();
    if (typeof l === "number" && Number.isFinite(l)) {
      const x = ts.logicalToCoordinate(l as Logical);
      if (typeof x === "number") return x;
    }
    const x = ts.timeToCoordinate(t as Time);
    return typeof x === "number" ? x : null;
  };
  const yFromPrice = (p: number): number | null => {
    const s = priceSeries;
    if (!s) return null;
    const y = s.priceToCoordinate(p);
    return typeof y === "number" ? y : null;
  };

  // Compute pixel bounds for a drawing
  const boundsOf = (d: Drawing): { left: number; top: number; right: number; bottom: number } | null => {
    const x1 = xFromAnchor(d.t1, d.l1); const y1 = yFromPrice(d.p1);
    const x2 = xFromAnchor(d.t2, d.l2); const y2 = yFromPrice(d.p2);
    if (x1 == null || y1 == null || x2 == null || y2 == null) return null;
    return {
      left: Math.min(x1, x2), right: Math.max(x1, x2),
      top: Math.min(y1, y2), bottom: Math.max(y1, y2),
    };
  };

  // Hit test - returns {id, handle} or null.
  const hitTest = (x: number, y: number): { id: string; handle: HandleName } | null => {
    // Iterate in reverse so topmost drawing wins
    const ds = drawingsRef.current;
    for (let i = ds.length - 1; i >= 0; i--) {
      const d = ds[i];

      // hline: hit if within HANDLE of the price line y. Handles left/right for
      // optional horizontal drag, but primarily the "body" selects for delete.
      if (d.kind === "hline") {
        const y0 = yFromPrice(d.p1);
        if (y0 == null) continue;
        if (Math.abs(y - y0) <= HANDLE) return { id: d.id, handle: "body" };
        continue;
      }

      // trendline: hit if close to the line segment, or near the endpoints.
      if (d.kind === "trendline") {
        const x1 = xFromAnchor(d.t1, d.l1); const y1 = yFromPrice(d.p1);
        const x2 = xFromAnchor(d.t2, d.l2); const y2 = yFromPrice(d.p2);
        if (x1 == null || y1 == null || x2 == null || y2 == null) continue;
        const near = (px: number, py: number) => Math.abs(x - px) <= HANDLE && Math.abs(y - py) <= HANDLE;
        if (near(x1, y1)) return { id: d.id, handle: "nw" };
        if (near(x2, y2)) return { id: d.id, handle: "se" };
        // Point-to-segment distance
        const dx = x2 - x1, dy = y2 - y1;
        const len2 = dx * dx + dy * dy || 1;
        const tProj = Math.max(0, Math.min(1, ((x - x1) * dx + (y - y1) * dy) / len2));
        const px = x1 + tProj * dx, py = y1 + tProj * dy;
        if (Math.hypot(x - px, y - py) <= HANDLE) return { id: d.id, handle: "body" };
        continue;
      }

      const b = boundsOf(d);
      if (!b) continue;
      const { left, right, top, bottom } = b;
      // Corners
      const near = (px: number, py: number) => Math.abs(x - px) <= HANDLE && Math.abs(y - py) <= HANDLE;
      if (near(left, top)) return { id: d.id, handle: "nw" };
      if (near(right, top)) return { id: d.id, handle: "ne" };
      if (near(left, bottom)) return { id: d.id, handle: "sw" };
      if (near(right, bottom)) return { id: d.id, handle: "se" };
      // Edges
      const onEdgeH = (ey: number) => Math.abs(y - ey) <= HANDLE && x >= left && x <= right;
      const onEdgeV = (ex: number) => Math.abs(x - ex) <= HANDLE && y >= top && y <= bottom;
      if (onEdgeH(top)) return { id: d.id, handle: "n" };
      if (onEdgeH(bottom)) return { id: d.id, handle: "s" };
      if (onEdgeV(left)) return { id: d.id, handle: "w" };
      if (onEdgeV(right)) return { id: d.id, handle: "e" };
      // Body
      if (x >= left && x <= right && y >= top && y <= bottom) return { id: d.id, handle: "body" };
    }
    return null;
  };

  const cursorForHandle = (h: HandleName): string => {
    switch (h) {
      case "nw": case "se": return "nwse-resize";
      case "ne": case "sw": return "nesw-resize";
      case "n": case "s": return "ns-resize";
      case "e": case "w": return "ew-resize";
      case "body": return "move";
      default: return "default";
    }
  };

  // --- mouse handlers ---
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const parent = c.parentElement;

    // POINTER-EVENTS STRATEGY
    // ------------------------------------------------------------------
    // The overlay canvas sits on top of the chart. If it captures every
    // mouse event, the chart below can never receive pan/zoom. So:
    //   - tool !== "none"  → canvas captures everything (create mode)
    //   - tool === "none"  → canvas is pointer-events:none by default,
    //     and we listen for mousemove on the PARENT (which still bubbles
    //     regardless of child pointer-events). When the cursor hovers a
    //     drawing or handle, we flip pointerEvents:auto so clicks land on
    //     the canvas. Otherwise the chart gets the event.
    // This keeps pan/zoom/crosshair fully responsive while drawings stay
    // interactive.
    // ------------------------------------------------------------------
    if (tool !== "none") {
      c.style.pointerEvents = "auto";
      c.style.cursor = "crosshair";
    } else {
      c.style.cursor = hoverCursor;
      c.style.pointerEvents = hoverCursor === "default" ? "none" : "auto";
    }

    const getXY = (e: MouseEvent) => {
      const rect = c.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top, inBounds: e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom };
    };

    const onDown = (e: MouseEvent) => {
      const { x, y, inBounds } = getXY(e);
      if (!inBounds) return;

      if (tool !== "none") {
        // create mode - capture BOTH time and logical so the drawing survives
        // being placed in the "future" empty area beyond the last candle.
        const l = logicalFromX(x);
        const p = priceFromY(y);
        // Logical is the primary anchor; require it. Time may be null in
        // future-area and that's fine - logical fallback handles render.
        if (l == null || p == null) return;
        const t = timeFromX(x) ?? 0;
        const d: Drawing = {
          id: `${Date.now()}-${Math.floor(Math.random() * 1e6)}`,
          kind: tool === "rect" ? "rect" : tool === "fib" ? "fib" : tool === "trendline" ? "trendline" : "hline",
          t1: t, p1: p, t2: t, p2: p,
          l1: l, l2: l,
        };
        dragRef.current = d;
        setDragging(d);
        interactionRef.current = {
          mode: "create", id: d.id, handle: "se",
          startX: x, startY: y,
          startT1: t, startP1: p, startT2: t, startP2: p,
          startL1: l, startL2: l,
        };
        return;
      }

      // selection mode - hit test
      const hit = hitTest(x, y);
      if (!hit) { setSelectedId(null); return; }
      setSelectedId(hit.id);
      const d = drawingsRef.current.find((dr) => dr.id === hit.id);
      if (!d) return;
      // Resolve logical anchors for the existing drawing. Prefer the stored
      // l1/l2 (captured on create); fall back to converting from its time
      // anchor so drawings persisted before the logical-fallback landed
      // still manipulate correctly.
      const ts = chart?.timeScale();
      const resolveL = (storedL: number | undefined, time: number): number => {
        if (typeof storedL === "number" && Number.isFinite(storedL)) return storedL;
        const xPx = ts?.timeToCoordinate(time as Time);
        if (typeof xPx === "number") {
          const li = ts?.coordinateToLogical(xPx);
          if (typeof li === "number" && Number.isFinite(li)) return li;
        }
        return 0;
      };
      const dL1 = resolveL(d.l1, d.t1);
      const dL2 = resolveL(d.l2, d.t2);
      interactionRef.current = {
        mode: hit.handle === "body" ? "move" : "resize",
        id: hit.id, handle: hit.handle,
        startX: x, startY: y,
        startT1: d.t1, startP1: d.p1, startT2: d.t2, startP2: d.p2,
        startL1: dL1, startL2: dL2,
      };
      e.preventDefault();
    };

    const onMove = (e: MouseEvent) => {
      const { x, y, inBounds } = getXY(e);
      const inter = interactionRef.current;

      // Hover feedback in selection mode - also toggles pointer-events so
      // the chart beneath receives pan/zoom when cursor isn't over a drawing.
      if (!inter && tool === "none") {
        if (inBounds) {
          const hit = hitTest(x, y);
          const next = hit ? cursorForHandle(hit.handle) : "default";
          if (next !== hoverCursor) setHoverCursor(next);
          // Direct DOM update for zero-latency event forwarding.
          c.style.pointerEvents = hit ? "auto" : "none";
        } else if (hoverCursor !== "default") {
          setHoverCursor("default");
          c.style.pointerEvents = "none";
        }
        return;
      }
      if (!inter) return;

      // Clamp to canvas bounds so drawings never extend outside the chart area.
      const cx = Math.max(0, Math.min(size.w, x));
      const cy = Math.max(0, Math.min(size.h, y));
      const t = timeFromX(cx) ?? inter.startT2;  // fall back to anchor if future-area
      const l = logicalFromX(cx);
      const p = priceFromY(cy);
      if (l == null || p == null) return;

      if (inter.mode === "create") {
        const cur = dragRef.current;
        if (!cur) return;
        const next = { ...cur, t2: t, p2: p, l2: l };
        dragRef.current = next;
        setDragging(next);
        return;
      }

      // move or resize on an existing drawing
      if (!inter.id) return;
      const origLeftL = Math.min(inter.startL1, inter.startL2);
      const origRightL = Math.max(inter.startL1, inter.startL2);
      const origTopP = Math.max(inter.startP1, inter.startP2);    // higher price = top
      const origBottomP = Math.min(inter.startP1, inter.startP2);

      let newT1 = inter.startT1, newP1 = inter.startP1;
      let newT2 = inter.startT2, newP2 = inter.startP2;
      let newL1 = inter.startL1, newL2 = inter.startL2;

      if (inter.mode === "move") {
        const startL = logicalFromX(inter.startX);
        const startP = priceFromY(inter.startY);
        if (startL == null || startP == null) return;
        const dL = l - startL;
        const dP = p - startP;
        newL1 = inter.startL1 + dL;
        newL2 = inter.startL2 + dL;
        newP1 = inter.startP1 + dP;
        newP2 = inter.startP2 + dP;
        // Recompute t1/t2 from the new logical positions when possible so
        // saved drawings still round-trip to time-based labels.
        const ts = chart?.timeScale();
        const x1 = ts?.logicalToCoordinate(newL1 as Logical);
        const x2 = ts?.logicalToCoordinate(newL2 as Logical);
        if (typeof x1 === "number") newT1 = timeFromX(x1) ?? inter.startT1;
        if (typeof x2 === "number") newT2 = timeFromX(x2) ?? inter.startT2;
      } else {
        // resize - adjust based on which handle is held (logical-space)
        let leftL = origLeftL, rightL = origRightL, topP = origTopP, bottomP = origBottomP;
        if (inter.handle === "nw") { leftL = l; topP = p; }
        else if (inter.handle === "ne") { rightL = l; topP = p; }
        else if (inter.handle === "sw") { leftL = l; bottomP = p; }
        else if (inter.handle === "se") { rightL = l; bottomP = p; }
        else if (inter.handle === "n") { topP = p; }
        else if (inter.handle === "s") { bottomP = p; }
        else if (inter.handle === "w") { leftL = l; }
        else if (inter.handle === "e") { rightL = l; }
        newL1 = leftL; newL2 = rightL; newP1 = topP; newP2 = bottomP;
        const ts = chart?.timeScale();
        const x1 = ts?.logicalToCoordinate(newL1 as Logical);
        const x2 = ts?.logicalToCoordinate(newL2 as Logical);
        if (typeof x1 === "number") newT1 = timeFromX(x1) ?? inter.startT1;
        if (typeof x2 === "number") newT2 = timeFromX(x2) ?? inter.startT2;
      }

      setDrawings((ds) => ds.map((d) => d.id === inter.id
        ? { ...d, t1: newT1, p1: newP1, t2: newT2, p2: newP2, l1: newL1, l2: newL2 }
        : d));
    };

    const onUp = () => {
      const inter = interactionRef.current;
      if (!inter) return;
      if (inter.mode === "create") {
        const cur = dragRef.current;
        if (cur && (cur.t1 !== cur.t2 || cur.p1 !== cur.p2)) {
          setDrawings((ds) => [...ds, cur]);
          setSelectedId(cur.id);
        }
        dragRef.current = null;
        setDragging(null);
      }
      interactionRef.current = null;
    };

    c.addEventListener("mousedown", onDown);
    // Listen on parent only (not also window) - parent has pointer-events:auto
    // and mouse events bubble. Registering on both fired onMove twice per move,
    // doubling redraw cost.
    const moveTarget: HTMLElement | Window = parent ?? window;
    moveTarget.addEventListener("mousemove", onMove as EventListener);
    window.addEventListener("mouseup", onUp);
    return () => {
      c.removeEventListener("mousedown", onDown);
      moveTarget.removeEventListener("mousemove", onMove as EventListener);
      window.removeEventListener("mouseup", onUp);
    };
    // priceFromY/timeFromX are closures over chart/priceSeries which are already in deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool, chart, priceSeries, setDrawings, hoverCursor]);

  // Keyboard: Delete / Backspace removes selected drawing; Esc clears selection
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "Delete" || e.key === "Backspace") {
        if (!selectedId) return;
        e.preventDefault();
        setDrawings((ds) => ds.filter((d) => d.id !== selectedId));
        setSelectedId(null);
      } else if (e.key === "Escape") {
        setSelectedId(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId, setDrawings]);

  // --- render (RAF loop) ---
  useEffect(() => {
    let raf = 0;
    const draw = () => {
      const c = canvasRef.current;
      if (!c || !chart || !priceSeries) { raf = requestAnimationFrame(draw); return; }
      const ctx = c.getContext("2d");
      if (!ctx) { raf = requestAnimationFrame(draw); return; }
      const dpr = window.devicePixelRatio || 1;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size.w, size.h);

      // ---- zone overlays (drawn first so user drawings sit on top) ----
      for (const z of zones) {
        const yTop = yFromPrice(z.price_high);
        const yBot = yFromPrice(z.price_low);
        if (yTop == null || yBot == null) continue;
        const tier = TIER_COLOR[z.tier] || TIER_COLOR.bronze;
        const top = Math.min(yTop, yBot);
        const h = Math.max(1, Math.abs(yBot - yTop));
        ctx.fillStyle = tier.fill;
        ctx.strokeStyle = tier.stroke;
        ctx.lineWidth = 1;
        ctx.fillRect(0, top, size.w, h);
        ctx.beginPath(); ctx.moveTo(0, top); ctx.lineTo(size.w, top); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0, top + h); ctx.lineTo(size.w, top + h); ctx.stroke();
        if (h > 14) {
          ctx.fillStyle = tier.stroke;
          ctx.font = "9px Inter, system-ui, sans-serif";
          const lbl = `${z.tier.toUpperCase()}${z.zone_type ? " · " + z.zone_type : ""}${z.score != null ? " · " + z.score.toFixed(2) : ""}`;
          ctx.fillText(lbl, 6, top + 10);
        }
      }

      const renderOne = (d: Drawing, ghost = false, selected = false) => {
        const b = boundsOf(d);
        if (!b) return;
        const { left, top, right, bottom } = b;
        const w = right - left;
        const h = bottom - top;
        ctx.globalAlpha = ghost ? 0.55 : 1;

        if (d.kind === "hline") {
          // Horizontal price line - spans full chart width at p1
          const y = yFromPrice(d.p1);
          if (y == null) return;
          ctx.strokeStyle = selected ? "#c6c6c7" : "#34d399";
          ctx.lineWidth = selected ? 1.75 : 1.25;
          ctx.setLineDash([]);
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(size.w, y);
          ctx.stroke();
          ctx.fillStyle = ctx.strokeStyle;
          ctx.font = "10px Inter, system-ui, sans-serif";
          ctx.fillText(fmt(d.p1), 6, y - 3);
          return;
        }

        if (d.kind === "trendline") {
          const x1 = xFromAnchor(d.t1, d.l1);
          const y1 = yFromPrice(d.p1);
          const x2 = xFromAnchor(d.t2, d.l2);
          const y2 = yFromPrice(d.p2);
          if (x1 == null || y1 == null || x2 == null || y2 == null) return;
          ctx.strokeStyle = selected ? "#c6c6c7" : "#a78bfa";
          ctx.lineWidth = selected ? 2 : 1.5;
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.stroke();
          // Endpoint markers
          ctx.fillStyle = "#0e0e0e";
          ctx.strokeStyle = selected ? "#c6c6c7" : "#a78bfa";
          for (const [ex, ey] of [[x1, y1], [x2, y2]]) {
            ctx.beginPath();
            ctx.arc(ex, ey, 3.5, 0, 2 * Math.PI);
            ctx.fill();
            ctx.stroke();
          }
          // Slope readout: price/time delta
          const dp = d.p2 - d.p1;
          const pctLabel = d.p1 !== 0 ? `${((dp / d.p1) * 100).toFixed(2)}%` : "";
          ctx.fillStyle = ctx.strokeStyle;
          ctx.font = "10px Inter, system-ui, sans-serif";
          ctx.fillText(`Δ ${fmt(dp)} (${pctLabel})`, Math.min(x1, x2) + 4, Math.min(y1, y2) - 4);
          return;
        }

        if (d.kind === "rect") {
          ctx.fillStyle = "rgba(96,165,250,0.10)";
          ctx.strokeStyle = selected ? "#c6c6c7" : "#60a5fa";
          ctx.lineWidth = selected ? 1.75 : 1.25;
          ctx.fillRect(left, top, w, h);
          ctx.strokeRect(left, top, w, h);
          ctx.fillStyle = ctx.strokeStyle;
          ctx.font = "10px Inter, system-ui, sans-serif";
          ctx.fillText(fmt(d.p1), left + 4, top - 3);
          ctx.fillText(fmt(d.p2), left + 4, bottom + 11);
        } else {
          // Fibonacci retracement
          for (const lvl of fibLevels) {
            if (!lvl.enabled) continue;
            const price = d.p1 + (d.p2 - d.p1) * lvl.ratio;
            const y = yFromPrice(price);
            if (y == null) continue;
            ctx.strokeStyle = lvl.color;
            ctx.lineWidth = selected && (lvl.ratio === 0 || lvl.ratio === 1) ? 1.75 : 1;
            ctx.setLineDash(lvl.ratio === 0 || lvl.ratio === 1 ? [] : [3, 3]);
            ctx.beginPath();
            ctx.moveTo(left, y);
            ctx.lineTo(right, y);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = lvl.color;
            ctx.font = "10px Inter, system-ui, sans-serif";
            ctx.fillText(`${(lvl.ratio * 100).toFixed(1)}%  ${fmt(price)}`, right + 4, y + 3);
          }
        }

        // Selection handles (rect + fib both treated as bboxes)
        if (selected && !ghost) {
          const handles: Array<[number, number]> = [
            [left, top], [right, top], [left, bottom], [right, bottom],
            [(left + right) / 2, top], [(left + right) / 2, bottom],
            [left, (top + bottom) / 2], [right, (top + bottom) / 2],
          ];
          ctx.fillStyle = "#0e0e0e";
          ctx.strokeStyle = "#c6c6c7";
          ctx.lineWidth = 1.25;
          for (const [hx, hy] of handles) {
            ctx.beginPath();
            ctx.rect(hx - 3, hy - 3, 6, 6);
            ctx.fill();
            ctx.stroke();
          }
        }
      };

      drawings.forEach((d) => renderOne(d, false, d.id === selectedId));
      if (dragging) renderOne(dragging, true);
      ctx.globalAlpha = 1;

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawings, dragging, chart, priceSeries, size, fibLevels, zones, selectedId]);

  // Delete chip (floating button next to selected drawing)
  const selected = drawings.find((d) => d.id === selectedId) || null;
  let chipPos: { left: number; top: number } | null = null;
  if (selected) {
    const b = boundsOf(selected);
    if (b) chipPos = { left: Math.min(size.w - 60, b.right - 56), top: Math.max(0, b.top - 26) };
  }

  return (
    <>
      <canvas
        ref={canvasRef}
        style={{
          position: "absolute",
          inset: 0,
          // pointerEvents is controlled dynamically in the mouse effect:
          //   - "auto" while a tool is armed or cursor hovers a drawing
          //   - "none" otherwise (so chart pan/zoom passes through)
          zIndex: 5,
        }}
      />
      {chipPos && (
        <button
          onClick={() => {
            if (!selectedId) return;
            setDrawings((ds) => ds.filter((d) => d.id !== selectedId));
            setSelectedId(null);
          }}
          style={{
            position: "absolute",
            left: chipPos.left,
            top: chipPos.top,
            zIndex: 6,
            padding: "3px 8px",
            background: "rgba(234,57,67,0.15)",
            color: "#ea3943",
            border: "1px solid #ea3943",
            borderRadius: 3,
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.1em",
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          ✕ DELETE
        </button>
      )}
    </>
  );
}

function fmt(n: number): string {
  if (!isFinite(n)) return "--";
  const abs = Math.abs(n);
  const digits = abs < 1 ? 5 : abs < 100 ? 3 : 2;
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
