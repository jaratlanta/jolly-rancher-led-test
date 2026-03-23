"""
Post-processing FX that layer on top of any animation.
Each FX modifies a (height, width, 3) uint8 frame in-place or returns a new one.
FX maintain their own state between frames via the FXEngine class.
"""
import math
import numpy as np


class FXEngine:
    """Manages and applies post-processing effects to animation frames."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.active_fx = None  # None = no FX
        self.intensity = 0.5   # FX strength 0..1

        # Persistent state
        self._trail_buffer = np.zeros((height, width, 3), dtype=np.float32)
        self._trail_hue_shift = np.zeros((height, width), dtype=np.float32)
        self._ripple_buf1 = np.zeros((height, width), dtype=np.float32)
        self._ripple_buf2 = np.zeros((height, width), dtype=np.float32)
        self._ripple_energy = np.zeros((height, width), dtype=np.float32)
        self._prev_frame = None
        self._glow_accum = np.zeros((height, width, 3), dtype=np.float32)
        self._time = 0.0

    def reset(self):
        """Clear all FX state buffers."""
        self._trail_buffer[:] = 0
        self._trail_hue_shift[:] = 0
        self._ripple_buf1[:] = 0
        self._ripple_buf2[:] = 0
        self._ripple_energy[:] = 0
        self._prev_frame = None
        self._glow_accum[:] = 0

    def set_fx(self, fx_name):
        """Set the active FX by name, or None to disable."""
        if fx_name != self.active_fx:
            self.active_fx = fx_name
            self.reset()

    def process(self, frame, dt):
        """Apply the active FX to a frame. Returns the modified frame."""
        self._time += dt

        if self.active_fx is None or self.active_fx == "none":
            self._prev_frame = frame.copy()
            return frame

        fn = FX_REGISTRY.get(self.active_fx)
        if fn is None:
            self._prev_frame = frame.copy()
            return frame

        result = fn(self, frame, dt)
        self._prev_frame = frame.copy()
        return result


# ─── Helper: multi-pass blur ─────────────────────────────────────────────────

def _blur(f, passes=1):
    """Fast box blur using numpy rolls. Multiple passes = smoother."""
    result = f.copy()
    for _ in range(passes):
        acc = np.zeros_like(result)
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                acc += np.roll(np.roll(result, dy, axis=0), dx, axis=1)
        result = acc / 9.0
    return result


# ─── FX: Glow ────────────────────────────────────────────────────────────────

def fx_glow(engine, frame, dt):
    """Dynamic bloom — bright areas radiate light outward with pulsing intensity.

    Multi-pass blur extracts a wide bloom from bright pixels and blends it
    back with a breathing intensity cycle so the glow visibly throbs.
    An accumulator adds temporal smoothness so the glow lingers and swells.
    """
    strength = 0.5 + engine.intensity * 1.5  # 0.5 to 2.0
    f = frame.astype(np.float32)

    # Extract bright areas (threshold to isolate highlights)
    brightness = f.max(axis=2)
    threshold = 60
    mask = (brightness > threshold)[:, :, np.newaxis].astype(np.float32)
    highlights = f * mask

    # Multi-pass blur for wide bloom spread
    num_passes = 2 + int(engine.intensity * 3)  # 2-5 passes
    bloom = _blur(highlights, passes=num_passes)

    # Breathing pulse on the bloom intensity
    pulse = 0.7 + 0.3 * math.sin(engine._time * 2.5)

    # Accumulate glow over time (smooth temporal bloom)
    engine._glow_accum = engine._glow_accum * 0.7 + bloom * 0.3

    # Combine: original + wide bloom + accumulated glow
    result = f + engine._glow_accum * strength * pulse + bloom * strength * 0.5 * pulse

    # Boost the original bright pixels too (simulates emissive surfaces)
    emissive_boost = mask * f * strength * 0.3
    result += emissive_boost

    return np.clip(result, 0, 255).astype(np.uint8)


# ─── FX: Trails ──────────────────────────────────────────────────────────────

def fx_trails(engine, frame, dt):
    """Comet trails — moving pixels leave long glowing tails that fade with
    a color shift toward cooler tones. Brighter pixels persist longer.

    The trail buffer decays each frame but retains peaks, creating streaks
    behind any motion. A subtle hue rotation makes old trail pixels shift
    toward blue/purple as they age.
    """
    # Higher intensity = longer persistence
    decay = 0.75 + engine.intensity * 0.22  # 0.75 to 0.97
    f = frame.astype(np.float32)

    # Detect which pixels are "new" (brighter than the trail)
    current_brightness = f.max(axis=2)
    trail_brightness = engine._trail_buffer.max(axis=2)
    new_pixels = current_brightness > trail_brightness + 5

    # Update trail: decay old, stamp new
    engine._trail_buffer *= decay
    engine._trail_buffer = np.maximum(engine._trail_buffer, f * 0.95)

    # Age tracking: pixels that aren't refreshed get older
    engine._trail_hue_shift += dt * 2.0
    engine._trail_hue_shift[new_pixels] = 0  # reset age for fresh pixels

    # Apply color shift on aged trail pixels: shift toward blue/purple
    aged = engine._trail_buffer.copy()
    shift_amount = np.clip(engine._trail_hue_shift * 0.15, 0, 1)
    # Reduce red, boost blue as trail ages
    aged[:, :, 0] *= (1.0 - shift_amount * 0.6)  # red fades
    aged[:, :, 2] = np.minimum(255, aged[:, :, 2] + aged[:, :, 0] * shift_amount * 0.4)  # blue gains

    # Combine: fresh frame on top, aged trails behind
    result = np.maximum(f, aged)

    # Add a subtle bloom to the trails
    trail_only = np.maximum(0, aged - f)
    if trail_only.max() > 5:
        trail_bloom = _blur(trail_only, passes=1)
        result += trail_bloom * 0.3

    return np.clip(result, 0, 255).astype(np.uint8)


# ─── FX: Ripple ──────────────────────────────────────────────────────────────

def fx_ripple(engine, frame, dt):
    """Water ripple — pixel motion and brightness inject energy into a 2D wave
    simulation that displaces the image, creating visible expanding rings.

    Uses the wave equation for propagation. The ripple displacement actually
    shifts which pixel you see (refraction-style), plus adds a brightness
    boost on the wavefronts for visible white-capped ripple edges.
    """
    f = frame.astype(np.float32)
    h, w = engine.height, engine.width
    strength = 0.5 + engine.intensity * 2.5  # 0.5 to 3.0

    # Inject energy from motion detection
    if engine._prev_frame is not None:
        diff = np.abs(f.mean(axis=2) - engine._prev_frame.astype(np.float32).mean(axis=2))
        # Only inject where there's significant motion
        motion_mask = diff > 15
        engine._ripple_buf1[motion_mask] += diff[motion_mask] * 0.08 * strength

    # Also inject energy from bright pixels (animations "drop" into the water)
    bright = f.max(axis=2)
    hot_spots = bright > 150
    engine._ripple_buf1[hot_spots] += (bright[hot_spots] / 255.0) * 0.03 * strength

    # Propagate wave equation (vectorized for speed)
    # wave[y,x] = avg(neighbors) * 2 - prev[y,x], with damping
    damping = 0.94 - engine.intensity * 0.04  # 0.94 to 0.90 (more intensity = more sustain)
    padded = np.pad(engine._ripple_buf1, 1, mode='edge')
    neighbors = (padded[:-2, 1:-1] + padded[2:, 1:-1] +
                 padded[1:-1, :-2] + padded[1:-1, 2:]) / 2.0
    engine._ripple_buf2 = (neighbors - engine._ripple_buf2) * damping

    # Swap
    engine._ripple_buf1, engine._ripple_buf2 = engine._ripple_buf2, engine._ripple_buf1

    ripple = engine._ripple_buf1

    # Displacement: shift pixel lookups based on ripple gradient
    # Compute gradient (where the wave is sloping)
    grad_x = np.zeros((h, w), dtype=np.float32)
    grad_y = np.zeros((h, w), dtype=np.float32)
    grad_x[:, 1:-1] = ripple[:, 2:] - ripple[:, :-2]
    grad_y[1:-1, :] = ripple[2:, :] - ripple[:-2, :]

    # Displacement magnitude scales with intensity
    disp_scale = 1.0 + engine.intensity * 3.0

    # Build displaced coordinates
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing='ij')
    src_x = np.clip((xx + grad_x * disp_scale).astype(int), 0, w - 1)
    src_y = np.clip((yy + grad_y * disp_scale).astype(int), 0, h - 1)

    # Sample from displaced positions
    result = f[src_y, src_x]

    # Add bright edges on wavefronts (where gradient is steep)
    edge_strength = np.sqrt(grad_x**2 + grad_y**2)
    edge_boost = np.clip(edge_strength * 15 * strength, 0, 120)
    result += edge_boost[:, :, np.newaxis]

    # Subtle darkening in wave troughs
    trough = np.clip(-ripple * 8 * strength, 0, 40)
    result -= trough[:, :, np.newaxis]

    return np.clip(result, 0, 255).astype(np.uint8)


# ─── FX Registry ─────────────────────────────────────────────────────────────

FX_REGISTRY = {
    "glow":   fx_glow,
    "trails": fx_trails,
    "ripple": fx_ripple,
}

# Ordered list for UI display
FX_LIST = [
    {"key": "none",   "name": "None"},
    {"key": "glow",   "name": "Glow"},
    {"key": "trails", "name": "Trails"},
    {"key": "ripple", "name": "Ripple"},
]
