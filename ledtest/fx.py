"""
Post-processing FX that layer on top of any animation.
Each FX modifies a (height, width, 3) uint8 frame in-place or returns a new one.
FX maintain their own state between frames via the FXEngine class.
"""
import math
import random
import numpy as np


class FXEngine:
    """Manages and applies post-processing effects to animation frames."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.active_fx = None  # None = no FX
        self.intensity = 0.5   # FX strength 0..1

        # Persistent state for stateful FX
        self._trail_buffer = np.zeros((height, width, 3), dtype=np.float32)
        self._ripple_buf1 = np.zeros((height, width), dtype=np.float32)
        self._ripple_buf2 = np.zeros((height, width), dtype=np.float32)
        self._prev_frame = None
        self._sparkle_map = np.zeros((height, width), dtype=np.float32)
        self._time = 0.0

    def reset(self):
        """Clear all FX state buffers."""
        self._trail_buffer[:] = 0
        self._ripple_buf1[:] = 0
        self._ripple_buf2[:] = 0
        self._prev_frame = None
        self._sparkle_map[:] = 0

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


# ─── FX Implementations ──────────────────────────────────────────────────────

def fx_glow(engine, frame, dt):
    """Bloom/glow — bright pixels bleed into neighbors."""
    strength = engine.intensity
    f = frame.astype(np.float32)

    # Simple 3x3 box blur for bloom
    blurred = np.zeros_like(f)
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            blurred += np.roll(np.roll(f, dy, axis=0), dx, axis=1)
    blurred /= 9.0

    # Blend: original + bloom on bright areas
    result = f + blurred * strength * 0.8
    return np.clip(result, 0, 255).astype(np.uint8)


def fx_trails(engine, frame, dt):
    """Persistence/afterimage — pixels fade slowly instead of snapping off."""
    decay = 0.6 + engine.intensity * 0.35  # 0.6 to 0.95
    f = frame.astype(np.float32)

    # Blend with trail buffer
    engine._trail_buffer = np.maximum(f, engine._trail_buffer * decay)
    return np.clip(engine._trail_buffer, 0, 255).astype(np.uint8)


def fx_ripple(engine, frame, dt):
    """Water ripple — motion creates expanding wave distortion."""
    f = frame.astype(np.float32)
    h, w = engine.height, engine.width

    # Detect motion to inject energy
    if engine._prev_frame is not None:
        diff = np.abs(f.mean(axis=2) - engine._prev_frame.astype(np.float32).mean(axis=2))
        engine._ripple_buf1 += diff * engine.intensity * 0.15

    # Propagate ripple (wave equation)
    damping = 0.92
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            engine._ripple_buf2[y, x] = (
                (engine._ripple_buf1[y-1, x] +
                 engine._ripple_buf1[y+1, x] +
                 engine._ripple_buf1[y, x-1] +
                 engine._ripple_buf1[y, x+1]) / 2.0
                - engine._ripple_buf2[y, x]
            ) * damping

    # Swap buffers
    engine._ripple_buf1, engine._ripple_buf2 = engine._ripple_buf2, engine._ripple_buf1

    # Apply ripple as brightness boost
    ripple_val = np.abs(engine._ripple_buf1)
    boost = 1.0 + ripple_val[:, :, np.newaxis] * 3.0
    result = f * boost
    return np.clip(result, 0, 255).astype(np.uint8)


def fx_pulse(engine, frame, dt):
    """Breathing pulse — global brightness oscillates smoothly."""
    t = engine._time
    freq = 1.0 + engine.intensity * 2.0  # 1-3 Hz
    # Sine wave from 0.3 to 1.0 (never fully dark)
    mod = 0.3 + 0.7 * ((math.sin(t * freq * math.pi * 2) + 1) / 2)
    result = frame.astype(np.float32) * mod
    return np.clip(result, 0, 255).astype(np.uint8)


def fx_mirror_h(engine, frame, dt):
    """Horizontal mirror — left half is reflected to right."""
    result = frame.copy()
    mid = engine.width // 2
    result[:, mid:, :] = result[:, :mid, :][:, ::-1, :]
    return result


def fx_mirror_v(engine, frame, dt):
    """Vertical mirror — top half is reflected to bottom."""
    result = frame.copy()
    mid = engine.height // 2
    result[mid:, :, :] = result[:mid, :, :][::-1, :, :]
    return result


def fx_kaleidoscope(engine, frame, dt):
    """Kaleidoscope — both horizontal and vertical mirror."""
    result = frame.copy()
    mid_x = engine.width // 2
    mid_y = engine.height // 2
    # Mirror top-left to all quadrants
    result[:mid_y, mid_x:, :] = result[:mid_y, :mid_x, :][:, ::-1, :]
    result[mid_y:, :, :] = result[:mid_y, :, :][::-1, :, :]
    return result


def fx_sparkle(engine, frame, dt):
    """Sparkle overlay — random bright pixels flash on top."""
    result = frame.astype(np.float32)

    # Decay existing sparkles
    engine._sparkle_map *= 0.85

    # Add new sparkles proportional to intensity
    chance = 0.02 + engine.intensity * 0.08
    new_sparkles = np.random.random((engine.height, engine.width)) < chance
    engine._sparkle_map[new_sparkles] = 1.0

    # Overlay sparkles as white additive
    sparkle_boost = engine._sparkle_map[:, :, np.newaxis] * 200
    result += sparkle_boost
    return np.clip(result, 0, 255).astype(np.uint8)


def fx_strobe(engine, frame, dt):
    """Strobe — fast on/off flashing at controlled rate."""
    freq = 2.0 + engine.intensity * 8.0  # 2-10 Hz
    on = math.sin(engine._time * freq * math.pi * 2) > 0
    if on:
        return frame
    else:
        return np.zeros_like(frame)


def fx_wave_distort(engine, frame, dt):
    """Wave distortion — rows shift horizontally in a sine wave pattern."""
    result = np.zeros_like(frame)
    t = engine._time
    amplitude = 1 + int(engine.intensity * 4)  # 1-5 pixel shift

    for y in range(engine.height):
        shift = int(math.sin(y * 0.5 + t * 3) * amplitude)
        result[y] = np.roll(frame[y], shift, axis=0)
    return result


def fx_color_shift(engine, frame, dt):
    """Color channel shift — R/G/B channels offset in different directions."""
    offset = max(1, int(engine.intensity * 3))
    result = np.zeros_like(frame)
    # Red shifts right, blue shifts left, green stays
    result[:, :, 0] = np.roll(frame[:, :, 0], offset, axis=1)   # R → right
    result[:, :, 1] = frame[:, :, 1]                              # G stays
    result[:, :, 2] = np.roll(frame[:, :, 2], -offset, axis=1)  # B → left
    return result


def fx_invert(engine, frame, dt):
    """Color invert — negative image effect."""
    return 255 - frame


def fx_threshold(engine, frame, dt):
    """Threshold — pixels are either full bright or off, no in-between."""
    threshold = int(60 + (1.0 - engine.intensity) * 140)  # higher intensity = lower threshold
    brightness = frame.astype(np.float32).mean(axis=2)
    mask = brightness > threshold
    result = np.zeros_like(frame)
    result[mask] = frame[mask]
    # Boost the survivors
    return np.clip(result.astype(np.float32) * 1.5, 0, 255).astype(np.uint8)


def fx_pixelate(engine, frame, dt):
    """Pixelate — reduce resolution by averaging blocks."""
    block = max(2, int(2 + engine.intensity * 4))  # 2-6 pixel blocks
    result = frame.copy()
    for y in range(0, engine.height, block):
        for x in range(0, engine.width, block):
            y_end = min(y + block, engine.height)
            x_end = min(x + block, engine.width)
            avg = frame[y:y_end, x:x_end].mean(axis=(0, 1)).astype(np.uint8)
            result[y:y_end, x:x_end] = avg
    return result


def fx_scan_line(engine, frame, dt):
    """Scan line — a bright horizontal line sweeps across the frame."""
    t = engine._time
    speed = 1.0 + engine.intensity * 2.0
    scan_y = (t * speed) % 1.0  # 0..1 normalized position
    result = frame.astype(np.float32)

    for y in range(engine.height):
        ny = y / max(engine.height - 1, 1)
        dist = abs(ny - scan_y)
        if dist < 0.15:
            boost = 1.0 + (1.0 - dist / 0.15) * 2.0
            result[y] *= boost

    return np.clip(result, 0, 255).astype(np.uint8)


def fx_vignette(engine, frame, dt):
    """Vignette — edges darken, center brightens."""
    result = frame.astype(np.float32)
    strength = 0.3 + engine.intensity * 0.7

    for y in range(engine.height):
        for x in range(engine.width):
            nx = x / max(engine.width - 1, 1)
            ny = y / max(engine.height - 1, 1)
            dist = math.sqrt((nx - 0.5)**2 + (ny - 0.5)**2) * 2  # 0 at center, ~1.4 at corners
            factor = max(0, 1.0 - dist * strength)
            result[y, x] *= factor

    return np.clip(result, 0, 255).astype(np.uint8)


# ─── FX Registry ─────────────────────────────────────────────────────────────

FX_REGISTRY = {
    "glow":         fx_glow,
    "trails":       fx_trails,
    "ripple":       fx_ripple,
    "pulse":        fx_pulse,
    "mirror_h":     fx_mirror_h,
    "mirror_v":     fx_mirror_v,
    "kaleidoscope": fx_kaleidoscope,
    "sparkle":      fx_sparkle,
    "strobe":       fx_strobe,
    "wave_distort": fx_wave_distort,
    "color_shift":  fx_color_shift,
    "invert":       fx_invert,
    "threshold":    fx_threshold,
    "pixelate":     fx_pixelate,
    "scan_line":    fx_scan_line,
    "vignette":     fx_vignette,
}

# Ordered list for UI display
FX_LIST = [
    {"key": "none",         "name": "None"},
    {"key": "glow",         "name": "Glow"},
    {"key": "trails",       "name": "Trails"},
    {"key": "ripple",       "name": "Ripple"},
    {"key": "pulse",        "name": "Pulse"},
    {"key": "sparkle",      "name": "Sparkle"},
    {"key": "strobe",       "name": "Strobe"},
    {"key": "wave_distort", "name": "Wave Distort"},
    {"key": "color_shift",  "name": "Color Shift"},
    {"key": "mirror_h",     "name": "Mirror H"},
    {"key": "mirror_v",     "name": "Mirror V"},
    {"key": "kaleidoscope", "name": "Kaleidoscope"},
    {"key": "invert",       "name": "Invert"},
    {"key": "threshold",    "name": "Threshold"},
    {"key": "pixelate",     "name": "Pixelate"},
    {"key": "scan_line",    "name": "Scan Line"},
    {"key": "vignette",     "name": "Vignette"},
]
