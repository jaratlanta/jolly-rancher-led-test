#!/usr/bin/env python3
"""
Focused test harness for Cym Grid visualization.

Renders at EXACT panel dimensions to verify:
1. Centering on all panel types
2. Audio reactivity (simulated bass sweep)
3. Animation speed/smoothness
4. Color quality

Output: test_output/cym_grid_*.png
"""
import math
import colorsys
import os
import numpy as np
from PIL import Image

OUTPUT_DIR = "test_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Exact panel dimensions
PANELS = {
    "front":  (72, 24),    # Front panel
    "side":   (220, 24),   # Left/Right side panel
    "test":   (24, 12),    # Test panel
}


def hsv_rgb(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1, s), min(1, v))
    return int(r * 255), int(g * 255), int(b * 255)


def nodal_line(val, thickness=0.15):
    v = max(0, 1.0 - abs(val) / thickness)
    return v * v


def cym_grid(nx, ny, t, bass=0, mid=0, treble=0):
    """Cymatics Grid — the pattern we're perfecting.

    GOALS:
    - Centered symmetric pattern on all panels
    - Slow, graceful default animation (not erratic)
    - Bass DRAMATICALLY changes the pattern structure
    - Multi-color holographic gradients (not monochrome)

    nx, ny: centered coordinates (-0.5 to 0.5 for square, wider for wide)
    t: time (should be slow — 0.1-0.3 speed range)
    bass/mid/treble: 0-1 audio values
    """
    r = math.sqrt(nx * nx + ny * ny)
    theta = math.atan2(ny, nx)

    # AUDIO: each band drives a different visual dimension
    # Bass  → radial ring spacing (more bass = rings expand outward)
    # Mid   → angular symmetry order (more mid = more complex symmetry)
    # Treble→ secondary pattern intensity + rotation speed

    r_freq1 = 3.5 + bass * 5.0            # bass: 3.5 to 8.5 rings
    n_angular = 4.0 + mid * 6.0           # mid: 4 to 10 fold symmetry
    r_freq2 = 6.0 + treble * 6.0          # treble: finer secondary detail
    rotation = t * 0.1 + treble * 1.5     # treble spins the pattern faster
    secondary_mix = 0.3 + treble * 0.5    # treble brings in the 2nd layer

    # Primary pattern: radial rings × angular symmetry
    p1 = math.cos(r * r_freq1 - rotation) + math.cos(n_angular * theta)

    # Secondary pattern: finer detail, shifted — treble controls how much it shows
    p2 = math.cos(r * r_freq2 + rotation * 0.7) * math.cos((n_angular + 2) * theta + math.pi / 4)

    # Combine: nodal lines where patterns cross zero
    # Treble controls how much the secondary layer contributes
    val = max(nodal_line(p1, 0.22), nodal_line(p2, 0.18) * secondary_mix)

    # HOLOGRAPHIC multi-color gradient:
    # Hue changes with BOTH angle AND radius for rainbow-across-the-pattern
    hue = (
        theta / (2.0 * math.pi) * 0.6  # angular rainbow (60% of hue range)
        + r * 0.8                         # radial color shift
        + t * 0.02                        # slow drift over time
    ) % 1.0

    # Higher saturation for vivid colors
    sat = 0.75 + 0.15 * math.sin(r * 5.0 + theta * 2.0)

    return hsv_rgb(hue, min(1.0, sat), min(1.0, val * 1.2))


def render_panel(panel_name, w, h, t, bass=0, mid=0, treble=0):
    """Render cym_grid to a panel at exact dimensions."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    aspect = w / max(h, 1)

    for y_px in range(h):
        ny = y_px / max(h - 1, 1) - 0.5  # -0.5 to 0.5
        for x_px in range(w):
            # Square coordinate space: X scaled by aspect ratio
            nx = (x_px / max(w - 1, 1) - 0.5) * aspect
            r, g, b = cym_grid(nx, ny, t, bass, mid, treble)
            img[y_px, x_px] = [r, g, b]

    return img


def save_filmstrip_vertical(name, frames):
    """Stack frames vertically with labels."""
    border = np.full((2, frames[0].shape[1], 3), 60, dtype=np.uint8)
    strips = []
    for i, f in enumerate(frames):
        if i > 0:
            strips.append(border)
        strips.append(f)
    filmstrip = np.concatenate(strips, axis=0)
    path = os.path.join(OUTPUT_DIR, f"{name}.png")
    Image.fromarray(filmstrip).save(path)
    print(f"  Saved: {path} ({filmstrip.shape[1]}x{filmstrip.shape[0]})")


def main():
    print("=== Cym Grid Test Harness ===\n")

    # Test 1: All panel types at t=0 (verify centering)
    print("[Test 1] Centering on all panel types (t=0)")
    for panel_name, (w, h) in PANELS.items():
        img = render_panel(panel_name, w, h, t=0)
        # Scale up for visibility (4x)
        scale = 4
        big = np.repeat(np.repeat(img, scale, axis=0), scale, axis=1)
        path = os.path.join(OUTPUT_DIR, f"cym_grid_center_{panel_name}.png")
        Image.fromarray(big).save(path)
        print(f"  {panel_name} ({w}x{h}) → {path}")

    # Test 2: Side panel animation (5 frames, slow animation)
    print("\n[Test 2] Side panel animation (5 frames, t=0,2,4,6,8)")
    frames = []
    for i in range(5):
        t = i * 2.0
        frame = render_panel("side", 220, 24, t)
        # Scale up 3x for visibility
        big = np.repeat(np.repeat(frame, 3, axis=0), 3, axis=1)
        frames.append(big)
    save_filmstrip_vertical("cym_grid_side_anim", frames)

    # Test 3: Front panel animation
    print("\n[Test 3] Front panel animation (5 frames)")
    frames = []
    for i in range(5):
        t = i * 2.0
        frame = render_panel("front", 72, 24, t)
        scale = 4
        big = np.repeat(np.repeat(frame, scale, axis=0), scale, axis=1)
        frames.append(big)
    save_filmstrip_vertical("cym_grid_front_anim", frames)

    # Test 4: Bass sweep (rings expand)
    print("\n[Test 4] Bass sweep (rings expand) 0.0 → 1.0")
    frames = []
    for i in range(5):
        bass = i * 0.25
        frame = render_panel("side", 220, 24, t=2.0, bass=bass)
        big = np.repeat(np.repeat(frame, 3, axis=0), 3, axis=1)
        frames.append(big)
    save_filmstrip_vertical("cym_grid_bass_sweep", frames)

    # Test 5: Mid sweep (symmetry complexity)
    print("\n[Test 5] Mid sweep (symmetry grows) 0.0 → 1.0")
    frames = []
    for i in range(5):
        mid = i * 0.25
        frame = render_panel("side", 220, 24, t=2.0, mid=mid)
        big = np.repeat(np.repeat(frame, 3, axis=0), 3, axis=1)
        frames.append(big)
    save_filmstrip_vertical("cym_grid_mid_sweep", frames)

    # Test 6: Treble sweep (detail + rotation)
    print("\n[Test 6] Treble sweep (detail + spin) 0.0 → 1.0")
    frames = []
    for i in range(5):
        treble = i * 0.25
        frame = render_panel("side", 220, 24, t=2.0, treble=treble)
        big = np.repeat(np.repeat(frame, 3, axis=0), 3, axis=1)
        frames.append(big)
    save_filmstrip_vertical("cym_grid_treble_sweep", frames)

    # Test 7: Full audio (all bands rising together)
    print("\n[Test 7] Full audio sweep (all bands 0.0 → 1.0)")
    frames = []
    for i in range(5):
        v = i * 0.25
        frame = render_panel("side", 220, 24, t=2.0, bass=v, mid=v, treble=v)
        big = np.repeat(np.repeat(frame, 3, axis=0), 3, axis=1)
        frames.append(big)
    save_filmstrip_vertical("cym_grid_full_audio", frames)

    print("\nDone! Check test_output/cym_grid_*.png")


if __name__ == "__main__":
    main()
