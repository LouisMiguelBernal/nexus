"""Generate Nexus icon.ico (multi-resolution) and icon.png from scratch.

Particle-rain "N" - the static, taskbar-safe sibling of Logo.tsx. Vertical
tick lanes drawn deterministically (seeded RNG) so every build is identical;
ticks inside the N silhouette are silver-gradient, ticks outside are dim
silver flecks for ambient data-field feel.

Pure Pillow - no SVG renderer needed. Writes icon.ico (16/24/32/48/64/128/256)
and icon.png (512px) next to this file.

Run manually when the design changes:
    python electron/build-icon.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent

# Canonical master size (everything gets drawn at this resolution, then resampled)
MASTER = 512
SIZES = [16, 24, 32, 48, 64, 128, 256]

# Deterministic seed → identical output across builds
SEED = 1729

# ── Palette (matches frontend --primary silver scale) ───────────────────────
SILVER_HI  = (0xE2, 0xE2, 0xE2)
SILVER_MID = (0xC6, 0xC6, 0xC7)
SILVER_LO  = (0x6B, 0x6B, 0x6C)
OBSIDIAN_HI = (0x1A, 0x1A, 0x1A)
OBSIDIAN_LO = (0x06, 0x06, 0x06)


# ── Primitives ──────────────────────────────────────────────────────────────
def rounded_rect_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return m


def silver_gradient(size: int) -> Image.Image:
    """Diagonal silver sheen: highlight → mid → shadow."""
    g = Image.new("RGB", (size, size), 0)
    px = g.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            if t < 0.55:
                k = t / 0.55
                r = int(SILVER_HI[0] * (1 - k) + SILVER_MID[0] * k)
                gn = int(SILVER_HI[1] * (1 - k) + SILVER_MID[1] * k)
                b = int(SILVER_HI[2] * (1 - k) + SILVER_MID[2] * k)
            else:
                k = (t - 0.55) / 0.45
                r = int(SILVER_MID[0] * (1 - k) + SILVER_LO[0] * k)
                gn = int(SILVER_MID[1] * (1 - k) + SILVER_LO[1] * k)
                b = int(SILVER_MID[2] * (1 - k) + SILVER_LO[2] * k)
            px[x, y] = (r, gn, b)
    return g


def obsidian_bg(size: int) -> Image.Image:
    """Soft obsidian radial gradient - slightly brighter top-center."""
    img = Image.new("RGB", (size, size), OBSIDIAN_LO)
    px = img.load()
    cx, cy = size / 2, size * 0.4
    max_r = size * 0.85
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - cx, y - cy) / max_r
            t = min(d, 1.0)
            v = int(OBSIDIAN_HI[0] * (1 - t) + OBSIDIAN_LO[0] * t)
            px[x, y] = (v, v, v)
    return img


# ── N silhouette test (matches Logo.tsx exactly) ────────────────────────────
def in_n(x: float, y: float, size: float) -> bool:
    """Point-in-N in [0,size]² space - two verticals + diagonal strip."""
    u = (x / size) * 32.0
    v = (y / size) * 32.0
    if 4 <= u <= 10 and 4 <= v <= 28:
        return True
    if 22 <= u <= 28 and 4 <= v <= 28:
        return True
    dx, dy = 12.0, 24.0
    len_sq = dx * dx + dy * dy
    px, py = u - 10.0, v - 4.0
    t = (px * dx + py * dy) / len_sq
    if t < 0.0 or t > 1.0:
        return False
    perp = (px * -dy + py * dx) / math.sqrt(len_sq)
    return abs(perp) <= 3.8


# ── Particle field ──────────────────────────────────────────────────────────
def draw_particle_field(base: Image.Image, size: int) -> Image.Image:
    """Vertical tick lanes - silver gradient inside N, dim flecks outside."""
    rng = random.Random(SEED)

    cols   = 22
    col_w  = size / cols
    tick_h = max(2.0, size / 32.0)
    gap    = tick_h * 0.32
    stride = tick_h + gap

    # Build two binary masks: inside-N ticks vs outside-N ticks.
    in_mask  = Image.new("L", (size, size), 0)
    out_mask = Image.new("L", (size, size), 0)
    in_d  = ImageDraw.Draw(in_mask)
    out_d = ImageDraw.Draw(out_mask)

    for i in range(cols):
        x = i * col_w + col_w * 0.18
        w = col_w * 0.64
        offset = rng.uniform(0, stride)
        # Each lane carries an occasional taller "candle" tick - variety
        candle_idx = rng.randrange(0, max(2, int(size / stride)))

        k = 0
        while True:
            y = k * stride - offset
            if y >= size:
                break
            if y + tick_h > 0:
                # Per-tick height jitter (deterministic via rng)
                hv = tick_h * (1.0 if k != candle_idx else rng.uniform(1.6, 2.4))
                hv *= rng.uniform(0.85, 1.15)
                cx = x + w / 2.0
                cy = y + hv / 2.0
                if in_n(cx, cy, size):
                    in_d.rectangle((x, y, x + w, y + hv), fill=235)
                else:
                    out_d.rectangle((x, y, x + w, y + hv), fill=255)
            k += 1

    # Inside-N: silver gradient at high alpha
    grad = silver_gradient(size).convert("RGBA")
    in_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    in_layer.paste(grad, (0, 0), in_mask)

    # Outside-N: flat dim silver flecks (ambient field, never loud)
    out_flat = Image.new("RGBA", (size, size), (*SILVER_MID, 18))  # ~7% alpha
    out_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out_layer.paste(out_flat, (0, 0), out_mask)

    # Subtle bloom on the inside layer for that "live" feel - very light
    bloom = in_layer.filter(ImageFilter.GaussianBlur(radius=size * 0.006))

    base = Image.alpha_composite(base, out_layer)
    base = Image.alpha_composite(base, bloom)
    base = Image.alpha_composite(base, in_layer)
    return base


def draw_master() -> Image.Image:
    size = MASTER
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Rounded-rect obsidian body
    bg = obsidian_bg(size).convert("RGBA")
    mask = rounded_rect_mask(size, radius=int(size * 0.22))
    body = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    body.paste(bg, (0, 0), mask)
    base = Image.alpha_composite(base, body)

    # Hairline silver border (institutional crispness at small sizes)
    hair = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hair)
    hd.rounded_rectangle(
        (3, 3, size - 4, size - 4),
        radius=int(size * 0.22) - 2,
        outline=(*SILVER_MID, 46),
        width=2,
    )
    base = Image.alpha_composite(base, hair)

    # Particle field - must be clipped to the rounded body
    field_full = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    field_full = draw_particle_field(field_full, size)
    field = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    field.paste(field_full, (0, 0), mask)
    base = Image.alpha_composite(base, field)

    return base


def main() -> None:
    master = draw_master()

    png_path = HERE / "icon.png"
    master.save(png_path, "PNG")
    print(f"Wrote {png_path} ({MASTER}x{MASTER})")

    sizes = [(s, s) for s in SIZES]
    ico_path = HERE / "icon.ico"
    master.save(ico_path, format="ICO", sizes=sizes)
    print(f"Wrote {ico_path} (sizes: {SIZES})")


if __name__ == "__main__":
    main()
