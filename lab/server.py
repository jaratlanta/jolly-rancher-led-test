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
FX_LIST = ["none", "glow", "trail", "ghost", "plasma"]

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
    """Get smoothed FFT value at normalized position 0-1. Returns 0-1."""
    bi = max(0, min(127, int(norm_pos * 127)))
    val = fft_data[bi] / 255.0
    # Average with neighbors
    for o in [-1, 1]:
        nb = max(0, min(127, bi + o))
        val = max(val, fft_data[nb] / 255.0 * 0.7)
    return val


def get_col_fft(w, offset=0):
    """Pre-compute smoothed FFT for each column — like Frequency Bars."""
    vals = np.zeros(w, dtype=np.float32)
    for x in range(w):
        raw = get_fft(x / max(w - 1, 1))
        vals[x] = smooth(offset + x, raw)
    return vals


def get_col_fft_mirror(w, offset=0):
    """Mirrored FFT: center = high freq, edges = low freq (symmetric)."""
    vals = np.zeros(w, dtype=np.float32)
    center = w / 2
    for x in range(w):
        dist = abs(x - center) / center
        norm = 1.0 - dist
        raw = get_fft(norm)
        vals[x] = smooth(offset + x, raw)
    return vals


def get_radial_fft(r, max_r=5.0, offset=0):
    """Get smoothed FFT value at radius r. For radial/cymatics patterns.
    r=0 → bass (bin 0), r=max_r → treble (bin 127). Truly symmetric."""
    r_norm = min(1.0, r / max_r)
    raw = get_fft(r_norm)
    idx = offset + int(r_norm * 50)
    return smooth(idx, raw)


def hsv(h, s=1.0, v=1.0):
    """HSV to RGB, blended with active palette."""
    rr, rg, rb = colorsys.hsv_to_rgb(h % 1.0, min(1, s), min(1, v))
    rr, rg, rb = rr * 255, rg * 255, rb * 255
    pal_colors = PALETTES[current_palette % len(PALETTES)][1]
    if pal_colors is None:
        return int(rr), int(rg), int(rb)  # pure rainbow
    # Blend with palette: h selects between palette colors
    t_val = h % 1.0
    if t_val < 0.5:
        t2 = t_val * 2
        pc = pal_colors[2]  # shadow
        pc2 = pal_colors[1]  # mid
    else:
        t2 = (t_val - 0.5) * 2
        pc = pal_colors[1]  # mid
        pc2 = pal_colors[0]  # highlight
    pr = pc[0] + (pc2[0] - pc[0]) * t2
    pg = pc[1] + (pc2[1] - pc[1]) * t2
    pb = pc[2] + (pc2[2] - pc[2]) * t2
    # Blend 50% rainbow + 50% palette, scaled by value
    blend = 0.5
    fr = (rr * (1 - blend) + pr * blend) * v
    fg = (rg * (1 - blend) + pg * blend) * v
    fb = (rb * (1 - blend) + pb * blend) * v
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
    """P3. Mirrored bars from center — bass at edges, treble at center."""
    mirror_fft = get_col_fft_mirror(w, offset=100)
    for x in range(w):
        bh = mirror_fft[x]
        if bh < 0.02: continue
        bar_top = int((1.0 - bh) * (h - 1))
        hue = (x / max(w-1, 1) * 0.8 + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.9, 1.0)
        for y in range(bar_top, h):
            frac = 1.0 - (y - bar_top) / max(1, h - 1 - bar_top)
            frame[y, x] = [int(r * (0.3 + 0.7 * frac)), int(g * (0.3 + 0.7 * frac)), int(b * (0.3 + 0.7 * frac))]


def exp_spectrum_waterfall(frame, w, h, t, col_fft):
    """P4. Striped waterfall — smooth horizontal stripes. Extra smoothed to reduce flicker."""
    mirror_fft = get_col_fft_mirror(w, offset=270)
    # Extra smooth pass to reduce flicker
    for x in range(len(mirror_fft)):
        mirror_fft[x] = smooth(270 + x, mirror_fft[x], attack=0.4, decay=0.95)
    for y in range(h):
        ny = y / (h-1)
        # Each row is a different horizontal band — offset by time for scrolling
        row_offset = (ny + t * 0.3) % 1.0
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
    """P7. Aurora — flowing curtains of light, height driven by FFT."""
    mirror_fft = get_col_fft_mirror(w, offset=150)
    for x in range(w):
        fv = mirror_fft[x]
        if fv < 0.02: continue
        # Curtain: fills from top, wavy bottom edge
        nx = x / max(w-1, 1)
        curtain_bottom = int(fv * h * 0.9)
        hue = (nx * 0.6 + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.7, 1.0)
        for y in range(curtain_bottom):
            depth = y / max(1, curtain_bottom)
            intensity = fv * (1.0 - depth * 0.3)
            frame[y, x] = [int(r * intensity), int(g * intensity), int(b * intensity)]


def exp_horizon(frame, w, h, t, col_fft):
    """P8. Horizon line — bright line at FFT height, glow above and below."""
    mirror_fft = get_col_fft_mirror(w, offset=200)
    for x in range(w):
        fv = mirror_fft[x]
        if fv < 0.02: continue
        line_y = int((1.0 - fv) * (h - 1) * 0.8 + h * 0.1)
        line_y = max(0, min(h-1, line_y))
        hue = (x / max(w-1, 1) * 0.7 + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.85, 1.0)
        for y in range(h):
            dist = abs(y - line_y)
            if dist == 0:
                frame[y, x] = [min(255, r + 60), min(255, g + 60), min(255, b + 60)]
            elif dist < 8:
                glow = (1.0 - dist / 8.0) * fv
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
    """C6. Concentric rings — each ring = different FFT bin by radius."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            r_norm = min(1.0, r / 5.0)
            fv = smooth(300 + int(r_norm * 50), get_fft(r_norm))
            if fv < 0.03: continue
            hue = (r_norm + t * 0.03) % 1.0
            rc, gc, bc = hsv(hue, 0.85, min(1.0, fv * 1.5))
            frame[y, x] = [rc, gc, bc]


def exp_cym_expanding(frame, w, h, t, col_fft):
    """C7. Expanding + twirling cymatics — radial FFT (no left-side line)."""
    aspect = w / max(h, 1)
    # Use radial FFT average for overall energy
    overall = smooth(497, sum(col_fft) / max(len(col_fft), 1), attack=0.3, decay=0.97)
    vis_radius = overall * 8.0 + 0.5
    # Ultra-smooth rotation using high decay smooth
    rotation = smooth(499, overall, attack=0.1, decay=0.995) * 3.0
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            if r > vis_radius: continue
            # Smooth twist: eases one direction then the other
            twist_phase = math.sin(rotation * 0.5) * 0.5
            twisted = theta + twist_phase + r * twist_phase * 1.5
            n_ang_raw = 4.0 + smooth(498, overall, attack=0.1, decay=0.99) * 4.0
            n_ang = round(n_ang_raw)  # integer = no theta discontinuity
            if n_ang < 4: n_ang = 4
            p = math.cos(r * (3.0 + overall * 3.0)) * (0.6 + 0.4 * math.cos(n_ang * twisted))
            p2 = math.cos(r * 6.0) * math.cos((n_ang + 2) * twisted) * 0.4
            val = max(nodal(p, 0.22), nodal(p2, 0.18) * 0.5)
            edge = max(0, 1.0 - (r / vis_radius) ** 2) if vis_radius > 0.01 else 0
            val *= edge
            if val > 0.03:
                hue = ((r * 0.15 + nx * 0.1 + 0.5) * 0.6 + r * 0.4 + t * 0.02) % 1.0
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
    """C9. Star burst — radial FFT (no left-side line)."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            r_norm = min(1.0, r / 5.0)
            fv = smooth(450 + int(r_norm * 50), get_fft(r_norm))
            if fv < 0.02: continue
            points = int(4 + fv * 8)
            star = abs(math.cos(points * theta))
            ring = math.cos(r * (2.0 + fv * 3.0))  # wider rings
            # Wider gradient — fills more space
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
            petals = max(4, int(5 + fv * 5))  # ensure even for symmetry
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
    """K1. Kaleidoscope grid — consistent grid, no center star."""
    aspect = w / max(h, 1)
    mirror_fft = get_col_fft_mirror(w, offset=500)
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
            # Grid lines only (no radial star — just horizontal+vertical in folded space)
            sf = 5.0 + fv * 4.0
            hline = abs(math.sin(fy * sf))
            vline = abs(math.sin(fx * sf))
            # Show grid lines where both sin values are high
            val = max(0, min(hline, vline)) * fv * 2.5
            if val > 0.03:
                hue = (fx * 0.3 + fy * 0.3 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val))
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
    """K3. Kaleidoscope color field — no center star, smooth color patterns."""
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
            # Smooth flowing pattern — avoid center convergence by using offset
            # Add radius-based offset so center doesn't dominate
            offset = r * 0.5 + 0.3
            v = math.sin(fx * sf + offset) * math.cos(fy * sf * 0.7 + offset * 0.5)
            val = (v * 0.5 + 0.5) * (0.3 + fv * 1.0)
            if val > 0.03:
                hue = (la / sec * 0.5 + r * 0.3 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val))
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
            val = combined * (0.3 + fv * 1.2)
            if val > 0.03:
                hue = (la / sec * 0.5 + r * 0.4 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val * 1.3))
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
    """Bonfire — classic fire: hot at bottom, cooling upward, turbulent edges."""
    if not hasattr(exp_bonfire, '_buf'):
        exp_bonfire._buf = np.zeros((30, 300, 3), dtype=np.float32)
    buf = exp_bonfire._buf
    bh, bw = buf.shape[:2]
    if bw < w:
        exp_bonfire._buf = np.zeros((30, max(w, 220), 3), dtype=np.float32)
        buf = exp_bonfire._buf
        bh, bw = buf.shape[:2]
    # Shift UP (fire rises) and slow decay (flames reach higher)
    buf[:-1, :, :] = buf[1:, :, :] * 0.92  # slower decay = taller flames
    buf[-1, :, :] = 0
    # Inject heat at bottom row based on FFT
    mirror_fft = get_col_fft_mirror(w, offset=310)
    for x in range(w):
        fv = mirror_fft[x]
        if fv < 0.02: continue
        # Hot colors at bottom: bright yellow/white
        heat = fv * 255
        buf[bh-1, x] = [min(255, heat * 1.0), min(255, heat * 0.7), min(255, heat * 0.2)]
        # Spread to neighbors
        if x > 0: buf[bh-1, x-1] = np.maximum(buf[bh-1, x-1], buf[bh-1, x] * 0.4)
        if x < bw-1: buf[bh-1, x+1] = np.maximum(buf[bh-1, x+1], buf[bh-1, x] * 0.4)
    # Multiple horizontal blur passes — eliminates ALL black stripes
    for _ in range(3):
        for y_buf in range(bh):
            for x in range(1, min(w, bw) - 1):
                buf[y_buf, x] = buf[y_buf, x] * 0.4 + buf[y_buf, x-1] * 0.3 + buf[y_buf, x+1] * 0.3
    # Cool as fire rises: shift colors from yellow→orange→red→dark
    for y_buf in range(bh):
        age = 1.0 - y_buf / bh  # 1 at top (old), 0 at bottom (new)
        buf[y_buf, :, 1] *= (1.0 - age * 0.03)  # green fades faster
        buf[y_buf, :, 2] *= (1.0 - age * 0.05)  # blue fades fastest
    # Copy to frame
    for y in range(h):
        src_y = int(y / (h-1) * (bh-1))
        for x in range(w):
            v = buf[src_y, x]
            if v[0] > 2 or v[1] > 2 or v[2] > 2:
                frame[y, x] = np.clip(v, 0, 255).astype(np.uint8)
    # Fire buffer handles colors directly — no hsv needed


def exp_vortex(frame, w, h, t, col_fft):
    """Vortex — spiral, radial FFT (no left-side line)."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            r_norm = min(1.0, r / 5.0)
            fv = smooth(320 + int(r_norm * 50), get_fft(r_norm))
            if fv < 0.02: continue
            # Multiple spiral arms with even spacing (4 arms = no visible seam)
            val = 0
            for arm in range(4):
                spiral = math.sin(4 * theta + r * (3.0 + fv * 3.0) + arm * math.pi * 0.5)
                val += max(0, spiral) * 0.5
            val = min(1.0, val * fv * 1.5)
            if val > 0.03:
                # Rich multi-color: hue varies with angle AND radius AND FFT
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
    """Prism — rainbow light splitting effect. FFT spreads the spectrum."""
    mirror_fft = get_col_fft_mirror(w, offset=340)
    center = h // 2
    for x in range(w):
        fv = mirror_fft[x]
        if fv < 0.02: continue
        nx = x / (w-1)
        # Rainbow spread: more FFT = wider color separation
        spread = int(fv * center * 0.8)
        for dy in range(-spread, spread + 1):
            y = center + dy
            if 0 <= y < h:
                # Map vertical position to hue (rainbow)
                hue = (dy / max(1, spread) * 0.5 + 0.5 + nx * 0.3 + t * 0.03) % 1.0
                dist = abs(dy) / max(1, spread)
                val = (1.0 - dist * 0.5) * fv * 1.5
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
        mirror_fft[x] = smooth(290 + x, mirror_fft[x], attack=0.1, decay=0.99)  # 4x slower
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
    """Firefly — tiny embers zipping with line trails. Abstract tangled paths."""
    if not hasattr(exp_firefly, '_trail'):
        exp_firefly._trail = np.zeros((24, 220, 3), dtype=np.float32)
    trail = exp_firefly._trail
    # Resize trail if needed
    if trail.shape[0] != h or trail.shape[1] != w:
        exp_firefly._trail = np.zeros((h, w, 3), dtype=np.float32)
        trail = exp_firefly._trail
    # Decay trail (creates the line history)
    trail *= 0.88

    mirror_fft = get_col_fft_mirror(w, offset=310)
    n_flies = 20  # more flies, smaller
    for i in range(n_flies):
        # Abstract tangled paths — multiple sine frequencies
        speed = 0.15 + i * 0.03  # slow graceful movement
        fx = (math.sin(t * speed + i * 2.3) * 0.4 +
              math.sin(t * speed * 1.7 + i * 0.9) * 0.3 + 0.5)
        fy = (math.cos(t * speed * 0.6 + i * 1.7) * 0.4 +
              math.cos(t * speed * 1.3 + i * 3.1) * 0.3 + 0.5)
        px = int(max(0, min(1, fx)) * (w - 1))
        py = int(max(0, min(1, fy)) * (h - 1))
        fv = mirror_fft[px] if px < len(mirror_fft) else 0.3
        if fv < 0.02: continue
        hue = (i / n_flies + t * 0.01) % 1.0
        r, g, b = hsv(hue, 0.75, min(1.0, fv * 2.0))
        # Small bright dot (1-2 pixel)
        trail[py, px] = [max(trail[py, px, 0], r * 0.9),
                         max(trail[py, px, 1], g * 0.9),
                         max(trail[py, px, 2], b * 0.9)]
        frame[py, px] = [min(255, int(r * 1.2)), min(255, int(g * 1.2)), min(255, int(b * 1.2))]
        # Tiny 1px glow
        for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
            gy, gx = py+dy, px+dx
            if 0 <= gy < h and 0 <= gx < w:
                frame[gy, gx] = [max(frame[gy, gx, 0], int(r * 0.4)),
                                 max(frame[gy, gx, 1], int(g * 0.4)),
                                 max(frame[gy, gx, 2], int(b * 0.4))]

    # Composite trail under the current frame
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
            # Grid lines (no radial star — just horizontal/vertical in folded space)
            sf = 5.0 + fv * 5.0
            hline = abs(math.sin(fy * sf))
            vline = abs(math.sin(fx * sf))
            val = max(0, min(hline, vline)) * fv * 2.0
            if val > 0.03:
                hue = (la / sec * 0.5 + fv * 0.3 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val))
                frame[y, x] = [rc, gc, bc]


def exp_matrix(frame, w, h, t, col_fft):
    """Matrix — digital rain columns scrolling at different speeds. FFT = speed."""
    mirror_fft = get_col_fft_mirror(w, offset=335)
    for x in range(w):
        fv = mirror_fft[x]
        if fv < 0.02: continue
        hue = (x / max(w-1, 1) * 0.15 + 0.3 + t * 0.01) % 1.0  # green-ish
        r, g, b = hsv(hue, 0.7, 1.0)
        # Column scroll speed varies with FFT
        scroll = (t * (0.025 + fv * 0.04) + x * 0.37) % 1.0  # 4x slower
        # Bright head + fading tail
        head_y = int(scroll * (h + 6)) - 3
        for y in range(h):
            dist = head_y - y
            if 0 <= dist < 8:
                fade = 1.0 - dist / 8.0
                intensity = fade * fv * 1.5
                frame[y, x] = [max(frame[y, x, 0], int(r * intensity)),
                               max(frame[y, x, 1], int(g * intensity)),
                               max(frame[y, x, 2], int(b * intensity))]


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
    n_flies = 10
    for i in range(n_flies):
        speed = 0.08 + i * 0.015
        # Smooth curved paths
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
    ("C8 Cym Dual", exp_cym_dual),
    ("C9 Cym Star", exp_cym_star),
    ("C10 Cym Flower", exp_cym_flower),
    # Kaleidoscopes (all symmetric)
    ("K1 Kal Radial", exp_kal_radial),
    ("K2 Kal Thickness", exp_kal_thick),
    ("K3 Kal Spatial", exp_kal_spatial),
    ("K4 Kal Grid", exp_kal_grid),
    ("K5 Kal Mirror", exp_kal_mirror),
    ("K6 Kal Crystal", exp_kal_crystal),
    ("K7 Circuit", exp_circuit),
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
    global running, ws_clients, audio_active, audio_last_time, current_fx, current_palette
    dt = 1.0 / FPS
    t = 0

    while running:
        t0 = time.monotonic()
        t += dt

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
    global current_exp, current_palette
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
