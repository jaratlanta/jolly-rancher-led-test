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

# Smooth state (fast attack, slow decay — like Frequency Bars)
smooth_state = np.zeros(512, dtype=np.float32)

# Panel dimensions
FRONT_W, FRONT_H = 72, 24
SIDE_W, SIDE_H = 220, 24
FPS = 20

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


def hsv(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1, s), min(1, v))
    return int(r * 255), int(g * 255), int(b * 255)


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
                hue = (theta / 6.28 * 0.6 + r * 0.5 + t * 0.02) % 1.0
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
                hue = (theta / 6.28 * 0.6 + r * 0.5 + t * 0.02) % 1.0
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
                hue = (theta / 6.28 * 0.6 + r * 0.5 + t * 0.02) % 1.0
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
                hue = (theta / 6.28 * 0.6 + r * 0.5 + t * 0.02) % 1.0
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


def exp_bars_top(frame, w, h, t, col_fft):
    """P3. Bars hanging from top."""
    for x in range(w):
        bh = col_fft[x]
        if bh < 0.02: continue
        bar_bot = int(bh * (h - 1))
        hue = (x / max(w-1, 1) * 0.8 + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.9, 1.0)
        for y in range(0, bar_bot + 1):
            frac = y / max(1, bar_bot)
            frame[y, x] = [int(r * (0.3 + 0.7 * frac)), int(g * (0.3 + 0.7 * frac)), int(b * (0.3 + 0.7 * frac))]


def exp_wave_single(frame, w, h, t, col_fft):
    """P4. Single sine wave — amplitude follows FFT."""
    center = h // 2
    for x in range(w):
        fv = col_fft[x]
        if fv < 0.02: continue
        wave_y = center + int(fv * center * 0.9 * math.sin(x / max(w-1, 1) * math.pi * 2))
        wave_y = max(0, min(h-1, wave_y))
        hue = (x / max(w-1, 1) + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.85, 1.0)
        y_lo, y_hi = min(center, wave_y), max(center, wave_y)
        for y in range(y_lo, y_hi + 1):
            frac = abs(y - center) / max(1, abs(wave_y - center))
            frame[y, x] = [int(r * (0.3 + 0.7 * frac)), int(g * (0.3 + 0.7 * frac)), int(b * (0.3 + 0.7 * frac))]


def exp_wave_triple(frame, w, h, t, col_fft):
    """P5. Three layered sine waves — each at different frequency."""
    center = h // 2
    for x in range(w):
        fv = col_fft[x]
        if fv < 0.02: continue
        hue = (x / max(w-1, 1) + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.85, 1.0)
        for i in range(3):
            amp = fv * (0.12 + i * 0.06)
            freq = 1.0 + i * 0.5
            wy = center + int(amp * center * math.sin(x / max(w-1, 1) * freq * math.pi * 2 + i * 1.5))
            wy = max(0, min(h-1, wy))
            frame[wy, x] = [min(255, r + 40), min(255, g + 40), min(255, b + 40)]
            if wy > 0: frame[wy-1, x] = [r // 2, g // 2, b // 2]
            if wy < h-1: frame[wy+1, x] = [r // 2, g // 2, b // 2]


def exp_dots_scatter(frame, w, h, t, col_fft):
    """P6. Scattered dots — height = FFT, position deterministic."""
    for x in range(w):
        fv = col_fft[x]
        if fv < 0.03: continue
        hue = (x / max(w-1, 1) + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.9, min(1.0, fv * 2.0))
        # Place dots at deterministic vertical positions based on x
        for i in range(3):
            dy = int((math.sin(x * 0.7 + i * 2.1) * 0.5 + 0.5) * fv * (h - 1))
            dy = max(0, min(h-1, dy))
            frame[dy, x] = [r, g, b]


def exp_gradient_fill(frame, w, h, t, col_fft):
    """P7. Full column gradient — brighter with more FFT energy."""
    for x in range(w):
        fv = col_fft[x]
        if fv < 0.02: continue
        hue = (x / max(w-1, 1) + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.8, 1.0)
        for y in range(h):
            ny = y / (h - 1)
            # Gradient: bright at center, dim at edges
            center_dist = abs(ny - 0.5) * 2
            intensity = fv * (1.0 - center_dist * 0.7)
            if intensity > 0.03:
                frame[y, x] = [int(r * intensity), int(g * intensity), int(b * intensity)]


def exp_rain_drops(frame, w, h, t, col_fft):
    """P8. Rain drops falling — FFT controls drop density/length per column."""
    for x in range(w):
        fv = col_fft[x]
        if fv < 0.03: continue
        hue = (x / max(w-1, 1) + t * 0.05) % 1.0
        r, g, b = hsv(hue, 0.85, 1.0)
        drop_len = max(1, int(fv * h * 0.4))
        # Drop position based on time + column (scrolling down)
        drop_y = int((t * 8 + x * 0.37) % h)
        for dy in range(drop_len):
            y = (drop_y + dy) % h
            frac = 1.0 - dy / max(1, drop_len)
            frame[y, x] = [int(r * frac * fv * 2), int(g * frac * fv * 2), int(b * frac * fv * 2)]


def exp_mountain(frame, w, h, t, col_fft):
    """P9. Mountain silhouette — FFT defines the ridge line, filled below."""
    for x in range(w):
        fv = col_fft[x]
        ridge_y = int((1.0 - fv) * (h - 1))
        ridge_y = max(0, min(h-1, ridge_y))
        hue = (x / max(w-1, 1) * 0.6 + t * 0.03) % 1.0
        r, g, b = hsv(hue, 0.75, 1.0)
        for y in range(ridge_y, h):
            depth = (y - ridge_y) / max(1, h - 1 - ridge_y)
            intensity = 0.8 - depth * 0.5
            frame[y, x] = [int(r * intensity), int(g * intensity), int(b * intensity)]
        # Bright ridge line
        if fv > 0.03:
            frame[ridge_y, x] = [min(255, r + 80), min(255, g + 80), min(255, b + 80)]


# ─── CYMATICS (10): radial patterns with FFT ────────────────────────────────

def exp_cym_visibility(frame, w, h, t, col_fft):
    """C1. Cymatics pattern — FFT controls visibility (brightness mask)."""
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
                hue = (theta / 6.28 * 0.6 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_cym_thick(frame, w, h, t, col_fft):
    """C2. Cymatics — FFT controls line thickness."""
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
                hue = (theta / 6.28 * 0.6 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_cym_spatial(frame, w, h, t, col_fft):
    """C3. Cymatics — FFT controls spatial frequency (breathing)."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            sf = 3.0 + fv * 6.0
            p = math.cos(r * sf) * (0.6 + 0.4 * math.cos(6 * theta))
            val = nodal(p, 0.2 + fv * 0.15) * (0.3 + fv * 1.0)
            if val > 0.03:
                hue = (theta / 6.28 * 0.6 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_cym_symmetry(frame, w, h, t, col_fft):
    """C4. Cymatics — FFT morphs angular symmetry order."""
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
                hue = (theta / 6.28 * 0.6 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_cym_color(frame, w, h, t, col_fft):
    """C5. Cymatics — FFT drives color (frequency = hue)."""
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
            val = nodal(p, 0.22) * (0.3 + fv * 1.2)
            if val > 0.03:
                hue = (fv * 0.7 + r * 0.2 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


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


def exp_cym_angular(frame, w, h, t, col_fft):
    """C7. Cymatics — FFT mapped to angle (different dirs = different freqs)."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            a_norm = (theta + math.pi) / (2 * math.pi)
            fv = smooth(360 + int(a_norm * 50), get_fft(a_norm))
            if fv < 0.03: continue
            p = math.cos(r * 4.0) * math.cos(6 * theta)
            val = nodal(p, 0.2) * fv * 2.0
            if val > 0.03:
                hue = (a_norm * 0.8 + r * 0.3 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val * 1.3))
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
                hue = (theta / 6.28 * 0.5 + r * 0.4 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val))
                frame[y, x] = [rc, gc, bc]


def exp_cym_star(frame, w, h, t, col_fft):
    """C9. Star burst — FFT drives how many points and how sharp."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            if fv < 0.03: continue
            points = int(4 + fv * 8)
            star = abs(math.cos(points * theta))
            ring = math.cos(r * (3.0 + fv * 4.0))
            val = star * max(0, ring) * fv * 2.0
            if val > 0.03:
                hue = (theta / 6.28 * 0.6 + r * 0.4 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_cym_flower(frame, w, h, t, col_fft):
    """C10. Flower petals — FFT controls petal count and openness."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            if fv < 0.03: continue
            petals = int(5 + fv * 5)
            petal = abs(math.cos(petals * theta * 0.5))
            petal_r = fv * 0.3 * (0.5 + 0.5 * petal)
            if r < petal_r * 10:
                inner = math.cos(r * (8 + fv * 10))
                val = (0.3 + 0.7 * max(0, inner)) * fv * 1.5
                if val > 0.03:
                    hue = (theta / 6.28 * 0.5 + r * 0.8 + t * 0.02) % 1.0
                    rc, gc, bc = hsv(hue, 0.8, min(1.0, val))
                    frame[y, x] = [rc, gc, bc]


# ─── KALEIDOSCOPES (10): mirror-folded patterns with FFT ────────────────────

def _kal_fold(theta, n_sectors=8):
    """Fold angle into kaleidoscope mirror sectors."""
    sector = math.pi / n_sectors
    si = int(theta / sector) if theta >= 0 else int(theta / sector) - 1
    la = theta - si * sector
    if si % 2 == 1: la = sector - la
    return la, sector


def exp_kal_visibility(frame, w, h, t, col_fft):
    """K1. Kaleidoscope — FFT controls visibility."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            if fv < 0.03: continue
            la, sec = _kal_fold(theta)
            fx, fy = r * math.cos(la), r * math.sin(la)
            v = abs(math.sin(fx * 7)) * abs(math.cos(fy * 7))
            val = v * fv * 2.0
            if val > 0.03:
                hue = (la / sec * 0.5 + r * 0.4 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.85, min(1.0, val))
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
    """K3. Kaleidoscope — FFT controls inner detail complexity."""
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
            sf = 4.0 + fv * 8.0
            v = math.sin(fx * sf) * math.cos(fy * sf * 0.7)
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


def exp_kal_color(frame, w, h, t, col_fft):
    """K5. Kaleidoscope — FFT drives color spectrum."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            if fv < 0.03: continue
            la, sec = _kal_fold(theta)
            fx, fy = r * math.cos(la), r * math.sin(la)
            v = abs(math.sin(fx * 7)) * abs(math.cos(fy * 7))
            val = v * (0.3 + fv * 1.2)
            if val > 0.03:
                hue = (fv * 0.7 + la / sec * 0.2 + t * 0.02) % 1.0
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


def exp_kal_mandala(frame, w, h, t, col_fft):
    """K7. Mandala — concentric rings in kaleidoscope with FFT."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            la, sec = _kal_fold(theta)
            n = 6 + int(fv * 4)
            v1 = math.cos(r * (4 + fv * 3)) * math.cos(n * theta)
            v2 = math.cos(r * 8) * math.cos(n * 2 * theta) * 0.4
            val = max(0, (v1 + v2 + 1.4) / 2.8) * (0.3 + fv * 1.2)
            if val > 0.03:
                hue = (theta / 6.28 * 0.5 + r * 0.4 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.3))
                frame[y, x] = [rc, gc, bc]


def exp_kal_starglass(frame, w, h, t, col_fft):
    """K8. Stained glass star — angular sectors with FFT brightness."""
    aspect = w / max(h, 1)
    for y in range(h):
        ny = y / (h-1) - 0.5
        for x in range(w):
            nx = (x / (w-1) - 0.5) * aspect
            r = math.sqrt(nx*nx + ny*ny)
            theta = math.atan2(ny, nx)
            fv = col_fft[x]
            if fv < 0.03: continue
            points = int(5 + fv * 6)
            la, sec = _kal_fold(theta, points)
            star = abs(math.cos(points * theta))
            ring = math.cos(r * (3 + fv * 4))
            val = star * max(0, ring) * fv * 2.0
            if val > 0.03:
                hue = (theta / 6.28 * 0.6 + r * 0.3 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.9, min(1.0, val * 1.3))
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
                hue = (theta / 6.28 * 0.4 + r * 0.5 + t * 0.02) % 1.0
                rc, gc, bc = hsv(hue, 0.8, min(1.0, val * 1.5))
                frame[y, x] = [rc, gc, bc]


EXPERIMENTS = [
    # Patterns (column-based)
    ("P1 Freq Bars", exp_freq_bars),
    ("P2 Bars Bottom", exp_bars_bottom),
    ("P3 Bars Top", exp_bars_top),
    ("P4 Wave Single", exp_wave_single),
    ("P5 Wave Triple", exp_wave_triple),
    ("P6 Dots Scatter", exp_dots_scatter),
    ("P7 Gradient Fill", exp_gradient_fill),
    ("P8 Rain Drops", exp_rain_drops),
    ("P9 Mountain", exp_mountain),
    ("P10 Mirror", exp_spectrum_mirror),
    # Cymatics (radial)
    ("C1 Cym Visibility", exp_cym_visibility),
    ("C2 Cym Thickness", exp_cym_thick),
    ("C3 Cym Breathing", exp_cym_spatial),
    ("C4 Cym Symmetry", exp_cym_symmetry),
    ("C5 Cym Color", exp_cym_color),
    ("C6 Cym Rings", exp_cym_rings),
    ("C7 Cym Angular", exp_cym_angular),
    ("C8 Cym Dual", exp_cym_dual),
    ("C9 Cym Star", exp_cym_star),
    ("C10 Cym Flower", exp_cym_flower),
    # Kaleidoscopes (mirror-folded)
    ("K1 Kal Visibility", exp_kal_visibility),
    ("K2 Kal Thickness", exp_kal_thick),
    ("K3 Kal Spatial", exp_kal_spatial),
    ("K4 Kal Sectors", exp_kal_sectors),
    ("K5 Kal Color", exp_kal_color),
    ("K6 Kal Crystal", exp_kal_crystal),
    ("K7 Kal Mandala", exp_kal_mandala),
    ("K8 Kal Starglass", exp_kal_starglass),
    ("K9 Kal Dual", exp_kal_dual),
    ("K10 Kal Web", exp_kal_web),
]


# ─── Render Loop ─────────────────────────────────────────────────────────────

running = True

def render_loop():
    global running
    dt = 1.0 / FPS
    t = 0

    while running:
        t0 = time.monotonic()
        t += dt

        with fft_lock:
            has_audio = np.max(fft_data) > 5  # is real audio coming in?

        # If no audio, generate simulated FFT for DEFAULT mode
        if not has_audio:
            for i in range(128):
                fft_data[i] = 80 + 60 * math.sin(i * 0.3 + t * 2.0) * math.sin(t * 0.5 + i * 0.1)
                fft_data[i] = max(0, fft_data[i])

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

        # Pack into one message: front + side stacked vertically
        combined = np.vstack([front, side])
        frame_bytes = combined.tobytes()

        # Send state + frame
        state = json.dumps({
            "type": "state",
            "exp_name": exp_name,
            "exp_idx": current_exp % len(EXPERIMENTS),
            "exp_count": len(EXPERIMENTS),
            "front_w": FRONT_W, "front_h": FRONT_H,
            "side_w": SIDE_W, "side_h": SIDE_H,
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
    global current_exp
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
                    with fft_lock:
                        fft_data[:] = np.frombuffer(data, dtype=np.uint8).astype(np.float32)
                continue

            msg = raw.get("text", "")
            if not msg: continue
            data = json.loads(msg)
            cmd = data.get("cmd")

            if cmd == "next_exp":
                current_exp = (current_exp + 1) % len(EXPERIMENTS)
            elif cmd == "prev_exp":
                current_exp = (current_exp - 1) % len(EXPERIMENTS)

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
