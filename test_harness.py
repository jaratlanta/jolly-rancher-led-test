#!/usr/bin/env python3
"""
Test harness for waveform/cymatics pattern development.

Renders patterns at high resolution (400x400) to PNG files so we can
see exactly what the math produces before plugging into the LED app.

For each pattern, renders 5 animation frames (t=0, 1, 2, 3, 4) as a
horizontal filmstrip so you can see how it animates.

Usage:
    python test_harness.py

Output:
    test_output/pattern_name.png (filmstrip of 5 frames)
"""
import math
import os
import colorsys
import numpy as np
from PIL import Image

OUTPUT_DIR = "test_output"
FRAME_W = 800   # width per frame (wide panels are ~9:1 aspect)
FRAME_H = 88    # height per frame (matches 220:24 ratio scaled up)
NUM_FRAMES = 5
TIME_STEP = 1.0  # seconds between frames

# Also render square versions for the front panel
SQUARE_SIZE = 300

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ─── Color helpers ───────────────────────────────────────────────────────────

def hsv_rgb(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1, s), min(1, v))
    return int(r * 255), int(g * 255), int(b * 255)


# ═════════════════════════════════════════════════════════════════════════════
# PATTERN FUNCTIONS
# Each: (nx, ny, t) -> (r, g, b) tuple 0-255
# nx, ny: normalized -0.5 to 0.5 (centered)
# t: time in seconds
# ═════════════════════════════════════════════════════════════════════════════


def cymatics_mandala(nx, ny, t):
    """6-fold symmetric mandala with concentric rings and angular harmonics."""
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    n1 = 3.0 + 1.5 * math.sin(t * 0.15)
    n2 = 6.0 + 2.0 * math.sin(t * 0.1 + 1.0)
    n3 = 9.0 + 3.0 * math.sin(t * 0.08 + 2.0)
    speed = 1.0

    # Three layers — bold, fewer rings
    v1 = math.cos(r * 8.0 - t * speed) * math.cos(n1 * theta)
    v2 = math.cos(r * 14.0 + t * speed * 0.6) * math.cos(n2 * theta) * 0.5
    v3 = math.cos(r * 22.0 - t * speed * 0.3) * math.cos(n3 * theta) * 0.25

    val = max(0, min(1.0, (v1 + v2 + v3 + 1.75) / 3.5))

    # Radial fade
    fade = max(0.05, 1.0 - r * 0.15)
    val *= fade

    hue = (theta / (2.0 * math.pi) + 0.5 + t * 0.02) % 1.0
    return hsv_rgb(hue, 0.8, val)


def cymatics_star(nx, ny, t):
    """Star-burst with sharp angular peaks."""
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    points = int(6 + 2 * math.sin(t * 0.1))
    sharpness = max(1, 4.0 + 2.0 * math.sin(t * 0.15))

    star_r = 1.0 + 0.5 * abs(math.cos(points * theta + t * 0.3)) ** sharpness
    ring = math.cos(r * 10.0 * star_r - t * 0.8)
    ring2 = math.cos(r * 18.0 / star_r + t * 0.5) * 0.3

    val = max(0, min(1.0, (ring + ring2 + 1.3) / 2.6))
    fade = max(0.05, 1.0 - r * 0.15)
    val *= fade

    hue = (theta / (2.0 * math.pi) + 0.5 + t * 0.03) % 1.0
    return hsv_rgb(hue, 0.85, val)


def cymatics_radiate(nx, ny, t):
    """Radiating flower — rings expand outward perpetually like a blooming flower.

    Concentric waves move OUTWARD from center (not spinning). Angular harmonics
    create petal-like shapes in the expanding rings. Looks like a flower
    endlessly blooming open.
    """
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    petals = 6
    # Rings radiate outward (r - t creates outward motion)
    ring1 = math.cos((r * 8.0 - t * 2.0)) * (0.5 + 0.5 * math.cos(petals * theta))
    ring2 = math.cos((r * 14.0 - t * 2.0) * 0.8) * (0.5 + 0.5 * math.cos(petals * 2 * theta + math.pi/6)) * 0.5
    ring3 = math.cos((r * 22.0 - t * 2.0) * 0.6) * (0.5 + 0.5 * math.cos(petals * 3 * theta)) * 0.25

    val = max(0, min(1.0, (ring1 + ring2 + ring3 + 1.75) / 3.0))

    # Gentle fade at edges but keep detail visible far out
    fade = max(0.05, 1.0 - r * 0.15)
    val *= fade

    hue = (r * 0.8 - t * 0.3 + theta / (2.0 * math.pi) * 0.5) % 1.0
    return hsv_rgb(hue, 0.85, val)


def kaleidoscope_mirror(nx, ny, t):
    """True kaleidoscope — fold space into mirror sectors with rich inner detail.

    Like looking through a real kaleidoscope: the image is divided into
    mirror-reflected sectors. Inner patterns shift and morph creating
    endless symmetric variety. NOT spinning — the symmetry shifts and breathes.
    """
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    # 6-sector mirror fold
    sectors = 6
    sector_angle = 2.0 * math.pi / sectors
    # Fold: mirror alternating sectors
    sector_idx = int(theta / sector_angle) if theta >= 0 else int(theta / sector_angle) - 1
    local_angle = theta - sector_idx * sector_angle
    if sector_idx % 2 == 1:
        local_angle = sector_angle - local_angle  # mirror

    # Use folded coords to create inner detail
    fx = r * math.cos(local_angle)
    fy = r * math.sin(local_angle)

    # Multiple detail layers using the folded coordinates
    v1 = math.sin(fx * 8.0 + t * 0.8) * math.cos(fy * 8.0 - t * 0.5)
    v2 = math.cos(fx * 12.0 - t * 0.6) * math.sin(fy * 5.0 + t * 0.4)
    v3 = math.sin((fx + fy) * 10.0 + t * 0.3)

    # Concentric ring structure
    rings = 0.5 + 0.5 * math.cos(r * 6.0 - t * 1.0)

    combined = (v1 + v2 * 0.5 + v3 * 0.3) * 0.5 + 0.5
    combined *= rings
    val = min(1.0, max(0, combined * 1.3))

    fade = max(0.05, 1.0 - r * 0.15)
    val *= fade

    hue = (local_angle / sector_angle + r * 0.5 + t * 0.04) % 1.0
    return hsv_rgb(hue, 0.85, val)


def cymatics_pulse(nx, ny, t):
    """Pulsing cymatics — the entire pattern breathes in and out.

    Concentric nodal rings that expand and contract rhythmically.
    Angular symmetry stays fixed while the radial structure pulses.
    Good for beat-synced animation.
    """
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    # Pulse: the radial frequency oscillates (pattern breathes)
    pulse = 1.0 + 0.3 * math.sin(t * 2.0)

    n_angular = 8
    ring_freq = 8.0 * pulse

    # Main pattern: Chladni-like standing wave — bold rings
    v1 = math.cos(r * ring_freq) * math.cos(n_angular * theta)
    # Secondary harmonics
    v2 = math.cos(r * ring_freq * 1.6) * math.cos(n_angular * 2 * theta) * 0.4
    v3 = math.cos(r * ring_freq * 2.3) * math.cos(n_angular * 3 * theta + t * 0.2) * 0.2

    val = max(0, min(1.0, (v1 + v2 + v3 + 1.6) / 3.0))

    fade = max(0.05, 1.0 - r * 0.15)
    val *= fade

    hue = (theta / (2.0 * math.pi) + 0.5 + r * 0.4) % 1.0
    sat = 0.7 + 0.3 * math.sin(r * 5.0)
    return hsv_rgb(hue, sat, val)


def cymatics_ripple(nx, ny, t):
    """Concentric rings with angular modulation — interference patterns."""
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    ring_freq = 10.0 + 3.0 * math.sin(t * 0.1)
    angular = 4.0 + 2.0 * math.sin(t * 0.15)
    speed = 1.5

    ring1 = math.sin(r * ring_freq - t * speed)
    ang_mod = 1.0 + 0.4 * math.cos(angular * theta)
    ring2 = math.sin(r * ring_freq * 1.5 * ang_mod + t * speed * 0.4) * 0.4

    val = max(0, min(1.0, (ring1 * ang_mod + ring2 + 1.4) / 2.8))
    fade = max(0.05, 1.0 - r * 0.15)
    val *= fade

    hue = (r * 0.6 + theta / (2.0 * math.pi) * 0.3 + t * 0.03) % 1.0
    return hsv_rgb(hue, 0.8, val)


def cymatics_vortex(nx, ny, t):
    """Spiraling mandala — arms + rings."""
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    arms = 4
    twist = 3.0 + math.sin(t * 0.12)
    ring_n = 8.0
    rot_speed = 0.8

    spiral_theta = theta + r * twist - t * rot_speed
    spiral_wave = math.cos(arms * spiral_theta)
    rings = math.cos(r * ring_n - t * 0.6)

    val = max(0, min(1.0, (spiral_wave * 0.6 + rings * 0.4 + 1.0) / 2.0))
    fade = max(0.05, 1.0 - r * 0.15)
    val *= fade

    hue = (spiral_theta / (2.0 * math.pi) * 0.5 + r * 0.5 + t * 0.02) % 1.0
    return hsv_rgb(hue, 0.85, val)


def cymatics_web(nx, ny, t):
    """Intricate web from overlapping angular harmonics."""
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    n1 = 4.0 + math.sin(t * 0.1)
    n2 = 7.0 + math.sin(t * 0.08 + 1.0)
    n3 = 11.0 + math.sin(t * 0.06 + 2.0)
    r_mod = 10.0

    web1 = math.cos(n1 * theta) * math.cos(r * r_mod - t * 0.5)
    web2 = math.cos(n2 * theta + math.pi / 3) * math.cos(r * r_mod * 0.7 + t * 0.3)
    web3 = math.cos(n3 * theta + math.pi / 5) * math.cos(r * r_mod * 1.3 - t * 0.2)

    combined = (web1 + web2 + web3 + 3.0) / 6.0
    val = min(1.0, combined * combined * 1.5)
    fade = max(0.05, 1.0 - r * 0.15)
    val *= fade

    hue = (theta / (2.0 * math.pi) + r * 0.8 + t * 0.02) % 1.0
    return hsv_rgb(hue, 0.8, val)


def kaleidoscope_wave(nx, ny, t):
    """Kaleidoscope with flowing sine waves folded into radial symmetry."""
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    # Fold theta into 8 mirror sectors
    sector = math.pi / 4  # 8 sectors
    folded = abs((theta % sector) - sector / 2)

    # Multiple sine layers using folded angle + radius
    v1 = math.sin(r * 8.0 + folded * 5.0 - t * 1.2)
    v2 = math.cos(r * 12.0 - folded * 8.0 + t * 0.8) * 0.5
    v3 = math.sin(r * 18.0 + folded * 10.0 + t * 0.5) * 0.25

    val = max(0, min(1.0, (v1 + v2 + v3 + 1.75) / 3.5))
    fade = max(0.05, 1.0 - r * 0.15)
    val *= fade

    hue = (folded / sector + r * 0.5 + t * 0.05) % 1.0
    return hsv_rgb(hue, 0.9, val)


def kaleidoscope_crystal(nx, ny, t):
    """Crystal kaleidoscope — sharp geometric facets."""
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    # 6-sector fold
    sector = math.pi / 3
    folded = abs((theta % sector) - sector / 2)

    # Sharp crystalline patterns (using abs/mod for hard edges)
    v1 = abs(math.sin(nx * 6.0 + t * 0.5)) * abs(math.cos(ny * 6.0 - t * 0.3))
    # Radial rings
    v2 = abs(math.sin(r * 8.0 - t * 0.8))
    # Angular spokes
    v3 = abs(math.cos(6.0 * theta + t * 0.2))

    # Combine with kaleidoscope folding
    combined = v1 * 0.4 + v2 * 0.3 + v3 * 0.3
    # Apply sector symmetry by modulating with folded angle
    combined *= (0.5 + 0.5 * math.cos(folded * 6.0))

    val = min(1.0, combined * 1.5)
    fade = max(0.05, 1.0 - r * 0.15)
    val *= fade

    hue = (folded / sector * 0.5 + r * 0.4 + t * 0.03) % 1.0
    return hsv_rgb(hue, 0.85, val)


# ═════════════════════════════════════════════════════════════════════════════
# RENDER ENGINE
# ═════════════════════════════════════════════════════════════════════════════

# ─── CYMATICS (thin bright lines on dark background) ─────────────────────────
# These emulate Chladni plate nodal line patterns: mostly dark, thin bright
# geometric lines forming circles, diamonds, crosses, curves.

def _nodal_line(val, thickness=0.15):
    """Convert a wave value to a bright line where val crosses zero.
    Thicker lines = more visible on low-res LED panels."""
    v = max(0, 1.0 - abs(val) / thickness)
    return v * v  # square for sharper falloff but still thick


def cymatics_circles(nx, ny, t):
    """Cymatics with circular/oval nodal lines — bold, clearly visible."""
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)
    n, m = 3.0 + 0.5 * math.sin(t * 0.2), 4.0 + 0.5 * math.sin(t * 0.15)
    # Lower spatial frequency for bolder shapes
    p1 = math.sin(n * nx * 4.0) * math.sin(m * ny * 8.0) - math.sin(m * nx * 4.0) * math.sin(n * ny * 8.0)
    p2 = math.cos(r * 6.0 - t * 0.3) * math.cos(4.0 * theta)  # radial circles
    val = max(_nodal_line(p1, 0.18), _nodal_line(p2, 0.2) * 0.7)
    hue = (theta / (2.0 * math.pi) + 0.5 + t * 0.02) % 1.0
    return hsv_rgb(hue, 0.5, min(1.0, val * 1.2))


def cymatics_diamonds(nx, ny, t):
    """Cymatics with diamond/cross nodal patterns — bold lines."""
    n = 3.0 + 0.5 * math.sin(t * 0.18)
    m = 4.0 + 0.5 * math.cos(t * 0.12)
    # Lower freq, bolder shapes
    p1 = math.sin(n * nx * 5.0) * math.sin(m * ny * 10.0) - math.sin(m * nx * 5.0) * math.sin(n * ny * 10.0)
    p2 = math.cos(n * nx * 3.0 + t * 0.2) * math.cos(m * ny * 6.0 - t * 0.15)
    val = max(_nodal_line(p1, 0.2), _nodal_line(p2, 0.2) * 0.6)
    hue = (0.55 + nx * 0.05 + t * 0.02) % 1.0
    return hsv_rgb(hue, 0.5, min(1.0, val * 1.2))


def cymatics_grid(nx, ny, t):
    """Cymatics with rounded cross/star patterns — bold intersecting curves."""
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)
    n = 3.0 + 0.3 * math.sin(t * 0.15)
    # Star-like: radial + angular creates bold cross shapes
    p1 = math.cos(r * 5.0 - t * 0.4) + math.cos(4.0 * theta)
    p2 = math.cos(r * 8.0 + t * 0.3) * math.cos(6.0 * theta + math.pi/4)
    val = max(_nodal_line(p1, 0.25), _nodal_line(p2, 0.2) * 0.6)
    hue = (0.5 + theta / (2.0 * math.pi) * 0.2 + t * 0.015) % 1.0
    return hsv_rgb(hue, 0.55, min(1.0, val * 1.1))


def cymatics_flower(nx, ny, t):
    """Cymatics with flower/petal nodal lines."""
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)
    petals = 6
    # Radial + angular: creates flower-like nodal pattern
    p1 = math.cos(r * 8.0 + t * 0.3) * math.cos(petals * theta)
    p2 = math.cos(r * 12.0 - t * 0.2) * math.cos(petals * 2 * theta + math.pi / 6)
    combined = p1 + p2 * 0.6
    val = _nodal_line(combined, 0.12)
    # Subtle radial glow at center
    center_glow = max(0, 0.15 - r * 0.3) if r < 0.5 else 0
    val = max(val, center_glow)
    hue = (0.52 + theta / (2.0 * math.pi) * 0.15 + t * 0.02) % 1.0
    return hsv_rgb(hue, 0.5, val * 0.9)


# ─── WAVEFORMS (multiple thin flowing sine curves) ───────────────────────────
# Like an oscilloscope with many traces — 10-20 individual thin lines
# following similar but offset wave paths. NOT filled bars.

def waveform_multi_sine(nx, ny, t):
    """3 bold flowing sine waves — centered, widely spaced, clearly visible at 24px."""
    val = 0.0
    for i in range(3):
        amp = 0.12 + i * 0.06
        freq = 1.2 + i * 0.4
        phase = t * (0.5 + i * 0.15) + i * 1.5
        wave_y = amp * math.sin(nx * freq * math.pi + phase)
        dist = abs(ny - wave_y)
        line = max(0, 1.0 - dist * 15.0)  # very thick
        val = max(val, line * (0.6 + 0.4 * (i + 1) / 3))
    hue = (nx * 0.3 + t * 0.05 + ny * 1.5 + 0.5) % 1.0
    return hsv_rgb(hue, 0.8, val)


def waveform_ocean(nx, ny, t):
    """4 smooth flowing ocean waves — centered, gentle, bold curves."""
    val = 0.0
    for i in range(4):
        base_y = -0.12 + i * 0.08  # spread across center
        amp = 0.06 + 0.03 * math.sin(t * 0.3 + i * 0.7)
        freq = 1.0 + i * 0.3
        phase = t * (0.3 + i * 0.08) + i * 1.3
        wave_y = base_y + amp * math.sin(nx * freq * math.pi + phase)
        dist = abs(ny - wave_y)
        line = max(0, 1.0 - dist * 18.0)  # thick
        val = max(val, line * 0.85)
    hue = (nx * 0.4 + t * 0.03) % 1.0
    return hsv_rgb(hue, 0.75, val)


def waveform_interference(nx, ny, t):
    """2 bold crossing waves — creates interference diamonds where they meet."""
    val = 0.0
    # Wave going right
    amp1 = 0.2
    wave1 = amp1 * math.sin(nx * 1.5 * math.pi + t * 0.5)
    dist1 = abs(ny - wave1)
    val += max(0, 1.0 - dist1 * 12.0) * 0.8
    # Wave going left
    amp2 = 0.2
    wave2 = amp2 * math.sin(nx * 1.8 * math.pi - t * 0.4)
    dist2 = abs(ny - wave2)
    val += max(0, 1.0 - dist2 * 12.0) * 0.7
    # Bright at intersection
    if dist1 < 0.06 and dist2 < 0.06:
        val += 0.5
    val = min(1.0, val)
    hue = (nx * 0.4 + ny + t * 0.04) % 1.0
    return hsv_rgb(hue, 0.85, val)


def waveform_pulse(nx, ny, t):
    """Single bold pulsing wave — amplitude breathes, centered."""
    pulse = 0.5 + 0.5 * math.sin(t * 1.5)
    amp = 0.25 * (0.3 + 0.7 * pulse)
    freq = 1.5
    phase = t * 0.4
    wave_y = amp * math.sin(nx * freq * math.pi + phase)
    wave_y += amp * 0.3 * math.sin(nx * freq * 2.5 * math.pi + phase * 1.5)
    dist = abs(ny - wave_y)
    val = max(0, 1.0 - dist * 10.0)  # very thick bold wave
    hue = (0.7 + nx * 0.3 + t * 0.03) % 1.0
    return hsv_rgb(hue, 0.7, val)


PATTERNS = {
    # Kaleidoscopes (kept from previous round)
    "kaleidoscope_crystal": kaleidoscope_crystal,
    "kaleidoscope_pulse": cymatics_pulse,
    "kaleidoscope_star": cymatics_star,
    "kaleidoscope_mandala": cymatics_mandala,
    # Cymatics (thin lines, dark background)
    "cymatics_circles": cymatics_circles,
    "cymatics_diamonds": cymatics_diamonds,
    "cymatics_grid": cymatics_grid,
    "cymatics_flower": cymatics_flower,
    # Waveforms (flowing multi-line traces)
    "waveform_multi_sine": waveform_multi_sine,
    "waveform_ocean": waveform_ocean,
    "waveform_interference": waveform_interference,
    "waveform_pulse": waveform_pulse,
}


def render_pattern(func, w, h, t):
    """Render a pattern function to a numpy RGB array.

    For non-square panels: uses SQUARE coordinate space based on height,
    centered horizontally. This means the pattern is NOT stretched —
    it's rendered as a circle/square and the wide panel crops the sides.
    """
    img = np.zeros((h, w, 3), dtype=np.uint8)
    # Square coordinate space: ny goes -0.5 to 0.5 over the height
    # nx uses the SAME scale, centered, so the pattern stays circular
    aspect = w / max(h, 1)
    half_w = aspect * 0.5  # how far nx extends from center

    for y in range(h):
        ny = y / max(h - 1, 1) - 0.5  # -0.5 to 0.5
        for x in range(w):
            nx = (x / max(w - 1, 1) - 0.5) * aspect  # wider range, same scale as ny
            r, g, b = func(nx, ny, t)
            img[y, x] = [r, g, b]
    return img


def render_filmstrip(name, func):
    """Render 5 frames at panel aspect ratio + square, save as PNGs."""
    # Wide panel filmstrip (220:24 aspect)
    frames_wide = []
    for i in range(NUM_FRAMES):
        t = i * TIME_STEP
        print(f"  Wide frame {i+1}/{NUM_FRAMES} (t={t:.1f}s)...")
        frame = render_pattern(func, FRAME_W, FRAME_H, t)
        frames_wide.append(frame)

    # Stack vertically (better for wide panels)
    border_w = np.full((2, FRAME_W, 3), 40, dtype=np.uint8)
    strips = []
    for i, f in enumerate(frames_wide):
        if i > 0:
            strips.append(border_w)
        strips.append(f)
    filmstrip_wide = np.concatenate(strips, axis=0)

    path_wide = os.path.join(OUTPUT_DIR, f"{name}_wide.png")
    Image.fromarray(filmstrip_wide).save(path_wide)
    print(f"  Saved wide: {path_wide}")

    # Square filmstrip (front panel / test panel)
    frames_sq = []
    for i in range(NUM_FRAMES):
        t = i * TIME_STEP
        print(f"  Square frame {i+1}/{NUM_FRAMES} (t={t:.1f}s)...")
        frame = render_pattern(func, SQUARE_SIZE, SQUARE_SIZE, t)
        frames_sq.append(frame)

    border_s = np.full((SQUARE_SIZE, 2, 3), 40, dtype=np.uint8)
    strips = []
    for i, f in enumerate(frames_sq):
        if i > 0:
            strips.append(border_s)
        strips.append(f)
    filmstrip_sq = np.concatenate(strips, axis=1)

    path_sq = os.path.join(OUTPUT_DIR, f"{name}_square.png")
    Image.fromarray(filmstrip_sq).save(path_sq)
    print(f"  Saved square: {path_sq}")


def main():
    print(f"\nRendering {len(PATTERNS)} patterns × {NUM_FRAMES} frames @ {FRAME_W}×{FRAME_H} wide + {SQUARE_SIZE}×{SQUARE_SIZE} square")
    print(f"Output: {OUTPUT_DIR}/\n")

    for name, func in PATTERNS.items():
        print(f"[{name}]")
        render_filmstrip(name, func)
        print()

    print("Done! Open the test_output/ folder to review patterns.")


if __name__ == "__main__":
    main()
