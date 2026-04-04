"""
Waveform visualizations — direct RGB rendering with persistence and color.

NEW ARCHITECTURE:
  render(frame, w, h, t, fft, td, bass, mid, treble)
    - frame: (h, w, 3) uint8 numpy array — draw directly into it
    - fft: 128 floats (frequency domain) or None for DEFAULT mode
    - td: 128 floats (time domain, centered at 128) or None
    - bass/mid/treble: 0-1 floats or 0 for DEFAULT

  Returns nothing — modifies frame in-place.

KEY TECHNIQUES:
  - Rainbow HSV color mapped by X position (not palette)
  - Persistence trail buffers that fade over time
  - Pre-compute per-column values, then fill pixels (fast)
  - Vertical bar fills with gradient edges
  - Multiple layers composited additively
"""
import math
import numpy as np
import colorsys
import time as _time


# ─── Palette Bias ────────────────────────────────────────────────────────────

# Current palette colors: (highlight, mid, shadow) as RGB tuples
_palette_colors = [(0, 255, 255), (255, 0, 255), (75, 0, 130)]
_palette_blend = 0.45  # how much palette influences waveform color (0=pure rainbow, 1=pure palette)


def set_palette_bias(colors):
    """Called by the engine each frame with the current palette's colors."""
    global _palette_colors
    if colors and len(colors) >= 2:
        _palette_colors = colors


# ─── Color Helpers ───────────────────────────────────────────────────────────

def _hsv_rgb(h, s=1.0, v=1.0):
    """HSV to RGB tuple (0-255 each). h is 0-1."""
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1, s), min(1, v))
    return int(r * 255), int(g * 255), int(b * 255)


def _rainbow_color(nx, t, speed=0.1, saturation=1.0, value=1.0):
    """Rainbow color biased toward the current palette.

    Blends a pure rainbow hue with the palette's highlight/mid colors
    so the waveform takes on the palette's character while still having
    color variety across X position.
    """
    hue = (nx + t * speed) % 1.0
    rr, rg, rb = colorsys.hsv_to_rgb(hue, min(1, saturation), min(1, value))
    rr, rg, rb = rr * 255, rg * 255, rb * 255

    # Palette color: lerp between highlight and mid based on nx
    p_hi = _palette_colors[0]
    p_mid = _palette_colors[1]
    px = nx  # position-based blend between highlight and mid
    pr = p_hi[0] * (1 - px) + p_mid[0] * px
    pg = p_hi[1] * (1 - px) + p_mid[1] * px
    pb = p_hi[2] * (1 - px) + p_mid[2] * px

    # Scale palette color by value
    pr *= value
    pg *= value
    pb *= value

    # Blend rainbow with palette
    blend = _palette_blend
    r = int(rr * (1 - blend) + pr * blend)
    g = int(rg * (1 - blend) + pg * blend)
    b = int(rb * (1 - blend) + pb * blend)

    return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))


_BRIGHTNESS_BOOST = 1.25  # global brightness multiplier for waveforms


def _add_pixel(frame, y, x, r, g, b):
    """Additive blend a color onto frame (clamped to 255)."""
    h, w = frame.shape[:2]
    if 0 <= y < h and 0 <= x < w:
        frame[y, x, 0] = min(255, int(frame[y, x, 0] + r * _BRIGHTNESS_BOOST))
        frame[y, x, 1] = min(255, int(frame[y, x, 1] + g * _BRIGHTNESS_BOOST))
        frame[y, x, 2] = min(255, int(frame[y, x, 2] + b * _BRIGHTNESS_BOOST))


def _set_pixel(frame, y, x, r, g, b):
    """Set pixel, taking max of existing and new (brightness boosted)."""
    h, w = frame.shape[:2]
    if 0 <= y < h and 0 <= x < w:
        frame[y, x, 0] = min(255, max(frame[y, x, 0], int(r * _BRIGHTNESS_BOOST)))
        frame[y, x, 1] = min(255, max(frame[y, x, 1], int(g * _BRIGHTNESS_BOOST)))
        frame[y, x, 2] = min(255, max(frame[y, x, 2], int(b * _BRIGHTNESS_BOOST)))


# ─── Trail / Persistence Buffers ─────────────────────────────────────────────

class TrailBuffer:
    """Persistent frame buffer that fades over time — creates afterglow."""
    def __init__(self):
        self._buf = None
        self._shape = None

    def get(self, h, w, decay=0.85):
        """Get the trail buffer, decayed. Creates/resizes as needed."""
        shape = (h, w, 3)
        if self._buf is None or self._shape != shape:
            self._buf = np.zeros(shape, dtype=np.float32)
            self._shape = shape
        self._buf *= decay
        return self._buf

    def stamp(self, y, x, r, g, b):
        """Stamp a bright pixel into the trail."""
        if self._buf is not None:
            h, w = self._buf.shape[:2]
            if 0 <= y < h and 0 <= x < w:
                self._buf[y, x, 0] = max(self._buf[y, x, 0], float(r))
                self._buf[y, x, 1] = max(self._buf[y, x, 1], float(g))
                self._buf[y, x, 2] = max(self._buf[y, x, 2], float(b))

    def apply(self, frame):
        """Composite the trail buffer onto the frame."""
        if self._buf is not None and self._buf.shape == frame.shape:
            np.maximum(frame, self._buf.astype(np.uint8), out=frame)


# One trail buffer per waveform slot
_trails = [TrailBuffer() for _ in range(25)]

# Scroll buffers for cardiogram modes
_scroll_bufs = [np.zeros(1024, dtype=np.float32) for _ in range(4)]
_scroll_idxs = [0] * 4
_scroll_times = [0.0] * 4


def _push_scroll(buf_id, value):
    global _scroll_idxs, _scroll_times
    now = _time.monotonic()
    if now - _scroll_times[buf_id] > 0.025:
        _scroll_bufs[buf_id][_scroll_idxs[buf_id] % 1024] = value
        _scroll_idxs[buf_id] += 1
        _scroll_times[buf_id] = now


def _read_scroll(buf_id, nx, width):
    age = int((1.0 - nx) * min(width * 2, 1024))
    idx = (_scroll_idxs[buf_id] - 1 - age) % 1024
    return _scroll_bufs[buf_id][idx]


# Smooth bar state
_bar_smooth = np.zeros(256, dtype=np.float32)

def _smooth(idx, raw, attack=1.0, decay=0.88):
    idx = idx % 256
    if raw > _bar_smooth[idx]:
        _bar_smooth[idx] = raw * attack + _bar_smooth[idx] * (1 - attack)
    else:
        _bar_smooth[idx] = _bar_smooth[idx] * decay + raw * (1 - decay)
    return _bar_smooth[idx]


# ═════════════════════════════════════════════════════════════════════════════
# WAVEFORM RENDERERS
# ═════════════════════════════════════════════════════════════════════════════


def _render_freq_bars(frame, w, h, t, fft, td, bass, mid, treble):
    """Classic EQ bars — rainbow gradient L→R, bars from bottom with trails."""
    trail = _trails[0].get(h, w, decay=0.75)

    for x in range(w):
        nx = x / max(w - 1, 1)
        # Get bar height
        if fft is not None:
            bi = min(127, int(nx * 100))  # log-ish mapping
            raw = fft[bi] / 255.0
            for o in [-1, 1]:
                raw = max(raw, fft[min(127, max(0, bi + o))] / 255.0 * 0.7)
            bh = _smooth(x, raw)
        else:
            bh = 0.3 + 0.4 * abs(math.sin(t * 2.0 + x * 0.3))
            bh += 0.15 * math.sin(t * 3.5 + x * 0.5)
            bh = max(0.05, min(0.95, bh))

        # Rainbow color for this column
        r, g, b = _rainbow_color(nx, t, speed=0.08)

        # Fill bar from bottom
        bar_top = int((1.0 - bh) * (h - 1))
        for y in range(bar_top, h):
            # Gradient: brighter toward top of bar
            frac = 1.0 - (y - bar_top) / max(1, h - 1 - bar_top)
            intensity = 0.3 + 0.7 * frac
            pr, pg, pb = int(r * intensity), int(g * intensity), int(b * intensity)
            _set_pixel(frame, y, x, pr, pg, pb)
            _trails[0].stamp(y, x, pr // 2, pg // 2, pb // 2)

        # Bright top line
        if 0 <= bar_top < h:
            _set_pixel(frame, bar_top, x, min(255, r + 60), min(255, g + 60), min(255, b + 60))

    _trails[0].apply(frame)


def _render_spectrum_mirror(frame, w, h, t, fft, td, bass, mid, treble):
    """Mirrored spectrum — bars grow from center up+down, rainbow, with trails."""
    trail = _trails[1].get(h, w, decay=0.78)
    center = h // 2

    for x in range(w):
        nx = x / max(w - 1, 1)
        if fft is not None:
            bi = min(127, int(nx * 127))
            raw = fft[bi] / 255.0
            for o in [-2, -1, 1, 2]:
                raw = max(raw, fft[min(127, max(0, bi + o))] / 255.0 * 0.5)
            amp = _smooth(x, raw)
        else:
            amp = 0.4 * abs(math.sin(nx * 4.0 * math.pi + t * 1.5))
            amp += 0.25 * abs(math.sin(nx * 9.0 * math.pi + t * 2.3))
            amp = min(0.95, amp)

        r, g, b = _rainbow_color(nx, t, speed=0.1)
        half_h = int(amp * center)

        for dy in range(half_h + 1):
            frac = dy / max(1, half_h)
            intensity = 0.2 + 0.8 * frac
            pr, pg, pb = int(r * intensity), int(g * intensity), int(b * intensity)
            # Upper half
            y_up = center - dy
            _set_pixel(frame, y_up, x, pr, pg, pb)
            _trails[1].stamp(y_up, x, pr // 3, pg // 3, pb // 3)
            # Lower half
            y_dn = center + dy
            _set_pixel(frame, y_dn, x, pr, pg, pb)
            _trails[1].stamp(y_dn, x, pr // 3, pg // 3, pb // 3)

    _trails[1].apply(frame)


def _render_bar_wave(frame, w, h, t, fft, td, bass, mid, treble):
    """Bar wave — mirrored bars + overlaid sine traces in contrasting color."""
    trail = _trails[2].get(h, w, decay=0.72)
    center = h // 2

    for x in range(w):
        nx = x / max(w - 1, 1)
        if fft is not None:
            bi = min(127, int(nx * 127))
            raw = fft[bi] / 255.0
            for o in [-1, 1]:
                raw += fft[min(127, max(0, bi + o))] / 255.0 * 0.3
            amp = _smooth(x + 64, min(0.95, raw / 1.6))
        else:
            amp = 0.35 + 0.4 * abs(math.sin(nx * 2.5 * math.pi + t * 1.0))
            amp += 0.15 * abs(math.sin(nx * 6.0 * math.pi + t * 1.8))
            amp = min(0.95, amp)

        # Bars: warm color
        r, g, b = _rainbow_color(nx, t, speed=0.06)
        half_h = int(amp * center)
        for dy in range(half_h + 1):
            frac = dy / max(1, half_h)
            intensity = 0.15 + 0.85 * frac
            pr, pg, pb = int(r * intensity), int(g * intensity), int(b * intensity)
            _set_pixel(frame, center - dy, x, pr, pg, pb)
            _set_pixel(frame, center + dy, x, pr, pg, pb)
            _trails[2].stamp(center - dy, x, pr // 3, pg // 3, pb // 3)
            _trails[2].stamp(center + dy, x, pr // 3, pg // 3, pb // 3)

    # Overlay sine traces in a different hue
    for x in range(w):
        nx = x / max(w - 1, 1)
        if td is not None:
            ti = min(127, int(nx * 127))
            trace_y = int(td[ti] / 255.0 * (h - 1))
        else:
            trace_y = int((0.5 + 0.3 * math.sin(nx * 3.0 * math.pi + t * 1.5)) * (h - 1))
        trace_y = max(0, min(h - 1, trace_y))
        # White-ish bright trace
        _set_pixel(frame, trace_y, x, 220, 220, 255)
        if trace_y > 0: _set_pixel(frame, trace_y - 1, x, 100, 100, 140)
        if trace_y < h - 1: _set_pixel(frame, trace_y + 1, x, 100, 100, 140)

    _trails[2].apply(frame)


_cardio_wave_buf = None  # persistent frame for wave cardiogram

def _render_cardiogram(frame, w, h, t, fft, td, bass, mid, treble):
    """Cardiogram — single wave trace, newest on LEFT, scrolls RIGHT."""
    global _cardio_wave_buf

    if _cardio_wave_buf is None or _cardio_wave_buf.shape != (h, w, 3):
        _cardio_wave_buf = np.zeros((h, w, 3), dtype=np.uint8)

    # Shift right
    _cardio_wave_buf[:, 1:, :] = _cardio_wave_buf[:, :-1, :]
    _cardio_wave_buf[:, 0, :] = 0

    center = h // 2

    # Get current audio level
    if td is not None:
        energy = bass * 0.6 + mid * 0.3 + treble * 0.1
    else:
        phase = (t * 1.5) % 1.0
        if phase < 0.1:
            energy = 0.8 * math.sin(phase / 0.1 * math.pi)
        elif phase < 0.2:
            energy = -0.3 * math.sin((phase - 0.1) / 0.1 * math.pi)
        else:
            energy = 0.05 * math.sin(phase * 8.0)
        energy = energy * 0.5 + 0.5

    wave_y = int((0.5 + (energy - 0.5) * 0.8) * (h - 1))
    wave_y = max(0, min(h - 1, wave_y))

    r, g, b = _rainbow_color(0.0, t, speed=0.05, saturation=0.85)

    # Draw bar from center to wave on leftmost column
    y_lo, y_hi = min(center, wave_y), max(center, wave_y)
    for y in range(y_lo, y_hi + 1):
        frac = abs(y - center) / max(1, abs(wave_y - center))
        intensity = 0.2 + 0.8 * frac
        _cardio_wave_buf[y, 0] = [int(r * intensity), int(g * intensity), int(b * intensity)]

    # Bright trace point
    _cardio_wave_buf[wave_y, 0] = [min(255, r + 80), min(255, g + 80), min(255, b + 80)]

    # Gentle age fade
    fade = np.ones((1, w, 1), dtype=np.float32)
    for x in range(w):
        fade[0, x, 0] = max(0.25, 1.0 - x * 0.004)
    faded = (_cardio_wave_buf.astype(np.float32) * fade).astype(np.uint8)

    np.maximum(frame, faded, out=frame)


_cardio_mirror_buf = None

def _render_cardio_mirror(frame, w, h, t, fft, td, bass, mid, treble):
    """Mirrored cardiogram — symmetric bars from center, newest LEFT, scrolls RIGHT."""
    global _cardio_mirror_buf

    if _cardio_mirror_buf is None or _cardio_mirror_buf.shape != (h, w, 3):
        _cardio_mirror_buf = np.zeros((h, w, 3), dtype=np.uint8)

    # Shift right
    _cardio_mirror_buf[:, 1:, :] = _cardio_mirror_buf[:, :-1, :]
    _cardio_mirror_buf[:, 0, :] = 0

    center = h // 2

    if td is not None:
        energy = bass * 0.7 + mid * 0.2 + treble * 0.1
    else:
        phase = (t * 1.2) % 1.0
        energy = 0.3 + 0.5 * abs(math.sin(phase * 6.0 * math.pi))

    half_span = int(energy * center * 0.9)
    r, g, b = _rainbow_color(0.0, t, speed=0.07)

    for dy in range(half_span + 1):
        frac = dy / max(1, half_span)
        intensity = 0.15 + 0.85 * frac
        pr, pg, pb = int(r * intensity), int(g * intensity), int(b * intensity)
        y_up = max(0, center - dy)
        y_dn = min(h - 1, center + dy)
        _cardio_mirror_buf[y_up, 0] = [pr, pg, pb]
        _cardio_mirror_buf[y_dn, 0] = [pr, pg, pb]

    if half_span > 0:
        y_top = max(0, center - half_span)
        y_bot = min(h - 1, center + half_span)
        _cardio_mirror_buf[y_top, 0] = [255, 255, 255]
        _cardio_mirror_buf[y_bot, 0] = [255, 255, 255]

    # Gentle age fade
    fade = np.ones((1, w, 1), dtype=np.float32)
    for x in range(w):
        fade[0, x, 0] = max(0.25, 1.0 - x * 0.004)
    faded = (_cardio_mirror_buf.astype(np.float32) * fade).astype(np.uint8)

    np.maximum(frame, faded, out=frame)


def _render_cascade(frame, w, h, t, fft, td, bass, mid, treble):
    """Layered cascade — 3 frequency bands stacked vertically, each with bars."""
    trail = _trails[5].get(h, w, decay=0.76)
    band_h = h // 3

    bands = [
        (0, band_h, 0, 20, 0.0),        # bass zone (top)
        (band_h, band_h * 2, 20, 60, 0.33),  # mid zone (middle)
        (band_h * 2, h, 60, 128, 0.66),    # treble zone (bottom)
    ]

    for y_start, y_end, fft_lo, fft_hi, hue_offset in bands:
        band_center = (y_start + y_end) // 2
        band_half = (y_end - y_start) // 2

        for x in range(w):
            nx = x / max(w - 1, 1)
            if fft is not None:
                bi = min(127, int(nx * (fft_hi - fft_lo) + fft_lo))
                raw = fft[bi] / 255.0
                amp = _smooth(x + int(hue_offset * 80), raw)
            else:
                amp = 0.3 * abs(math.sin(nx * (3.0 + hue_offset * 4) * math.pi + t * (1.0 + hue_offset)))

            r, g, b = _rainbow_color(nx + hue_offset, t, speed=0.08)
            span = int(amp * band_half * 0.9)

            for dy in range(span + 1):
                frac = dy / max(1, span)
                intensity = 0.2 + 0.8 * frac
                pr, pg, pb = int(r * intensity), int(g * intensity), int(b * intensity)
                y_up = max(y_start, band_center - dy)
                y_dn = min(y_end - 1, band_center + dy)
                _set_pixel(frame, y_up, x, pr, pg, pb)
                _set_pixel(frame, y_dn, x, pr, pg, pb)
                _trails[5].stamp(y_up, x, pr // 4, pg // 4, pb // 4)
                _trails[5].stamp(y_dn, x, pr // 4, pg // 4, pb // 4)

    _trails[5].apply(frame)


def _render_twin_ribbon(frame, w, h, t, fft, td, bass, mid, treble):
    """Two thick intertwining ribbons with contrasting colors and fills."""
    trail = _trails[6].get(h, w, decay=0.80)

    for x in range(w):
        nx = x / max(w - 1, 1)
        if td is not None:
            idx = min(127, int(nx * 127))
            raw = (td[idx] - 128.0) / 128.0 * (0.5 + bass * 0.5)
        else:
            raw = 0.6 * math.sin(nx * 3.0 * math.pi + t * 1.2)

        y1_norm = 0.5 + raw * 0.35
        y2_norm = 0.5 - raw * 0.35
        y1 = int(y1_norm * (h - 1))
        y2 = int(y2_norm * (h - 1))

        # Ribbon 1: blue-cyan range
        r1, g1, b1 = _rainbow_color(nx, t, speed=0.06)
        # Ribbon 2: shifted hue
        r2, g2, b2 = _rainbow_color(nx + 0.5, t, speed=0.06)

        # Fill each ribbon (3 pixels thick)
        for dy in range(-2, 3):
            frac = 1.0 - abs(dy) / 3.0
            py1, py2 = y1 + dy, y2 + dy
            _set_pixel(frame, py1, x, int(r1 * frac), int(g1 * frac), int(b1 * frac))
            _set_pixel(frame, py2, x, int(r2 * frac), int(g2 * frac), int(b2 * frac))
            _trails[6].stamp(py1, x, r1 // 4, g1 // 4, b1 // 4)
            _trails[6].stamp(py2, x, r2 // 4, g2 // 4, b2 // 4)

        # Fill between ribbons (subtle)
        lo, hi = min(y1, y2), max(y1, y2)
        for y in range(lo, hi + 1):
            _add_pixel(frame, y, x, 15, 10, 25)

    _trails[6].apply(frame)


def _render_flame(frame, w, h, t, fft, td, bass, mid, treble):
    """Flame spectrum — bars from bottom, warm colors, flickering tops."""
    trail = _trails[7].get(h, w, decay=0.70)

    for x in range(w):
        nx = x / max(w - 1, 1)
        if fft is not None:
            bi = min(127, int(nx * 80))
            raw = fft[bi] / 255.0
            bh = _smooth(x + 128, raw)
        else:
            col = int(nx * 20)
            phase = t * 2.5 + col * 0.6
            bh = 0.25 + 0.4 * abs(math.sin(phase))
            bh += 0.1 * math.sin(phase * 3.0 + col * 1.5)
            bh = max(0.05, min(0.9, bh))

        bar_top = int((1.0 - bh) * (h - 1))

        # Warm flame colors: red at bottom → orange → yellow at top
        for y in range(bar_top, h):
            frac = (h - 1 - y) / max(1, h - 1 - bar_top)  # 0 at bottom, 1 at top
            # Color shift: deep red → orange → yellow → white at tip
            hue = 0.0 + frac * 0.12  # red to yellow range
            sat = 1.0 - frac * 0.3
            val = 0.4 + 0.6 * frac
            r, g, b = _hsv_rgb(hue, sat, val)
            _set_pixel(frame, y, x, r, g, b)
            _trails[7].stamp(y, x, r // 3, g // 3, b // 3)

    _trails[7].apply(frame)


def _render_waterfall(frame, w, h, t, fft, td, bass, mid, treble):
    """Waterfall spectrogram — scrolls vertically, rainbow colors, persistent."""
    trail = _trails[8].get(h, w, decay=0.92)  # slow decay for persistence

    # Shift trail buffer down by 1 row (scroll effect)
    if trail.shape[0] > 1:
        trail[1:, :, :] = trail[:-1, :, :]
        trail[0, :, :] = 0  # clear top row

    # Write new data to top row
    for x in range(w):
        nx = x / max(w - 1, 1)
        if fft is not None:
            bi = min(127, int(nx * 127))
            val = fft[bi] / 255.0
        else:
            val = abs(math.sin(nx * 8.0 + t * 3.0))
            val += 0.3 * abs(math.sin(nx * 16.0 + t * 5.0))
            val = min(1.0, val * 0.6)

        r, g, b = _rainbow_color(nx, t, speed=0.15, value=val)
        _trails[8].stamp(0, x, float(r), float(g), float(b))

    _trails[8].apply(frame)


def _render_scope_bars(frame, w, h, t, fft, td, bass, mid, treble):
    """Oscilloscope with bar fills underneath — scope trace + vertical fills."""
    trail = _trails[9].get(h, w, decay=0.74)
    center = h // 2

    for x in range(w):
        nx = x / max(w - 1, 1)
        if td is not None:
            idx = min(127, int(nx * 127))
            y_norm = td[idx] / 255.0
        else:
            y_norm = 0.5 + 0.2 * math.sin(nx * 6.0 * math.pi + t * 2.0)
            y_norm += 0.1 * math.sin(nx * 14.0 * math.pi + t * 3.5)

        wave_y = int(y_norm * (h - 1))
        wave_y = max(0, min(h - 1, wave_y))
        r, g, b = _rainbow_color(nx, t, speed=0.08)

        # Bar fill from center to wave
        y_lo, y_hi = min(center, wave_y), max(center, wave_y)
        for y in range(y_lo, y_hi + 1):
            frac = abs(y - center) / max(1, abs(wave_y - center))
            intensity = 0.15 + 0.5 * frac
            _set_pixel(frame, y, x, int(r * intensity), int(g * intensity), int(b * intensity))

        # Bright scope trace
        _set_pixel(frame, wave_y, x, min(255, r + 80), min(255, g + 80), min(255, b + 80))
        _trails[9].stamp(wave_y, x, float(r) * 0.4, float(g) * 0.4, float(b) * 0.4)
        if wave_y > 0:
            _trails[9].stamp(wave_y - 1, x, float(r) * 0.2, float(g) * 0.2, float(b) * 0.2)

    _trails[9].apply(frame)


_pulse_scroll_buf = None

def _render_pulse_scroll(frame, w, h, t, fft, td, bass, mid, treble):
    """Pulse Scroll — mirrored bars, newest LEFT, scrolls RIGHT with persistence."""
    global _pulse_scroll_buf

    if _pulse_scroll_buf is None or _pulse_scroll_buf.shape != (h, w, 3):
        _pulse_scroll_buf = np.zeros((h, w, 3), dtype=np.uint8)

    # Shift right
    _pulse_scroll_buf[:, 1:, :] = _pulse_scroll_buf[:, :-1, :]
    _pulse_scroll_buf[:, 0, :] = 0

    center = h // 2

    if td is not None:
        energy = bass * 0.7 + mid * 0.2 + treble * 0.1
    else:
        phase = (t * 1.8) % 1.0
        energy = 0.2 + 0.6 * abs(math.sin(phase * 5.0 * math.pi))

    half_span = int(energy * center * 0.9)
    r, g, b = _rainbow_color(0.0, t, speed=0.1, saturation=0.9)

    for dy in range(half_span + 1):
        frac = dy / max(1, half_span)
        intensity = 0.1 + 0.9 * frac
        pr, pg, pb = int(r * intensity), int(g * intensity), int(b * intensity)
        y_up = max(0, center - dy)
        y_dn = min(h - 1, center + dy)
        _pulse_scroll_buf[y_up, 0] = [max(_pulse_scroll_buf[y_up, 0, 0], pr),
                                        max(_pulse_scroll_buf[y_up, 0, 1], pg),
                                        max(_pulse_scroll_buf[y_up, 0, 2], pb)]
        _pulse_scroll_buf[y_dn, 0] = [max(_pulse_scroll_buf[y_dn, 0, 0], pr),
                                        max(_pulse_scroll_buf[y_dn, 0, 1], pg),
                                        max(_pulse_scroll_buf[y_dn, 0, 2], pb)]

    # Gentle age fade
    fade = np.ones((1, w, 1), dtype=np.float32)
    for x in range(w):
        fade[0, x, 0] = max(0.2, 1.0 - x * 0.004)
    faded = (_pulse_scroll_buf.astype(np.float32) * fade).astype(np.uint8)
    np.maximum(frame, faded, out=frame)


def _render_multi_band(frame, w, h, t, fft, td, bass, mid, treble):
    """3 horizontal zones — bass/mid/treble each with their own bars + color."""
    trail = _trails[11].get(h, w, decay=0.75)
    band_h = h // 3

    zones = [
        (0, band_h, bass if fft is not None else 0.5 + 0.3 * math.sin(t * 1.5), 0.0),
        (band_h, band_h * 2, mid if fft is not None else 0.4 + 0.3 * math.sin(t * 2.0), 0.33),
        (band_h * 2, h, treble if fft is not None else 0.3 + 0.3 * math.sin(t * 2.8), 0.66),
    ]

    for y_start, y_end, amp, hue_off in zones:
        band_center = (y_start + y_end) // 2
        bh = (y_end - y_start) // 2

        for x in range(w):
            nx = x / max(w - 1, 1)
            if fft is not None:
                # Modulate across X with FFT
                bi_lo = int(hue_off * 128)
                bi_hi = int((hue_off + 0.33) * 128)
                bi = min(127, int(nx * (bi_hi - bi_lo) + bi_lo))
                local_amp = fft[bi] / 255.0
            else:
                local_amp = amp * (0.5 + 0.5 * abs(math.sin(nx * 4.0 * math.pi + t + hue_off * 5)))

            span = int(local_amp * bh * 0.9)
            r, g, b = _rainbow_color(nx + hue_off, t, speed=0.06)

            for dy in range(span + 1):
                frac = dy / max(1, span)
                intensity = 0.2 + 0.8 * frac
                pr, pg, pb = int(r * intensity), int(g * intensity), int(b * intensity)
                y_up = max(y_start, band_center - dy)
                y_dn = min(y_end - 1, band_center + dy)
                _set_pixel(frame, y_up, x, pr, pg, pb)
                _set_pixel(frame, y_dn, x, pr, pg, pb)

    _trails[11].apply(frame)


def _render_diamond(frame, w, h, t, fft, td, bass, mid, treble):
    """Diamond lattice — crossing diagonal lines with rainbow fill."""
    trail = _trails[12].get(h, w, decay=0.70)

    scale = 5.0
    if fft is not None:
        scale = 3.0 + bass * 3.0

    for y in range(h):
        ny = y / max(h - 1, 1)
        for x in range(w):
            nx = x / max(w - 1, 1)
            v1 = abs(math.sin((nx + ny) * scale * math.pi + t * 1.5))
            v2 = abs(math.sin((nx - ny) * scale * math.pi + t * 1.2))

            thresh = 0.7
            if fft is not None:
                thresh = 0.6 - mid * 0.2

            val = 0.0
            if v1 > thresh: val += (v1 - thresh) / (1.0 - thresh)
            if v2 > thresh: val += (v2 - thresh) / (1.0 - thresh)
            val = min(1.0, val)

            if val > 0.01:
                r, g, b = _rainbow_color(nx, t, speed=0.1, value=val)
                _set_pixel(frame, y, x, r, g, b)
                _trails[12].stamp(y, x, float(r) * 0.3, float(g) * 0.3, float(b) * 0.3)

    _trails[12].apply(frame)


def _render_helix(frame, w, h, t, fft, td, bass, mid, treble):
    """DNA helix — two spiraling traces with fill between, dual colors."""
    trail = _trails[13].get(h, w, decay=0.78)

    for x in range(w):
        nx = x / max(w - 1, 1)
        if td is not None:
            idx = min(127, int(nx * 127))
            raw = (td[idx] - 128.0) / 128.0 * (0.5 + bass * 0.5)
        else:
            raw = 0.6 * math.sin(nx * 3.0 * math.pi + t * 1.5)

        y1 = int((0.5 + raw * 0.35) * (h - 1))
        y2 = int((0.5 - raw * 0.35) * (h - 1))
        y1 = max(0, min(h - 1, y1))
        y2 = max(0, min(h - 1, y2))

        r1, g1, b1 = _rainbow_color(nx, t, speed=0.08)
        r2, g2, b2 = _rainbow_color(nx + 0.4, t, speed=0.08)

        # Fill between
        lo, hi = min(y1, y2), max(y1, y2)
        for y in range(lo, hi + 1):
            _add_pixel(frame, y, x, 20, 10, 30)

        # Bright traces
        for dy in range(-1, 2):
            frac = 1.0 - abs(dy) * 0.4
            _set_pixel(frame, y1 + dy, x, int(r1 * frac), int(g1 * frac), int(b1 * frac))
            _set_pixel(frame, y2 + dy, x, int(r2 * frac), int(g2 * frac), int(b2 * frac))
            _trails[13].stamp(y1 + dy, x, float(r1) * 0.3, float(g1) * 0.3, float(b1) * 0.3)
            _trails[13].stamp(y2 + dy, x, float(r2) * 0.3, float(g2) * 0.3, float(b2) * 0.3)

    _trails[13].apply(frame)


def _render_neon_rain(frame, w, h, t, fft, td, bass, mid, treble):
    """Neon rain — rainbow columns falling at different speeds with trails."""
    trail = _trails[14].get(h, w, decay=0.88)

    for x in range(w):
        nx = x / max(w - 1, 1)
        if fft is not None:
            bi = min(127, int(nx * 80))
            raw = fft[bi] / 255.0
            drop_len = int(raw * h * 0.6)
        else:
            drop_len = int((0.15 + 0.3 * abs(math.sin(x * 0.5 + t))) * h)

        col = int(nx * 30) % 30
        drop_start = int(((t * 0.4 + col * 0.37) % 1.0) * h)

        r, g, b = _rainbow_color(nx, t, speed=0.12)

        for dy in range(drop_len):
            y = (drop_start + dy) % h
            frac = 1.0 - dy / max(1, drop_len)
            pr, pg, pb = int(r * frac), int(g * frac), int(b * frac)
            _set_pixel(frame, y, x, pr, pg, pb)
            _trails[14].stamp(y, x, float(pr) * 0.4, float(pg) * 0.4, float(pb) * 0.4)

    _trails[14].apply(frame)


def _render_heartbeat(frame, w, h, t, fft, td, bass, mid, treble):
    """Heartbeat — ECG trace scrolling with bar fills and red/pink colors."""
    trail = _trails[15].get(h, w, decay=0.80)
    center = h // 2

    for x in range(w):
        nx = x / max(w - 1, 1)
        if td is not None:
            idx = min(127, int(nx * 127))
            y_norm = td[idx] / 255.0
        else:
            phase = (nx * 4.0 + t * 1.5) % 1.0
            if phase < 0.08:
                y_norm = 0.5 + 0.35 * math.sin(phase / 0.08 * math.pi)
            elif phase < 0.17:
                y_norm = 0.5 - 0.15 * math.sin((phase - 0.08) / 0.09 * math.pi)
            else:
                y_norm = 0.5 + 0.02 * math.sin(phase * 8.0)

        wave_y = int(y_norm * (h - 1))
        wave_y = max(0, min(h - 1, wave_y))

        # Red/pink color for heartbeat
        r, g, b = _hsv_rgb(0.95 + nx * 0.1, 0.8, 0.9)

        # Bar from center
        y_lo, y_hi = min(center, wave_y), max(center, wave_y)
        for y in range(y_lo, y_hi + 1):
            frac = abs(y - center) / max(1, abs(wave_y - center))
            intensity = 0.2 + 0.8 * frac
            _set_pixel(frame, y, x, int(r * intensity), int(g * intensity), int(b * intensity))
            _trails[15].stamp(y, x, float(r) * 0.2 * intensity, float(g) * 0.2 * intensity, float(b) * 0.2 * intensity)

        _set_pixel(frame, wave_y, x, 255, 200, 220)

    _trails[15].apply(frame)


def _render_wormhole(frame, w, h, t, fft, td, bass, mid, treble):
    """Wormhole — spiral zoom with rainbow rings and persistence."""
    trail = _trails[16].get(h, w, decay=0.82)
    cx, cy = w / 2, h / 2

    speed = 5.0
    freq = 22.0
    if fft is not None:
        speed = 3.0 + bass * 5.0
        freq = 15.0 + treble * 10.0

    for y in range(h):
        for x in range(w):
            dx = (x - cx) / max(w, 1)
            dy = (y - cy) / max(h, 1)
            d = math.sqrt(dx * dx + dy * dy) + 0.001
            angle = math.atan2(dy, dx)
            spiral = math.sin(d * freq - t * speed + angle * 4.0)

            if spiral > 0.75:
                val = (spiral - 0.75) / 0.25
                hue = d * 3.0 + t * 0.2
                r, g, b = _hsv_rgb(hue, 0.9, val)
                _set_pixel(frame, y, x, r, g, b)
                _trails[16].stamp(y, x, float(r) * 0.3, float(g) * 0.3, float(b) * 0.3)

    _trails[16].apply(frame)


def _render_rings(frame, w, h, t, fft, td, bass, mid, treble):
    """Sound rings — expanding concentric rings with rainbow colors."""
    trail = _trails[17].get(h, w, decay=0.83)
    cx, cy = w / 2, h / 2

    speed = 4.0
    ring_freq = 25.0
    if fft is not None:
        speed = 2.5 + bass * 4.0
        ring_freq = 18.0 + treble * 10.0

    for y in range(h):
        for x in range(w):
            dx = (x - cx) / max(w, 1)
            dy = (y - cy) / max(h, 1)
            d = math.sqrt(dx * dx + dy * dy)
            ring = math.sin(d * ring_freq - t * speed)

            if ring > 0.78:
                val = (ring - 0.78) / 0.22
                r, g, b = _hsv_rgb(d * 5.0 + t * 0.3, 0.9, val)
                _set_pixel(frame, y, x, r, g, b)
                _trails[17].stamp(y, x, float(r) * 0.4, float(g) * 0.4, float(b) * 0.4)

    _trails[17].apply(frame)


_scroll_spec_buf = None

def _render_scroll_spectrum(frame, w, h, t, fft, td, bass, mid, treble):
    """Scroll Spectrum — mirrored bars, newest LEFT, scrolls RIGHT with rainbow."""
    global _scroll_spec_buf

    if _scroll_spec_buf is None or _scroll_spec_buf.shape != (h, w, 3):
        _scroll_spec_buf = np.zeros((h, w, 3), dtype=np.uint8)

    # Shift right
    _scroll_spec_buf[:, 1:, :] = _scroll_spec_buf[:, :-1, :]
    _scroll_spec_buf[:, 0, :] = 0

    center = h // 2

    if fft is not None:
        energy = bass * 0.5 + mid * 0.3 + treble * 0.2
    else:
        energy = 0.3 + 0.4 * abs(math.sin(t * 2.0))

    half_span = int(energy * center * 0.95)
    r, g, b = _rainbow_color(0.0, t, speed=0.12, saturation=0.85)

    for dy in range(half_span + 1):
        frac = dy / max(1, half_span)
        intensity = 0.1 + 0.9 * frac
        pr, pg, pb = int(r * intensity), int(g * intensity), int(b * intensity)
        y_up = max(0, center - dy)
        y_dn = min(h - 1, center + dy)
        _scroll_spec_buf[y_up, 0] = [max(_scroll_spec_buf[y_up, 0, 0], pr),
                                      max(_scroll_spec_buf[y_up, 0, 1], pg),
                                      max(_scroll_spec_buf[y_up, 0, 2], pb)]
        _scroll_spec_buf[y_dn, 0] = [max(_scroll_spec_buf[y_dn, 0, 0], pr),
                                      max(_scroll_spec_buf[y_dn, 0, 1], pg),
                                      max(_scroll_spec_buf[y_dn, 0, 2], pb)]

    # Gentle age fade
    fade = np.ones((1, w, 1), dtype=np.float32)
    for x in range(w):
        fade[0, x, 0] = max(0.2, 1.0 - x * 0.003)
    faded = (_scroll_spec_buf.astype(np.float32) * fade).astype(np.uint8)
    np.maximum(frame, faded, out=frame)


# ─── Frequency Cardiogram ────────────────────────────────────────────────────
# Newest audio on LEFT edge, old data scrolls RIGHT.
# Each column = one snapshot of the spectrum at a moment in time.
# Like a hospital heart monitor: the "pen" writes on the left, paper moves right.

_cardio_frame_buf = None  # (h, w, 3) persistent frame that shifts right each tick

def _render_freq_cardio(frame, w, h, t, fft, td, bass, mid, treble):
    """Frequency Cardiogram — live audio on left, history scrolls right."""
    global _cardio_frame_buf

    # Initialize or resize the persistent buffer
    if _cardio_frame_buf is None or _cardio_frame_buf.shape != (h, w, 3):
        _cardio_frame_buf = np.zeros((h, w, 3), dtype=np.uint8)

    # Shift the entire buffer 1 column to the RIGHT (oldest data falls off right edge)
    _cardio_frame_buf[:, 1:, :] = _cardio_frame_buf[:, :-1, :]
    _cardio_frame_buf[:, 0, :] = 0  # clear leftmost column

    # Write new data into leftmost column (x=0)
    if fft is not None:
        # Compute the overall energy for a bar-style display
        # Map vertical position to frequency: bottom = bass, top = treble
        for y in range(h):
            ny = y / max(h - 1, 1)
            # Log-ish frequency mapping: more bass resolution
            bin_idx = min(127, int((1.0 - ny) ** 1.3 * 127))
            val = fft[bin_idx] / 255.0

            # Also grab neighbors for smoothness
            for offset in [-2, -1, 1, 2]:
                nb = min(127, max(0, bin_idx + offset))
                val = max(val, fft[nb] / 255.0 * 0.6)

            if val > 0.05:
                # Color: rainbow mapped by vertical position (frequency)
                r, g, b = _rainbow_color(1.0 - ny, t, speed=0.03)
                _cardio_frame_buf[y, 0] = [
                    min(255, int(r * val)),
                    min(255, int(g * val)),
                    min(255, int(b * val))
                ]
    else:
        # DEFAULT mode: simulated audio
        for y in range(h):
            ny = y / max(h - 1, 1)
            val = 0.3 + 0.5 * abs(math.sin(ny * 6.0 + t * 2.5 + math.sin(t * 0.7) * 3))
            val *= 0.5 + 0.5 * abs(math.sin(t * 1.5 + ny * 3.0))
            if val > 0.1:
                r, g, b = _rainbow_color(1.0 - ny, t, speed=0.03)
                _cardio_frame_buf[y, 0] = [
                    min(255, int(r * val)),
                    min(255, int(g * val)),
                    min(255, int(b * val))
                ]

    # Age fade: dim older columns slightly (right side = older)
    # Apply a very gentle fade so it's not abrupt
    fade = np.ones((1, w, 1), dtype=np.float32)
    for x in range(w):
        fade[0, x, 0] = max(0.3, 1.0 - x * 0.003)  # very gentle: 0.3% dimmer per column

    faded = (_cardio_frame_buf.astype(np.float32) * fade).astype(np.uint8)

    # Copy to output frame
    np.maximum(frame, faded, out=frame)


# ─── Registry ────────────────────────────────────────────────────────────────

WAVEFORMS = [
    {"name": "Frequency Bars",    "render": _render_freq_bars},
    {"name": "Freq Cardiogram",  "render": _render_freq_cardio},
    {"name": "Spectrum Mirror",   "render": _render_spectrum_mirror},
    {"name": "Bar Wave",          "render": _render_bar_wave},
    {"name": "Cardiogram",        "render": _render_cardiogram},
    {"name": "Cardio Mirror",     "render": _render_cardio_mirror},
    {"name": "Wave Cascade",      "render": _render_cascade},
    {"name": "Twin Ribbon",       "render": _render_twin_ribbon},
    {"name": "Flame Spectrum",    "render": _render_flame},
    {"name": "Waterfall",         "render": _render_waterfall},
    {"name": "Scope + Bars",      "render": _render_scope_bars},
    {"name": "Pulse Scroll",      "render": _render_pulse_scroll},
    {"name": "Multi-Band",        "render": _render_multi_band},
    {"name": "Neon Rain",         "render": _render_neon_rain},
    {"name": "Diamond Lattice",   "render": _render_diamond},
    {"name": "Helix",             "render": _render_helix},
    {"name": "Heartbeat",         "render": _render_heartbeat},
    {"name": "Wormhole",          "render": _render_wormhole},
    {"name": "Sound Rings",       "render": _render_rings},
    {"name": "Scroll Spectrum",   "render": _render_scroll_spectrum},
]

WAVEFORM_COUNT = len(WAVEFORMS)
