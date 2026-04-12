#!/usr/bin/env python3
"""
ANIMATION LAB — minimal app for perfecting visualizer animations.

NO engine, NO audio_fx, NO beat_push, NO models, NO FX, NO presets.
Just: browser mic → FFT → render function → pixels on screen.

The browser does ALL audio processing and sends raw FFT bins.
The server renders patterns and streams frames via WebSocket.

Usage:
    cd lab
    python server.py
    # Opens http://localhost:8090
"""
import asyncio
import json
import math
import os
import time
import threading
import colorsys
import webbrowser

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
import uvicorn

app = FastAPI(title="Animation Lab")

# ─── State ───────────────────────────────────────────────────────────────────

# FFT data from browser (128 bins, 0-255)
fft_data = np.zeros(128, dtype=np.float32)
fft_lock = threading.Lock()

# Current experiment index
current_exp = 0

# Color palette
PALETTES = [
    ("Rainbow", None),  # None = default rainbow
    ("Cyberpunk", [(0, 255, 255), (255, 0, 255), (75, 0, 130)]),
    ("Sunset", [(255, 140, 0), (255, 105, 180), (46, 8, 84)]),
    ("Fire", [(255, 215, 0), (255, 69, 0), (139, 0, 0)]),
    ("Ocean", [(0, 210, 255), (58, 123, 213), (0, 12, 32)]),
    ("Forest", [(34, 139, 34), (0, 100, 0), (10, 26, 10)]),
    ("Neon", [(57, 255, 20), (0, 255, 0), (0, 34, 0)]),
    ("Royal", [(65, 105, 225), (255, 215, 0), (0, 0, 51)]),
    ("Glacier", [(240, 248, 255), (173, 216, 230), (30, 144, 255)]),
    ("Magma", [(255, 69, 0), (128, 0, 0), (255, 165, 0)]),
]
current_palette = 0

# Global speed (BPM slider: 0-200, default 120, maps to 0-1.67x speed)
global_bpm = 120

# Whether browser is sending real audio
audio_active = False
audio_last_time = 0

# Smooth state (fast attack, slow decay — like Frequency Bars)
smooth_state = np.zeros(512, dtype=np.float32)

# Panel dimensions
TEST_W, TEST_H = 24, 12
FRONT_W, FRONT_H = 72, 24
SIDE_W, SIDE_H = 220, 24
FPS = 20

# FX state
current_fx = "none"  # "none", "glow", "trail"
FX_LIST = ["none", "glow", "trail", "ghost"]

# Trail buffers (persistent frame that decays)
_trail_test = np.zeros((TEST_H, TEST_W, 3), dtype=np.float32)
_trail_front = np.zeros((FRONT_H, FRONT_W, 3), dtype=np.float32)
_trail_side = np.zeros((SIDE_H, SIDE_W, 3), dtype=np.float32)

# WebSocket clients
ws_clients = set()
ws_lock = threading.Lock()


def smooth(idx, raw, attack=0.8, decay=0.92):
    """Fast attack, slow decay — the Frequency Bars secret sauce."""
    idx = idx % 512
    if raw > smooth_state[idx]:
        smooth_state[idx] = smooth_state[idx] * (1 - attack) + raw * attack
    else:
        smooth_state[idx] = smooth_state[idx] * decay + raw * (1 - decay)
    return smooth_state[idx]


def get_fft(norm_pos):
    """Get FFT value at normalized position 0-1. Returns 0-1.

    CRITICAL: Real mic FFT has energy in bins 0-50 and near-zero in 50-127.
    We compress the ENTIRE panel into bins 0-55 so the full width has data.
    Also uses log-scale so bass (bins 0-10) doesn't hog 50% of the panel.
    """
    # Log-scale within the usable range (bins 0-55)
    # norm_pos=0 → bin 0 (bass), norm_pos=1 → bin 55 (upper-mid, still has energy)
    MAX_BIN = 55  # real audio rarely has meaningful data above bin 55
    log_pos = norm_pos ** 0.7  # mild log: spread bass, compress treble
    bi = max(0, min(127, int(log_pos * MAX_BIN)))
    # Average across a wider neighborhood (±3 bins) for smoother, filled-in look
    val = 0
    total_weight = 0
    for o in range(-3, 4):
        nb = max(0, min(127, bi + o))
        w_o = 1.0 - abs(o) * 0.2  # triangle kernel
        val = max(val, fft_data[nb] / 255.0 * w_o)
    # Treble compensation: bins higher up are naturally quieter
    treble_boost = 1.0 + norm_pos * 1.5  # up to 2.5x boost at the far end
    val = min(1.0, val * treble_boost)
    return val


def _auto_normalize(vals):
    """Normalize FFT array so quietest freq → ~0, loudest → ~0.8.
    Caps at 0.8 so visuals never overflow the panel (bars leave headroom).
    Only applies when audio is active (real mic data)."""
    if not audio_active:
        return vals
    vmin = float(np.min(vals))
    vmax = float(np.max(vals))
    spread = vmax - vmin
    if spread < 0.02:
        return vals * 0.3
    # Normalize: min→0.05 (baseline visible), max→0.8 (headroom)
    normalized = (vals - vmin) / spread
    return normalized * 0.75 + 0.05


def get_col_fft(w, offset=0):
    """Pre-compute smoothed FFT for each column — auto-normalized in audio mode."""
    vals = np.zeros(w, dtype=np.float32)
    for x in range(w):
        raw = get_fft(x / max(w - 1, 1))
        vals[x] = smooth(offset + x, raw)
    return _auto_normalize(vals)


def get_col_fft_mirror(w, offset=0):
    """Mirrored FFT: edges = low freq, center = higher freq. Auto-normalized."""
    vals = np.zeros(w, dtype=np.float32)
    center = w / 2
    for x in range(w):
        dist = abs(x - center) / center
        norm = 1.0 - dist
        raw = get_fft(norm)
        vals[x] = smooth(offset + x, raw)
    return _auto_normalize(vals)


def get_radial_fft(r, max_r=5.0, offset=0):
    """Get smoothed FFT value at radius r. For radial/cymatics patterns.
    r=0 → bass (bin 0), r=max_r → upper-mid. Uses slower decay to reduce flicker."""
    r_norm = min(1.0, r / max_r)
    raw = get_fft(r_norm)
    idx = offset + int(r_norm * 50)
    # Radial patterns need more smoothing to avoid flicker (slower attack, higher decay)
    return smooth(idx, raw, attack=0.4, decay=0.95)


BRIGHTNESS_BOOST = 1.5  # global LED brightness multiplier (1.8 washed out kaleidoscopes)

def hsv(h, s=1.0, v=1.0):
    """HSV to RGB, blended with active palette, with brightness boost.
    Palette blending uses smooth cosine interpolation — no hard color edges."""
    rr, rg, rb = colorsys.hsv_to_rgb(h % 1.0, min(1, s), min(1, v))
    rr, rg, rb = rr * 255, rg * 255, rb * 255
    pal_colors = PALETTES[current_palette % len(PALETTES)][1]
    if pal_colors is None:
        boost = BRIGHTNESS_BOOST
        return int(min(255, rr * boost)), int(min(255, rg * boost)), int(min(255, rb * boost))
    # Smooth 3-color circular blend using cosine weights (no hard edges)
    # Each color gets a cosine "bump" centered at 0, 1/3, 2/3 of the cycle
    t_val = h % 1.0
    c0, c1, c2 = pal_colors[0], pal_colors[1], pal_colors[2]  # highlight, mid, shadow
    # Cosine basis: smooth bump centered at each third
    w0 = (math.cos((t_val - 0.0) * math.pi * 2) + 1) * 0.5   # peak at 0.0
    w1 = (math.cos((t_val - 0.333) * math.pi * 2) + 1) * 0.5  # peak at 0.333
    w2 = (math.cos((t_val - 0.667) * math.pi * 2) + 1) * 0.5  # peak at 0.667
    wt = w0 + w1 + w2
    if wt < 0.01:
        wt = 1.0
    w0 /= wt; w1 /= wt; w2 /= wt
    pr = c0[0] * w0 + c1[0] * w1 + c2[0] * w2
    pg = c0[1] * w0 + c1[1] * w1 + c2[1] * w2
    pb = c0[2] * w0 + c1[2] * w1 + c2[2] * w2
    # Blend 50% rainbow + 50% palette, apply brightness boost once
    blend = 0.5
    boost = BRIGHTNESS_BOOST
    fr = (rr * (1 - blend) + pr * blend) * boost
    fg = (rg * (1 - blend) + pg * blend) * boost
    fb = (rb * (1 - blend) + pb * blend) * boost
    return int(min(255, fr)), int(min(255, fg)), int(min(255, fb))


def nodal(val, thickness=0.2):
    v = max(0, 1.0 - abs(val) / thickness)
    return v * v


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENTS — each is a render function: (frame, w, h, t, col_fft) → None
#
# RULES:
#   - col_fft[x] is the smoothed FFT value for that column (0-1)
#   - In audio mode: col_fft comes from real mic FFT
#   - In default mode: col_fft comes from simulated sine waves
#   - NO beat_push, NO bass/mid/treble scalars
#   - The visual IS the FFT data at each position
# ═════════════════════════════════════════════════════════════════════════════

def exp_freq_bars(frame, w, h, t, col_fft):
    """1. Frequency Bars — the gold standard."""
    for x in range(w):
        bh = col_fft[x]
        if bh < 0.02: continue
        bar_top = int((1.0 - bh) * (h - 1))
        hue = (x / max(w-1, 1) + t * 0.05) % 1.0
        r, g, b = hsv(hue, 0.85, 1.0)
        for y in range(bar_top, h):
            frac = 1.0 - (y - bar_top) / max(1, h - 1 - bar_top)
            frame[y, x] = [int(r * (0.3 + 0.7 * frac)),
                           int(g * (0.3 + 0.7 * frac)),
                           int(b * (0.3 + 0.7 * frac))]


def exp_spectrum_mirror(frame, w, h, t, col_fft):
    """2. Mirrored bars from center — up AND down."""
    center = h // 2
    for x in range(w):
        bh = col_fft[x]
        if bh < 0.02: continue
        half = int(bh * center)
        hue = (x / max(w-1, 1) + t * 0.05) % 1.0
        r, g, b = hsv(hue, 0.85, 1.0)
        for dy in range(half + 1):
            frac = dy / max(1, half)
            pr = int(r * (0.3 + 0.7 * frac))
            pg = int(g * (0.3 + 0.7 * frac))
            pb = int(b * (0.3 + 0.7 * frac))
            if center - dy >= 0: frame[center - dy, x] = [pr, pg, pb]
            if center + dy < h: frame[center + dy, x] = [pr, pg, pb]


def exp_cym_nodal_fft(frame, w, h, t, col_fft):
    """3. Cymatics lines visible where FFT is active."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            if fv < 0.03: continue
            p = math.cos(r * 4.0) * (0.6 + 0.4 * math.cos(6 * theta))
            val = nodal(p, 0.22) * fv * 2.0
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.6 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_kal_nodal_fft(frame, w, h, t, col_fft):
    """4. Kaleidoscope visible where FFT is active."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            if fv < 0.03: continue
            sector = math.pi / 4
            si = int(theta / sector) if theta >= 0 else int(theta / sector) - 1
            la = theta - si * sector
            if si % 2 == 1: la = sector - la
            fx, fy = r * math.cos(la), r * math.sin(la)
            v = abs(math.sin(fx * 7.0)) * abs(math.cos(fy * 7.0))
            val = v * fv * 2.0
            if val > 0.03:
                hue = (la / sector * 0.5 + r * 0.4 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val))
                frame[y, x] = [rc, gc, bc]


def exp_cym_thickness(frame, w, h, t, col_fft):
    """5. Cymatics where FFT controls line thickness per column."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            thick = 0.05 + fv * 0.35
            p = math.cos(r * 4.0) * (0.6 + 0.4 * math.cos(6 * theta))
            val = nodal(p, thick) * (0.3 + fv * 1.2)
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.6 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_cym_breathing(frame, w, h, t, col_fft):
    """6. Cymatics where FFT controls spatial frequency per column."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            sf = 3.0 + fv * 6.0  # spatial freq driven by FFT
            p = math.cos(r * sf) * (0.6 + 0.4 * math.cos(6 * theta))
            val = nodal(p, 0.2 + fv * 0.15) * (0.3 + fv * 1.0)
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.6 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_wave_height(frame, w, h, t, col_fft):
    """7. Sine waves whose amplitude = FFT at each column."""
    center = h // 2
    for x in range(w):
        nx = x / max(w - 1, 1)
        fv = col_fft[x]
        if fv < 0.02: continue
        hue = (nx + t * 0.05) % 1.0
        r, g, b = hsv(hue, 0.85, 1.0)
        for i in range(3):
            amp = fv * (0.15 + i * 0.05)
            freq = 1.2 + i * 0.4
            wave_y = center + int(amp * math.sin(nx * freq * math.pi * 2 + i * 1.5) * center)
            wave_y = max(0, min(h - 1, wave_y))
            y_lo, y_hi = min(center, wave_y), max(center, wave_y)
            for y in range(y_lo, y_hi + 1):
                frac = abs(y - center) / max(1, abs(wave_y - center))
                frame[y, x] = [int(r * (0.3 + 0.7 * frac)),
                               int(g * (0.3 + 0.7 * frac)),
                               int(b * (0.3 + 0.7 * frac))]


def exp_cym_symmetry(frame, w, h, t, col_fft):
    """8. Cymatics where FFT changes angular symmetry order per column."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            n = 3.0 + fv * 8.0
            p = math.cos(r * 4.0) * math.cos(n * theta)
            val = nodal(p, 0.22) * (0.3 + fv * 1.2)
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.6 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


# ─── PATTERNS (10): waveform-style, column-based ────────────────────────────

def exp_bars_bottom(frame, w, h, t, col_fft):
    """P2. Bars from bottom — like freq bars but wider."""
    for x in range(w):
        bh = col_fft[x]
        if bh < 0.02: continue
        bar_top = int((1.0 - bh) * (h - 1))
        hue = (x / max(w-1, 1) * 0.8 + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.9, 1.0)
        for y in range(bar_top, h):
            frac = 1.0 - (y - bar_top) / max(1, h - 1 - bar_top)
            frame[y, x] = [int(r * (0.3 + 0.7 * frac)), int(g * (0.3 + 0.7 * frac)), int(b * (0.3 + 0.7 * frac))]


def exp_bars_mirror(frame, w, h, t, col_fft):
    """P3. Vertical bars spreading left/right from center — each row is a frequency."""
    # Each ROW maps to a frequency bin (low at top, high at bottom)
    row_fft = np.zeros(h, dtype=np.float32)
    for y in range(h):
        raw = get_fft(y / max(h - 1, 1))
        row_fft[y] = smooth(100 + y, raw)
    # Auto-normalize rows
    row_fft = _auto_normalize(row_fft)
    center = w // 2
    for y in range(h):
        bw = row_fft[y]  # bar width as fraction
        if bw < 0.02: continue
        half = int(bw * center)
        hue = (y / max(h-1, 1) + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.9, 1.0)
        for dx in range(half + 1):
            frac = 1.0 - dx / max(1, half)
            pr = int(r * (0.3 + 0.7 * frac))
            pg = int(g * (0.3 + 0.7 * frac))
            pb = int(b * (0.3 + 0.7 * frac))
            if center - dx >= 0: frame[y, center - dx] = [pr, pg, pb]
            if center + dx < w: frame[y, center + dx] = [pr, pg, pb]


def exp_spectrum_waterfall(frame, w, h, t, col_fft):
    """P4. Striped waterfall — smooth horizontal stripes. Extra smoothed to reduce flicker."""
    mirror_fft = get_col_fft_mirror(w, offset=270)
    # Extra smooth pass to reduce flicker
    for x in range(len(mirror_fft)):
        mirror_fft[x] = smooth(270 + x, mirror_fft[x], attack=0.4, decay=0.95)
    for y in range(h):
        ny = y / (h-1)
        # Each row is a different horizontal band — offset by time for scrolling
        row_offset = (ny + t * 0.15) % 1.0  # halved for slower scroll
        # Alternate bright/dark bands
        band = abs(math.sin(row_offset * math.pi * 6))
        for x in range(w):
            fv = mirror_fft[x]
            val = band * fv * 1.5
            if val > 0.02:
                hue = (x / max(w-1, 1) * 0.8 + row_offset * 0.3 + t * 0.02) % 1.0
                r, g, b = hsv(hue, 0.85, min(1.0, val))
                frame[y, x] = [r, g, b]


def exp_nebula(frame, w, h, t, col_fft):
    """P5. Nebula — swirling colored clouds, FFT drives intensity."""
    mirror_fft = get_col_fft_mirror(w, offset=200)
    for y in range(h):
        ny = y / (h-1)
        for x in range(w):
            nx = x / (w-1)
            fv = mirror_fft[x]
            # Multiple cloud layers
            v1 = math.sin(nx * 5 + ny * 3 + t * 0.8) * math.cos(ny * 4 - t * 0.5)
            v2 = math.cos(nx * 3 + ny * 5 - t * 0.6)
            v3 = math.sin((nx * nx + ny * ny) * 3 + t * 0.4)
            cloud = (v1 + v2 + v3 + 3) / 6.0
            val = cloud * (0.2 + fv * 1.3)
            if val > 0.03:
                hue = (cloud * 0.4 + nx * 0.3 + t * 0.02) % 1.0
                r, g, b = hsv(hue, 0.75, min(1.0, val))
                frame[y, x] = [r, g, b]


def exp_pulse_rings(frame, w, h, t, col_fft):
    """P6. Distorted ripple rings — FFT warps ring shape, creates cool interference."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            r_norm = min(1.0, r / 5.0)
            fv = smooth(300 + int(r_norm * 50), get_fft(r_norm))
            if fv < 0.02: continue
            # Distorted radius — FFT warps the rings into non-circular shapes
            # Use angle-based FFT instead of column to avoid left-side line
            a_norm = ((theta + math.pi) / (2 * math.pi))
            col_fv = smooth(350 + int(a_norm * 50), get_fft(a_norm))
            distorted_r = r + col_fv * 0.5 * math.sin(theta * 4 + r * 2)
            # Multiple ring frequencies for interference pattern
            ring1 = math.sin(distorted_r * 4.0)
            ring2 = math.sin(distorted_r * 6.0 + theta * 2) * 0.5
            val = max(0, ring1 + ring2) * fv * 1.3
            if val > 0.03:
                hue = (r_norm * 0.5 + (r * 0.15 + nx * 0.1 + 0.5) * 0.4 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_aurora(frame, w, h, t, col_fft):
    """P7. Aurora — flowing curtains of light with smooth, beautiful motion."""
    if not hasattr(exp_aurora, '_curtain'):
        exp_aurora._curtain = {}
    key = w
    if key not in exp_aurora._curtain:
        exp_aurora._curtain[key] = np.full(w, 0.3, dtype=np.float32)
    stored = exp_aurora._curtain[key]
    mirror_fft = get_col_fft_mirror(w, offset=150)
    # Target curtain heights from FFT
    target = np.zeros(w, dtype=np.float32)
    for x in range(w):
        target[x] = max(mirror_fft[x], 0.1)
    # Spatial smooth: 11-pixel kernel, 2 passes for silky curves
    for _p in range(2):
        padded = np.pad(target, (5, 5), mode='edge')
        smoothed = np.zeros_like(target)
        for dx in range(-5, 6):
            smoothed += padded[5+dx:5+dx+w] * (1.0 - abs(dx)/6.0)
        target = smoothed / sum(1.0 - abs(dx)/6.0 for dx in range(-5, 6))
    # Temporal smooth: slow chase for beautiful easing
    stored[:] = stored * 0.9 + target * 0.1
    for x in range(w):
        fv = stored[x]
        nx = x / max(w-1, 1)
        curtain_bottom = int(fv * h * 0.9)
        if curtain_bottom < 1: continue
        # Slowly shifting hue across width + gentle wave
        hue = (nx * 0.6 + math.sin(nx * 4 + t * 0.15) * 0.08 + t * 0.015) % 1.0
        r, g, b = hsv(hue, 0.65, 1.0)
        for y in range(curtain_bottom):
            depth = y / max(1, curtain_bottom)
            # Soft vertical gradient: bright at top, gentle fade
            intensity = fv * (1.0 - depth * 0.4) * (0.6 + 0.4 * math.sin(depth * 3.14))
            frame[y, x] = [int(r * intensity), int(g * intensity), int(b * intensity)]


def exp_horizon(frame, w, h, t, col_fft):
    """P8. Horizon line — bright line at FFT height, glow above and below.
    Smoothed across columns to prevent center gap on wide panels."""
    mirror_fft = get_col_fft_mirror(w, offset=200)
    # Ensure no dead zone: interpolate across gaps where fft might be low
    # Compute line heights first, then smooth them
    line_heights = np.zeros(w, dtype=np.float32)
    intensities = np.zeros(w, dtype=np.float32)
    for x in range(w):
        fv = max(mirror_fft[x], 0.08)  # minimum line visibility
        intensities[x] = fv
        line_heights[x] = (1.0 - fv) * (h - 1) * 0.8 + h * 0.1
    # Smooth line heights across 5 pixels to prevent sharp breaks
    padded = np.pad(line_heights, (2, 2), mode='edge')
    line_heights = (padded[:-4] * 0.1 + padded[1:-3] * 0.2 + padded[2:-2] * 0.4 +
                    padded[3:-1] * 0.2 + padded[4:] * 0.1)
    for x in range(w):
        fv = intensities[x]
        line_y = int(max(0, min(h-1, line_heights[x])))
        hue = (x / max(w-1, 1) * 0.7 + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.85, 1.0)
        glow_radius = max(4, int(fv * 10))
        for y in range(h):
            dist = abs(y - line_y)
            if dist == 0:
                frame[y, x] = [min(255, r + 60), min(255, g + 60), min(255, b + 60)]
            elif dist < glow_radius:
                glow = (1.0 - dist / glow_radius) * fv
                frame[y, x] = [int(r * glow), int(g * glow), int(b * glow)]


def exp_horizon_smooth(frame, w, h, t, col_fft):
    """P8b. Horizon Smooth — heavily smoothed line that follows music gently.
    Uses persistent smoothed height buffer for silky smooth motion."""
    if not hasattr(exp_horizon_smooth, '_heights'):
        exp_horizon_smooth._heights = {}
    key = w
    if key not in exp_horizon_smooth._heights:
        # Start at center
        exp_horizon_smooth._heights[key] = np.full(w, h * 0.5, dtype=np.float32)
    stored = exp_horizon_smooth._heights[key]
    mirror_fft = get_col_fft_mirror(w, offset=200)
    # Compute target heights from FFT
    target = np.zeros(w, dtype=np.float32)
    for x in range(w):
        fv = max(mirror_fft[x], 0.08)
        target[x] = (1.0 - fv) * (h - 1) * 0.8 + h * 0.1
    # Spatial smooth the target: 15-pixel wide kernel for very smooth curves
    for _pass in range(3):
        padded = np.pad(target, (7, 7), mode='edge')
        smoothed = np.zeros_like(target)
        for dx in range(-7, 8):
            weight = 1.0 - abs(dx) / 8.0
            smoothed += padded[7+dx:7+dx+w] * weight
        target = smoothed / sum(1.0 - abs(dx)/8.0 for dx in range(-7, 8))
    # Temporal smooth: stored heights chase target slowly
    chase_speed = 0.08  # very slow chase = silky smooth
    stored[:] = stored * (1.0 - chase_speed) + target * chase_speed
    # Render the smooth line with glow
    for x in range(w):
        line_y = int(max(0, min(h-1, stored[x])))
        fv = max(mirror_fft[x], 0.08)
        hue = (x / max(w-1, 1) * 0.7 + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.85, 1.0)
        glow_radius = max(5, int(fv * 12))
        for y in range(h):
            dist = abs(y - line_y)
            if dist == 0:
                frame[y, x] = [min(255, r + 60), min(255, g + 60), min(255, b + 60)]
            elif dist < glow_radius:
                glow = (1.0 - dist / glow_radius) ** 1.5 * fv
                frame[y, x] = [int(r * glow), int(g * glow), int(b * glow)]


def exp_plasma_fft(frame, w, h, t, col_fft):
    """P9. Plasma clouds — FFT modulates plasma. No center gap."""
    mirror_fft = get_col_fft_mirror(w, offset=250)
    # Overall energy for base visibility
    overall = max(0.15, sum(col_fft) / max(len(col_fft), 1))
    for y in range(h):
        ny = y / (h-1)
        for x in range(w):
            nx = x / (w-1)
            fv = max(mirror_fft[x], overall * 0.5)  # never fully dark
            v1 = math.sin(nx * 6 + t * 1.2) * math.cos(ny * 5 - t * 0.6)
            v2 = math.cos(nx * 4 + ny * 3 + t * 0.4)
            v3 = math.sin(math.sqrt(nx*nx + ny*ny) * 4 + t * 0.8)
            plasma = (v1 + v2 + v3 + 3) / 6.0
            val = plasma * fv * 1.5
            if val > 0.03:
                hue = (plasma * 0.5 + nx * 0.3 + t * 0.02) % 1.0
                r, g, b = hsv(hue, 0.8, min(1.0, val))
                frame[y, x] = [r, g, b]


# ─── CYMATICS (10): radial patterns with FFT ────────────────────────────────

def exp_cym_radial(frame, w, h, t, col_fft):
    """C1. Cymatics — FFT mapped to RADIUS (centered, symmetric)."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            # FFT at this radius — symmetric!
            r_norm = min(1.0, r / 5.0)
            fv = smooth(350 + int(r_norm * 50), get_fft(r_norm))
            if fv < 0.03: continue
            p = math.cos(r * 4.0) * (0.6 + 0.4 * math.cos(6 * theta))
            val = nodal(p, 0.22) * fv * 2.0
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.6 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_cym_mirror(frame, w, h, t, col_fft):
    """C2. Cymatics — mirrored FFT (symmetric left/right)."""
    aspect = w / max(h, 1)
    mirror_fft = get_col_fft_mirror(w, offset=400)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = mirror_fft[x]
            thick = 0.05 + fv * 0.35
            p = math.cos(r * 4.0) * (0.6 + 0.4 * math.cos(6 * theta))
            val = nodal(p, thick) * (0.3 + fv * 1.2)
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.6 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_cym_spatial(frame, w, h, t, col_fft):
    """C3. Cymatics breathing — thick colored lines. Radial FFT."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = get_radial_fft(r, offset=380)
            sf = 3.0 + fv * 4.0
            # Even-number angular freq = no seam
            p = math.cos(r * sf) * (0.6 + 0.4 * math.cos(6 * theta))
            val = nodal(p, 0.4 + fv * 0.2) * (0.4 + fv * 0.8)  # thick, always visible
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.6 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_horizon_multi(frame, w, h, t, col_fft):
    """C4. Cardiogram — 3 lines, each a frequency band. Always visible."""
    # 3 bands: bass (bottom), mid (center), treble (top)
    bands = [
        (0.75, 0, 20, 0.0),    # bass: bottom, bins 0-20, red hue
        (0.50, 20, 60, 0.33),   # mid: center, bins 20-60, green hue
        (0.25, 60, 127, 0.66),  # treble: top, bins 60-127, blue hue
    ]
    for x in range(w):
        nx = x / max(w-1, 1)
        for base_h, fft_lo, fft_hi, hue_off in bands:
            # Get FFT energy for this band at this column
            bi = min(127, int(nx * (fft_hi - fft_lo) + fft_lo))
            raw = get_fft(bi / 127.0)
            fv = max(smooth(390 + int(hue_off * 100) + (x % 50), raw), 0.08)
            hue = (nx * 0.5 + hue_off + t * 0.02) % 1.0
            r, g, b = hsv(hue, 0.85, 1.0)
            # Cardiogram wave: amplitude from FFT
            wave = fv * 6.0 * math.sin(nx * math.pi * 3 + hue_off * 5 + t * 0.5)
            line_y = int(base_h * h + wave)
            line_y = max(2, min(h-3, line_y))
            glow_r = int(3 + fv * 3)
            for y in range(max(0, line_y - glow_r), min(h, line_y + glow_r + 1)):
                dist = abs(y - line_y)
                glow = (1.0 - dist / glow_r) * min(1.0, fv * 1.3)
                pr, pg, pb = int(r * glow), int(g * glow), int(b * glow)
                frame[y, x] = [max(frame[y, x, 0], pr), max(frame[y, x, 1], pg), max(frame[y, x, 2], pb)]


def exp_horizon_pulse(frame, w, h, t, col_fft):
    """C5. Pulsing horizon — center line that thickens/thins with FFT."""
    mirror_fft = get_col_fft_mirror(w, offset=420)
    center = h // 2
    for x in range(w):
        fv = mirror_fft[x]
        if fv < 0.02: continue
        # Line thickness driven by FFT
        thickness = int(1 + fv * (h * 0.4))
        hue = (x / max(w-1, 1) * 0.7 + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.85, 1.0)
        for y in range(max(0, center - thickness), min(h, center + thickness + 1)):
            dist = abs(y - center) / max(1, thickness)
            intensity = (1.0 - dist) * fv * 1.5
            frame[y, x] = [max(frame[y, x, 0], int(r * intensity)),
                           max(frame[y, x, 1], int(g * intensity)),
                           max(frame[y, x, 2], int(b * intensity))]


def exp_cym_rings(frame, w, h, t, col_fft):
    """C6. Concentric rings — overall energy drives ring count, smooth and beautiful."""
    aspect = w / max(h, 1)
    # Pre-compute: smooth FFT at a few radial bins (not per-pixel)
    # 10 radial zones, each very smooth
    radial_fft = np.zeros(10, dtype=np.float32)
    for zone in range(10):
        r_norm = zone / 9.0
        radial_fft[zone] = smooth(300 + zone, get_fft(r_norm), attack=0.1, decay=0.97)
    overall = smooth(310, float(np.mean(radial_fft)), attack=0.08, decay=0.97)
    # Ring frequency slowly grows with energy
    ring_freq = 3.0 + overall * 4.0
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            r_norm = min(1.0, r / 5.0)
            # Lookup smoothed radial FFT (interpolated between zones)
            zone_f = r_norm * 9.0
            z0 = min(9, int(zone_f))
            z1 = min(9, z0 + 1)
            frac = zone_f - z0
            fv = radial_fft[z0] * (1 - frac) + radial_fft[z1] * frac
            if fv < 0.03: continue
            # Beautiful concentric rings with smooth radial pattern
            ring = (math.cos(r * ring_freq + t * 0.2) + 1.0) * 0.5
            val = ring * fv * 1.3
            if val > 0.03:
                hue = (r_norm * 0.7 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val))
                frame[y, x] = [rc, gc, bc]


def exp_cym_expanding(frame, w, h, t, col_fft):
    """C7. Expanding + twirling cymatics — radial FFT (no left-side line)."""
    aspect = w / max(h, 1)
    # Overall energy — use max of top 10 bins for better sensitivity to real audio
    top_energy = float(np.sort(col_fft)[-max(1, len(col_fft)//10):].mean()) if len(col_fft) > 0 else 0
    overall = smooth(497, max(top_energy, sum(col_fft) / max(len(col_fft), 1) * 2.5), attack=0.2, decay=0.9)
    vis_radius = overall * 12.0 + 2.0  # larger base + bigger multiplier
    # Smooth rotation — responds to energy changes
    rotation = smooth(499, overall, attack=0.1, decay=0.95) * 3.0 + t * 0.08  # gentle rotation
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            if r > vis_radius: continue
            # Twist that actually moves: base rotation + energy-driven acceleration
            twist_phase = math.sin(rotation * 0.3) * 0.8 + math.cos(rotation * 0.17) * 0.4
            twisted = theta + twist_phase + r * twist_phase * 1.5
            n_ang_raw = 4.0 + smooth(498, overall, attack=0.2, decay=0.9) * 4.0
            n_ang = round(n_ang_raw)
            if n_ang < 4: n_ang = 4
            # Radial frequency pulses with time
            radial_freq = 3.0 + overall * 3.0 + math.sin(t * 0.2) * 0.5
            p = math.cos(r * radial_freq) * (0.6 + 0.4 * math.cos(n_ang * twisted))
            p2 = math.cos(r * 6.0 + t * 0.1) * math.cos((n_ang + 2) * twisted) * 0.4
            val = max(nodal(p, 0.22), nodal(p2, 0.18) * 0.5)
            edge = max(0, 1.0 - (r / vis_radius) ** 2) if vis_radius > 0.01 else 0
            val *= edge
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.6 + r * 0.4 + t * 0.03) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.5))
                frame[y, x] = [rc, gc, bc]


def exp_cym_dual(frame, w, h, t, col_fft):
    """C8. Dual cymatics — two overlapping patterns, each driven by different FFT range."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            # Bass pattern (bins 0-40)
            fv_bass = smooth(420 + x % 60, get_fft(x / max(w-1, 1) * 0.3))
            # Treble pattern (bins 60-127)
            fv_tre = smooth(480 + x % 60, get_fft(0.5 + x / max(w-1, 1) * 0.5))
            p1 = math.cos(r * 3.0) * math.cos(4 * theta)
            p2 = math.cos(r * 6.0) * math.cos(8 * theta)
            val = nodal(p1, 0.25) * fv_bass * 1.5 + nodal(p2, 0.18) * fv_tre * 1.0
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.5 + r * 0.4 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val))
                frame[y, x] = [rc, gc, bc]


def exp_cym_star(frame, w, h, t, col_fft):
    """C8. Star burst — smooth growth driven by overall energy."""
    aspect = w / max(h, 1)
    # Overall energy drives star shape (smooth growth, not twitchy)
    overall = smooth(450, sum(col_fft) / max(len(col_fft), 1), attack=0.12, decay=0.97)
    points = int(4 + overall * 8)
    ring_freq = 2.0 + overall * 3.0
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            r_norm = min(1.0, r / 5.0)
            # Per-pixel FFT only for brightness, very smooth
            fv = smooth(451 + int(r_norm * 50), get_fft(r_norm), attack=0.15, decay=0.97)
            if fv < 0.02: continue
            star = abs(math.cos(points * theta))
            ring = math.cos(r * ring_freq)
            val = (star * 0.6 + 0.4) * (max(0, ring) * 0.7 + 0.3) * fv * 1.8
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.6 + r * 0.4 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_cym_flower(frame, w, h, t, col_fft):
    """C10. Flower petals — radial FFT, no left-side line."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = get_radial_fft(r, offset=440)
            if fv < 0.02: continue
            petals = max(2, int(3 + fv * 3)) * 2  # always even = no theta discontinuity
            petal = abs(math.cos(petals * theta * 0.5))
            petal_r = fv * 1.0 * (0.5 + 0.5 * petal)
            # Soft falloff instead of hard edge
            dist = r / max(0.01, petal_r * 5)
            softness = max(0, 1.0 - dist * dist)  # quadratic falloff
            if softness > 0.01:
                inner = math.cos(r * (6 + fv * 8))
                val = softness * (0.4 + 0.6 * max(0, inner)) * fv * 1.8
                if val > 0.02:
                    hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.5 + r * 0.6 + t * 0.02) % 1.0
                    rc, gc, bc = hsv(hue, 0.75, min(1.0, val))
                    frame[y, x] = [rc, gc, bc]


# ─── KALEIDOSCOPES (10): mirror-folded patterns with FFT ────────────────────

def _kal_fold(theta, n_sectors=8):
    """Fold angle into kaleidoscope mirror sectors."""
    sector = math.pi / n_sectors
    si = int(theta / sector) if theta >= 0 else int(theta / sector) - 1
    la = theta - si * sector
    if si % 2 == 1: la = sector - la
    return la, sector


def exp_kal_radial(frame, w, h, t, col_fft):
    """K1. Kaleidoscope grid — smooth growth driven by overall energy."""
    aspect = w / max(h, 1)
    mirror_fft = get_col_fft_mirror(w, offset=500)
    # Overall energy drives grid scale (smooth growth, not per-pixel twitching)
    overall = smooth(500, sum(col_fft) / max(len(col_fft), 1), attack=0.12, decay=0.97)
    sf = 5.0 + overall * 4.0  # grid scale based on overall, not per-pixel
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = mirror_fft[x]
            if fv < 0.02: continue
            la, sec = _kal_fold(theta, 8)
            fx, fy = r * math.cos(la), r * math.sin(la)
            hline = abs(math.sin(fy * sf))
            vline = abs(math.sin(fx * sf))
            line_h = max(0, 1.0 - (1.0 - hline) * 5.0)
            line_v = max(0, 1.0 - (1.0 - vline) * 5.0)
            val = max(line_h, line_v) * fv * 1.5
            if val > 0.03:
                hue = (fx * 0.3 + fy * 0.3 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(0.85, val))
                frame[y, x] = [rc, gc, bc]


def exp_kal_thick(frame, w, h, t, col_fft):
    """K2. Kaleidoscope — FFT controls detail thickness."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            la, sec = _kal_fold(theta)
            fx, fy = r * math.cos(la), r * math.sin(la)
            v = math.sin(fx * 7) * math.cos(fy * 7)
            thick = 0.05 + fv * 0.4
            val = nodal(v, thick) * (0.3 + fv * 1.2)
            if val > 0.03:
                hue = (la / sec * 0.5 + r * 0.4 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_kal_spatial(frame, w, h, t, col_fft):
    """K3. Kaleidoscope color field — no center shape, smooth color patterns."""
    aspect = w / max(h, 1)
    mirror_fft = get_col_fft_mirror(w, offset=510)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = mirror_fft[x]
            la, sec = _kal_fold(theta, 6)
            fx, fy = r * math.cos(la), r * math.sin(la)
            sf = 4.0 + fv * 6.0
            # Larger offset pushes the pattern outward, eliminating center shape
            offset_r = r * 0.8 + 1.0
            v = math.sin(fx * sf + offset_r) * math.cos(fy * sf * 0.7 + offset_r * 0.5)
            val = max(0, v) ** 1.5 * (0.3 + fv * 0.9)
            # Aggressively fade center — r < 1.5 on the aspect-scaled space
            center_fade = min(1.0, max(0, (r - 0.3) * 2.0))
            val *= center_fade
            if val > 0.02:
                hue = (la / sec * 0.5 + r * 0.3 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(0.85, val))
                frame[y, x] = [rc, gc, bc]


def exp_kal_sectors(frame, w, h, t, col_fft):
    """K4. Kaleidoscope — FFT changes number of mirror sectors."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            n_sec = max(3, int(3 + fv * 8))
            la, sec = _kal_fold(theta, n_sec)
            fx, fy = r * math.cos(la), r * math.sin(la)
            v = abs(math.sin(fx * 6)) * abs(math.cos(fy * 6))
            val = v * (0.3 + fv * 1.2)
            if val > 0.03:
                hue = (la / sec * 0.5 + r * 0.3 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val))
                frame[y, x] = [rc, gc, bc]


def exp_kal_mirror(frame, w, h, t, col_fft):
    """K5. Kaleidoscope — mirrored FFT (symmetric)."""
    aspect = w / max(h, 1)
    mirror_fft = get_col_fft_mirror(w, offset=440)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = mirror_fft[x]
            if fv < 0.03: continue
            la, sec = _kal_fold(theta)
            fx, fy = r * math.cos(la), r * math.sin(la)
            v = abs(math.sin(fx * 7)) * abs(math.cos(fy * 7))
            val = v * (0.3 + fv * 1.2)
            if val > 0.03:
                hue = (fv * 0.5 + la / sec * 0.3 + r * 0.2 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val))
                frame[y, x] = [rc, gc, bc]


def exp_kal_crystal(frame, w, h, t, col_fft):
    """K6. Crystal kaleidoscope — sharp faceted pattern."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            la, sec = _kal_fold(theta, 6)
            sf = 6.0 + fv * 4.0
            v1 = abs(math.sin(nx * sf)) * abs(math.cos(ny * sf))
            v2 = abs(math.sin(r * (6 + fv * 3)))
            v3 = abs(math.cos(6 * theta))
            combined = v1 * 0.4 + v2 * 0.3 + v3 * 0.3
            combined *= (0.5 + 0.5 * math.cos(la * 6))
            # Sharper: use power curve to preserve fine crystal edges
            val = (combined ** 1.3) * (0.3 + fv * 0.9)
            if val > 0.02:
                hue = (la / sec * 0.5 + r * 0.4 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(0.85, val))
                frame[y, x] = [rc, gc, bc]


def exp_kal_expanding(frame, w, h, t, col_fft):
    """K7. Expanding kaleidoscope — overall energy controls visible radius."""
    aspect = w / max(h, 1)
    overall = sum(col_fft) / max(len(col_fft), 1)
    vis_radius = overall * 8.0 + 0.5
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            if r > vis_radius: continue
            theta = math.atan2(ny, nx)
            la, sec = _kal_fold(theta)
            fx, fy = r * math.cos(la), r * math.sin(la)
            v = abs(math.sin(fx * 6)) * abs(math.cos(fy * 6))
            edge = max(0, 1.0 - (r / vis_radius) ** 2) if vis_radius > 0.01 else 0
            val = v * edge * 1.5
            if val > 0.03:
                hue = (la / sec * 0.5 + r * 0.3 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val))
                frame[y, x] = [rc, gc, bc]


def exp_kal_bloom(frame, w, h, t, col_fft):
    """K8. Blooming kaleidoscope — FFT opens/closes like a flower."""
    aspect = w / max(h, 1)
    mirror_fft = get_col_fft_mirror(w, offset=460)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = mirror_fft[x]
            if fv < 0.03: continue
            la, sec = _kal_fold(theta, 6)
            # Petals open based on FFT
            petal = abs(math.cos(6 * theta * 0.5))
            petal_r = fv * 3.0 * (0.5 + 0.5 * petal)
            if r < petal_r:
                inner = math.cos(r * (6 + fv * 5))
                val = (0.3 + 0.7 * max(0, inner)) * fv * 1.5
                if val > 0.03:
                    hue = (la / sec * 0.5 + r * 0.4 + t * 0.02) % 1.0
                    rc, gc, bc = hsv(hue, 0.85, min(1.0, val))
                    frame[y, x] = [rc, gc, bc]


def exp_kal_dual(frame, w, h, t, col_fft):
    """K9. Dual kaleidoscope — bass and treble drive different layers."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv_lo = smooth(420 + x % 60, get_fft(x / max(w-1, 1) * 0.3))
            fv_hi = smooth(480 + x % 60, get_fft(0.5 + x / max(w-1, 1) * 0.5))
            la, sec = _kal_fold(theta)
            fx, fy = r * math.cos(la), r * math.sin(la)
            v1 = abs(math.sin(fx * 5)) * abs(math.cos(fy * 5)) * fv_lo * 1.5
            v2 = abs(math.sin(fx * 10)) * abs(math.cos(fy * 10)) * fv_hi * 1.0
            val = v1 + v2
            if val > 0.03:
                hue = (la / sec * 0.5 + r * 0.3 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val))
                frame[y, x] = [rc, gc, bc]


def exp_kal_web(frame, w, h, t, col_fft):
    """K10. Web kaleidoscope — overlapping harmonics create web pattern."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            la, sec = _kal_fold(theta, 6)
            fx, fy = r * math.cos(la), r * math.sin(la)
            w1 = math.cos(4 * theta) * math.cos(r * (4 + fv * 4))
            w2 = math.cos(7 * theta + math.pi/3) * math.cos(r * 6 * 0.7)
            w3 = math.cos(11 * theta + math.pi/5) * math.cos(r * 6 * 1.3)
            combined = (w1 + w2 * 0.5 + w3 * 0.3 + 1.8) / 3.6
            val = combined * combined * (0.3 + fv * 1.2)
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.4 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.5))
                frame[y, x] = [rc, gc, bc]


# ─── NEW: Patterns inspired by original app favorites ────────────────────────

def exp_sand(frame, w, h, t, col_fft):
    """Sand — Chladni nodal lines (where sand collects). FFT morphs pattern."""
    mirror_fft = get_col_fft_mirror(w, offset=280)
    for y in range(h):
        ny = y / (h-1)
        for x in range(w):
            nx = x / (w-1)
            fv = mirror_fft[x]
            # FFT morphs the Chladni mode numbers
            n = 3.0 + fv * 3.0
            m = 4.0 + fv * 2.0
            px, py = nx * math.pi, ny * math.pi
            v = math.sin(n * px) * math.sin(m * py) - math.sin(m * px) * math.sin(n * py)
            # Nodal lines (v≈0) are bright — where sand collects
            closeness = max(0, 1.0 - abs(v) * 3.0)
            val = closeness * (0.3 + fv * 1.2)
            if val > 0.03:
                hue = (nx * 0.5 + ny * 0.3 + t * 0.02) % 1.0
                r, g, b = hsv(hue, 0.6, min(1.0, val * 1.3))
                frame[y, x] = [r, g, b]


def exp_color_cycle(frame, w, h, t, col_fft):
    """Color Cycle — smooth color gradients that shift with FFT."""
    mirror_fft = get_col_fft_mirror(w, offset=290)
    for y in range(h):
        ny = y / (h-1)
        for x in range(w):
            nx = x / (w-1)
            fv = mirror_fft[x]
            # Blobby plasma pattern (not vertical lines)
            v1 = math.sin(nx * 4 + ny * 3 + t * 0.4)
            v2 = math.cos(nx * 3 - ny * 4 + t * 0.3)
            v3 = math.sin(math.sqrt(nx*nx + ny*ny) * 5 + t * 0.5)
            v = (v1 + v2 + v3 + 3) / 6.0
            val = v * (0.3 + fv * 1.2)
            if val > 0.03:
                # Hue shifts with FFT — different frequencies = different colors
                hue = (fv * 0.6 + nx * 0.3 + t * 0.03) % 1.0
                r, g, b = hsv(hue, 0.85, min(1.0, val))
                frame[y, x] = [r, g, b]


def exp_scanner(frame, w, h, t, col_fft):
    """Scanner — sweeping beam whose position and width = FFT."""
    mirror_fft = get_col_fft_mirror(w, offset=300)
    for x in range(w):
        nx = x / (w-1)
        fv = mirror_fft[x]
        if fv < 0.02: continue
        # Scan beam: bright vertical line that sweeps based on FFT position
        # Each column's brightness = how close it is to the "scan point"
        scan_pos = fv  # FFT value IS the scan position (0-1)
        dist = abs(nx - scan_pos)
        beam_val = max(0, 1.0 - dist * 5.0) * fv * 2.0
        if beam_val > 0.02:
            hue = (nx + t * 0.05) % 1.0
            r, g, b = hsv(hue, 0.85, min(1.0, beam_val))
            for y in range(h):
                frame[y, x] = [r, g, b]


def exp_bonfire(frame, w, h, t, col_fft):
    """Bonfire — tall flames with sharp wisps reaching the top."""
    if not hasattr(exp_bonfire, '_heat'):
        exp_bonfire._heat = np.zeros((48, 300), dtype=np.float32)
        exp_bonfire._frame_count = 0
    heat = exp_bonfire._heat
    bh, bw = heat.shape
    if bw < w:
        exp_bonfire._heat = np.zeros((48, max(w + 20, 240)), dtype=np.float32)
        heat = exp_bonfire._heat
        bh, bw = heat.shape
    exp_bonfire._frame_count += 1
    fc = exp_bonfire._frame_count
    # Shift UP with SLOW decay — flames reach much higher
    heat[:-1, :] = heat[1:, :] * 0.94  # was 0.88 — much slower = taller flames
    heat[-1, :] = 0
    # Inject heat at bottom 3 rows based on FFT
    mirror_fft = get_col_fft_mirror(w, offset=310)
    for x in range(min(w, bw)):
        fv = max(mirror_fft[x], 0.25)  # strong minimum heat
        heat[bh-1, x] = max(heat[bh-1, x], fv * 1.2)
        heat[bh-2, x] = max(heat[bh-2, x], fv * 0.85)
        heat[bh-3, x] = max(heat[bh-3, x], fv * 0.5)
    # Sharp wisps: inject narrow vertical streaks of intense heat that shoot upward
    # These create the sharp pointed tips at the top
    n_wisps = max(3, w // 15)
    for i in range(n_wisps):
        # Each wisp has a pseudo-random X position that drifts slowly
        wisp_x = int((math.sin(fc * 0.03 + i * 7.13) * 0.4 + 0.5) * (w - 1))
        wisp_x = max(0, min(w - 1, wisp_x))
        # Wisp intensity based on FFT at that position + random variation
        wisp_energy = mirror_fft[wisp_x] * (0.7 + 0.3 * math.sin(fc * 0.07 + i * 3.1))
        if wisp_energy > 0.15:
            # Inject heat up a tall narrow column (the wisp)
            wisp_height = int(bh * 0.6 * wisp_energy)  # wisps reach 60% of buffer height
            for dy in range(wisp_height):
                row = bh - 1 - dy
                if row < 0: break
                fade = 1.0 - (dy / max(wisp_height, 1)) ** 1.5  # sharp pointed falloff
                # Narrow: only 1-2 pixels wide
                heat[row, wisp_x] = max(heat[row, wisp_x], wisp_energy * fade * 0.9)
                if wisp_x > 0:
                    heat[row, wisp_x-1] = max(heat[row, wisp_x-1], wisp_energy * fade * 0.3)
                if wisp_x < bw - 1:
                    heat[row, wisp_x+1] = max(heat[row, wisp_x+1], wisp_energy * fade * 0.3)
    # Moderate horizontal blur — enough to kill black stripes but preserve wisp sharpness
    padded = np.pad(heat, ((0, 0), (2, 2)), mode='edge')
    blurred = (padded[:, :-4] * 0.1 + padded[:, 1:-3] * 0.2 +
               padded[:, 2:-2] * 0.4 +
               padded[:, 3:-1] * 0.2 + padded[:, 4:] * 0.1)
    heat[:, :blurred.shape[1]] = blurred
    # Very light vertical blur — preserve sharp wisp tips
    padded_v = np.pad(heat, ((1, 1), (0, 0)), mode='edge')
    heat[:, :] = (padded_v[:-2, :] * 0.15 + padded_v[1:-1, :] * 0.7 + padded_v[2:, :] * 0.15)
    # Add slight horizontal turbulence: shift alternating rows left/right
    for row in range(0, bh, 2):
        shift = int(math.sin(row * 0.5 + fc * 0.08) * 1.5)
        if shift != 0:
            heat[row, :] = np.roll(heat[row, :], shift)
    # Render to frame with fire color ramp
    for y in range(h):
        src_y = int(y / (h-1) * (bh-1))
        age = 1.0 - src_y / bh  # 1 at top, 0 at bottom
        for x in range(w):
            v = heat[src_y, x]
            if v < 0.015: continue
            v = min(1.0, v * 1.8)  # boost brightness
            if v < 0.25:
                t2 = v / 0.25
                r_c = int(t2 * 180)
                g_c = int(t2 * 20)
                b_c = 0
            elif v < 0.5:
                t2 = (v - 0.25) / 0.25
                r_c = int(180 + t2 * 75)
                g_c = int(20 + t2 * 100)
                b_c = 0
            elif v < 0.75:
                t2 = (v - 0.5) / 0.25
                r_c = 255
                g_c = int(120 + t2 * 100)
                b_c = int(t2 * 40)
            else:
                t2 = (v - 0.75) / 0.25
                r_c = 255
                g_c = int(220 + t2 * 35)
                b_c = int(40 + t2 * 160)
            # Top of flame is redder/darker
            g_c = int(g_c * (1.0 - age * 0.5))
            b_c = int(b_c * (1.0 - age * 0.7))
            frame[y, x] = [min(255, r_c), min(255, g_c), min(255, b_c)]


def exp_vortex(frame, w, h, t, col_fft):
    """Vortex — smooth swirling spiral. Overall energy drives swirl, not per-pixel FFT."""
    aspect = w / max(h, 1)
    # Use overall energy for smooth swirl — not per-pixel (which causes twitching)
    overall = smooth(320, sum(col_fft) / max(len(col_fft), 1), attack=0.15, decay=0.96)
    # Swirl phase accumulates smoothly based on energy (like default sine waves)
    swirl_speed = 0.3 + overall * 0.8
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            r_norm = min(1.0, r / 5.0)
            # Per-pixel FFT only for brightness, heavily smoothed
            fv = smooth(321 + int(r_norm * 50), get_fft(r_norm), attack=0.2, decay=0.97)
            if fv < 0.02: continue
            # Spiral arms use overall energy for frequency (smooth swirl)
            spiral_freq = 3.0 + overall * 3.0
            val = 0
            for arm in range(4):
                spiral = math.sin(4 * theta + r * spiral_freq + arm * math.pi * 0.5 + t * swirl_speed)
                val += max(0, spiral) * 0.5
            val = min(1.0, val * fv * 1.5)
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.4 + r * 0.3 + fv * 0.3 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.9, min(1.0, val))
                frame[y, x] = [rc, gc, bc]


def exp_falling(frame, w, h, t, col_fft):
    """Falling — gentle particles drifting down with soft trails."""
    mirror_fft = get_col_fft_mirror(w, offset=330)
    for x in range(w):
        fv = mirror_fft[x]
        if fv < 0.02: continue
        hue = (x / max(w-1, 1) * 0.7 + t * 0.02) % 1.0
        r, g, b = hsv(hue, 0.85, 1.0)
        # Gentle drift down
        drop_y = ((t * 0.08 + x * 0.17) % 1.0)
        py = int(drop_y * (h - 1))
        # Soft trail above
        trail_len = int(3 + fv * 6)
        for dy in range(trail_len):
            ty = py - dy
            if 0 <= ty < h:
                fade = (1.0 - dy / trail_len) ** 1.5
                intensity = fade * fv * 1.3
                frame[ty, x] = [max(frame[ty, x, 0], int(r * intensity)),
                                max(frame[ty, x, 1], int(g * intensity)),
                                max(frame[ty, x, 2], int(b * intensity))]


def exp_prism(frame, w, h, t, col_fft):
    """Prism — rainbow light splitting effect. FFT spreads the spectrum. Soft edges."""
    mirror_fft = get_col_fft_mirror(w, offset=340)
    center = h // 2
    for x in range(w):
        fv = mirror_fft[x]
        if fv < 0.02: continue
        nx = x / (w-1)
        # Rainbow spread: more FFT = wider color separation
        spread = int(fv * center * 0.8)
        if spread < 1: continue
        for dy in range(-spread, spread + 1):
            y = center + dy
            if 0 <= y < h:
                hue = (dy / max(1, spread) * 0.5 + 0.5 + nx * 0.3 + t * 0.03) % 1.0
                dist = abs(dy) / max(1, spread)
                # Soft edge: smooth cubic falloff at the outer boundary
                edge_fade = max(0, 1.0 - dist) ** 2  # squared = soft outer edge
                val = edge_fade * fv * 1.5
                r, g, b = hsv(hue, 0.9, min(1.0, val))
                frame[y, x] = [max(frame[y, x, 0], r),
                               max(frame[y, x, 1], g),
                               max(frame[y, x, 2], b)]


# ─── Previous replacement experiments ────────────────────────────────────────

def exp_horizon_dual(frame, w, h, t, col_fft):
    """Dual horizon — two flowing lines at 1/3 and 2/3 height, mirrored FFT."""
    mirror_fft = get_col_fft_mirror(w, offset=280)
    for x in range(w):
        fv = mirror_fft[x]
        if fv < 0.02: continue
        hue = (x / max(w-1, 1) * 0.7 + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.85, 1.0)
        for band_y in [h * 0.33, h * 0.67]:
            line_y = int(band_y + fv * 4 * math.sin(x * 0.05 + t))
            line_y = max(0, min(h-1, line_y))
            for y in range(h):
                dist = abs(y - line_y)
                if dist < 6:
                    glow = (1.0 - dist / 6.0) * fv * 1.5
                    pr, pg, pb = int(r * glow), int(g * glow), int(b * glow)
                    frame[y, x] = [max(frame[y, x, 0], pr), max(frame[y, x, 1], pg), max(frame[y, x, 2], pb)]


def exp_hex_grid(frame, w, h, t, col_fft):
    """Hexagonal grid — hexes grow/shrink in slow waves driven by FFT."""
    # Use extra-slow smooth for calmer animation
    mirror_fft = get_col_fft_mirror(w, offset=290)
    # Ultra-slow smoothing — 4x calmer animation
    for x in range(len(mirror_fft)):
        mirror_fft[x] = smooth(290 + x, mirror_fft[x], attack=0.03, decay=0.998)  # ultra slow
    for y in range(h):
        ny = y / (h-1)
        for x in range(w):
            nx = x / (w-1)
            fv = mirror_fft[x]
            if fv < 0.02: continue
            # Hex size modulated by FFT — creates grow/shrink wave
            hex_size = 0.08 + fv * 0.08
            hx = nx / hex_size
            hy = ny / hex_size
            if int(hy) % 2 == 1: hx += 0.5
            cx = round(hx)
            cy = round(hy)
            dx = abs(hx - cx) * 2
            dy = abs(hy - cy) * 2
            dist = max(dx, (dx + dy) / 2)
            # Hex outline — thicker with more FFT
            edge_thick = 6.0 + fv * 4.0
            edge = max(0, 1.0 - abs(dist - 0.8) * edge_thick) * fv * 2.0
            if edge > 0.03:
                hue = (nx * 0.5 + ny * 0.3 + t * 0.02) % 1.0
                r, g, b = hsv(hue, 0.8, min(1.0, edge))
                frame[y, x] = [r, g, b]


def exp_firefly(frame, w, h, t, col_fft):
    """Firefly — tiny embers with trails. More flies spawn on audio beats."""
    if not hasattr(exp_firefly, '_trail'):
        exp_firefly._trail = np.zeros((24, 220, 3), dtype=np.float32)
    trail = exp_firefly._trail
    if trail.shape[0] != h or trail.shape[1] != w:
        exp_firefly._trail = np.zeros((h, w, 3), dtype=np.float32)
        trail = exp_firefly._trail
    trail *= 0.88

    mirror_fft = get_col_fft_mirror(w, offset=310)
    # Audio energy drives fly count: base 15, up to 45 on loud beats
    overall_energy = sum(col_fft) / max(len(col_fft), 1)
    n_flies = int(12 + overall_energy * 20)
    for i in range(n_flies):
        # All flies move at similar slow speed — variety comes from phase, not speed
        speed = 0.03 + (i % 5) * 0.005  # 0.03-0.055, very slow, capped
        fx = (math.sin(t * speed + i * 2.3) * 0.4 +
              math.sin(t * speed * 1.7 + i * 0.9) * 0.3 + 0.5)
        fy = (math.cos(t * speed * 0.6 + i * 1.7) * 0.4 +
              math.cos(t * speed * 1.3 + i * 3.1) * 0.3 + 0.5)
        px = int(max(0, min(1, fx)) * (w - 1))
        py = int(max(0, min(1, fy)) * (h - 1))
        fv = mirror_fft[px] if px < len(mirror_fft) else 0.3
        if fv < 0.02: continue
        hue = (i / max(n_flies, 1) + t * 0.01) % 1.0
        r, g, b = hsv(hue, 0.75, min(1.0, fv * 2.0))
        trail[py, px] = [max(trail[py, px, 0], r * 0.9),
                         max(trail[py, px, 1], g * 0.9),
                         max(trail[py, px, 2], b * 0.9)]
        frame[py, px] = [min(255, int(r * 1.2)), min(255, int(g * 1.2)), min(255, int(b * 1.2))]
        for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
            gy, gx = py+dy, px+dx
            if 0 <= gy < h and 0 <= gx < w:
                frame[gy, gx] = [max(frame[gy, gx, 0], int(r * 0.4)),
                                 max(frame[gy, gx, 1], int(g * 0.4)),
                                 max(frame[gy, gx, 2], int(b * 0.4))]

    result = np.maximum(frame.astype(np.float32), trail)
    frame[:] = np.clip(result, 0, 255).astype(np.uint8)


def exp_circuit(frame, w, h, t, col_fft):
    """Circuit board lines — horizontal and vertical traces lit by FFT."""
    mirror_fft = get_col_fft_mirror(w, offset=320)
    for y in range(h):
        ny = y / (h-1)
        for x in range(w):
            nx = x / (w-1)
            fv = mirror_fft[x]
            if fv < 0.02: continue
            # Grid lines (thicker when louder)
            hline = abs(ny * 8 % 1.0 - 0.5) < (0.02 + fv * 0.15)
            vline = abs(nx * 12 % 1.0 - 0.5) < (0.02 + fv * 0.1)
            if hline or vline:
                val = fv * 1.5
                hue = (nx * 0.4 + ny * 0.3 + t * 0.02) % 1.0
                r, g, b = hsv(hue, 0.7, min(1.0, val))
                frame[y, x] = [r, g, b]


def exp_galaxy(frame, w, h, t, col_fft):
    """Galaxy spiral — FFT drives arm brightness with trailing glow."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            r_norm = min(1.0, r / 5.0)
            fv = smooth(480 + int(r_norm * 50), get_fft(r_norm))
            if fv < 0.02: continue
            # Two spiral arms
            arm1 = math.sin(2 * theta + r * 4.0)
            arm2 = math.sin(2 * theta + r * 4.0 + math.pi)
            val = (max(0, arm1) + max(0, arm2) * 0.5) * fv * 1.5
            if val > 0.03:
                hue = (r_norm * 0.5 + (r * 0.15 + nx * 0.1 + 0.5) * 0.4 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val))
                frame[y, x] = [rc, gc, bc]


def exp_ripple_fft(frame, w, h, t, col_fft):
    """Ripple rings — concentric expanding rings, brightness from radial FFT."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            r_norm = min(1.0, r / 5.0)
            fv = smooth(500 + int(r_norm * 40), get_fft(r_norm))
            if fv < 0.03: continue
            ring = math.sin(r * 8.0)
            val = max(0, ring) * fv * 2.0
            if val > 0.03:
                hue = (r_norm * 0.6 + t * 0.03) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val))
                frame[y, x] = [rc, gc, bc]


def exp_kal_grid(frame, w, h, t, col_fft):
    """Kaleidoscope grid — no center star, clean grid pattern that moves with FFT."""
    aspect = w / max(h, 1)
    mirror_fft = get_col_fft_mirror(w, offset=470)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = mirror_fft[x]
            if fv < 0.03: continue
            la, sec = _kal_fold(theta, 8)
            fx, fy = r * math.cos(la), r * math.sin(la)
            sf = 5.0 + fv * 5.0
            hline = abs(math.sin(fy * sf))
            vline = abs(math.sin(fx * sf))
            # Sharp grid lines using nodal approach
            line_h = max(0, 1.0 - (1.0 - hline) * 6.0)
            line_v = max(0, 1.0 - (1.0 - vline) * 6.0)
            val = max(line_h, line_v) * fv * 1.3
            if val > 0.03:
                hue = (la / sec * 0.5 + fv * 0.3 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(0.85, val))
                frame[y, x] = [rc, gc, bc]


def exp_matrix(frame, w, h, t, col_fft):
    """Matrix — digital rain using persistent trail buffer. No blackouts possible."""
    if not hasattr(exp_matrix, '_buf'):
        exp_matrix._buf = {}
    key = (w, h)
    if key not in exp_matrix._buf:
        exp_matrix._buf[key] = np.zeros((h, w, 3), dtype=np.float32)
    buf = exp_matrix._buf[key]
    # Decay: existing pixels dim each frame (creates trailing effect)
    buf *= 0.85
    col_fft_m = get_col_fft_mirror(w, offset=335)
    # Each column has a rain head that moves down. Track heads persistently.
    if not hasattr(exp_matrix, '_heads'):
        exp_matrix._heads = {}
    if key not in exp_matrix._heads:
        # Initialize: spread heads across different Y positions
        heads = []
        for x in range(w):
            # 2 heads per column at different positions
            for d in range(2):
                hy = (int(math.sin(x * 1.618 + d * 3.7) * 1000) % h)
                speed = 0.15 + (math.sin(x * 0.7 + d * 2.1) * 0.5 + 0.5) * 0.35  # 0.15-0.5 rows/frame (halved)
                heads.append([x, float(hy), speed, d])
        exp_matrix._heads[key] = heads
    heads = exp_matrix._heads[key]
    for head in heads:
        x, hy, base_speed, drop_id = head
        fv = max(col_fft_m[x], 0.2)
        # Speed: base + FFT boost
        speed = base_speed * (0.4 + fv * 0.8)  # gentler FFT influence
        hy += speed
        if hy >= h + 5:
            hy = -3.0  # reset to top
        head[1] = hy
        iy = int(hy)
        if 0 <= iy < h:
            hue = (x / max(w-1, 1) * 0.15 + 0.3 + t * 0.01) % 1.0
            r, g, b = hsv(hue, 0.7, 1.0)
            bright = fv * (1.5 if drop_id == 0 else 0.8)
            buf[iy, x] = [max(buf[iy, x, 0], r * bright),
                          max(buf[iy, x, 1], g * bright),
                          max(buf[iy, x, 2], b * bright)]
    # Copy buffer to frame
    frame[:] = np.clip(buf, 0, 255).astype(np.uint8)


def exp_firefly_trail(frame, w, h, t, col_fft):
    """Firefly with thin paint-stroke trails that slowly evaporate."""
    if not hasattr(exp_firefly_trail, '_trail'):
        exp_firefly_trail._trail = np.zeros((30, 300, 3), dtype=np.float32)
    trail = exp_firefly_trail._trail
    if trail.shape[0] < h or trail.shape[1] < w:
        exp_firefly_trail._trail = np.zeros((max(h, 30), max(w, 300), 3), dtype=np.float32)
        trail = exp_firefly_trail._trail
    # Slow evaporation — trails linger for seconds
    trail *= 0.985

    mirror_fft = get_col_fft_mirror(w, offset=315)
    overall_energy = sum(col_fft) / max(len(col_fft), 1)
    n_flies = int(6 + overall_energy * 12)
    for i in range(n_flies):
        # Slow graceful speed — variety from phase offset, not speed scaling
        speed = 0.025 + (i % 4) * 0.004  # 0.025-0.037, very slow, capped
        fx = math.sin(t * speed + i * 2.3) * 0.35 + math.sin(t * speed * 1.4 + i * 0.7) * 0.25 + 0.5
        fy = math.cos(t * speed * 0.5 + i * 1.7) * 0.35 + math.cos(t * speed * 1.1 + i * 2.9) * 0.25 + 0.5
        px = int(max(0, min(0.999, fx)) * (w - 1))
        py = int(max(0, min(0.999, fy)) * (h - 1))
        fv = mirror_fft[px] if px < len(mirror_fft) else 0.3
        if fv < 0.02: continue
        hue = (i / n_flies + t * 0.005) % 1.0
        r, g, b = hsv(hue, 0.8, min(1.0, fv * 2.0))
        # Paint a thin line: just the single pixel, high brightness
        # The trail persistence creates the "paint stroke" effect
        trail[py, px, 0] = min(255, max(trail[py, px, 0], r * 1.0))
        trail[py, px, 1] = min(255, max(trail[py, px, 1], g * 1.0))
        trail[py, px, 2] = min(255, max(trail[py, px, 2], b * 1.0))
        # Bright moving head
        frame[py, px] = [min(255, int(r * 1.5)), min(255, int(g * 1.5)), min(255, int(b * 1.5))]

    # Composite trail (the evaporating paint strokes)
    for y in range(h):
        for x in range(w):
            for c in range(3):
                frame[y, x, c] = max(frame[y, x, c], int(min(255, trail[y, x, c])))


# ─── New geometric animations inspired by reference images ───────────────────

def exp_network_globe(frame, w, h, t, col_fft):
    """Network Globe — curved mesh lines with bright nodes. Like a data sphere."""
    mirror_fft = get_col_fft_mirror(w, offset=350)
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            fv = mirror_fft[x]
            # Curved grid: sine-based mesh that curves like a sphere surface
            # Horizontal curves (latitude lines)
            lat = math.sin(ny * math.pi * 4 + nx * 0.5 + t * 0.3)
            # Vertical curves (longitude lines that converge)
            lon = math.sin(nx * 3.0 + ny * ny * 2 + t * 0.2)
            # Mesh: bright where either line is near zero (crossing lines)
            mesh = max(0, 1.0 - abs(lat) * 4.0) + max(0, 1.0 - abs(lon) * 5.0)
            # Node glow at intersections (where both are near zero)
            node = max(0, 1.0 - (abs(lat) + abs(lon)) * 3.0) * 2.0
            val = (mesh * 0.5 + node * 1.0) * (0.3 + fv * 1.2)
            if val > 0.03:
                # Cyan/pink color scheme like the reference
                hue = (nx * 0.1 + ny * 0.2 + fv * 0.3 + 0.5) % 1.0
                r, g, b = hsv(hue, 0.7, min(1.0, val))
                frame[y, x] = [r, g, b]


def exp_light_web(frame, w, h, t, col_fft):
    """Light Web — beams whose vertical position tracks FFT like frequency bars."""
    mirror_fft = get_col_fft_mirror(w, offset=360)
    aspect = w / max(h, 1)
    wave_phase = t * 0.4
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            fv = mirror_fft[x]
            # FFT drives vertical displacement — like freq bars but for beams
            fft_push = (fv - 0.3) * 0.6  # negative = beams sink, positive = rise
            warp = math.sin(nx * 1.5 + wave_phase) * 0.1
            ny_warped = ny + warp - fft_push  # FFT pushes beams up when loud
            val = 0.0
            for i in range(6):
                base_angle = i * math.pi / 6
                angle = base_angle + t * (0.08 + i * 0.02) + math.sin(t * 0.12 + i) * 0.3
                # Base beam position — FFT modulates amplitude of oscillation
                amp = 0.15 + fv * 0.25  # louder = bigger vertical swings
                beam_y = amp * math.sin(nx * 2.0 + angle) * math.cos(angle + t * 0.05)
                beam_y += math.sin(nx * 4.0 + t * 0.3 + i * 1.1) * 0.04
                beam_dist = abs(ny_warped - beam_y)
                width = 10.0 - fv * 4.0
                beam = max(0, 1.0 - beam_dist * width)
                val += beam * 0.35
            val = min(1.0, val * (0.3 + fv * 1.5))
            if val > 0.03:
                hue = (nx * 0.15 + ny * 0.1 + t * 0.03 + 0.55) % 1.0
                r, g, b = hsv(hue, 0.75, min(1.0, val))
                frame[y, x] = [r, g, b]


def exp_constellation(frame, w, h, t, col_fft):
    """Constellation — animated stars with traveling color bursts along connection rays."""
    mirror_fft = get_col_fft_mirror(w, offset=370)
    # 15 stars that drift slowly
    n_stars = 15
    stars = []
    for i in range(n_stars):
        base_x = math.sin(i * 3.7 + 1.3) * 0.5 + 0.5
        base_y = math.cos(i * 2.9 + 0.7) * 0.5 + 0.5
        # Each star drifts in a small orbit
        drift_x = math.sin(t * 0.06 + i * 1.7) * 0.04
        drift_y = math.cos(t * 0.08 + i * 2.3) * 0.04
        stars.append((max(0.02, min(0.98, base_x + drift_x)),
                       max(0.02, min(0.98, base_y + drift_y))))
    # Pre-compute connection data with traveling pulse positions
    connections = []
    for i in range(len(stars)):
        for j in range(i+1, min(i+4, len(stars))):
            sx1, sy1 = stars[i]
            sx2, sy2 = stars[j]
            seg_len = math.sqrt((sx2-sx1)**2 + (sy2-sy1)**2)
            if seg_len < 0.01: continue
            # Traveling pulse along this connection (wraps 0→1)
            pulse_pos = (t * (0.15 + i * 0.02) + j * 0.3) % 1.0
            connections.append((sx1, sy1, sx2, sy2, seg_len, pulse_pos, i))
    for y in range(h):
        ny = y / (h-1)
        for x in range(w):
            nx = x / (w-1)
            fv = mirror_fft[x]
            if fv < 0.01: continue
            val = 0.0
            hue_shift = 0.0
            # Star glow — pulses with time
            for i, (sx, sy) in enumerate(stars):
                dist = math.sqrt((nx - sx)**2 + (ny - sy)**2)
                pulse = 0.6 + 0.4 * math.sin(t * 0.3 + i * 1.2)  # brightness pulse
                glow_r = 0.06 + fv * 0.04  # glow radius grows with FFT
                if dist < glow_r:
                    star_val = max(0, (glow_r - dist) / glow_r) ** 0.8 * 1.8 * pulse
                    val += star_val
                    hue_shift += i * 0.07  # each star tints nearby pixels
            # Connection lines with traveling color bursts
            for sx1, sy1, sx2, sy2, seg_len, pulse_pos, ci in connections:
                dx, dy = sx2 - sx1, sy2 - sy1
                t_proj = max(0, min(1, ((nx-sx1)*dx + (ny-sy1)*dy) / (seg_len*seg_len)))
                px, py = sx1 + t_proj * dx, sy1 + t_proj * dy
                line_dist = math.sqrt((nx-px)**2 + (ny-py)**2)
                line_width = 0.015 + fv * 0.01
                if line_dist < line_width:
                    line_val = max(0, (line_width - line_dist) / line_width) * 0.4
                    # Traveling pulse: bright burst moving along the line
                    pulse_dist = abs(t_proj - pulse_pos)
                    pulse_dist = min(pulse_dist, 1.0 - pulse_dist)  # wrap
                    pulse_bright = max(0, 1.0 - pulse_dist * 8.0) * 1.5
                    line_val += pulse_bright * max(0, (line_width - line_dist) / line_width) * fv
                    val += line_val
                    hue_shift += pulse_bright * 0.15  # color burst shifts hue
            val = min(1.0, val * (0.3 + fv * 1.2))
            if val > 0.02:
                hue = (nx * 0.2 + ny * 0.1 + t * 0.03 + hue_shift * 0.3 + 0.6) % 1.0
                r, g, b = hsv(hue, 0.6, min(1.0, val))
                frame[y, x] = [r, g, b]


def exp_geometric_flow(frame, w, h, t, col_fft):
    """Geometric Flow — diamond grid with smooth wave distortion."""
    mirror_fft = get_col_fft_mirror(w, offset=380)
    # Overall energy for warp amount — smooth so no glitching
    overall = smooth(380, sum(col_fft) / max(len(col_fft), 1), attack=0.1, decay=0.97)
    warp_amt = 0.5 + overall * 0.5  # smooth warp multiplier
    for y in range(h):
        ny = y / (h-1)
        for x in range(w):
            nx = x / (w-1)
            fv = mirror_fft[x]
            if fv < 0.02: continue
            # Wave distortion uses smooth overall energy, not per-pixel fv
            warp_x = math.sin(ny * 6.0 + t * 0.2) * 0.15 + math.sin(ny * 3.0 - t * 0.12) * 0.1
            warp_y = math.cos(nx * 4.0 + t * 0.15) * 0.12 + math.sin(nx * 7.0 + t * 0.08) * 0.06
            nx_w = nx + warp_x * warp_amt
            ny_w = ny + warp_y * warp_amt
            # Diamond grid that flows and scales with FFT
            grid_scale = 6.0 + math.sin(t * 0.06) * 2.0  # grid breathes slowly
            gx = nx_w * grid_scale + t * 0.15
            gy = ny_w * (grid_scale * 0.5) + math.sin(t * 0.08) * 0.5
            # Diamond pattern
            dx = abs((gx % 1.0) - 0.5) * 2
            dy = abs((gy % 1.0) - 0.5) * 2
            diamond = dx + dy
            # Edge glow with pulsing thickness
            thickness = 6.0 + math.sin(t * 0.25 + nx * 3.0) * 2.0
            edge = max(0, 1.0 - abs(diamond - 0.8) * thickness)
            # Triangular subdivisions with their own distortion
            tri_phase = t * 0.35
            tri = max(0, 1.0 - abs(math.sin(gx * math.pi + tri_phase) *
                                   math.sin(gy * math.pi - tri_phase * 0.7)) * 5.0) * 0.5
            # Diagonal streaks that sweep across
            streak = max(0, 1.0 - abs(math.sin((nx_w + ny_w) * 12.0 + t * 0.6)) * 4.0) * 0.3
            val = (edge + tri + streak) * (0.3 + fv * 1.3)
            if val > 0.03:
                hue = (nx * 0.3 + ny * 0.2 + fv * 0.25 + t * 0.03 + warp_x * 0.5) % 1.0
                r, g, b = hsv(hue, 0.8, min(1.0, val))
                frame[y, x] = [r, g, b]


# ─── Pixel Font (bold block 7x9) ─────────────────────────────────────────────
# Each char is 7 wide x 9 tall — chunky bold style with serifs & weight
_FONT = {
    'J': ['0011111','0000110','0000110','0000110','0000110','0000110','1100110','1100110','0111100'],
    'O': ['0111110','1100011','1100011','1100011','1100011','1100011','1100011','1100011','0111110'],
    'L': ['1100000','1100000','1100000','1100000','1100000','1100000','1100000','1100000','1111111'],
    'Y': ['1100011','1100011','0110110','0011100','0001000','0001000','0001000','0001000','0001000'],
    'R': ['1111100','1100110','1100110','1100110','1111100','1101100','1100110','1100011','1100011'],
    'A': ['0011100','0110110','1100011','1100011','1111111','1100011','1100011','1100011','1100011'],
    'N': ['1100011','1110011','1111011','1101111','1100111','1100011','1100011','1100011','1100011'],
    'C': ['0111110','1100011','1100000','1100000','1100000','1100000','1100000','1100011','0111110'],
    'H': ['1100011','1100011','1100011','1100011','1111111','1100011','1100011','1100011','1100011'],
    'E': ['1111111','1100000','1100000','1100000','1111110','1100000','1100000','1100000','1111111'],
    ' ': ['0000000','0000000','0000000','0000000','0000000','0000000','0000000','0000000','0000000'],
}
_TICKER_TEXT = "JOLLY RANCHER"
_CHAR_W = 7
_CHAR_H = 9
_CHAR_GAP = 2  # 2px gap between chars for readability

def _render_text_bitmap():
    """Pre-render the full ticker text into a bitmap (rows of booleans)."""
    total_w = len(_TICKER_TEXT) * (_CHAR_W + _CHAR_GAP) - _CHAR_GAP
    bitmap = [[False] * total_w for _ in range(_CHAR_H)]
    cx = 0
    for ch in _TICKER_TEXT:
        glyph = _FONT.get(ch, _FONT[' '])
        for row in range(_CHAR_H):
            for col in range(_CHAR_W):
                if glyph[row][col] == '1':
                    bitmap[row][cx + col] = True
        cx += _CHAR_W + _CHAR_GAP
    return bitmap, total_w

_TICKER_BITMAP, _TICKER_TOTAL_W = _render_text_bitmap()


def exp_ticker(frame, w, h, t, col_fft):
    """JOLLY RANCHER — 3D wave text with perspective, fire trail, and FFT glow."""
    mirror_fft = get_col_fft_mirror(w, offset=390)
    # Fast scroll
    scroll_offset = t * 6.0
    scale = max(1, int(h * 0.55 / _CHAR_H))
    text_h = _CHAR_H * scale
    total_pw = _TICKER_TOTAL_W * scale
    # Add generous spacing so text re-enters cleanly
    scroll_px = int(scroll_offset * scale) % (total_pw + w + w // 2)

    # Pre-render: for each column, determine if text is present and compute 3D effects
    for x in range(w):
        fv = mirror_fft[x]
        # 3D sine wave: vertical offset per column creates a wave rolling through
        wave_y = math.sin(x * 0.04 - t * 0.8) * h * 0.18  # big vertical wave
        wave_y += math.sin(x * 0.09 + t * 0.5) * h * 0.06  # secondary ripple
        # Perspective scale: text is "closer" at wave peaks (bigger), farther in troughs
        persp = 1.0 + math.sin(x * 0.04 - t * 0.8) * 0.25
        local_scale = max(1, int(scale * persp))
        local_text_h = _CHAR_H * local_scale
        text_top = int((h - local_text_h) / 2 + wave_y)

        # FFT pushes text up (bass = rise)
        fft_push = fv * h * 0.15
        text_top -= int(fft_push)

        tx_f = x + scroll_px - w
        bmp_x = tx_f // local_scale if local_scale > 0 else -1

        if bmp_x < 0 or bmp_x >= _TICKER_TOTAL_W:
            continue

        # Check if ANY pixel in this column has text (for glow below)
        has_text_col = any(_TICKER_BITMAP[row][bmp_x] for row in range(_CHAR_H))
        if not has_text_col:
            continue

        for y in range(h):
            ty_f = y - text_top
            if ty_f < 0 or ty_f >= local_text_h:
                # Below text: fire/glow trail dripping down
                below_dist = y - (text_top + local_text_h)
                if 0 <= below_dist < 8:
                    trail_fade = (1.0 - below_dist / 8.0) ** 2
                    trail_val = trail_fade * (0.2 + fv * 0.6)
                    if trail_val > 0.02:
                        hue = (x / max(w-1,1) * 0.3 + t * 0.03 + 0.05) % 1.0
                        r, g, b = hsv(hue, 0.95, min(1.0, trail_val))
                        frame[y, x] = [max(frame[y,x,0], r), max(frame[y,x,1], g), max(frame[y,x,2], b)]
                # Above text: upward glow
                above_dist = text_top - y
                if 0 < above_dist < 5:
                    glow_fade = (1.0 - above_dist / 5.0) ** 2
                    glow_val = glow_fade * (0.15 + fv * 0.4)
                    if glow_val > 0.02:
                        hue = (x / max(w-1,1) * 0.3 + t * 0.03 + 0.55) % 1.0
                        r, g, b = hsv(hue, 0.8, min(1.0, glow_val))
                        frame[y, x] = [max(frame[y,x,0], r), max(frame[y,x,1], g), max(frame[y,x,2], b)]
                continue

            bmp_y = ty_f // local_scale
            if bmp_y < 0 or bmp_y >= _CHAR_H:
                continue

            if _TICKER_BITMAP[bmp_y][bmp_x]:
                # Letter pixel — chrome/metallic gradient
                vert_frac = ty_f / max(1, local_text_h - 1)
                # 3D lighting: top of letter bright, bottom darker
                light = 1.0 - vert_frac * 0.5
                # Specular highlight: a bright band that moves across
                spec_pos = (math.sin(t * 0.6) * 0.5 + 0.5)
                spec = max(0, 1.0 - abs(x / max(w-1,1) - spec_pos) * 4.0) * 0.4
                # Color: sweeping rainbow wave
                hue = (x / max(w-1,1) * 0.35 + t * 0.04 + math.sin(x * 0.03 - t * 0.3) * 0.1) % 1.0
                brightness = min(1.0, light * 0.8 + spec + fv * 0.25)
                r, g, b = hsv(hue, 0.7 - spec * 0.3, brightness)
                frame[y, x] = [r, g, b]
            else:
                # Inner glow between letter strokes
                glow = 0.0
                for dy in range(-1, 2):
                    by = bmp_y + dy
                    if by < 0 or by >= _CHAR_H: continue
                    for dx_g in range(-1, 2):
                        bx = bmp_x + dx_g
                        if bx < 0 or bx >= _TICKER_TOTAL_W: continue
                        if _TICKER_BITMAP[by][bx]:
                            dist = math.sqrt(dx_g*dx_g + dy*dy)
                            glow = max(glow, max(0, 1.0 - dist / 2.0))
                if glow > 0.1:
                    hue = (x / max(w-1,1) * 0.35 + t * 0.04) % 1.0
                    r, g, b = hsv(hue, 0.9, min(0.6, glow * 0.35 * (0.4 + fv)))
                    frame[y, x] = [r, g, b]


# ─── Oregon Trail pixel art ──────────────────────────────────────────────────
# 24 rows tall, ~105 cols wide. Encoded as strings: '#' = green pixel, '.' = off
# Scene: dust trail + vertical grass/dirt + ox + covered wagon with wheels
_OT_SPRITE_RAW = [
    #  dust/particles          grass/bars      ox                    yoke   wagon cover                    wagon body + wheels
    ".........................................................................................................",  # row 0
    ".........................................................................................................",  # row 1
    "...............................................................................##########...............",  # row 2 wagon cover top
    "..............................................................................############..............",  # row 3
    ".............................................................................##############.............",  # row 4
    "............................................................................################............",  # row 5
    "...........................................................................##################...........",  # row 6
    "..........................................................................##..##############..##........",  # row 7 cover sides
    ".........................................................................#....############....#........",  # row 8
    "........................................................................#.....############.....#.......",  # row 9
    ".......................................##...............................#......############......#......",  # row 10 ox horns
    "......................................####.............................########..........########......",  # row 11 wagon body top
    ".....................................##..##............................#..........................#.....",  # row 12
    "..............................##....##....##...........############...#..........................#.....",  # row 13 ox head + yoke
    ".............................####...########...........#..........#..#..........................#.....",  # row 14
    "............................######..########...........#..........#..#..........................#.....",  # row 15 ox body
    "............................######..########...........############..############################.....",  # row 16
    "...........................########.########...........#..........#..#..........................#.....",  # row 17
    "...........#...#..........########.########...........#..........#..#..........................#.....",  # row 18
    ".#.#......##..###........#.##..##..##....##...........############..#....####..........####....#.....",  # row 19 legs + wheels
    "####.....###..####......##.##..##..##....##........................#...##....##......##....##..#.....",  # row 20
    "####....####..#####....###..............................................#....#........#....#..........",  # row 21 wheel spokes
    "####...#####..######..####..............................................##..##........##..##..........",  # row 22
    "####..######..#######.#####..............................................####..........####...........",  # row 23 ground
]

def _build_ot_sprite():
    """Convert string sprite to numpy bool array."""
    rows = len(_OT_SPRITE_RAW)
    cols = max(len(r) for r in _OT_SPRITE_RAW)
    bmp = np.zeros((rows, cols), dtype=bool)
    for y, row in enumerate(_OT_SPRITE_RAW):
        for x, ch in enumerate(row):
            if ch == '#':
                bmp[y, x] = True
    return bmp, cols, rows

_OT_BITMAP, _OT_W, _OT_H = _build_ot_sprite()


def exp_oregon_trail(frame, w, h, t, col_fft):
    """Oregon Trail — classic pixel art wagon scrolling right to left."""
    mirror_fft = get_col_fft_mirror(w, offset=400)
    # Scale sprite to fill panel height
    scale = max(1, h // _OT_H)
    sprite_w = _OT_W * scale
    sprite_h = _OT_H * scale
    y_offset = (h - sprite_h) // 2  # center vertically

    # Scroll right to left — sprite starts off-screen right, exits off-screen left
    scroll_speed = 3.0  # pixels of t per frame
    total_travel = sprite_w + w
    scroll_px = int(t * scroll_speed * scale) % total_travel
    # Sprite x position: starts at w (off right), moves left
    sprite_x = w - scroll_px

    # Classic green phosphor color with slight hue variation
    overall = sum(col_fft) / max(len(col_fft), 1)

    for y in range(h):
        for x in range(w):
            # Map to sprite coordinates
            sx = x - sprite_x
            sy = y - y_offset
            if sx < 0 or sx >= sprite_w or sy < 0 or sy >= sprite_h:
                continue
            # Map scaled pixel back to bitmap
            bmp_x = sx // scale
            bmp_y = sy // scale
            if bmp_x < 0 or bmp_x >= _OT_W or bmp_y < 0 or bmp_y >= _OT_H:
                continue
            if _OT_BITMAP[bmp_y, bmp_x]:
                # Classic green phosphor with slight scanline effect
                scanline = 0.85 + 0.15 * ((y % 2) == 0)
                # Slight brightness variation across the sprite
                depth = 0.7 + 0.3 * (1.0 - bmp_y / _OT_H)
                # FFT makes the green pulse slightly
                pulse = 0.8 + overall * 0.3
                brightness = min(1.0, scanline * depth * pulse)
                # Classic phosphor green: RGB(0, 255, 0) with warm tint
                g_val = int(min(255, 220 * brightness))
                r_val = int(min(255, 30 * brightness))
                b_val = int(min(255, 10 * brightness))
                frame[y, x] = [r_val, g_val, b_val]

    # Ground line at bottom
    ground_y = min(h - 1, y_offset + sprite_h - 1)
    for x in range(w):
        # Dashed ground line
        if (x + int(t * 2)) % 6 < 4:
            fv = max(mirror_fft[x], 0.15)
            brightness = 0.3 + fv * 0.3
            frame[ground_y, x] = [int(20 * brightness), int(140 * brightness), int(8 * brightness)]

    # Dust particles behind the wagon
    if not hasattr(exp_oregon_trail, '_dust'):
        exp_oregon_trail._dust = []
    dust = exp_oregon_trail._dust
    # Spawn dust at wagon's rear (left side of sprite)
    wagon_rear_x = sprite_x + int(2 * scale)
    wagon_rear_y = y_offset + int(18 * scale)
    if len(dust) < 30 and 0 <= wagon_rear_x < w:
        dust.append([float(wagon_rear_x), float(min(h-2, wagon_rear_y)),
                     -0.5 - overall * 1.5, -0.3 - overall * 0.5, 1.0])
    # Update and render dust
    new_dust = []
    for d in dust:
        dx, dy, vx, vy, life = d
        dx += vx
        dy += vy
        vy += 0.05  # gravity
        life -= 0.04
        if life > 0 and 0 <= int(dx) < w and 0 <= int(dy) < h:
            px, py = int(dx), int(dy)
            g = int(min(255, 120 * life))
            r = int(min(255, 20 * life))
            frame[py, px] = [max(frame[py, px, 0], r),
                             max(frame[py, px, 1], g),
                             max(frame[py, px, 2], 0)]
            new_dust.append([dx, dy, vx, vy, life])
    exp_oregon_trail._dust = new_dust


EXPERIMENTS = [
    # Patterns (column-based, all symmetric or mirrored)
    ("P1 Freq Bars", exp_freq_bars),
    ("P2 Spectrum Mirror", exp_spectrum_mirror),
    ("P3 Bars Mirror", exp_bars_mirror),
    ("P4 Waterfall", exp_spectrum_waterfall),
    ("P5 Nebula", exp_nebula),
    ("P6 Pulse Rings", exp_pulse_rings),
    ("P7 Aurora", exp_aurora),
    ("P8 Horizon", exp_horizon),
    ("P8b Horizon Smooth", exp_horizon_smooth),
    ("P9 Plasma", exp_plasma_fft),
    ("P10 Sand", exp_sand),
    ("P11 Color Cycle", exp_color_cycle),
    ("P12 Scanner", exp_scanner),
    ("P13 Bonfire", exp_bonfire),
    ("P14 Matrix", exp_matrix),
    ("P15 Prism", exp_prism),
    # Cymatics / Horizon styles
    ("C1 Hex Grid", exp_hex_grid),
    ("C2 Firefly", exp_firefly),
    ("C2b Firefly Trail", lambda f,w,h,t,c: exp_firefly_trail(f,w,h,t,c)),
    ("C3 Cym Breathing", exp_cym_spatial),
    ("C5 Vortex", exp_vortex),
    ("C6 Cym Rings", exp_cym_rings),
    ("C7 Cym Expanding", exp_cym_expanding),
    ("C8 Cym Star", exp_cym_star),
    ("C10 Cym Flower", exp_cym_flower),
    # Kaleidoscopes (all symmetric)
    ("K1 Kal Radial", exp_kal_radial),
    ("K2 Kal Spatial", exp_kal_spatial),
    ("K4 Kal Grid", exp_kal_grid),
    ("K5 Kal Mirror", exp_kal_mirror),
    ("K6 Kal Crystal", exp_kal_crystal),
    ("K7 Circuit", exp_circuit),
    # New geometric animations
    ("G1 Network Globe", exp_network_globe),
    ("G2 Light Web", exp_light_web),
    ("G3 Geometric Flow", exp_geometric_flow),
    # Special
    ("Oregon Trail", exp_oregon_trail),
]


# ─── Render Loop ─────────────────────────────────────────────────────────────

running = True

def apply_fx(frame, trail_buf):
    """Apply current FX to a rendered frame."""
    if current_fx == "glow":
        # Glow: multi-pass blur to soften hard LED edges into smooth gradients
        f = frame.astype(np.float32)
        # 3 passes of box blur for a soft, diffused look
        for _ in range(3):
            blurred = np.zeros_like(f)
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    blurred += np.roll(np.roll(f, dy, axis=0), dx, axis=1)
            f = blurred / 9.0
        # Blend: mostly blurred, some original for definition
        result = f * 0.7 + frame.astype(np.float32) * 0.3
        return np.clip(result, 0, 255).astype(np.uint8)

    elif current_fx == "trail":
        # Trail: long persistent afterglow — extreme for cool movement effects
        f = frame.astype(np.float32)
        trail_buf *= 0.92  # slow decay = long trails
        trail_buf[:] = np.maximum(trail_buf, f)  # stamp current frame
        # Color shift: old trails shift toward blue/purple
        aged = trail_buf.copy()
        # Reduce red, boost blue as trail ages
        diff = trail_buf - f
        age_mask = (diff.max(axis=2) > 10)
        aged[age_mask, 0] *= 0.85  # red fades
        aged[age_mask, 2] = np.minimum(255, aged[age_mask, 2] * 1.1)  # blue grows
        result = np.maximum(f, aged)
        return np.clip(result, 0, 255).astype(np.uint8)

    elif current_fx == "ghost":
        # Strong edge corona: bright edges bloom outward with blur
        f = frame.astype(np.float32)
        h, w = f.shape[:2]
        bright = f.max(axis=2)
        # Detect edges
        edge_map = np.zeros((h, w), dtype=np.float32)
        for y in range(1, h-1):
            for x in range(1, w-1):
                grad = (abs(float(bright[y,x]) - float(bright[y,x-1])) +
                        abs(float(bright[y,x]) - float(bright[y-1,x])) +
                        abs(float(bright[y,x]) - float(bright[y,x+1])) +
                        abs(float(bright[y,x]) - float(bright[y+1,x]))) / 4
                edge_map[y, x] = grad
        # Multi-pass blur on edge map for soft spread
        blurred_edges = edge_map.copy()
        for _ in range(3):
            tmp = np.zeros_like(blurred_edges)
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    tmp += np.roll(np.roll(blurred_edges, dy, axis=0), dx, axis=1)
            blurred_edges = tmp / 9.0
        # Apply: boost pixels proportional to blurred edge strength
        edge_boost = blurred_edges[:, :, np.newaxis] / 80.0  # normalize
        result = f + f * edge_boost * 2.0  # strong bloom
        return np.clip(result, 0, 255).astype(np.uint8)

    elif current_fx == "plasma":
        # Plasma emission: edges emit spreading colored plasma
        f = frame.astype(np.float32)
        h, w = f.shape[:2]
        trail_buf *= 0.88
        # Horizontal spread (plasma bleeds sideways)
        spread = trail_buf.copy()
        spread[:, 1:, :] = np.maximum(spread[:, 1:, :], trail_buf[:, :-1, :] * 0.6)
        spread[:, :-1, :] = np.maximum(spread[:, :-1, :], trail_buf[:, 1:, :] * 0.6)
        spread[1:, :, :] = np.maximum(spread[1:, :, :], trail_buf[:-1, :, :] * 0.5)
        trail_buf[:] = spread
        # Inject at bright edges
        bright = f.max(axis=2)
        edges = np.zeros_like(bright)
        edges[:, 1:] = np.abs(bright[:, 1:].astype(float) - bright[:, :-1].astype(float))
        inject = (edges > 20)
        trail_buf[inject] = np.maximum(trail_buf[inject], f[inject] * 0.7)
        result = np.maximum(f, trail_buf)
        return np.clip(result, 0, 255).astype(np.uint8)

    return frame


def render_loop():
    global running, ws_clients, audio_active, audio_last_time, current_fx, current_palette, global_bpm
    dt = 1.0 / FPS
    t = 0

    while running:
        t0 = time.monotonic()
        # BPM only affects DEFAULT mode speed. In AUDIO mode, t runs at fixed rate.
        if audio_active:
            t += dt  # fixed speed in audio mode
        else:
            t += dt * (global_bpm / 120.0)  # BPM slider controls default mode speed

        # Auto-deactivate audio if no FFT data for 2 seconds
        if audio_active and time.monotonic() - audio_last_time > 2.0:
            audio_active = False

        # DEFAULT mode: rich simulated FFT with traveling peaks
        if not audio_active:
            for i in range(128):
                n = i / 127.0
                v = 0
                v += 100 * max(0, math.sin(n * 6.0 + t * 1.5)) ** 3
                v += 80 * max(0, math.sin(n * 3.0 - t * 0.8)) ** 2
                v += 60 * max(0, math.cos(n * 10.0 + t * 2.5)) ** 4
                v += 40 * (0.5 + 0.5 * math.sin(n * 2.0 + t * 0.3))
                fft_data[i] = max(0, min(255, v))

        exp_name, exp_fn = EXPERIMENTS[current_exp % len(EXPERIMENTS)]

        # Render front panel
        front = np.zeros((FRONT_H, FRONT_W, 3), dtype=np.uint8)
        front_fft = get_col_fft(FRONT_W, offset=0)
        try:
            exp_fn(front, FRONT_W, FRONT_H, t, front_fft)
        except Exception as e:
            pass

        # Render side panel
        side = np.zeros((SIDE_H, SIDE_W, 3), dtype=np.uint8)
        side_fft = get_col_fft(SIDE_W, offset=100)
        try:
            exp_fn(side, SIDE_W, SIDE_H, t, side_fft)
        except Exception as e:
            pass

        # Render test panel
        test = np.zeros((TEST_H, TEST_W, 3), dtype=np.uint8)
        test_fft = get_col_fft(TEST_W, offset=200)
        try:
            exp_fn(test, TEST_W, TEST_H, t, test_fft)
        except Exception:
            pass

        # Apply FX
        test = apply_fx(test, _trail_test)
        front = apply_fx(front, _trail_front)
        side = apply_fx(side, _trail_side)

        # Pack: test + front + side
        frame_bytes = test.tobytes() + front.tobytes() + side.tobytes()

        # Send state + frame
        state = json.dumps({
            "type": "state",
            "exp_name": exp_name,
            "exp_idx": current_exp % len(EXPERIMENTS),
            "exp_count": len(EXPERIMENTS),
            "test_w": TEST_W, "test_h": TEST_H,
            "front_w": FRONT_W, "front_h": FRONT_H,
            "side_w": SIDE_W, "side_h": SIDE_H,
            "fx": current_fx,
            "palette_name": PALETTES[current_palette % len(PALETTES)][0],
            "palette_idx": current_palette % len(PALETTES),
            "palette_count": len(PALETTES),
            "bpm": global_bpm,
            "audio_active": audio_active,
        })

        with ws_lock:
            dead = set()
            for ws in ws_clients:
                try:
                    loop = ws._loop
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(ws.send_text(state), loop)
                        asyncio.run_coroutine_threadsafe(ws.send_bytes(frame_bytes), loop)
                except Exception:
                    dead.add(ws)
            ws_clients -= dead

        elapsed = time.monotonic() - t0
        sleep_time = dt - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    global current_exp, current_palette, global_bpm
    await ws.accept()
    loop = asyncio.get_event_loop()
    ws._loop = loop

    with ws_lock:
        ws_clients.add(ws)

    try:
        while True:
            raw = await ws.receive()
            if raw.get("type") == "websocket.receive" and "bytes" in raw and raw["bytes"]:
                # FFT data from browser
                data = raw["bytes"]
                if len(data) == 128:
                    global audio_active, audio_last_time
                    with fft_lock:
                        fft_data[:] = np.frombuffer(data, dtype=np.uint8).astype(np.float32)
                    audio_active = True
                    audio_last_time = time.monotonic()
                continue

            msg = raw.get("text", "")
            if not msg: continue
            data = json.loads(msg)
            cmd = data.get("cmd")

            if cmd == "next_exp":
                current_exp = (current_exp + 1) % len(EXPERIMENTS)
            elif cmd == "prev_exp":
                current_exp = (current_exp - 1) % len(EXPERIMENTS)
            elif cmd == "random_exp":
                import random as _rnd
                current_exp = _rnd.randint(0, len(EXPERIMENTS) - 1)
                current_palette = _rnd.randint(0, len(PALETTES) - 1)
            elif cmd == "next_palette":
                current_palette = (current_palette + 1) % len(PALETTES)
            elif cmd == "prev_palette":
                current_palette = (current_palette - 1) % len(PALETTES)
            elif cmd == "set_bpm":
                global_bpm = max(0, min(200, int(data.get("value", 120))))
            elif cmd == "set_fx":
                global current_fx
                current_fx = data.get("fx", "none")
                _trail_front[:] = 0
                _trail_side[:] = 0

    except WebSocketDisconnect:
        pass
    finally:
        with ws_lock:
            ws_clients.discard(ws)


@app.on_event("startup")
async def startup():
    thread = threading.Thread(target=render_loop, daemon=True)
    thread.start()
    print("\n  Animation Lab running at http://localhost:8090\n")


if __name__ == "__main__":
    threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open("http://localhost:8090")), daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="warning")
