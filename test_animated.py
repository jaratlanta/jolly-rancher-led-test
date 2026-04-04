#!/usr/bin/env python3
"""
Animated test harness — renders visualizers as GIF animations.

This solves the core problem: we can SEE the animation running
before shipping to the live app. No more guessing.

Renders at EXACT panel dimensions, simulates audio input,
and outputs animated GIFs that show exactly what the LED panel will display.

Usage:
    python test_animated.py                    # render all tests
    python test_animated.py cym_grid           # render just cym_grid
    python test_animated.py cym_grid --audio   # with simulated audio beats

Output: test_output/*.gif
"""
import math
import colorsys
import os
import sys
import numpy as np
from PIL import Image

OUTPUT_DIR = "test_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Panel dimensions
SIDE_W, SIDE_H = 220, 24
FRONT_W, FRONT_H = 72, 24
SCALE = 4  # upscale for visibility

# Animation settings
FPS = 15
DURATION_S = 4.0
NUM_FRAMES = int(FPS * DURATION_S)
FRAME_DELAY_MS = int(1000 / FPS)


def hsv_rgb(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1, s), min(1, v))
    return int(r * 255), int(g * 255), int(b * 255)


def nodal_line(val, thickness=0.15):
    v = max(0, 1.0 - abs(val) / thickness)
    return v * v


# ═════════════════════════════════════════════════════════════════════════════
# SIMULATED AUDIO — generates realistic bass/mid/treble with beat pulses
# ═════════════════════════════════════════════════════════════════════════════

class SimulatedAudio:
    """Simulates audio with sharp beat pulses at a given BPM.

    Tracks accumulated beat count for patterns that need to step forward
    on each beat (like radiating cymatics).
    """

    def __init__(self, bpm=120):
        self.bpm = bpm
        self.beat_interval = 60.0 / bpm
        self._accumulated_push = 0.0
        self._last_beat_idx = -1

    def get(self, t):
        """Returns (bass, mid, treble, beat_push).

        beat_push: accumulated value that STEPS FORWARD on each beat.
        This is what drives the radial expansion — it never goes backwards,
        it just keeps pushing outward, one step per beat.
        """
        beat_idx = int(t / self.beat_interval)
        phase = (t % self.beat_interval) / self.beat_interval

        # Accumulate push on each NEW beat
        if beat_idx != self._last_beat_idx:
            self._accumulated_push += 1.0  # one step per beat
            self._last_beat_idx = beat_idx

        # Bass envelope: sharp spike on beat, fast decay between
        bass_envelope = math.exp(-phase * 6.0)

        # Mid: smooth presence
        mid = 0.3 + 0.35 * math.exp(-phase * 3.0)

        # Treble: hi-hat on off-beats
        off_phase = ((t + self.beat_interval / 2) % self.beat_interval) / self.beat_interval
        treble = 0.15 + 0.4 * math.exp(-off_phase * 10.0)

        # beat_push = accumulated steps + smooth easing within current beat
        ease = 1.0 - math.exp(-phase * 8.0)  # eases from 0 to ~1 within the beat
        beat_push = self._accumulated_push + ease

        return bass_envelope, mid, treble, beat_push


# ═════════════════════════════════════════════════════════════════════════════
# VISUALIZER FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def cym_grid(nx, ny, t, bass=0, mid=0, treble=0, beat_push=0):
    """Cymatics Grid with beat-driven radial expansion.

    beat_push: accumulated value that steps forward on each beat.
    Each beat advances the radial phase by 1.0, so the rings
    visibly EXPAND outward one step per beat. Between beats,
    the rings ease smoothly to the next position.

    This creates the "radiating from center on every beat" effect.
    """
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    # Structural changes from frequency bands
    r_freq1 = 3.5 + bass * 1.5
    n_angular = 4.0 + mid * 5.0
    r_freq2 = 6.0 + treble * 3.0
    rotation = t * 0.08

    # THE KEY: beat_push drives radial phase
    # Each beat pushes rings outward by one full cycle
    # The pattern perpetually expands from center
    radial_phase = beat_push * 1.2  # 1.2 radians per beat = visible ring step

    p1 = math.cos(r * r_freq1 - radial_phase - rotation) + math.cos(n_angular * theta)
    p2 = math.cos(r * r_freq2 - radial_phase * 0.7 + rotation * 0.5) * math.cos((n_angular + 2) * theta + math.pi / 4)

    secondary_mix = 0.3 + treble * 0.4
    val = max(nodal_line(p1, 0.22), nodal_line(p2, 0.18) * secondary_mix)

    # Brightness pulses with bass envelope
    val *= (0.5 + bass * 1.2)

    hue = (theta / (2.0 * math.pi) * 0.6 + r * 0.8 + t * 0.02) % 1.0
    sat = min(1.0, 0.75 + 0.15 * math.sin(r * 5.0 + theta * 2.0))
    return hsv_rgb(hue, sat, min(1.0, val * 1.3))


def cym_grid_default(nx, ny, t):
    """Default mode — gentle slow animation, no audio."""
    return cym_grid(nx, ny, t, bass=0.15, mid=0.1, treble=0.08)


# ═════════════════════════════════════════════════════════════════════════════
# RENDER ENGINE
# ═════════════════════════════════════════════════════════════════════════════

def render_frame(func, w, h, t, audio=None):
    """Render one frame."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    aspect = w / max(h, 1)

    if audio:
        bass, mid, treble, beat_push = audio.get(t)
    else:
        # DEFAULT mode: smooth continuous expansion at manual BPM pace
        # beat_push advances steadily (one "beat" per 0.5s at 120 BPM)
        beat_push = t * 2.0  # continuous smooth advance
        bass = 0.2 + 0.1 * math.sin(t * 0.3)
        mid = 0.15 + 0.08 * math.sin(t * 0.4)
        treble = 0.1 + 0.06 * math.sin(t * 0.5)

    for y_px in range(h):
        ny = y_px / max(h - 1, 1) - 0.5
        for x_px in range(w):
            nx = (x_px / max(w - 1, 1) - 0.5) * aspect
            r, g, b = func(nx, ny, t, bass, mid, treble, beat_push)
            img[y_px, x_px] = [r, g, b]
    return img


def render_gif(name, func, w, h, audio=None, scale=SCALE):
    """Render an animated GIF."""
    frames = []
    dt = 1.0 / FPS

    print(f"  Rendering {NUM_FRAMES} frames at {w}x{h} ({w*scale}x{h*scale} upscaled)...")

    for i in range(NUM_FRAMES):
        t = i * dt
        img = render_frame(func, w, h, t, audio)
        # Upscale for visibility
        big = np.repeat(np.repeat(img, scale, axis=0), scale, axis=1)
        frames.append(Image.fromarray(big))

    path = os.path.join(OUTPUT_DIR, f"{name}.gif")
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_DELAY_MS,
        loop=0
    )
    print(f"  Saved: {path} ({len(frames)} frames, {DURATION_S}s)")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def cym_grid_radiate(nx, ny, t, bass=0, mid=0, treble=0, beat_push=0):
    """Cymatics Grid Radiate — rings expand outward perpetually from center.

    Like flying into a tunnel. Rings ONLY move outward, never inward.
    beat_push drives the expansion speed — each beat accelerates the outward flow.
    Between beats the expansion continues but slower.
    """
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    n_angular = 4.0 + mid * 5.0
    r_freq = 4.0 + bass * 2.0

    # THE KEY: subtract beat_push from r so rings move outward
    # As beat_push increases, a ring at radius R now appears at radius R-push
    # which means it has moved outward. New rings emerge from center.
    outward = beat_push * 1.5  # continuous outward motion

    # Pattern: concentric rings expanding outward with angular symmetry
    p1 = math.cos((r * r_freq) - outward) * (0.6 + 0.4 * math.cos(n_angular * theta))

    # Secondary layer: finer detail also expanding
    p2 = math.cos((r * r_freq * 1.8) - outward * 1.3) * math.cos((n_angular + 2) * theta) * 0.4

    val = max(nodal_line(p1, 0.25), nodal_line(p2, 0.2) * (0.3 + treble * 0.5))

    # Brightness: brighter on beat, always visible
    val *= (0.5 + bass * 1.0)

    # Holographic colors
    hue = (theta / (2.0 * math.pi) * 0.6 + r * 0.8 + t * 0.02) % 1.0
    sat = min(1.0, 0.75 + 0.15 * math.sin(r * 5.0 + theta * 2.0))
    return hsv_rgb(hue, sat, min(1.0, val * 1.3))


TESTS = {
    "cym_grid_pulse": {
        "func": cym_grid,
        "desc": "Cymatics Grid Pulse — shape throbs with each beat",
    },
    "cym_grid_radiate": {
        "func": cym_grid_radiate,
        "desc": "Cymatics Grid Radiate — rings expand outward like a tunnel",
    },
}


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    use_audio = "--audio" in sys.argv

    print(f"\n=== Animated Test Harness ===")
    print(f"FPS: {FPS}, Duration: {DURATION_S}s, Frames: {NUM_FRAMES}")
    print(f"Audio: {'120 BPM simulated beats' if use_audio else 'DEFAULT (no audio)'}\n")

    audio = SimulatedAudio(bpm=120) if use_audio else None

    for name, test in TESTS.items():
        if target and target != name:
            continue

        func = test["func"]
        print(f"[{name}] {test['desc']}")

        # Side panel (wide)
        suffix = "_audio" if use_audio else "_default"
        render_gif(f"{name}_side{suffix}", func, SIDE_W, SIDE_H, audio, scale=3)

        # Front panel
        render_gif(f"{name}_front{suffix}", func, FRONT_W, FRONT_H, audio, scale=4)

    print(f"\nDone! Open test_output/*.gif to review animations.")


if __name__ == "__main__":
    main()
