#!/usr/bin/env python3
"""Convert Oregon Trail reference image to pixel art bitmaps at various resolutions.
Outputs multiple methods so user can choose the best looking one."""

from PIL import Image
import numpy as np
import os

IMG_PATH = os.path.join(os.path.dirname(__file__), '..', 'bitmaps', 'oregon.jpg')

def load_and_threshold(path):
    """Load image, extract green channel, threshold to binary."""
    img = Image.open(path).convert('RGB')
    arr = np.array(img)
    # Green channel dominates in this image
    green = arr[:, :, 1].astype(float)
    red = arr[:, :, 0].astype(float)
    blue = arr[:, :, 2].astype(float)
    # Threshold: green > 80 and green > red * 0.8
    mask = (green > 80) & (green > red * 0.6)
    return mask, img.size  # mask is (H, W), size is (W, H)


def downsample(mask, target_h):
    """Downsample binary mask to target height, preserving aspect ratio."""
    src_h, src_w = mask.shape
    scale = src_h / target_h
    target_w = int(src_w / scale)
    result = np.zeros((target_h, target_w), dtype=bool)
    for y in range(target_h):
        for x in range(target_w):
            # Sample the block and use majority vote
            y0 = int(y * scale)
            y1 = int((y + 1) * scale)
            x0 = int(x * scale)
            x1 = int((x + 1) * scale)
            block = mask[y0:y1, x0:x1]
            # Lit if >30% of source pixels are lit
            result[y, x] = block.mean() > 0.30
    return result


def trim(bmp):
    """Remove empty rows/cols around the sprite."""
    rows = np.any(bmp, axis=1)
    cols = np.any(bmp, axis=0)
    if not rows.any():
        return bmp
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    return bmp[r0:r1+1, c0:c1+1]


def print_ascii(bmp, label=""):
    """Print bitmap as ASCII art."""
    h, w = bmp.shape
    print(f"\n{'='*60}")
    print(f"  {label}  ({w}x{h})")
    print(f"{'='*60}")
    for y in range(h):
        row = ''
        for x in range(w):
            row += '##' if bmp[y, x] else '..'
        print(row)


def print_python(bmp, label=""):
    """Print as Python code for pasting into server.py."""
    h, w = bmp.shape
    print(f"\n# --- {label} ({w}x{h}) ---")
    print(f"_OT_ROWS = [")
    for y in range(h):
        row = ''
        for x in range(w):
            row += '#' if bmp[y, x] else '.'
        print(f'    "{row}",')
    print(f"]")


def main():
    mask, (img_w, img_h) = load_and_threshold(IMG_PATH)
    print(f"Source image: {img_w}x{img_h}")
    print(f"Lit pixels: {mask.sum()} / {mask.size}")

    # Generate multiple resolutions
    for target_h in [20, 24, 28, 32]:
        bmp = downsample(mask, target_h)
        bmp = trim(bmp)
        label = f"Method: {target_h}px tall"
        print_ascii(bmp, label)
        print_python(bmp, label)


if __name__ == '__main__':
    main()
