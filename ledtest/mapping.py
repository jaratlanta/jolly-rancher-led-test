"""
Serpentine pixel mapping: converts (x, y) grid coordinates to linear pixel indices.

Origin is upper-left. Even rows (0, 2, 4, ...) run left-to-right.
Odd rows (1, 3, 5, ...) run right-to-left (serpentine).
"""
import numpy as np


def build_mapping(width, height, serpentine=True):
    """Build a (height, width) array where mapping[y][x] = pixel index."""
    mapping = np.zeros((height, width), dtype=np.int32)
    for y in range(height):
        for x in range(width):
            if serpentine and y % 2 == 1:
                mapping[y][x] = y * width + (width - 1 - x)
            else:
                mapping[y][x] = y * width + x
    return mapping


def build_multi_panel_mapping(model_info, serpentine=True):
    """Build a mapping for a multi-panel model.

    The virtual canvas is all panels laid out side-by-side (total_cols × rows).
    Each panel maps to a sequential range of pixel indices for sACN output.

    Args:
        model_info: dict from models.get_model() with panels, rows, total_cols
        serpentine: use serpentine wiring within each panel

    Returns:
        np.ndarray of shape (rows, total_cols), pixel index at each position.
        Pixel indices are globally unique across all panels.
    """
    rows = model_info["rows"]
    total_cols = model_info["total_cols"]
    mapping = np.full((rows, total_cols), -1, dtype=np.int32)

    for panel in model_info["panels"]:
        p_cols = panel["cols"]
        p_rows = panel["rows"]
        col_start = panel["col_offset"]
        pixel_base = panel["pixel_offset"]
        flip_h = panel.get("flip_h", False)

        for y in range(p_rows):
            for x in range(p_cols):
                # Determine physical x within the panel
                if flip_h:
                    phys_x = p_cols - 1 - x
                else:
                    phys_x = x

                # Serpentine within the panel
                if serpentine and y % 2 == 1:
                    pixel_idx = pixel_base + y * p_cols + (p_cols - 1 - phys_x)
                else:
                    pixel_idx = pixel_base + y * p_cols + phys_x

                mapping[y][col_start + x] = pixel_idx

    return mapping


def frame_to_pixels(frame, mapping):
    """Convert a (height, width, 3) RGB frame to (num_pixels, 3) ordered by pixel index.

    Args:
        frame: np.ndarray of shape (height, width, 3), dtype uint8
        mapping: np.ndarray of shape (height, width), pixel index at each position

    Returns:
        np.ndarray of shape (num_pixels, 3), ordered by pixel index 0..N-1
    """
    height, width = mapping.shape
    num_pixels = int(mapping.max()) + 1
    pixels = np.zeros((num_pixels, 3), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            idx = mapping[y][x]
            if idx >= 0:
                pixels[idx] = frame[y][x]
    return pixels
