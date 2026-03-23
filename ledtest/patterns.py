"""
Test pattern generators. Each yields (height, width, 3) uint8 frames forever.
"""
import numpy as np


def solid_colors(width, height, hold_frames=60):
    """Cycle through solid R, G, B, White. Hold each for hold_frames."""
    colors = [
        ("Red",   [255, 0, 0]),
        ("Green", [0, 255, 0]),
        ("Blue",  [0, 0, 255]),
        ("White", [255, 255, 255]),
    ]
    while True:
        for name, color in colors:
            frame = np.full((height, width, 3), color, dtype=np.uint8)
            for _ in range(hold_frames):
                yield frame


def pixel_identify(width, height, hold_frames=3):
    """Light one pixel at a time in index order. Verifies serpentine wiring."""
    num_pixels = width * height
    while True:
        for idx in range(num_pixels):
            y, x_raw = divmod(idx, width)
            # Reverse x for odd (serpentine) rows to get grid position
            if y % 2 == 1:
                x = width - 1 - x_raw
            else:
                x = x_raw
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[y][x] = [255, 255, 255]
            for _ in range(hold_frames):
                yield frame


def column_wipe(width, height, hold_frames=4):
    """White column sweeps left to right."""
    while True:
        for col in range(width):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:, col] = [255, 255, 255]
            for _ in range(hold_frames):
                yield frame


def row_wipe(width, height, hold_frames=6):
    """White row sweeps top to bottom."""
    while True:
        for row in range(height):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[row, :] = [255, 255, 255]
            for _ in range(hold_frames):
                yield frame


def serpentine_chase(width, height, tail=8):
    """Single pixel chases through the physical wire path with a fading tail."""
    num_pixels = width * height
    while True:
        for head in range(num_pixels):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            for t in range(tail):
                idx = (head - t) % num_pixels
                y, x_raw = divmod(idx, width)
                if y % 2 == 1:
                    x = width - 1 - x_raw
                else:
                    x = x_raw
                brightness = int(255 * (1.0 - t / tail))
                frame[y][x] = [brightness, brightness, brightness]
            yield frame


def checkerboard(width, height, hold_frames=30):
    """Alternating 2x2 checkerboard, toggles on/off."""
    frames = []
    for phase in range(2):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        for y in range(height):
            for x in range(width):
                if ((x // 2) + (y // 2) + phase) % 2 == 0:
                    frame[y][x] = [255, 255, 255]
        frames.append(frame)
    while True:
        for frame in frames:
            for _ in range(hold_frames):
                yield frame


def gradient(width, height, hold_frames=120):
    """Red horizontal gradient + green vertical gradient."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            frame[y][x][0] = int(255 * x / max(width - 1, 1))   # red = column
            frame[y][x][1] = int(255 * y / max(height - 1, 1))   # green = row
    while True:
        for _ in range(hold_frames):
            yield frame


def all_white(width, height):
    """All pixels white at full brightness (capped by brightness_cap in output)."""
    frame = np.full((height, width, 3), 255, dtype=np.uint8)
    while True:
        yield frame


def rainbow_scroll(width, height):
    """Horizontal rainbow that scrolls across the matrix."""
    offset = 0
    while True:
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        for x in range(width):
            hue = ((x + offset) % width) / width
            r, g, b = _hsv_to_rgb(hue, 1.0, 1.0)
            frame[:, x] = [r, g, b]
        offset = (offset + 1) % width
        yield frame


def _hsv_to_rgb(h, s, v):
    """Simple HSV to RGB, returns (r, g, b) as 0-255 ints."""
    if s == 0.0:
        r = g = b = int(v * 255)
        return r, g, b
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = i % 6
    if i == 0:   r, g, b = v, t, p
    elif i == 1: r, g, b = q, v, p
    elif i == 2: r, g, b = p, v, t
    elif i == 3: r, g, b = p, q, v
    elif i == 4: r, g, b = t, p, v
    elif i == 5: r, g, b = v, p, q
    return int(r * 255), int(g * 255), int(b * 255)


# Registry: name -> (description, generator factory)
PATTERNS = {
    "1": ("Solid Colors (R/G/B/W cycle)", solid_colors),
    "2": ("Pixel Identify (single pixel chase)", pixel_identify),
    "3": ("Column Wipe (left to right)", column_wipe),
    "4": ("Row Wipe (top to bottom)", row_wipe),
    "5": ("Serpentine Chase (follows wire path)", serpentine_chase),
    "6": ("Checkerboard (alternating toggle)", checkerboard),
    "7": ("Gradient (red=column, green=row)", gradient),
    "8": ("All White (burn / power test)", all_white),
    "9": ("Rainbow Scroll", rainbow_scroll),
}
