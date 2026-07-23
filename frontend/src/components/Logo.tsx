"use client";

/**
 * Nexus particle logo - "N" rendered as a Matrix-esque vertical
 * data-rain field, masked by the letter silhouette in the AfterQuery
 * slab idiom. Silver gradient inside, ambient flecks outside, with
 * sparse "trade pulse" bursts on random columns.
 *
 * Visually concise: ~32-40px in the header, never cluttered.
 * Pauses when the tab is hidden to stay polite on CPU.
 */

import { useEffect, useRef } from "react";

interface Props {
  size?: number;        // px, default 32
  density?: number;     // columns, default 16
  pulse?: boolean;      // enable random pulse bursts (default true)
}

export default function NexusLogo({ size = 32, density = 16, pulse = true }: Props) {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    const W = size, H = size;
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    ctx.scale(dpr, dpr);

    // ── N silhouette in a 32-unit virtual space ────────────────────────────
    // Two verticals + diagonal strip - the AfterQuery slab feel applied to N.
    const inN = (x: number, y: number) => {
      const u = (x / W) * 32, v = (y / H) * 32;
      // Left vertical bar
      if (u >= 4  && u <= 10 && v >= 4 && v <= 28) return true;
      // Right vertical bar
      if (u >= 22 && u <= 28 && v >= 4 && v <= 28) return true;
      // Diagonal strip: line (10,4) → (22,28), half-width 3
      const dx = 12, dy = 24;
      const lenSq = dx * dx + dy * dy;
      const px = u - 10, py = v - 4;
      const t = (px * dx + py * dy) / lenSq;
      if (t < 0 || t > 1) return false;
      const perp = (px * -dy + py * dx) / Math.sqrt(lenSq);
      return Math.abs(perp) <= 3.8;
    };

    // ── Lane state - columns of drifting ticks ─────────────────────────────
    const COLS = density;
    const colW = W / COLS;
    type Lane = { offset: number; speed: number; pulse: number };
    const lanes: Lane[] = Array.from({ length: COLS }, () => ({
      offset: Math.random() * H,
      speed:  0.18 + Math.random() * 0.42,   // px / frame - visibly alive
      pulse:  0,
    }));

    const tickH = Math.max(1.2, H / 22);
    const gap   = Math.max(0.5, tickH * 0.45);
    const stride = tickH + gap;
    const ticksPerLane = Math.ceil(H / stride) + 2;

    let raf = 0;
    let lastPulseT = 0;
    let alive = true;

    const draw = (t: number) => {
      if (!alive) return;
      if (document.hidden) { raf = requestAnimationFrame(draw); return; }

      ctx.clearRect(0, 0, W, H);

      // Silver gradient - matches --primary #c6c6c7 hierarchy
      const grad = ctx.createLinearGradient(0, 0, W, H);
      grad.addColorStop(0,    "#e2e2e2");
      grad.addColorStop(0.55, "#c6c6c7");
      grad.addColorStop(1,    "#6b6b6c");

      // Pulse trigger - more frequent so the mark feels alive at small size
      if (pulse && t - lastPulseT > 900 + Math.random() * 900) {
        lanes[Math.floor(Math.random() * COLS)].pulse = 1;
        lastPulseT = t;
      }

      for (let i = 0; i < COLS; i++) {
        const lane = lanes[i];
        lane.offset = (lane.offset + lane.speed) % H;
        lane.pulse *= 0.93;

        const x = i * colW + colW * 0.20;
        const w = colW * 0.60;

        for (let k = 0; k < ticksPerLane; k++) {
          const y  = (k * stride - lane.offset + H) % H;
          const cx = x + w / 2;
          const cy = y + tickH / 2;
          const inside = inN(cx, cy);

          if (inside) {
            ctx.fillStyle   = grad;
            ctx.globalAlpha = 0.72 + lane.pulse * 0.28;
            ctx.fillRect(x, y, w, tickH);
          } else {
            ctx.fillStyle   = "#c6c6c7";
            ctx.globalAlpha = 0.05 + lane.pulse * 0.10;
            ctx.fillRect(x, y, w, tickH);
          }
        }
      }
      ctx.globalAlpha = 1;

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => { alive = false; cancelAnimationFrame(raf); };
  }, [size, density, pulse]);

  return (
    <canvas
      ref={ref}
      style={{ width: size, height: size, display: "block" }}
      aria-label="Nexus"
      role="img"
    />
  );
}
