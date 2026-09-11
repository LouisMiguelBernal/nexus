"use client";

/**
 * Nexus - ParticleField
 *
 * Theme-aligned dynamic backdrop. Lives BEHIND content (pointer-events:none,
 * z-index:0) and never competes with data. Modes:
 *
 *   • "rain"   - vertical Matrix-style data rain
 *   • "tape"   - horizontal particle tape with cluster bands
 *   • "mesh"   - sparse node graph + traveling sparks
 *   • "flow"   - curl-noise vector-field streamlines (Van Gogh / Wind-Map feel)
 *   • "ascii"  - moving block-char ASCII geometry on a monospace grid
 *
 * Adapts to light/dark via CSS vars (--primary, --surface). Re-reads palette
 * on the `nexus-theme-change` event dispatched by Header. Single canvas per
 * instance, ResizeObserver-driven, paused on hidden tab.
 */

import { useEffect, useRef } from "react";

type Mode = "rain" | "tape" | "mesh" | "flow" | "ascii";

interface Props {
  mode?: Mode;
  /** Max alpha multiplier for particles. Lower = more subtle. Default 0.55. */
  intensity?: number;
  /** Particle density per 10k px². Default 0.35. */
  density?: number;
  /** Optional className for the wrapping div. */
  className?: string;
  /** Disable the soft radial mask on edges (true → fields touch the panel edge). */
  edgeToEdge?: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────
function parseColor(v: string): [number, number, number] {
  const s = v.trim();
  if (s.startsWith("#")) {
    const h = s.slice(1);
    const n = h.length === 3
      ? h.split("").map((c) => c + c).join("")
      : h;
    return [
      parseInt(n.slice(0, 2), 16),
      parseInt(n.slice(2, 4), 16),
      parseInt(n.slice(4, 6), 16),
    ];
  }
  const m = s.match(/rgba?\(([^)]+)\)/);
  if (m) {
    const [r, g, b] = m[1].split(",").map((x) => parseInt(x.trim(), 10));
    return [r, g, b];
  }
  return [198, 198, 199];
}

function readPalette() {
  if (typeof window === "undefined") {
    return {
      rgb: [198, 198, 199] as [number, number, number],
      surface: [14, 14, 14] as [number, number, number],
      light: false,
    };
  }
  const cs = getComputedStyle(document.documentElement);
  const primary = cs.getPropertyValue("--primary") || "#c6c6c7";
  const surface = cs.getPropertyValue("--surface") || "#0e0e0e";
  const light = document.documentElement.classList.contains("light");
  return {
    rgb: parseColor(primary),
    surface: parseColor(surface),
    light,
  };
}

// Cheap pseudo-noise for the flow field - sums of offset sines.
// Returns angle in radians for a given (x, y, t).
function flowAngle(x: number, y: number, t: number, scale: number): number {
  const u = x * scale;
  const v = y * scale;
  return (
    Math.sin(u + t * 0.0003) * 1.2
    + Math.cos(v * 1.3 - t * 0.00025) * 1.1
    + Math.sin((u + v) * 0.5 + t * 0.0002) * 0.6
  ) * 0.7;
}

const ASCII_GLYPHS = "·∙•◦░▒▓█▀▄▌▐╱╲╳━│┼┤┴◢◣◤◥◇◈◉○◌";

export default function ParticleField({
  mode = "rain",
  intensity = 0.55,
  density = 0.35,
  className,
  edgeToEdge = false,
}: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    let W = 0, H = 0;

    // ── Theme palette (live) ───────────────────────────────────────────────
    let palette = readPalette();
    const onTheme = () => { palette = readPalette(); };
    window.addEventListener("nexus-theme-change", onTheme);

    // Light mode benefits from a slightly higher intensity ceiling so silver
    // particles don't disappear against the porcelain surface.
    const lightBoost = () => (palette.light ? 1.45 : 1.0);

    // ── State ─────────────────────────────────────────────────────────────
    type Drop  = { x: number; y: number; speed: number; len: number; alpha: number };
    type Glide = { x: number; y: number; vx: number; r: number; alpha: number; band: number };
    type Node  = { x: number; y: number; r: number; phase: number; freq: number };
    type Spark = { from: number; to: number; t: number; dur: number };
    type FlowP = { x: number; y: number; age: number; life: number; speed: number };
    type Cell  = { glyph: number; alpha: number };
    let drops:  Drop[]  = [];
    let glides: Glide[] = [];
    let bands:  number[] = [];
    let nodes:  Node[]  = [];
    let edges:  Array<[number, number, number]> = [];
    let sparks: Spark[] = [];
    let flowParts: FlowP[] = [];
    let asciiCols = 0, asciiRows = 0;
    let asciiCells: Cell[] = [];

    // ── Seeders ───────────────────────────────────────────────────────────
    const seedRain = () => {
      const n = Math.max(40, Math.floor((W * H) / 10000 * density * 18));
      drops = Array.from({ length: n }, () => ({
        x: Math.random() * W, y: Math.random() * H,
        speed: 0.4 + Math.random() * 1.4,
        len:   8 + Math.random() * 26,
        alpha: 0.15 + Math.random() * 0.6,
      }));
    };

    const seedTape = () => {
      const nBands = 3 + Math.floor(Math.random() * 3);
      bands = Array.from({ length: nBands }, () => 0.15 + Math.random() * 0.7);
      const n = Math.max(60, Math.floor((W * H) / 10000 * density * 24));
      glides = Array.from({ length: n }, () => {
        const useBand = Math.random() < 0.55 && bands.length > 0;
        const bi = Math.floor(Math.random() * bands.length);
        const yBase = useBand ? bands[bi] * H : Math.random() * H;
        const jitter = useBand ? (Math.random() - 0.5) * 18 : 0;
        return {
          x: Math.random() * W, y: yBase + jitter,
          vx: 0.5 + Math.random() * 2.0,
          r:  0.6 + Math.random() * 1.6,
          alpha: 0.20 + Math.random() * 0.55,
          band: useBand ? bi : -1,
        };
      });
    };

    const seedMesh = () => {
      const n = Math.max(10, Math.min(28, Math.floor((W * H) / 10000 * density * 4)));
      nodes = Array.from({ length: n }, () => ({
        x: 8 + Math.random() * (W - 16),
        y: 8 + Math.random() * (H - 16),
        r: 1.2 + Math.random() * 1.6,
        phase: Math.random() * Math.PI * 2,
        freq:  0.001 + Math.random() * 0.0025,
      }));
      edges = [];
      for (let i = 0; i < nodes.length; i++) {
        const dists: Array<[number, number]> = [];
        for (let j = 0; j < nodes.length; j++) {
          if (i === j) continue;
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          dists.push([j, dx * dx + dy * dy]);
        }
        dists.sort((a, b) => a[1] - b[1]);
        const k = 2 + (Math.random() < 0.4 ? 1 : 0);
        for (let m = 0; m < k && m < dists.length; m++) {
          const j = dists[m][0];
          if (i < j) edges.push([i, j, 0.10 + Math.random() * 0.18]);
        }
      }
      sparks = [];
    };

    const seedFlow = () => {
      const n = Math.max(80, Math.floor((W * H) / 10000 * density * 26));
      flowParts = Array.from({ length: n }, () => ({
        x: Math.random() * W,
        y: Math.random() * H,
        age: Math.random() * 200,
        life: 140 + Math.random() * 200,
        speed: 0.6 + Math.random() * 1.0,
      }));
    };

    const seedAscii = () => {
      const cellW = 9, cellH = 12;
      asciiCols = Math.max(1, Math.floor(W / cellW));
      asciiRows = Math.max(1, Math.floor(H / cellH));
      asciiCells = new Array(asciiCols * asciiRows).fill(0).map(() => ({
        glyph: Math.floor(Math.random() * ASCII_GLYPHS.length),
        alpha: 0,
      }));
    };

    // ── Resize ────────────────────────────────────────────────────────────
    const resize = () => {
      const r = wrap.getBoundingClientRect();
      W = Math.max(1, Math.floor(r.width));
      H = Math.max(1, Math.floor(r.height));
      canvas.width  = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width  = `${W}px`;
      canvas.style.height = `${H}px`;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);
      switch (mode) {
        case "rain":  seedRain();  break;
        case "tape":  seedTape();  break;
        case "mesh":  seedMesh();  break;
        case "flow":  seedFlow();  break;
        case "ascii": seedAscii(); break;
      }
    };
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    resize();

    // ── Surface-aware wash (so trails fade to surface, not always black) ──
    const surfaceWash = (alpha: number) => {
      const [sr, sg, sb] = palette.surface;
      ctx.fillStyle = `rgba(${sr},${sg},${sb},${alpha})`;
      ctx.fillRect(0, 0, W, H);
    };

    // ── Drawers ───────────────────────────────────────────────────────────
    const drawRain = () => {
      surfaceWash(0.18);
      const [cr, cg, cb] = palette.rgb;
      const boost = lightBoost();
      for (const d of drops) {
        d.y += d.speed;
        if (d.y - d.len > H) {
          d.y = -d.len; d.x = Math.random() * W;
          d.speed = 0.4 + Math.random() * 1.4;
          d.alpha = 0.15 + Math.random() * 0.6;
        }
        const grad = ctx.createLinearGradient(d.x, d.y - d.len, d.x, d.y);
        grad.addColorStop(0, `rgba(${cr},${cg},${cb},0)`);
        grad.addColorStop(1, `rgba(${cr},${cg},${cb},${d.alpha * intensity * boost})`);
        ctx.strokeStyle = grad;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(d.x, d.y - d.len);
        ctx.lineTo(d.x, d.y);
        ctx.stroke();
      }
    };

    const drawTape = () => {
      surfaceWash(0.16);
      const [cr, cg, cb] = palette.rgb;
      const boost = lightBoost();
      ctx.strokeStyle = `rgba(${cr},${cg},${cb},${0.05 * intensity * boost})`;
      ctx.lineWidth = 1;
      for (const by of bands) {
        const y = by * H;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(W, y);
        ctx.stroke();
      }
      for (const p of glides) {
        p.x += p.vx;
        if (p.x - p.r > W) {
          p.x = -p.r;
          if (Math.random() < 0.25 && bands.length > 0) {
            const bi = Math.floor(Math.random() * bands.length);
            p.y = bands[bi] * H + (Math.random() - 0.5) * 18;
            p.band = bi;
          }
        }
        const grad = ctx.createLinearGradient(p.x - 14, p.y, p.x, p.y);
        grad.addColorStop(0, `rgba(${cr},${cg},${cb},0)`);
        grad.addColorStop(1, `rgba(${cr},${cg},${cb},${p.alpha * intensity * boost})`);
        ctx.strokeStyle = grad;
        ctx.lineWidth = p.r;
        ctx.beginPath();
        ctx.moveTo(p.x - 14, p.y);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
        ctx.fillStyle = `rgba(${cr},${cg},${cb},${Math.min(1, p.alpha * 1.2) * intensity * boost})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const drawMesh = (t: number) => {
      surfaceWash(0.10);
      const [cr, cg, cb] = palette.rgb;
      const boost = lightBoost();
      ctx.lineWidth = 1;
      for (const [a, b, base] of edges) {
        ctx.strokeStyle = `rgba(${cr},${cg},${cb},${base * intensity * boost})`;
        ctx.beginPath();
        ctx.moveTo(nodes[a].x, nodes[a].y);
        ctx.lineTo(nodes[b].x, nodes[b].y);
        ctx.stroke();
      }
      if (Math.random() < 0.05 && edges.length > 0) {
        const ei = Math.floor(Math.random() * edges.length);
        const [a, b] = edges[ei];
        sparks.push({
          from: Math.random() < 0.5 ? a : b,
          to:   Math.random() < 0.5 ? b : a,
          t: 0, dur: 600 + Math.random() * 700,
        });
      }
      sparks = sparks.filter((s) => {
        s.t += 16;
        const k = Math.min(1, s.t / s.dur);
        const x = nodes[s.from].x + (nodes[s.to].x - nodes[s.from].x) * k;
        const y = nodes[s.from].y + (nodes[s.to].y - nodes[s.from].y) * k;
        const a = (1 - k) * intensity * boost;
        const grd = ctx.createRadialGradient(x, y, 0, x, y, 9);
        grd.addColorStop(0, `rgba(${cr},${cg},${cb},${0.85 * a})`);
        grd.addColorStop(1, `rgba(${cr},${cg},${cb},0)`);
        ctx.fillStyle = grd;
        ctx.fillRect(x - 9, y - 9, 18, 18);
        ctx.fillStyle = `rgba(${cr},${cg},${cb},${a})`;
        ctx.beginPath();
        ctx.arc(x, y, 1.6, 0, Math.PI * 2);
        ctx.fill();
        return k < 1;
      });
      for (const n of nodes) {
        const pulse = 0.55 + 0.45 * Math.sin(n.phase + t * n.freq);
        const a = (0.35 + pulse * 0.45) * intensity * boost;
        ctx.fillStyle = `rgba(${cr},${cg},${cb},${a})`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r * (0.85 + pulse * 0.4), 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const drawFlow = (t: number) => {
      // Long-trail wash so curling streamlines persist as Van-Gogh-esque sweeps
      surfaceWash(0.06);
      const [cr, cg, cb] = palette.rgb;
      const boost = lightBoost();
      const scale = 0.012;
      ctx.lineCap = "round";
      ctx.lineWidth = 1.1;
      for (const p of flowParts) {
        const ang = flowAngle(p.x, p.y, t, scale);
        const dx = Math.cos(ang) * p.speed;
        const dy = Math.sin(ang) * p.speed;
        const nx = p.x + dx;
        const ny = p.y + dy;
        const lifeK = p.age / p.life;
        const a = (1 - Math.abs(lifeK - 0.5) * 2) * intensity * 0.85 * boost;
        ctx.strokeStyle = `rgba(${cr},${cg},${cb},${Math.max(0, a)})`;
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(nx, ny);
        ctx.stroke();
        p.x = nx; p.y = ny; p.age += 1;
        if (p.age > p.life || p.x < -4 || p.x > W + 4 || p.y < -4 || p.y > H + 4) {
          p.x = Math.random() * W;
          p.y = Math.random() * H;
          p.age = 0;
          p.life = 140 + Math.random() * 200;
          p.speed = 0.6 + Math.random() * 1.0;
        }
      }
    };

    const drawAscii = (t: number) => {
      surfaceWash(palette.light ? 0.22 : 0.20);
      const [cr, cg, cb] = palette.rgb;
      const boost = lightBoost();
      const cellW = W / asciiCols;
      const cellH = H / asciiRows;
      ctx.font = `${Math.max(8, Math.min(13, cellH * 0.95))}px ui-monospace, "JetBrains Mono", Consolas, monospace`;
      ctx.textBaseline = "top";

      const tt = t * 0.0015;
      // Three traveling wave centers create geometric interference (diamonds, rings)
      const c1x = (Math.sin(tt * 0.7) * 0.4 + 0.5) * asciiCols;
      const c1y = (Math.cos(tt * 0.9) * 0.4 + 0.5) * asciiRows;
      const c2x = (Math.cos(tt * 1.1) * 0.4 + 0.5) * asciiCols;
      const c2y = (Math.sin(tt * 0.5) * 0.4 + 0.5) * asciiRows;

      for (let r = 0; r < asciiRows; r++) {
        for (let c = 0; c < asciiCols; c++) {
          const i = r * asciiCols + c;
          const cell = asciiCells[i];
          // Manhattan + radial waves → ascii-friendly geometric patterns
          const d1 = Math.abs(c - c1x) + Math.abs(r - c1y);                 // diamond
          const d2 = Math.hypot(c - c2x, r - c2y);                          // ring
          const w = Math.sin(d1 * 0.45 - tt * 4.0)
                  + Math.cos(d2 * 0.55 - tt * 3.0);
          // Map wave to glyph index range
          const norm = (w + 2) / 4; // 0..1
          const target = Math.floor(norm * (ASCII_GLYPHS.length - 1));
          // Slow advection of glyph (avoids strobing)
          if (Math.random() < 0.06) cell.glyph = target;
          // Cell alpha tracks wave amplitude for depth
          const amp = Math.max(0, norm - 0.35) / 0.65;
          cell.alpha += (amp - cell.alpha) * 0.18;

          if (cell.alpha < 0.05) continue;
          const a = cell.alpha * intensity * boost;
          ctx.fillStyle = `rgba(${cr},${cg},${cb},${a})`;
          ctx.fillText(ASCII_GLYPHS[cell.glyph], c * cellW, r * cellH);
        }
      }
    };

    // ── Loop ──────────────────────────────────────────────────────────────
    let raf = 0;
    let alive = true;
    const tick = (t: number) => {
      if (!alive) return;
      if (document.hidden) { raf = requestAnimationFrame(tick); return; }
      switch (mode) {
        case "rain":  drawRain();    break;
        case "tape":  drawTape();    break;
        case "mesh":  drawMesh(t);   break;
        case "flow":  drawFlow(t);   break;
        case "ascii": drawAscii(t);  break;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("nexus-theme-change", onTheme);
    };
  }, [mode, intensity, density]);

  return (
    <div
      ref={wrapRef}
      className={className}
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        zIndex: 0,
        overflow: "hidden",
        ...(edgeToEdge
          ? {}
          : {
              maskImage: "radial-gradient(ellipse at center, #000 70%, transparent 100%)",
              WebkitMaskImage: "radial-gradient(ellipse at center, #000 70%, transparent 100%)",
            }),
      }}
      aria-hidden="true"
    >
      <canvas ref={canvasRef} style={{ display: "block" }} />
    </div>
  );
}
