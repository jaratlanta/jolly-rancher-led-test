#!/usr/bin/env python3
"""
Audio experiment harness — 10 different audio-mapping strategies
for Cym Radiate and Kal Crystal. Renders animated GIFs with
simulated 120 BPM beats so we can SEE the difference.

Each experiment tries a fundamentally different approach to
mapping audio → visual motion.

Usage:
    python test_audio_experiments.py
"""
import math
import colorsys
import os
import numpy as np
from PIL import Image

OUTPUT_DIR = "test_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

FPS = 15
DURATION_S = 4.0
NUM_FRAMES = int(FPS * DURATION_S)
FRAME_DELAY_MS = int(1000 / FPS)
W, H = 220, 24
SCALE = 3


def hsv_rgb(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1, s), min(1, v))
    return int(r * 255), int(g * 255), int(b * 255)


def nodal_line(val, thickness=0.15):
    v = max(0, 1.0 - abs(val) / thickness)
    return v * v


class SimAudio:
    def __init__(self, bpm=120):
        self.beat_interval = 60.0 / bpm
        self._push = 0.0
        self._last = -1

    def get(self, t):
        bi = int(t / self.beat_interval)
        phase = (t % self.beat_interval) / self.beat_interval
        if bi != self._last:
            self._push += 1.0
            self._last = bi
        ease = 1.0 - math.exp(-phase * 8.0)
        bp = self._push + ease
        bass = math.exp(-phase * 6.0)
        mid = 0.3 + 0.35 * math.exp(-phase * 3.0)
        treble = 0.15 + 0.4 * math.exp(-((phase - 0.5) ** 2) / 0.02)
        return bass, mid, treble, bp


# ═══════════════════════════════════════════════════════════════════════
# EXPERIMENT: 10 different audio→visual mapping strategies
# Applied to Cym Radiate (radial pattern)
# ═══════════════════════════════════════════════════════════════════════

def exp1_beat_push_radial(nx, ny, t, bass, mid, treble, bp):
    """E1: beat_push drives outward expansion (current approach)."""
    r = math.sqrt(nx*nx + ny*ny)
    theta = math.atan2(ny, nx)
    p1 = math.cos(r * 4.0 - bp * 1.5) * (0.6 + 0.4 * math.cos(4.0 * theta))
    p2 = math.cos(r * 7.0 - bp * 1.0) * math.cos(6.0 * theta) * 0.4
    val = max(nodal_line(p1, 0.25), nodal_line(p2, 0.2) * 0.4)
    val *= (0.5 + bass)
    return hsv_rgb((theta / 6.28 * 0.6 + r * 0.8) % 1.0, 0.8, min(1, val * 1.3))


def exp2_bass_as_time(nx, ny, t, bass, mid, treble, bp):
    """E2: Use accumulated bass as the ONLY time driver (freeze when silent)."""
    r = math.sqrt(nx*nx + ny*ny)
    theta = math.atan2(ny, nx)
    # Accumulated bass energy as time — pattern ONLY moves when bass plays
    bass_time = bp * 0.8  # bp already accumulates on beats
    p1 = math.cos(r * 4.0 - bass_time) * (0.6 + 0.4 * math.cos(4.0 * theta))
    p2 = math.cos(r * 7.0 - bass_time * 0.7) * math.cos(6.0 * theta) * 0.4
    val = max(nodal_line(p1, 0.25), nodal_line(p2, 0.2) * 0.4)
    return hsv_rgb((theta / 6.28 * 0.6 + r * 0.8) % 1.0, 0.8, min(1, val * 1.3))


def exp3_bass_scale_radius(nx, ny, t, bass, mid, treble, bp):
    """E3: Bass scales the effective radius (zoom in/out)."""
    r = math.sqrt(nx*nx + ny*ny)
    theta = math.atan2(ny, nx)
    # Bass zooms: high bass = zoomed in, low bass = zoomed out
    r_scaled = r * (0.5 + bass * 2.0)
    p1 = math.cos(r_scaled * 4.0 - t * 0.3) * (0.6 + 0.4 * math.cos(4.0 * theta))
    p2 = math.cos(r_scaled * 7.0 + t * 0.2) * math.cos(6.0 * theta) * 0.4
    val = max(nodal_line(p1, 0.25), nodal_line(p2, 0.2) * 0.4)
    return hsv_rgb((theta / 6.28 * 0.6 + r * 0.8) % 1.0, 0.8, min(1, val * 1.3))


def exp4_bass_angular_rotation(nx, ny, t, bass, mid, treble, bp):
    """E4: Bass rotates the angular pattern (twist on beat)."""
    r = math.sqrt(nx*nx + ny*ny)
    theta = math.atan2(ny, nx)
    # Bass rotates the whole pattern
    rot_theta = theta + bp * 0.5
    p1 = math.cos(r * 4.0 - t * 0.2) * (0.6 + 0.4 * math.cos(4.0 * rot_theta))
    p2 = math.cos(r * 7.0 + t * 0.15) * math.cos(6.0 * rot_theta) * 0.4
    val = max(nodal_line(p1, 0.25), nodal_line(p2, 0.2) * 0.4)
    return hsv_rgb((rot_theta / 6.28 * 0.6 + r * 0.8) % 1.0, 0.8, min(1, val * 1.3))


def exp5_bass_symmetry_morph(nx, ny, t, bass, mid, treble, bp):
    """E5: Bass smoothly morphs the symmetry order (4→8 fold)."""
    r = math.sqrt(nx*nx + ny*ny)
    theta = math.atan2(ny, nx)
    n = 4.0 + bass * 4.0  # 4-fold in silence, 8-fold on beat
    p1 = math.cos(r * 4.0 - t * 0.2) * (0.6 + 0.4 * math.cos(n * theta))
    p2 = math.cos(r * 7.0 + t * 0.15) * math.cos((n + 2) * theta) * 0.4
    val = max(nodal_line(p1, 0.25), nodal_line(p2, 0.2) * 0.4)
    return hsv_rgb((theta / 6.28 * 0.6 + r * 0.8) % 1.0, 0.8, min(1, val * 1.3))


def exp6_bass_ring_freq(nx, ny, t, bass, mid, treble, bp):
    """E6: Bass changes ring frequency (more rings on beat)."""
    r = math.sqrt(nx*nx + ny*ny)
    theta = math.atan2(ny, nx)
    rf = 3.0 + bass * 6.0  # 3 rings silence, 9 rings on beat
    p1 = math.cos(r * rf - t * 0.2) * (0.6 + 0.4 * math.cos(4.0 * theta))
    p2 = math.cos(r * rf * 1.5 + t * 0.15) * math.cos(6.0 * theta) * 0.4
    val = max(nodal_line(p1, 0.25), nodal_line(p2, 0.2) * 0.4)
    return hsv_rgb((theta / 6.28 * 0.6 + r * 0.8) % 1.0, 0.8, min(1, val * 1.3))


def exp7_hue_shift(nx, ny, t, bass, mid, treble, bp):
    """E7: Bass shifts the entire color spectrum (hue rotation on beat)."""
    r = math.sqrt(nx*nx + ny*ny)
    theta = math.atan2(ny, nx)
    p1 = math.cos(r * 4.0 - t * 0.2) * (0.6 + 0.4 * math.cos(4.0 * theta))
    p2 = math.cos(r * 7.0 + t * 0.15) * math.cos(6.0 * theta) * 0.4
    val = max(nodal_line(p1, 0.25), nodal_line(p2, 0.2) * 0.4)
    # Hue shifts dramatically with each beat
    hue = (theta / 6.28 * 0.6 + r * 0.8 + bp * 0.15) % 1.0
    return hsv_rgb(hue, 0.8, min(1, val * 1.3))


def exp8_thickness_pulse(nx, ny, t, bass, mid, treble, bp):
    """E8: Bass changes line thickness (thick on beat, thin between)."""
    r = math.sqrt(nx*nx + ny*ny)
    theta = math.atan2(ny, nx)
    thick = 0.1 + bass * 0.3  # thin in silence, fat on beat
    p1 = math.cos(r * 4.0 - t * 0.2) * (0.6 + 0.4 * math.cos(4.0 * theta))
    p2 = math.cos(r * 7.0 + t * 0.15) * math.cos(6.0 * theta) * 0.4
    val = max(nodal_line(p1, thick), nodal_line(p2, thick * 0.8) * 0.4)
    return hsv_rgb((theta / 6.28 * 0.6 + r * 0.8) % 1.0, 0.8, min(1, val * 1.3))


def exp9_combo_push_zoom(nx, ny, t, bass, mid, treble, bp):
    """E9: Combo — beat_push expands + bass zooms + mid rotates."""
    r = math.sqrt(nx*nx + ny*ny)
    theta = math.atan2(ny, nx)
    r_scaled = r * (0.7 + bass * 1.0)
    rot = theta + bp * 0.3
    p1 = math.cos(r_scaled * 4.0 - bp * 1.0) * (0.6 + 0.4 * math.cos(4.0 * rot))
    p2 = math.cos(r_scaled * 7.0 - bp * 0.6) * math.cos(6.0 * rot) * 0.4
    val = max(nodal_line(p1, 0.22), nodal_line(p2, 0.18) * 0.4)
    val *= (0.4 + bass * 1.0)
    return hsv_rgb((rot / 6.28 * 0.6 + r * 0.8 + bp * 0.1) % 1.0, 0.8, min(1, val * 1.3))


def exp10_frequency_bars_hybrid(nx, ny, t, bass, mid, treble, bp):
    """E10: Use bass envelope as a HEIGHT like frequency bars but radially."""
    r = math.sqrt(nx*nx + ny*ny)
    theta = math.atan2(ny, nx)
    # The pattern is always there but bass controls how much of it is visible
    # Like frequency bars: bass = how high the bar goes
    visibility_radius = bass * 0.6 + 0.1  # how far from center is visible
    p1 = math.cos(r * 4.0 - bp * 1.0) * (0.6 + 0.4 * math.cos(4.0 * theta))
    p2 = math.cos(r * 7.0 - bp * 0.7) * math.cos(6.0 * theta) * 0.4
    val = max(nodal_line(p1, 0.25), nodal_line(p2, 0.2) * 0.4)
    # Fade based on distance — bass controls how far the pattern reaches
    if r > visibility_radius:
        val *= max(0, 1.0 - (r - visibility_radius) * 5.0)
    return hsv_rgb((theta / 6.28 * 0.6 + r * 0.8 + bp * 0.08) % 1.0, 0.8, min(1, val * 1.3))


EXPERIMENTS = [
    ("E01_beat_push_radial", exp1_beat_push_radial),
    ("E02_bass_as_time", exp2_bass_as_time),
    ("E03_bass_scale_radius", exp3_bass_scale_radius),
    ("E04_bass_angular_rotation", exp4_bass_angular_rotation),
    ("E05_bass_symmetry_morph", exp5_bass_symmetry_morph),
    ("E06_bass_ring_freq", exp6_bass_ring_freq),
    ("E07_hue_shift", exp7_hue_shift),
    ("E08_thickness_pulse", exp8_thickness_pulse),
    ("E09_combo_push_zoom", exp9_combo_push_zoom),
    ("E10_freq_bars_hybrid", exp10_frequency_bars_hybrid),
]


def render_gif(name, func):
    audio = SimAudio(bpm=120)
    frames = []
    for i in range(NUM_FRAMES):
        t = i / FPS
        bass, mid, treble, bp = audio.get(t)
        img = np.zeros((H, W, 3), dtype=np.uint8)
        aspect = W / H
        for y in range(H):
            ny = y / (H - 1) - 0.5
            for x in range(W):
                nx = (x / (W - 1) - 0.5) * aspect
                r, g, b = func(nx, ny, t, bass, mid, treble, bp)
                img[y, x] = [r, g, b]
        big = np.repeat(np.repeat(img, SCALE, axis=0), SCALE, axis=1)
        frames.append(Image.fromarray(big))

    path = os.path.join(OUTPUT_DIR, f"{name}.gif")
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=FRAME_DELAY_MS, loop=0)
    print(f"  {name}.gif ✓")


def main():
    print(f"=== Audio Experiments: {len(EXPERIMENTS)} variants ===\n")
    for name, func in EXPERIMENTS:
        render_gif(name, func)
    print(f"\nDone! Open test_output/E*.gif to compare.")


if __name__ == "__main__":
    main()
