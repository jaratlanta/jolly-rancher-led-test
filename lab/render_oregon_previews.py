#!/usr/bin/env python3
"""Render Oregon Trail sprite at all 4 resolutions onto simulated LED panels.
Outputs PNGs showing what each would look like as actual LED dots on the 3 panel sizes."""

from PIL import Image, ImageDraw
import numpy as np
import math
import os

# Panel dimensions
PANELS = [
    ("Test 24x12", 24, 12),
    ("Front 72x24", 72, 24),
    ("Side 220x24", 220, 24),
]

# LED dot rendering params
DOT_RADIUS_FRAC = 0.38  # dot radius as fraction of cell size
BG_COLOR = (15, 15, 20)
DOT_OFF_COLOR = (25, 25, 30)
GREEN = (30, 230, 10)

IMG_PATH = os.path.join(os.path.dirname(__file__), '..', 'bitmaps', 'oregon.jpg')


def load_and_threshold(path):
    from PIL import Image as PILImage
    img = PILImage.open(path).convert('RGB')
    arr = np.array(img)
    green = arr[:, :, 1].astype(float)
    red = arr[:, :, 0].astype(float)
    mask = (green > 80) & (green > red * 0.6)
    return mask


def downsample(mask, target_h):
    src_h, src_w = mask.shape
    scale = src_h / target_h
    target_w = int(src_w / scale)
    result = np.zeros((target_h, target_w), dtype=bool)
    for y in range(target_h):
        for x in range(target_w):
            y0 = int(y * scale)
            y1 = int((y + 1) * scale)
            x0 = int(x * scale)
            x1 = int((x + 1) * scale)
            block = mask[y0:y1, x0:x1]
            result[y, x] = block.mean() > 0.30
    return result


def trim(bmp):
    rows = np.any(bmp, axis=1)
    cols = np.any(bmp, axis=0)
    if not rows.any():
        return bmp
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    return bmp[r0:r1+1, c0:c1+1]


def render_led_panel(panel_w, panel_h, sprite_bmp, cell_size=18):
    """Render a simulated LED panel with the sprite placed on it."""
    img_w = panel_w * cell_size
    img_h = panel_h * cell_size
    img = Image.new('RGB', (img_w, img_h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    sprite_h, sprite_w = sprite_bmp.shape

    # Scale sprite to fit panel height
    scale = max(1, panel_h // sprite_h)
    scaled_w = sprite_w * scale
    scaled_h = sprite_h * scale

    # Center vertically, position about 60% from left (wagon entering from right)
    y_offset = (panel_h - scaled_h) // 2
    x_offset = int(panel_w * 0.55) - scaled_w // 2

    # Build the frame buffer
    frame = np.zeros((panel_h, panel_w), dtype=bool)
    for sy in range(scaled_h):
        for sx in range(scaled_w):
            px = x_offset + sx
            py = y_offset + sy
            if 0 <= px < panel_w and 0 <= py < panel_h:
                bmp_x = sx // scale
                bmp_y = sy // scale
                if 0 <= bmp_x < sprite_w and 0 <= bmp_y < sprite_h:
                    if sprite_bmp[bmp_y, bmp_x]:
                        frame[py, px] = True

    # Draw LED dots
    dot_r = max(2, int(cell_size * DOT_RADIUS_FRAC))
    for y in range(panel_h):
        for x in range(panel_w):
            cx = x * cell_size + cell_size // 2
            cy = y * cell_size + cell_size // 2
            if frame[y, x]:
                # Lit LED — bright green with glow
                # Outer glow
                glow_r = int(dot_r * 1.6)
                draw.ellipse([cx - glow_r, cy - glow_r, cx + glow_r, cy + glow_r],
                             fill=(8, 60, 3))
                # Main dot
                draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
                             fill=GREEN)
                # Bright center
                inner_r = max(1, dot_r // 2)
                draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
                             fill=(120, 255, 80))
            else:
                # Unlit LED — dim dot
                tiny_r = max(1, dot_r // 3)
                draw.ellipse([cx - tiny_r, cy - tiny_r, cx + tiny_r, cy + tiny_r],
                             fill=DOT_OFF_COLOR)

    return img


def main():
    mask = load_and_threshold(IMG_PATH)
    os.makedirs('bitmaps/tests', exist_ok=True)

    for sprite_h in [20, 24, 28, 32]:
        bmp = downsample(mask, sprite_h)
        bmp = trim(bmp)
        bh, bw = bmp.shape
        print(f"\n=== Sprite {sprite_h}px ({bw}x{bh}) ===")

        # For each panel size
        images = []
        for panel_name, pw, ph in PANELS:
            # Choose cell size based on panel
            if pw <= 24:
                cell = 24
            elif pw <= 72:
                cell = 14
            else:
                cell = 7  # side panel is wide, smaller cells

            img = render_led_panel(pw, ph, bmp, cell_size=cell)
            images.append((panel_name, img))
            print(f"  {panel_name}: {img.size[0]}x{img.size[1]}px")

        # Combine all 3 panels into one tall image
        total_w = max(img.size[0] for _, img in images)
        padding = 20
        total_h = sum(img.size[1] for _, img in images) + padding * (len(images) + 1)
        combined = Image.new('RGB', (total_w, total_h), (0, 0, 0))

        y_pos = padding
        for panel_name, img in images:
            # Center horizontally
            x_pos = (total_w - img.size[0]) // 2
            combined.paste(img, (x_pos, y_pos))
            y_pos += img.size[1] + padding

        out_path = f'bitmaps/tests/oregon_led_{sprite_h}px.png'
        combined.save(out_path)
        print(f"  -> Saved {out_path}")


if __name__ == '__main__':
    main()
