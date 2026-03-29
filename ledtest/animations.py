"""
Pattern system: each pattern defines a shape with two animation modes.
- Default: time-driven auto-movement (fn)
- Audio: subtle ambient + audio-exaggerated movement (audio_fn)

Pattern functions: (nx, ny, time, width, height) -> brightness 0-255
Audio functions: (nx, ny, time, width, height, bass, mid, treble) -> brightness 0-255

Palettes map brightness values to RGB colors.
"""
import math
import random


# ─── Palettes (33 color schemes from /jollyrancher) ─────────────────────────

PALETTES = [
    {"name": "Cyberpunk",      "colors": [(0, 255, 255), (255, 0, 255), (75, 0, 130)]},
    {"name": "Sunset",         "colors": [(255, 140, 0), (255, 105, 180), (46, 8, 84)]},
    {"name": "Aurora",         "colors": [(0, 255, 204), (50, 205, 50), (0, 68, 34)]},
    {"name": "Vaporwave",      "colors": [(255, 182, 193), (135, 206, 235), (72, 61, 139)]},
    {"name": "Fire",           "colors": [(255, 215, 0), (255, 69, 0), (139, 0, 0)]},
    {"name": "Deep Sea",       "colors": [(0, 210, 255), (58, 123, 213), (0, 12, 32)]},
    {"name": "Emerald",        "colors": [(80, 200, 120), (0, 77, 0), (10, 26, 10)]},
    {"name": "Midnight",       "colors": [(25, 25, 112), (0, 0, 0), (75, 0, 130)]},
    {"name": "Toxic",          "colors": [(173, 255, 47), (0, 255, 0), (0, 34, 0)]},
    {"name": "Glacier",        "colors": [(240, 248, 255), (173, 216, 230), (30, 144, 255)]},
    {"name": "Magma",          "colors": [(255, 69, 0), (128, 0, 0), (255, 165, 0)]},
    {"name": "Void",           "colors": [(255, 0, 0), (0, 0, 0), (26, 26, 26)]},
    {"name": "Neon Gold",      "colors": [(255, 215, 0), (255, 140, 0), (51, 34, 0)]},
    {"name": "Ocean Breeze",   "colors": [(0, 255, 255), (0, 128, 128), (0, 0, 128)]},
    {"name": "Cherry Blossom", "colors": [(255, 183, 197), (255, 105, 180), (74, 14, 30)]},
    {"name": "Frozen",         "colors": [(0, 242, 255), (255, 255, 255), (0, 68, 102)]},
    {"name": "Forest",         "colors": [(34, 139, 34), (0, 100, 0), (10, 26, 10)]},
    {"name": "Volcano",        "colors": [(255, 69, 0), (255, 215, 0), (42, 0, 0)]},
    {"name": "Cotton Candy",   "colors": [(255, 192, 203), (173, 216, 230), (128, 0, 128)]},
    {"name": "Deep Space",     "colors": [(75, 0, 130), (0, 0, 51), (0, 0, 0)]},
    {"name": "Martian",        "colors": [(255, 69, 0), (139, 69, 19), (61, 26, 16)]},
    {"name": "Citrus",         "colors": [(255, 170, 0), (204, 255, 0), (51, 68, 0)]},
    {"name": "Royal",          "colors": [(65, 105, 225), (255, 215, 0), (0, 0, 51)]},
    {"name": "Toxic Sludge",   "colors": [(57, 255, 20), (26, 47, 15), (0, 0, 0)]},
    {"name": "Hyper Blue",     "colors": [(0, 0, 255), (0, 255, 255), (0, 0, 68)]},
    {"name": "Cyber Forest",   "colors": [(0, 255, 127), (255, 0, 255), (0, 17, 0)]},
    {"name": "Sunset Gold",    "colors": [(255, 140, 0), (138, 43, 226), (34, 17, 0)]},
    {"name": "Ghostly",        "colors": [(204, 255, 204), (51, 51, 51), (17, 17, 17)]},
    {"name": "Electric Purple", "colors": [(191, 0, 255), (255, 0, 255), (34, 0, 68)]},
    {"name": "Solar Flair",    "colors": [(255, 255, 0), (255, 69, 0), (68, 17, 0)]},
    {"name": "Deep Sea 2",     "colors": [(0, 191, 255), (0, 0, 139), (5, 5, 16)]},
    {"name": "Galactic",       "colors": [(30, 144, 255), (255, 0, 255), (17, 0, 34)]},
    # ── Multi-color holographic palettes (5-7 color stops) ──
    {"name": "Holographic",    "colors": [(255, 0, 100), (255, 100, 0), (255, 255, 0), (0, 255, 100), (0, 100, 255), (150, 0, 255), (5, 0, 10)]},
    {"name": "Oil Slick",      "colors": [(255, 0, 200), (0, 200, 255), (100, 255, 0), (255, 150, 0), (200, 0, 255), (0, 5, 15)]},
    {"name": "Prism Light",    "colors": [(255, 255, 255), (255, 200, 200), (255, 100, 50), (255, 255, 0), (50, 255, 100), (50, 100, 255), (200, 50, 255), (10, 5, 15)]},
    {"name": "Neon Rainbow",   "colors": [(255, 0, 60), (255, 150, 0), (200, 255, 0), (0, 255, 80), (0, 180, 255), (130, 0, 255), (0, 0, 0)]},
    {"name": "Aurora Borealis","colors": [(180, 255, 200), (0, 255, 150), (0, 200, 255), (80, 0, 255), (200, 0, 150), (0, 80, 40), (0, 5, 10)]},
    {"name": "Iridescent",     "colors": [(255, 220, 255), (200, 150, 255), (100, 200, 255), (150, 255, 200), (255, 255, 150), (255, 180, 200), (10, 5, 10)]},
    {"name": "Chrome",         "colors": [(255, 255, 255), (180, 200, 220), (80, 100, 140), (200, 210, 230), (255, 255, 255), (40, 50, 70), (5, 5, 10)]},
    {"name": "Bismuth",        "colors": [(255, 200, 50), (200, 100, 255), (0, 200, 200), (255, 50, 100), (100, 255, 50), (50, 0, 80), (5, 0, 5)]},
    {"name": "Soap Bubble",    "colors": [(255, 200, 250), (200, 255, 200), (200, 220, 255), (255, 255, 200), (220, 200, 255), (180, 255, 240), (5, 5, 8)]},
    {"name": "Laser Show",     "colors": [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255), (0, 0, 0)]},
    {"name": "Molten Metal",   "colors": [(255, 255, 220), (255, 200, 50), (255, 80, 0), (200, 0, 50), (80, 0, 100), (20, 0, 40), (0, 0, 0)]},
    {"name": "Deep Spectrum",  "colors": [(255, 0, 80), (200, 0, 200), (0, 0, 255), (0, 150, 200), (0, 200, 100), (150, 200, 0), (5, 0, 5)]},
]


def palette_color(brightness, palette_idx):
    """Map a brightness value (0-255) to an RGB tuple using a palette.

    Supports palettes with any number of color stops (3, 5, 7, etc.).
    Colors are listed dark→bright: [shadow, ..., highlight].
    Brightness 0 = black (LEDs off), 255 = brightest color in palette.
    """
    pal = PALETTES[palette_idx % len(PALETTES)]
    colors = pal["colors"]
    b = max(0.0, min(1.0, brightness / 255.0))
    n = len(colors)

    if n < 2:
        c = colors[0]
        return (int(c[0] * b), int(c[1] * b), int(c[2] * b))

    # Map b (0..1) across color stops.
    # colors[0] = shadow (darkest), colors[-1] = highlight (brightest)
    # Reverse so b=0 → shadow, b=1 → highlight
    pos = b * (n - 1)
    idx = int(pos)
    t = pos - idx
    if idx >= n - 1:
        idx = n - 2
        t = 1.0

    # Interpolate between colors[idx] and colors[idx+1]
    # Note: colors are ordered [highlight, mid, shadow] for 3-color palettes
    # and [highlight, ..., shadow] for multi-color. We reverse to go dark→bright.
    c0 = colors[n - 1 - idx]
    c1 = colors[n - 2 - idx]

    r = c0[0] + (c1[0] - c0[0]) * t
    g = c0[1] + (c1[1] - c0[1]) * t
    b_ch = c0[2] + (c1[2] - c0[2]) * t

    # Scale by brightness so 0 = truly black
    r = int(r * b)
    g = int(g * b)
    b_ch = int(b_ch * b)

    return (r, g, b_ch)


# ─── Animation Functions ─────────────────────────────────────────────────────
# Each: (nx, ny, time, width, height) -> val (0-255)
# nx, ny are normalized 0..1; width/height are pixel dimensions for scaling

def anim_wave(nx, ny, t, w, h):
    x, y = nx * w, ny * h
    return int((math.sin(x * 0.1 + t) * math.cos(y * 0.1 - t * 0.5) + 1) * 127)

def anim_plasma(nx, ny, t, w, h):
    v = (math.sin(nx*10+t) + math.sin(ny*10+t) + math.sin((nx+ny)*10+t) + math.sin(math.sqrt(nx*nx+ny*ny)*10+t) + 4) / 8
    return int(v * 255)

def anim_scanner(nx, ny, t, w, h):
    scan_x = (math.sin(t * 2) + 1) / 2
    return int(max(0, 1 - abs(nx - scan_x) * 5) * 255)

def anim_rain(nx, ny, t, w, h):
    return 255 if math.sin(ny*20 + t*5 + math.sin(nx*50)) > 0.9 else 0

def anim_noise(nx, ny, t, w, h):
    return 255 if random.random() > 0.95 else 0

def anim_stars(nx, ny, t, w, h):
    sx = (nx - 0.5) * (math.sin(t) + 2)
    sy = (ny - 0.5) * (math.sin(t) + 2)
    return 255 if math.sin(math.sqrt(sx*sx + sy*sy)*20 - t*10) > 0.8 else 0

def anim_circle(nx, ny, t, w, h):
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    return 255 if abs(math.sin(d*20 - t*5)) > 0.8 else 0

def anim_pulse(nx, ny, t, w, h):
    return int((math.sin(t * 3) + 1) / 2 * 255)

def anim_digital(nx, ny, t, w, h):
    return 255 if (int(nx*10+t) % 2 == 0 and int(ny*10-t) % 2 == 0) else 20

def anim_snow(nx, ny, t, w, h):
    x, y = nx*w, ny*h
    return 255 if math.sin(x*0.5 + y*0.5 + random.random()*10) > 0.9 else 0

def anim_cloud(nx, ny, t, w, h):
    return int((math.sin(nx*5 + t*0.2) * math.cos(ny*5 - t*0.3) + 1) / 2 * 255)

def anim_blob(nx, ny, t, w, h):
    v = (math.sin(nx*3+t) + math.cos(ny*4+t*0.8) + math.sin(math.sqrt(nx*nx+ny*ny)*5-t)) / 3 * 255
    return int(max(0, v)) if v >= 100 else 0

def anim_sparkle(nx, ny, t, w, h):
    return 255 if random.random() > 0.99 else 0

def anim_tunnel(nx, ny, t, w, h):
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2) + 0.01
    return 255 if math.sin(1/d - t*5) > 0.5 else 0

def anim_fire(nx, ny, t, w, h):
    return int(max(0, min(255, (math.sin(nx*5+t) * math.cos(ny*2-t*2) + (1-ny)) * 127)))

def anim_bolt(nx, ny, t, w, h):
    if random.random() > 0.98:
        return 255
    return 20 if random.random() > 0.5 else 0

def anim_spiral(nx, ny, t, w, h):
    a = math.atan2(ny-0.5, nx-0.5)
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    return 255 if math.sin(a*5 + d*20 - t*10) > 0 else 0

def anim_bands(nx, ny, t, w, h):
    return 255 if math.sin(nx*20 + t*5) > 0.8 else 0

def anim_grid(nx, ny, t, w, h):
    return 255 if (int(nx*8) + int(ny*8)) % 2 == 0 else 0

def anim_sweep(nx, ny, t, w, h):
    a = math.atan2(ny-0.5, nx-0.5)
    return 255 if abs((a + math.pi + t) % (math.pi*2)) < 0.2 else 20

def anim_twist(nx, ny, t, w, h):
    return 255 if math.sin(nx*10 + math.sin(ny*5+t)*5) > 0 else 0

def anim_bounce(nx, ny, t, w, h):
    by = (math.sin(t*3) + 1) / 2
    return int(max(0, 1 - abs(ny - by) * 10) * 255)

def anim_gravity(nx, ny, t, w, h):
    return 255 if math.sin(ny*10 + math.sin(nx*5)*10 + t*15) > 0.9 else 0

def anim_stripe2(nx, ny, t, w, h):
    return 255 if (int(nx*20 + math.sin(ny*10+t)*5) % 2 == 0) else 0

def anim_glitch(nx, ny, t, w, h):
    gy = int(ny*10) / 10
    return 255 if math.sin(nx*10 + math.sin(gy*100+t*20)) > 0.5 else 0

def anim_kaleido(nx, ny, t, w, h):
    knx, kny = abs(nx-0.5), abs(ny-0.5)
    return 255 if math.sin(knx*10 + kny*10 + t) > 0.5 else 0

def anim_tint(nx, ny, t, w, h):
    return int((math.sin(nx*5+t) * math.sin(ny*5+t*0.5) + 1) * 127)

def anim_flux(nx, ny, t, w, h):
    # Offset each wave so they don't cancel → stays visible throughout cycle
    v = (math.sin(nx*3+t*1.5) + math.sin(ny*4-t*1.2) + math.sin((nx+ny)*2.5+t*0.8) + 3) / 6
    return int(max(0, min(255, v * 255)))

def anim_top(nx, ny, t, w, h):
    return int(max(0, min(255, (1 - ny - math.sin(t)*0.2) * 255)))

def anim_side(nx, ny, t, w, h):
    return int(max(0, min(255, (1 - nx - math.cos(t)*0.2) * 255)))

def anim_voronoi(nx, ny, t, w, h):
    d1 = math.sqrt((nx-0.3)**2 + (ny-0.7)**2)
    d2 = math.sqrt((nx-0.8)**2 + (ny-0.2)**2)
    return 255 if math.sin(min(d1, d2)*30 - t*5) > 0.5 else 0

def anim_glow(nx, ny, t, w, h):
    return int(math.sin(nx*math.pi)**2 * math.sin(ny*math.pi)**2 * 255)

def anim_point(nx, ny, t, w, h):
    px = (math.sin(t) + 1) / 2
    py = (math.cos(t*0.7) + 1) / 2
    return int(max(0, 1 - math.sqrt((nx-px)**2 + (ny-py)**2) * 15) * 255)

def anim_flash(nx, ny, t, w, h):
    return 255 if math.sin(t*10) > 0 else 0

def anim_sweep2(nx, ny, t, w, h):
    return 255 if (abs(nx-0.5) < 0.05 or abs(ny - (math.sin(t)+1)/2) < 0.05) else 0

def anim_shape(nx, ny, t, w, h):
    return 255 if (abs(nx-0.5) + abs(ny-0.5) < (math.sin(t)+1)/4) else 0

def anim_pond(nx, ny, t, w, h):
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    return int(math.sin(d*40 - t*10) * 127 + 127)

def anim_trail(nx, ny, t, w, h):
    v = math.sin(nx*10 - t*5) * 255
    return int(max(0, v))

def anim_crystal(nx, ny, t, w, h):
    return 255 if math.sin(nx*50 + ny*50) > 0.9 else 0

def anim_fade(nx, ny, t, w, h):
    return int(max(0, min(255, nx * ny * (math.sin(t)+1) * 127)))

def anim_helix(nx, ny, t, w, h):
    return 255 if abs(math.sin(ny*10 + math.sin(t)*5) - nx) < 0.1 else 0

def anim_sinus(nx, ny, t, w, h):
    return 255 if math.sin(nx*30+t*10) * math.sin(ny*30+t*5) > 0.5 else 0

def anim_laser(nx, ny, t, w, h):
    return 255 if abs(ny - (math.sin(t*5)+1)/2) < 0.02 else 0

def anim_streak(nx, ny, t, w, h):
    return int(max(0, 1 - abs(nx - (t % 1)) * 20) * 255)

def anim_float(nx, ny, t, w, h):
    return 255 if math.sin(ny*5 + t) > 0.8 else 0

def anim_boids(nx, ny, t, w, h):
    return 255 if (math.sin(nx*15+t) + math.cos(ny*15+t)) > 1.5 else 0

def anim_time(nx, ny, t, w, h):
    angle_t = (t % 60) / 60 * math.pi * 2
    dist_t = abs(math.atan2(ny-0.5, nx-0.5) - angle_t)
    return 255 if dist_t < 0.1 else 20

def anim_rotary(nx, ny, t, w, h):
    return 255 if math.sin(math.atan2(ny-0.5, nx-0.5)*6 + t*5) > 0.5 else 0

def anim_heart(nx, ny, t, w, h):
    hx, hy = nx-0.5, ny-0.5
    v = (hx*hx + hy*hy - 0.1)**3 - hx*hx * hy*hy*hy
    return 255 if v < 0 else 0

def anim_ang(nx, ny, t, w, h):
    return 255 if math.sin((nx+ny)*20 + t*10) > 0.8 else 0

def anim_fuzz(nx, ny, t, w, h):
    return int(random.random() * 255)

def anim_crt(nx, ny, t, w, h):
    return 255 if (int(ny*100) % 2 == 0) else 50

def anim_zoom(nx, ny, t, w, h):
    d = max(0.1, math.sqrt((nx-0.5)**2 + (ny-0.5)**2))
    return 255 if math.sin(1/d - t*10) > 0 else 0

def anim_flow(nx, ny, t, w, h):
    return int((math.sin(nx*10+t) + math.cos(ny*10+t)) * 127 + 127)

def anim_dust(nx, ny, t, w, h):
    return 255 if random.random() > 0.995 else 0

def anim_pop(nx, ny, t, w, h):
    return 255 if math.sin(t*10) > 0.9 else 0

def anim_ocean(nx, ny, t, w, h):
    return int((math.sin(nx*5+t) + math.sin(ny*2+t*0.5)) * 127 + 127)

def anim_bits(nx, ny, t, w, h):
    return 255 if random.random() > 0.9 else 0

def anim_sky(nx, ny, t, w, h):
    return int(max(0, min(255, (1-ny)*200 + math.sin(t)*55)))

def anim_tech(nx, ny, t, w, h):
    return 100 if (int(nx*10) % 2 == 0 or int(ny*10) % 2 == 0) else 0

def anim_shiver(nx, ny, t, w, h):
    return 255 if math.sin(nx*100+t*50) > 0.5 else 0

def anim_lens(nx, ny, t, w, h):
    return int(max(0, 255 - math.sqrt((nx-0.5)**2 + (ny-0.5)**2) * 500))

def anim_shift(nx, ny, t, w, h):
    return 255 if (nx + t) % 1 > 0.9 else 0

def anim_lavaflow(nx, ny, t, w, h):
    return int((math.sin(nx*4+t) * math.sin(ny*4-t)) * 127 + 127)

def anim_rainbow(nx, ny, t, w, h):
    return int(((nx + ny + t) % 1) * 255)

def anim_twist2(nx, ny, t, w, h):
    return 255 if math.sin(nx*10 + ny*10 + t*5) > 0.5 else 0

def anim_ghosting(nx, ny, t, w, h):
    return int(max(0, min(255, math.sin(nx*5-t)*100 + 100)))

def anim_sun(nx, ny, t, w, h):
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    # Breathing pulse: 0.3 to 1.0 (never goes dark)
    pulse = 0.3 + 0.7 * (math.sin(t * 1.5) + 1) / 2
    return int(max(0, (1 - d * 3) * 255 * pulse))

def anim_block(nx, ny, t, w, h):
    return 255 if (int(nx*20) + int(ny*20)) % 2 == 0 else 20

def anim_drift(nx, ny, t, w, h):
    return int(math.sin(nx*5 + ny*2 + t) * 127 + 127)

def anim_ping(nx, ny, t, w, h):
    pd = (t % 2) / 2
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    return 255 if abs(d - pd) < 0.05 else 0

def anim_wire(nx, ny, t, w, h):
    return 255 if (abs(nx % 0.1) < 0.01 or abs(ny % 0.1) < 0.01) else 0

def anim_run(nx, ny, t, w, h):
    return 255 if abs(nx - (t % 1)) < 0.05 else 0

def anim_grain(nx, ny, t, w, h):
    return int(random.random() * 100)

def anim_wave3(nx, ny, t, w, h):
    return int(math.sin(nx*10 + math.sin(ny*10+t)) * 127 + 127)

def anim_moon(nx, ny, t, w, h):
    return 255 if math.sqrt((nx-0.5)**2 + (ny-0.5)**2) < 0.2 else 0

def anim_wind(nx, ny, t, w, h):
    return int(math.sin(nx*5 + t*10) * 127 + 127)

def anim_beat(nx, ny, t, w, h):
    return 255 if math.sin(t*10) > 0 else 50

def anim_storm(nx, ny, t, w, h):
    return 255 if random.random() > 0.98 else int(random.random() * 30)

def anim_shock(nx, ny, t, w, h):
    return 255 if abs(math.sin(nx*100+t*20)) > 0.9 else 0

def anim_dark(nx, ny, t, w, h):
    return int(max(0, min(255, nx * ny * 50)))

def anim_nova(nx, ny, t, w, h):
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    v = (1 - d) * 255 * math.sin(t)
    return int(max(0, min(255, v)))

def anim_breath(nx, ny, t, w, h):
    return int((math.sin(t*2) + 1) / 2 * 255)

def anim_speed(nx, ny, t, w, h):
    v = max(0, 1 - abs(ny-0.5)*5) * 255 * math.sin(nx*10+t*20)
    return int(max(0, min(255, v)))

def anim_digital2(nx, ny, t, w, h):
    return 255 if (int(nx*50) + int(ny*50) + int(t*10)) % 2 == 0 else 0

def anim_glow2(nx, ny, t, w, h):
    return int(max(0, math.sin(nx * math.pi) * 255))

def anim_retro(nx, ny, t, w, h):
    return 150 if (int(ny*20) % 2 == 0) else 20

def anim_candle(nx, ny, t, w, h):
    return int(max(0, min(255, (math.sin(t*10) + math.sin(t*1.5))*50 + 150)))

def anim_shaft(nx, ny, t, w, h):
    return 255 if abs(nx - 0.5) < 0.1 else 0

def anim_halo(nx, ny, t, w, h):
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    return 255 if (d > 0.3 and d < 0.35) else 0


# ─── Audio Pattern Functions ────────────────────────────────────────────────
# Each: (nx, ny, audio_time, width, height, bass, mid, treble) -> val (0-255)
#
# RULE: NO movement except sound-based movement.
# - `bass` is used as DIRECT DISPLACEMENT (like a speaker cone position)
# - `t` (audio_time) provides slow accumulated drift from sustained audio
# - When silent: bass=0, t frozen → pattern completely static and visible
# - When bass hits: pattern physically displaces/morphs
# - Full brightness always — audio never dims the pattern

def audio_wave(nx, ny, t, w, h, bass, mid, treble):
    """Interference — wave amplitude displaced by bass."""
    x, y = nx * w, ny * h
    # Bass directly pushes the wave amplitude — like a speaker membrane
    amp = bass * 2.0
    return int((math.sin(x * 0.1 + t) * math.cos(y * 0.1 - t * 0.5) * amp + 1) * 127)

def audio_plasma(nx, ny, t, w, h, bass, mid, treble):
    """Plasma — bass expands/contracts plasma cells."""
    freq = 8 + bass * 12  # bass stretches the cell size
    v = (math.sin(nx*freq+t) + math.sin(ny*freq+t) +
         math.sin((nx+ny)*freq+t) + math.sin(math.sqrt(nx*nx+ny*ny)*freq+t) + 4) / 8
    return int(v * 255)

def audio_scanner(nx, ny, t, w, h, bass, mid, treble):
    """Scanner — bass directly pushes bar position left/right."""
    scan_x = 0.5 + (bass - 0.5) * 0.8  # bass displaces from center
    return int(max(0, 1 - abs(nx - scan_x) * 8) * 255)

def audio_noise(nx, ny, t, w, h, bass, mid, treble):
    """Pixels — bass/treble control pixel density. Silent = no pixels."""
    energy = bass + treble
    if energy < 0.02:
        return 0
    threshold = 1.0 - energy * 0.35
    return 255 if random.random() > threshold else 0

def audio_circle(nx, ny, t, w, h, bass, mid, treble):
    """Orbit — bass pushes rings outward like a speaker cone."""
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    ring_radius = 0.15 + bass * 0.35  # bass directly sets ring size
    return 255 if abs(d - ring_radius) < 0.04 else 0

def audio_digital(nx, ny, t, w, h, bass, mid, treble):
    """Matrix — bass offsets grid. Treble flickers."""
    offset = bass * 5  # bass shifts the grid
    on = (int(nx*10 + offset) % 2 == 0 and int(ny*10 + offset) % 2 == 0)
    return 255 if on else (int(treble * 60))

def audio_snow(nx, ny, t, w, h, bass, mid, treble):
    """Blizzard — bass controls snowfall density. Silent = clear."""
    if bass < 0.02:
        return 0
    x, y = nx*w, ny*h
    threshold = 1.0 - bass * 0.25
    return 255 if math.sin(x*0.5 + y*0.5 + t*2 + random.random()*5) > threshold else 0

def audio_cloud(nx, ny, t, w, h, bass, mid, treble):
    """Nebula — bass swells cloud brightness and size."""
    v = (math.sin(nx*5 + t*0.3) * math.cos(ny*5 - t*0.2) + 1) / 2
    return int(v * (bass * 255 + 30))  # dim when quiet, bright on bass

def audio_blob(nx, ny, t, w, h, bass, mid, treble):
    """Lava — bass pushes blobs outward from center."""
    # Bass displaces blob positions radially
    cx, cy = nx - 0.5, ny - 0.5
    push = 1.0 + bass * 2.0  # bass expands the blob field
    bx, by = cx * push + 0.5, cy * push + 0.5
    v = (math.sin(bx*3+t) + math.cos(by*4+t*0.8) +
         math.sin(math.sqrt(bx*bx+by*by)*5-t)) / 3 * 255
    return int(max(0, v)) if v >= 80 else 0

def audio_sparkle(nx, ny, t, w, h, bass, mid, treble):
    """Sparkle — treble controls sparkle rate. Silent = dark."""
    energy = treble + bass * 0.3
    if energy < 0.03:
        return 0
    threshold = 1.0 - energy * 0.15
    return 255 if random.random() > threshold else 0

def audio_tunnel(nx, ny, t, w, h, bass, mid, treble):
    """Tunnel — bass directly zooms the tunnel depth."""
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2) + 0.01
    zoom = bass * 8  # bass directly sets zoom offset
    return 255 if math.sin(1/d - zoom - t*2) > 0.5 else 0

def audio_fire(nx, ny, t, w, h, bass, mid, treble):
    """Bonfire — bass controls flame height."""
    flame_height = bass * 0.8  # bass directly lifts flames
    v = (math.sin(nx*5+t) * math.cos(ny*2-t*1.5) + (1-ny) * (0.3 + flame_height))
    return int(max(0, min(255, v * 200)))

def audio_spiral(nx, ny, t, w, h, bass, mid, treble):
    """Vortex — bass directly rotates the spiral."""
    a = math.atan2(ny-0.5, nx-0.5)
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    rotation = bass * 6 + t * 2  # bass directly twists
    return 255 if math.sin(a*5 + d*20 - rotation) > 0 else 0

def audio_bands(nx, ny, t, w, h, bass, mid, treble):
    """Stripes — bass directly shifts stripe position."""
    offset = bass * 3 + t  # bass pushes stripes
    return 255 if math.sin(nx*20 + offset) > 0.8 else 0

def audio_twist(nx, ny, t, w, h, bass, mid, treble):
    """Twister — bass directly controls twist amount."""
    twist_amt = bass * 8  # bass sets distortion directly
    return 255 if math.sin(nx*10 + math.sin(ny*5 + t)*twist_amt) > 0 else 0

def audio_bounce(nx, ny, t, w, h, bass, mid, treble):
    """Bouncer — bass directly pushes bar position. Like a VU meter."""
    by = 0.5 + (bass - 0.5) * 0.6  # bass directly positions the bar
    return int(max(0, 1 - abs(ny - by) * 10) * 255)

def audio_gravity(nx, ny, t, w, h, bass, mid, treble):
    """Falling — bass triggers particle drops. Silent = frozen."""
    if bass < 0.03:
        return 0
    speed = t * 8
    threshold = 0.92 - bass * 0.2
    return 255 if math.sin(ny*10 + math.sin(nx*5)*10 + speed) > threshold else 0

def audio_tint(nx, ny, t, w, h, bass, mid, treble):
    """Prism — bass shifts the color blend position."""
    offset = bass * 3 + t * 0.5
    return int((math.sin(nx*5 + offset) * math.sin(ny*5 + offset*0.5) + 1) * 127)

def audio_flux(nx, ny, t, w, h, bass, mid, treble):
    """Flow — bass directly displaces the flow field."""
    offset = bass * 4 + t
    v = (math.sin(nx*2+offset) + math.sin(ny*3-offset) + math.sin(nx+ny+offset)) / 3 * 255
    return int(max(0, min(255, v)))

def audio_shape(nx, ny, t, w, h, bass, mid, treble):
    """Diamond — bass directly controls diamond size. Speaker cone."""
    size = 0.05 + bass * 0.4  # bass expands diamond
    return 255 if (abs(nx-0.5) + abs(ny-0.5) < size) else 0

def audio_pond(nx, ny, t, w, h, bass, mid, treble):
    """Ripple — bass directly pushes ripple outward from center."""
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    ripple_push = bass * 0.5 + t * 0.5  # bass pushes the ripple ring out
    return int(math.sin((d - ripple_push) * 40) * 127 + 127)

def audio_trail(nx, ny, t, w, h, bass, mid, treble):
    """Echo — mid directly shifts trail position."""
    offset = mid * 5 + t
    v = math.sin(nx*10 - offset) * 255
    return int(max(0, v))

def audio_fade(nx, ny, t, w, h, bass, mid, treble):
    """Ghost — bass directly controls ghost visibility."""
    amp = bass * 2.0 + 0.1  # bass brightens the ghost
    return int(max(0, min(255, nx * ny * amp * 255)))

def audio_helix(nx, ny, t, w, h, bass, mid, treble):
    """DNA — bass directly compresses/stretches the helix."""
    stretch = 5 + bass * 8  # bass changes helix frequency
    phase = t * 2
    return 255 if abs(math.sin(ny*stretch + math.sin(phase)*3) - nx) < 0.1 else 0

def audio_laser(nx, ny, t, w, h, bass, mid, treble):
    """Beams — bass directly positions the beam. VU meter style."""
    beam_y = 0.5 + (bass - 0.5) * 0.8  # bass sets beam Y position
    return 255 if abs(ny - beam_y) < 0.025 else 0

def audio_streak(nx, ny, t, w, h, bass, mid, treble):
    """Comet — bass launches comet. Frozen when silent."""
    pos = (t * 1.0) % 1.0
    return int(max(0, 1 - abs(nx - pos) * 20) * 255)

def audio_rotary(nx, ny, t, w, h, bass, mid, treble):
    """Gear — bass directly rotates the gear."""
    rotation = bass * 4 + t  # bass turns the gear
    return 255 if math.sin(math.atan2(ny-0.5, nx-0.5)*6 + rotation) > 0.5 else 0

def audio_ang(nx, ny, t, w, h, bass, mid, treble):
    """ZigZag — bass directly shifts zigzag position."""
    offset = bass * 5 + t
    return 255 if math.sin((nx+ny)*20 + offset) > 0.8 else 0

def audio_zoom(nx, ny, t, w, h, bass, mid, treble):
    """Wormhole — bass directly pushes zoom in/out. Speaker cone."""
    d = max(0.1, math.sqrt((nx-0.5)**2 + (ny-0.5)**2))
    # Bass DIRECTLY controls zoom displacement — like a pulsing speaker
    zoom = bass * 6 + t
    return 255 if math.sin(1/d - zoom) > 0 else 0

def audio_flow(nx, ny, t, w, h, bass, mid, treble):
    """Nebula2 — bass displaces flow field."""
    offset = bass * 3 + t
    return int((math.sin(nx*10+offset) + math.cos(ny*10+offset)) * 127 + 127)

def audio_ocean(nx, ny, t, w, h, bass, mid, treble):
    """Waves — bass directly controls wave height."""
    amp = 0.3 + bass * 1.5  # bass lifts the waves
    offset = t * 0.5
    return int((math.sin(nx*5+offset)*amp + math.sin(ny*2+offset*0.5)) / 2 * 255 + 127)

def audio_lens(nx, ny, t, w, h, bass, mid, treble):
    """Focus — bass directly expands/contracts spotlight."""
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    spread = 0.1 + bass * 0.4  # bass sets spotlight size
    return int(max(0, 255 * (1 - d / spread))) if d < spread else 0

def audio_lavaflow(nx, ny, t, w, h, bass, mid, treble):
    """Eruption — bass pushes lava pattern."""
    offset = bass * 4 + t
    return int((math.sin(nx*4+offset) * math.sin(ny*4-offset)) * 127 + 127)

def audio_rainbow(nx, ny, t, w, h, bass, mid, treble):
    """Prism2 — bass shifts rainbow position."""
    offset = bass * 0.5 + t * 0.3
    return int(((nx + ny + offset) % 1) * 255)

def audio_ghosting(nx, ny, t, w, h, bass, mid, treble):
    """Echoes — mid directly shifts ghost layers."""
    offset = mid * 3 + t
    return int(max(0, min(255, math.sin(nx*5-offset)*100 + 100)))

def audio_sun(nx, ny, t, w, h, bass, mid, treble):
    """Radiate — bass directly expands the glow radius. Speaker push."""
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    spread = 0.1 + bass * 0.5  # bass pushes glow outward
    return int(max(0, 255 * (1 - d / spread))) if d < spread else 0

def audio_drift(nx, ny, t, w, h, bass, mid, treble):
    """Tides — bass directly shifts tide position."""
    offset = bass * 3 + t
    return int(math.sin(nx*5 + ny*2 + offset) * 127 + 127)

def audio_wave3(nx, ny, t, w, h, bass, mid, treble):
    """Mirage — bass directly controls wave distortion amount."""
    distort = bass * 3  # bass sets distortion magnitude
    return int(math.sin(nx*10 + math.sin(ny*10 + t) * distort) * 127 + 127)


# ─── Cymatics Patterns ────────────────────────────────────────────────────
# Based on real physics: Chladni plates, drum modes, standing waves.
# These produce geometric nodal-line patterns like real cymatics on vibrating surfaces.

def _bessel_j0_approx(x):
    """Fast approximation of Bessel J0 for cymatics. Accurate enough for visuals."""
    ax = abs(x)
    if ax < 3.0:
        y = x * x
        return 1.0 - y*(0.25 - y*(0.015625 - y*0.000434))
    else:
        y = 3.0 / ax
        return math.sqrt(0.6366 / ax) * math.cos(ax - 0.785 - y*(0.0156 + y*0.00017))

def _bessel_j1_approx(x):
    """Fast approximation of Bessel J1."""
    ax = abs(x)
    sign = 1.0 if x >= 0 else -1.0
    if ax < 3.0:
        y = x * x
        return sign * ax * 0.5 * (1.0 - y*(0.125 - y*(0.005208 - y*0.0001)))
    else:
        y = 3.0 / ax
        return sign * math.sqrt(0.6366 / ax) * math.cos(ax - 2.356 - y*(0.0469 + y*0.00039))

# ── 1. Chladni ── Square plate nodal lines: sin(n*x)*sin(m*y) ± sin(m*x)*sin(n*y) = 0
# The nodal lines (where brightness=0) form the geometric patterns.
# n,m integers slowly morph over time to transition between plate modes.

def anim_chladni(nx, ny, t, w, h):
    """Chladni plate — square nodal patterns that morph between modes."""
    # Cycle through mode pairs over time
    phase = t * 0.15
    n = 2 + math.sin(phase) * 2          # ranges 0-4
    m = 3 + math.cos(phase * 0.7) * 2    # ranges 1-5
    # Second mode pair for blending
    n2 = 3 + math.sin(phase * 0.6 + 1.5) * 2
    m2 = 2 + math.cos(phase * 0.4 + 0.8) * 2

    blend = (math.sin(t * 0.3) + 1) / 2  # 0..1 crossfade between two modes

    x, y = nx * math.pi, ny * math.pi
    v1 = math.sin(n*x) * math.sin(m*y) - math.sin(m*x) * math.sin(n*y)
    v2 = math.sin(n2*x) * math.sin(m2*y) - math.sin(m2*x) * math.sin(n2*y)
    v = v1 * (1-blend) + v2 * blend

    # Nodal lines are at v≈0; bright away from nodes
    brightness = abs(v)
    # Apply contrast curve to sharpen the nodal lines
    brightness = min(1.0, brightness * 2.5)
    brightness = brightness ** 0.6  # gamma to soften slightly
    return int(brightness * 255)

def audio_chladni(nx, ny, t, w, h, bass, mid, treble):
    """Chladni — bass sets the mode number (higher bass = more complex pattern)."""
    n = 1.5 + bass * 5    # bass controls complexity
    m = 2.0 + mid * 4     # mid controls second mode
    x, y = nx * math.pi, ny * math.pi
    v = math.sin(n*x) * math.sin(m*y) - math.sin(m*x) * math.sin(n*y)
    brightness = min(1.0, abs(v) * 2.5) ** 0.6
    return int(brightness * 255)

# ── 2. Resonance ── Circular drum modes using Bessel functions: J_n(kr) * cos(nθ)
# Creates the mandala-like circular patterns from the reference images.

def anim_resonance(nx, ny, t, w, h):
    """Resonance — circular mandala patterns from drum modes."""
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2  # 0..~1.4
    theta = math.atan2(dy, dx)

    # Slowly cycle between angular modes
    n_mode = 3 + math.sin(t * 0.2) * 3  # ranges 0-6

    # Radial frequency also shifts
    k = 6 + math.sin(t * 0.15) * 3      # ranges 3-9

    # Bessel-like radial * angular
    radial = _bessel_j0_approx(k * r * math.pi)
    angular = math.cos(n_mode * theta + t * 0.5)
    v = radial * angular

    brightness = min(1.0, abs(v) * 2.0) ** 0.7
    return int(brightness * 255)

def audio_resonance(nx, ny, t, w, h, bass, mid, treble):
    """Resonance — bass controls radial frequency, treble controls angular mode."""
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    n_mode = 2 + treble * 8    # treble = more angular divisions
    k = 4 + bass * 10          # bass = tighter radial rings
    radial = _bessel_j0_approx(k * r * math.pi)
    angular = math.cos(n_mode * theta)
    brightness = min(1.0, abs(radial * angular) * 2.0) ** 0.7
    return int(brightness * 255)

# ── 3. Standing Wave ── Concentric rings from constructive/destructive interference
# Like the Mercury Tone image — clean concentric circles with varying spacing.

def anim_standing(nx, ny, t, w, h):
    """Standing Wave — concentric interference rings that breathe."""
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy)

    # Two wave sources at slightly different frequencies create standing pattern
    freq1 = 12 + math.sin(t * 0.2) * 4
    freq2 = 14 + math.cos(t * 0.17) * 3
    wave1 = math.sin(r * freq1 * math.pi)
    wave2 = math.sin(r * freq2 * math.pi + t * 0.3)

    v = (wave1 + wave2) / 2
    # Sharpen rings
    brightness = (v + 1) / 2
    brightness = max(0, min(1, brightness))
    brightness = brightness ** 0.5  # boost contrast
    return int(brightness * 255)

def audio_standing(nx, ny, t, w, h, bass, mid, treble):
    """Standing Wave — bass controls ring spacing, mid shifts phase."""
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy)
    freq = 8 + bass * 20    # bass = more/fewer rings
    phase = mid * math.pi * 2
    v = math.sin(r * freq * math.pi + phase)
    brightness = max(0, min(1, (v + 1) / 2)) ** 0.5
    return int(brightness * 255)

# ── 4. Harmonics ── Multiple frequency superposition → complex flower patterns
# Like Moon siderical — flower/mandala from summing several angular harmonics.

def anim_harmonics(nx, ny, t, w, h):
    """Harmonics — superimposed frequencies create flower/mandala patterns."""
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)

    # Sum 4 harmonics with slowly drifting parameters
    v = 0
    for i in range(4):
        n = 2 + i + math.sin(t * (0.1 + i * 0.07)) * 1.5
        k = 3 + i * 2 + math.cos(t * (0.08 + i * 0.05)) * 2
        v += math.sin(n * theta + t * 0.2 * (i+1)) * _bessel_j0_approx(k * r)

    v /= 4
    brightness = min(1.0, abs(v) * 3.0) ** 0.6
    return int(brightness * 255)

def audio_harmonics(nx, ny, t, w, h, bass, mid, treble):
    """Harmonics — each frequency band controls a different harmonic."""
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    # Bass = fundamental, mid = 2nd harmonic, treble = 3rd+4th
    v = (math.sin(3*theta) * _bessel_j0_approx(5*r) * bass +
         math.sin(5*theta) * _bessel_j0_approx(8*r) * mid +
         math.sin(7*theta) * _bessel_j0_approx(11*r) * treble +
         math.sin(9*theta) * _bessel_j0_approx(14*r) * treble * 0.5)
    v /= max(0.01, bass + mid + treble + 0.01)
    brightness = min(1.0, abs(v) * 3.0) ** 0.6
    return int(brightness * 255)

# ── 5. Interference ── Two point sources creating ripple overlap → cell divisions
# Like the Earth (day) image — organic cell-like boundaries.

def anim_cymatic_interference(nx, ny, t, w, h):
    """Interference cells — two oscillating point sources create cell divisions."""
    # Two source points that orbit slowly
    s1x = 0.35 + math.sin(t * 0.3) * 0.12
    s1y = 0.5 + math.cos(t * 0.25) * 0.12
    s2x = 0.65 + math.sin(t * 0.35 + 1) * 0.12
    s2y = 0.5 + math.cos(t * 0.3 + 1.5) * 0.12

    d1 = math.sqrt((nx - s1x)**2 + (ny - s1y)**2)
    d2 = math.sqrt((nx - s2x)**2 + (ny - s2y)**2)

    freq = 18 + math.sin(t * 0.1) * 5
    wave1 = math.sin(d1 * freq * math.pi + t)
    wave2 = math.sin(d2 * freq * math.pi - t * 0.5)

    # Interference pattern
    v = (wave1 + wave2) / 2
    brightness = (v + 1) / 2
    # Sharpen cell boundaries
    brightness = brightness ** 1.5
    return int(brightness * 255)

def audio_cymatic_interference(nx, ny, t, w, h, bass, mid, treble):
    """Interference cells — bass controls frequency, sources pulse with treble."""
    s1x, s1y = 0.35, 0.5
    s2x, s2y = 0.65, 0.5
    d1 = math.sqrt((nx - s1x)**2 + (ny - s1y)**2)
    d2 = math.sqrt((nx - s2x)**2 + (ny - s2y)**2)
    freq = 10 + bass * 25   # bass = more/fewer cells
    wave1 = math.sin(d1 * freq * math.pi)
    wave2 = math.sin(d2 * freq * math.pi)
    v = (wave1 + wave2) / 2
    brightness = max(0, min(1, (v + 1) / 2)) ** 1.5
    return int(brightness * 255)

# ── 6. Cymatic Bloom ── Rotating flower pattern from angular harmonics + radial decay
# Like the Sirius period image — ornate rotating mandala with radial glow.

def anim_cymatic_bloom(nx, ny, t, w, h):
    """Cymatic Bloom — ornate rotating mandala with radial glow."""
    dx, dy = nx - 0.5, ny - 0.5
    # Correct for aspect ratio so bloom fills the full vertical space
    aspect = w / max(h, 1)
    dx_adj = dx * min(aspect, 1.0)
    dy_adj = dy / max(aspect, 1.0) if aspect < 1 else dy
    r = math.sqrt(dx_adj*dx_adj + dy*dy) * 2
    theta = math.atan2(dy, dx_adj)

    # Multi-petal rotating flower
    petals = 6 + math.sin(t * 0.1) * 2  # 4-8 petals
    rot = t * 0.3

    # Petal shape: angular modulation * radial envelope
    angular = (math.cos(petals * (theta + rot)) + 1) / 2
    # Inner ring modulation
    inner = (math.cos(petals * 2 * (theta - rot * 0.7) + math.pi/4) + 1) / 2

    # Radial envelope — stretch to fill panel
    radial = max(0, 1.0 - r * 0.9)
    radial_ring = (math.sin(r * 8 + t * 0.5) + 1) / 2

    # Combine layers
    v = (angular * 0.5 + inner * 0.3 + radial_ring * 0.2) * radial
    # Add bright center
    center_glow = max(0, 1.0 - r * 4) ** 2
    v = v * 0.8 + center_glow * 0.2

    brightness = min(1.0, v * 2.5)
    return int(brightness * 255)

def audio_cymatic_bloom(nx, ny, t, w, h, bass, mid, treble):
    """Cymatic Bloom — bass controls petal count, treble controls rotation."""
    dx, dy = nx - 0.5, ny - 0.5
    aspect = w / max(h, 1)
    dx_adj = dx * min(aspect, 1.0)
    r = math.sqrt(dx_adj*dx_adj + dy*dy) * 2
    theta = math.atan2(dy, dx_adj)
    petals = 3 + bass * 8
    rot = treble * math.pi * 2
    angular = (math.cos(petals * (theta + rot)) + 1) / 2
    inner = (math.cos(petals * 2 * (theta - rot * 0.5)) + 1) / 2
    radial = max(0, 1.0 - r * 0.9)
    radial_ring = (math.sin(r * (6 + mid * 10)) + 1) / 2
    v = (angular * 0.5 + inner * 0.3 + radial_ring * 0.2) * radial
    center_glow = max(0, 1.0 - r * 4) ** 2
    v = v * 0.8 + center_glow * 0.2
    brightness = min(1.0, v * 2.5)
    return int(brightness * 255)


# ── 7. Cymatic Pulse ── Radial rings that pulse from center like a heartbeat
def anim_cymatic_pulse(nx, ny, t, w, h):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    # Rings emanate from center with time-varying spacing
    freq = 10 + math.sin(t * 0.5) * 4
    phase = t * 3  # rings expand outward
    v = math.sin(r * freq - phase)
    # Envelope: fade at edges
    env = max(0, 1.0 - r * 0.8)
    brightness = max(0, min(1, (v + 1) / 2 * env)) ** 0.7
    return int(brightness * 255)

def audio_cymatic_pulse(nx, ny, t, w, h, bass, mid, treble):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    freq = 6 + bass * 18
    v = math.sin(r * freq)
    env = max(0, 1.0 - r * 0.8)
    brightness = max(0, min(1, (v + 1) / 2 * env)) ** 0.7
    return int(brightness * 255)

# ── 8. Cymatic Web ── Spider web from intersecting radial + angular standing waves
def anim_cymatic_web(nx, ny, t, w, h):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    spokes = 8 + math.sin(t * 0.15) * 3
    radial = math.sin(r * 12 + t * 0.5)
    angular = math.sin(spokes * theta + t * 0.2)
    # Web = intersection of radial rings and angular spokes
    v = radial * 0.5 + angular * 0.5
    env = max(0, 1.0 - r * 0.7)
    brightness = max(0, min(1, (v + 1) / 2)) * env
    return int(brightness * 255)

def audio_cymatic_web(nx, ny, t, w, h, bass, mid, treble):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    spokes = 4 + bass * 12
    radial = math.sin(r * (8 + mid * 15))
    angular = math.sin(spokes * theta)
    v = radial * 0.5 + angular * 0.5
    env = max(0, 1.0 - r * 0.7)
    brightness = max(0, min(1, (v + 1) / 2)) * env
    return int(brightness * 255)

# ── 9. Cymatic Lotus ── Higher-order Bessel modes → lotus flower
def anim_cymatic_lotus(nx, ny, t, w, h):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    n = 5 + math.sin(t * 0.12) * 2
    # Layered petals using J0 at different radial frequencies
    layer1 = _bessel_j0_approx(r * 8) * math.cos(n * theta + t * 0.3)
    layer2 = _bessel_j0_approx(r * 14) * math.cos((n+2) * theta - t * 0.2)
    v = (layer1 + layer2) / 2
    brightness = min(1.0, abs(v) * 3.0) ** 0.5
    return int(brightness * 255)

def audio_cymatic_lotus(nx, ny, t, w, h, bass, mid, treble):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    n = 3 + bass * 8
    layer1 = _bessel_j0_approx(r * (6 + mid * 12)) * math.cos(n * theta)
    layer2 = _bessel_j0_approx(r * (10 + treble * 10)) * math.cos((n+2) * theta)
    v = (layer1 + layer2) / 2
    brightness = min(1.0, abs(v) * 3.0) ** 0.5
    return int(brightness * 255)

# ── 10. Cymatic Fractal ── Nested circular patterns at different scales
def anim_cymatic_fractal(nx, ny, t, w, h):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    v = 0
    for octave in range(4):
        scale = 2 ** octave
        freq = (4 + octave * 3) + math.sin(t * (0.1 + octave * 0.05)) * 2
        n_ang = 3 + octave * 2
        v += _bessel_j0_approx(r * freq * scale * 0.5) * math.cos(n_ang * theta + t * 0.2 * scale) / scale
    brightness = min(1.0, abs(v) * 4.0) ** 0.6
    return int(brightness * 255)

def audio_cymatic_fractal(nx, ny, t, w, h, bass, mid, treble):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    bands = [bass, mid, treble, (bass+treble)/2]
    v = 0
    for octave in range(4):
        scale = 2 ** octave
        freq = 4 + bands[octave] * 15
        n_ang = 3 + octave * 2
        v += _bessel_j0_approx(r * freq * scale * 0.5) * math.cos(n_ang * theta) / scale
    brightness = min(1.0, abs(v) * 4.0) ** 0.6
    return int(brightness * 255)

# ── 11. Cymatic Vortex ── Spiral standing wave (rotating nodal lines)
def anim_cymatic_vortex(nx, ny, t, w, h):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    # Spiral: r and theta coupled
    spiral = math.sin(r * 10 - theta * 3 + t * 2)
    radial = _bessel_j0_approx(r * 8 + t * 0.5)
    v = spiral * 0.6 + radial * 0.4
    env = max(0, 1.0 - r * 0.6)
    brightness = max(0, min(1, (v + 1) / 2 * env))
    return int(brightness * 255)

def audio_cymatic_vortex(nx, ny, t, w, h, bass, mid, treble):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    spiral = math.sin(r * (6 + bass * 15) - theta * (2 + treble * 5))
    radial = _bessel_j0_approx(r * (5 + mid * 10))
    v = spiral * 0.6 + radial * 0.4
    env = max(0, 1.0 - r * 0.6)
    brightness = max(0, min(1, (v + 1) / 2 * env))
    return int(brightness * 255)

# ── 12. Cymatic Grid ── Rectangular plate modes (square cymatics)
def anim_cymatic_grid(nx, ny, t, w, h):
    # Two rectangular standing wave modes superimposed
    m1, n1 = 3 + math.sin(t * 0.2) * 2, 4 + math.cos(t * 0.17) * 2
    m2, n2 = 5 + math.sin(t * 0.15) * 2, 3 + math.cos(t * 0.22) * 2
    v1 = math.sin(m1 * nx * math.pi) * math.sin(n1 * ny * math.pi)
    v2 = math.cos(m2 * nx * math.pi) * math.cos(n2 * ny * math.pi)
    v = v1 * 0.6 + v2 * 0.4
    brightness = min(1.0, abs(v) * 2.5) ** 0.6
    return int(brightness * 255)

def audio_cymatic_grid(nx, ny, t, w, h, bass, mid, treble):
    m = 2 + bass * 6
    n = 2 + mid * 6
    v1 = math.sin(m * nx * math.pi) * math.sin(n * ny * math.pi)
    v2 = math.cos((m+1) * nx * math.pi) * math.cos((n+1) * ny * math.pi)
    v = v1 * 0.6 + v2 * 0.4
    brightness = min(1.0, abs(v) * 2.5) ** 0.6
    return int(brightness * 255)

# ── 13. Cymatic Star ── Star/pentagram patterns from angular harmonics
def anim_cymatic_star(nx, ny, t, w, h):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    points = 5 + math.sin(t * 0.1) * 2  # 3-7 point star
    # Star shape: angular modulation with sharp peaks
    star = abs(math.cos(points * theta / 2 + t * 0.4))
    star = star ** 0.4  # sharpen the points
    radial = _bessel_j0_approx(r * 10 + t * 0.3)
    v = star * radial
    env = max(0, 1.0 - r * 0.9)
    brightness = min(1.0, abs(v) * 2.5) * env
    return int(brightness * 255)

def audio_cymatic_star(nx, ny, t, w, h, bass, mid, treble):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    points = 3 + bass * 6
    star = abs(math.cos(points * theta / 2)) ** 0.4
    radial = _bessel_j0_approx(r * (6 + mid * 12))
    env = max(0, 1.0 - r * 0.9)
    brightness = min(1.0, abs(star * radial) * 2.5) * env
    return int(brightness * 255)

# ── 14. Cymatic Ripple ── Multiple point sources with interference
def anim_cymatic_ripple(nx, ny, t, w, h):
    v = 0
    # 3 sources orbiting center
    for i in range(3):
        angle = t * 0.3 + i * math.pi * 2 / 3
        sx = 0.5 + math.cos(angle) * 0.2
        sy = 0.5 + math.sin(angle) * 0.2
        d = math.sqrt((nx - sx)**2 + (ny - sy)**2)
        freq = 15 + math.sin(t * 0.1 + i) * 3
        v += math.sin(d * freq * math.pi - t * 2) / 3
    brightness = (v + 1) / 2
    brightness = max(0, min(1, brightness)) ** 0.8
    return int(brightness * 255)

def audio_cymatic_ripple(nx, ny, t, w, h, bass, mid, treble):
    v = 0
    for i in range(3):
        angle = i * math.pi * 2 / 3
        sx = 0.5 + math.cos(angle) * 0.2
        sy = 0.5 + math.sin(angle) * 0.2
        d = math.sqrt((nx - sx)**2 + (ny - sy)**2)
        freq = 8 + bass * 20
        v += math.sin(d * freq * math.pi) / 3
    brightness = max(0, min(1, (v + 1) / 2)) ** 0.8
    return int(brightness * 255)

# ── 15. Cymatic Kaleidoscope ── Angular symmetry with radial modulation
def anim_cymatic_kaleidoscope(nx, ny, t, w, h):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    # Fold theta into a symmetry sector
    segments = 6 + math.sin(t * 0.08) * 2
    folded = abs(((theta / math.pi + 1) * segments / 2) % 2 - 1)
    # Pattern within sector
    inner = math.sin(folded * 8 + r * 10 + t)
    radial = math.cos(r * 6 - t * 0.8)
    v = inner * 0.6 + radial * 0.4
    env = max(0, 1.0 - r * 0.7)
    brightness = max(0, min(1, (v + 1) / 2)) * env
    return int(brightness * 255)

def audio_cymatic_kaleidoscope(nx, ny, t, w, h, bass, mid, treble):
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 2
    theta = math.atan2(dy, dx)
    segments = 4 + bass * 8
    folded = abs(((theta / math.pi + 1) * segments / 2) % 2 - 1)
    inner = math.sin(folded * (5 + mid * 10) + r * (6 + treble * 10))
    radial = math.cos(r * (4 + bass * 8))
    v = inner * 0.6 + radial * 0.4
    env = max(0, 1.0 - r * 0.7)
    brightness = max(0, min(1, (v + 1) / 2)) * env
    return int(brightness * 255)

# ── 16. Cymatic Sand ── Particles accumulate at nodal lines (Chladni sand)
def anim_cymatic_sand(nx, ny, t, w, h):
    # Chladni pattern but inverted — bright at nodal lines (where sand collects)
    phase = t * 0.12
    n = 3 + math.sin(phase) * 2
    m = 4 + math.cos(phase * 0.7) * 2
    x, y = nx * math.pi, ny * math.pi
    v = math.sin(n*x) * math.sin(m*y) - math.sin(m*x) * math.sin(n*y)
    # Invert: nodal lines (v≈0) are BRIGHT (sand collects there)
    closeness = max(0, 1.0 - abs(v) * 4)
    # Add slight granularity (sand texture)
    grain = 0.85 + random.random() * 0.15
    brightness = closeness * grain
    return int(brightness * 255)

def audio_cymatic_sand(nx, ny, t, w, h, bass, mid, treble):
    n = 2 + bass * 6
    m = 3 + mid * 5
    x, y = nx * math.pi, ny * math.pi
    v = math.sin(n*x) * math.sin(m*y) - math.sin(m*x) * math.sin(n*y)
    closeness = max(0, 1.0 - abs(v) * 4)
    grain = 0.85 + random.random() * 0.15
    brightness = closeness * grain
    return int(brightness * 255)


# ═══════════════════════════════════════════════════════════════════════════
# BPM functions — pure metronome: (nx, ny, beat_count, beat_phase, w, h) → 0-255
# beat_count = integer, increments each beat
# beat_phase = 0.0 on the beat, 1.0 just before next beat
# No frequency data — purely driven by BPM metronome
# ═══════════════════════════════════════════════════════════════════════════

def _ease_out(phase):
    """Smooth ease-out: 1.0 at phase=0, 0.0 at phase=1."""
    return max(0.0, 1.0 - phase ** 0.5)

def _ease_pulse(phase):
    """Fast attack, very slow decay — never goes dark.

    phase 0.0 = on beat (brightness 1.0)
    phase 1.0 = just before next beat (brightness ~0.35)
    Uses exponential decay for a long glowing tail.
    """
    # Exponential decay: slow falloff so brightness lingers
    raw = math.exp(-phase * 1.5)  # 1.0 → ~0.22 over one beat
    return 0.30 + 0.70 * raw  # floor 0.30, peak 1.0

def bpm_color_cycle(nx, ny, bc, bp, w, h):
    """One random orb pulses per beat — elegant shifting glow.

    6 fixed orb positions. On each beat, only ONE orb lights up
    (chosen pseudo-randomly by beat count). All orbs have a soft
    ambient glow, but the active one flares bright on the downbeat.
    """
    orbs = [
        (0.20, 0.25),
        (0.80, 0.25),
        (0.35, 0.50),
        (0.65, 0.50),
        (0.25, 0.78),
        (0.75, 0.78),
    ]

    # Which orb is active this beat (pseudo-random, never same twice in a row)
    active = (bc * 3 + bc // 2) % len(orbs)

    pulse = _ease_pulse(bp)
    spread = 0.20

    val = 0.0
    for i, (ox, oy) in enumerate(orbs):
        dx = nx - ox
        dy = ny - oy
        dist_sq = dx * dx + dy * dy
        glow = math.exp(-dist_sq / (2 * spread * spread))

        if i == active:
            # Active orb: bright pulse on beat, soft between
            val += glow * (40 + 215 * pulse)
        else:
            # Inactive orbs: very soft ambient
            val += glow * 25

    return int(max(0, min(255, val)))

def bpm_wave(nx, ny, bc, bp, w, h):
    """Wave steps to new position each beat with glowing hotspots.

    Two wave centers shift each beat. The pattern stays visible
    with ambient glow; the pulse brightens the active hotspots.
    """
    # Two hotspot centers that shift each beat
    cx1 = (math.sin(bc * 1.8) + 1) / 2
    cy1 = (math.cos(bc * 2.3) + 1) / 2
    cx2 = (math.sin(bc * 1.1 + 2) + 1) / 2
    cy2 = (math.cos(bc * 1.5 + 1) + 1) / 2

    # Interference from two sources
    d1 = math.sqrt((nx - cx1)**2 + (ny - cy1)**2)
    d2 = math.sqrt((nx - cx2)**2 + (ny - cy2)**2)
    wave = (math.sin(d1 * 15) + math.sin(d2 * 12) + 2) / 4  # 0 to 1

    pulse = _ease_pulse(bp)
    # Ambient shape always visible, pulse boosts the peaks
    val = wave * (80 + 175 * pulse)
    return int(max(0, min(255, val)))

def bpm_plasma(nx, ny, bc, bp, w, h):
    """Plasma shifts to new state each beat — always visible, pulses brighter.

    The plasma field steps to a new frozen frame each beat.
    Ambient glow keeps the shape visible; downbeat flares it up.
    """
    t = bc * 0.8
    v = (math.sin(nx*10+t) + math.sin(ny*10+t) + math.sin((nx+ny)*10+t) + 4) / 8

    pulse = _ease_pulse(bp)
    # Always visible (ambient 0.3), pulses to full on beat
    val = v * 255 * (0.35 + 0.65 * pulse)
    return int(max(0, min(255, val)))

def bpm_scanner(nx, ny, bc, bp, w, h):
    """Bar jumps to new position each beat."""
    positions = [0.1, 0.25, 0.4, 0.55, 0.7, 0.85]
    scan_x = positions[bc % len(positions)]
    val = max(0, 1 - abs(nx - scan_x) * 8) * 255
    return int(val * _ease_pulse(bp))

def bpm_noise(nx, ny, bc, bp, w, h):
    """Burst of random pixels on beat, dark between."""
    if bp < 0.2:
        return 255 if random.random() > 0.6 else 0
    return 0

def bpm_circle(nx, ny, bc, bp, w, h):
    """Orbit — multiple rings at different radii, pulse bright on beat."""
    dist = math.sqrt((nx - 0.5) ** 2 + (ny - 0.5) ** 2)
    t = bc * 0.6
    rings = (math.sin(dist * 20 - t) + 1) / 2  # ring pattern
    pulse = _ease_pulse(bp)
    val = rings * (80 + 175 * pulse)
    return int(max(0, min(255, val)))

def bpm_digital(nx, ny, bc, bp, w, h):
    """Checkerboard — large squares, toggles each beat, always visible."""
    offset = bc
    val = ((int(nx * 4) + int(ny * 4) + offset) % 2 == 0)
    pulse = _ease_pulse(bp)
    bright = 60 + 195 * pulse if val else 30 + 50 * pulse
    return int(max(0, min(255, bright)))

def bpm_snow(nx, ny, bc, bp, w, h):
    """Snow burst on beat."""
    if bp < 0.25:
        return 255 if random.random() > 0.85 else 0
    return 0

def bpm_cloud(nx, ny, bc, bp, w, h):
    """Nebula intensity pulses on beat."""
    t = bc * 0.3
    val = (math.sin(nx * 5 + t) * math.cos(ny * 5 - t) + 1) / 2
    return int(val * 255 * _ease_pulse(bp))

def bpm_blob(nx, ny, bc, bp, w, h):
    """Lava — organic shapes shift each beat, always visible."""
    t = bc * 0.6
    val = (math.sin(nx*3+t) + math.cos(ny*4+t*0.8) + math.sin(math.sqrt(nx*nx+ny*ny)*5-t) + 3) / 6
    pulse = _ease_pulse(bp)
    bright = val * (80 + 175 * pulse)
    return int(max(0, min(255, bright)))

def bpm_sparkle(nx, ny, bc, bp, w, h):
    """Bright sparkle burst on beat, dark between."""
    if bp < 0.15:
        return 255 if random.random() > 0.5 else 0
    return 0

def bpm_tunnel(nx, ny, bc, bp, w, h):
    """Tunnel zooms in one step per beat."""
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2) + 0.01
    t = bc * 0.8
    val = math.sin(1 / d - t) > 0.3
    return int(255 * val * _ease_pulse(bp))

def bpm_fire(nx, ny, bc, bp, w, h):
    """Fire intensity bursts on beat."""
    t = bc * 0.4
    val = max(0, (math.sin(nx*5+t) * math.cos(ny*2-t*2) + (1-ny)) * 127)
    return int(min(255, val * (0.2 + 0.8 * _ease_pulse(bp))))

def bpm_spiral(nx, ny, bc, bp, w, h):
    """Spiral advances by fixed angle per beat."""
    angle = math.atan2(ny - 0.5, nx - 0.5)
    dist = math.sqrt((nx - 0.5)**2 + (ny - 0.5)**2)
    t = bc * 1.2
    val = 255 if math.sin(angle * 5 + dist * 20 - t) > 0 else 0
    return int(val * _ease_pulse(bp))

def bpm_bands(nx, ny, bc, bp, w, h):
    """Stripes shift one step per beat."""
    offset = bc * 0.2
    val = 255 if math.sin(nx * 20 + offset) > 0.5 else 0
    return int(val * _ease_pulse(bp))

def bpm_twist(nx, ny, bc, bp, w, h):
    """Twister pattern steps per beat."""
    t = bc * 0.5
    val = math.sin(nx * 10 + math.sin(ny * 5 + t) * 5) > 0
    return int(255 * val * _ease_pulse(bp))

def bpm_bounce(nx, ny, bc, bp, w, h):
    """Large glowing orb at different positions each beat, always visible."""
    positions = [(0.2, 0.3), (0.5, 0.7), (0.8, 0.2), (0.3, 0.6), (0.7, 0.5), (0.5, 0.5)]
    cx, cy = positions[bc % len(positions)]
    d = math.sqrt((nx - cx)**2 + (ny - cy)**2)
    glow = math.exp(-d * d / (2 * 0.2 * 0.2))  # wider spread
    pulse = _ease_pulse(bp)
    val = glow * (70 + 185 * pulse) + 25  # ambient floor
    return int(max(0, min(255, val)))

def bpm_gravity(nx, ny, bc, bp, w, h):
    """Particles fall on beat."""
    drop_y = bp * 0.8
    val = max(0, 1 - abs(ny - drop_y) * 8) * (1 if (int(nx * 15 + bc * 3) % 3 == 0) else 0)
    return int(val * 255)

def bpm_tint(nx, ny, bc, bp, w, h):
    """Color field shifts each beat."""
    t = bc * 0.4
    val = (math.sin(nx * 5 + t) * math.sin(ny * 5 + t * 0.5) + 1) * 127
    return int(val * _ease_pulse(bp))

def bpm_flux(nx, ny, bc, bp, w, h):
    """Flow pattern steps per beat."""
    t = bc * 0.3
    val = (math.sin(nx*2+t) + math.sin(ny*3-t) + math.sin(nx+ny+t)) / 3
    return int(max(0, val * 255 * _ease_pulse(bp)))

def bpm_shape(nx, ny, bc, bp, w, h):
    """Diamond grows/shrinks on beat."""
    size = 0.1 + _ease_out(bp) * 0.3
    val = 255 if (abs(nx - 0.5) + abs(ny - 0.5) < size) else 0
    return val

def bpm_pond(nx, ny, bc, bp, w, h):
    """Ripple ring expands from center on each beat."""
    dist = math.sqrt((nx - 0.5)**2 + (ny - 0.5)**2)
    radius = bp * 0.7
    ring = max(0, 1 - abs(dist - radius) * 12)
    return int(ring * 255)

def bpm_trail(nx, ny, bc, bp, w, h):
    """Horizontal trail sweeps per beat."""
    pos = bp
    val = max(0, 1 - abs(nx - pos) * 6)
    return int(val * 255)

def bpm_fade(nx, ny, bc, bp, w, h):
    """Gradient shifts each beat."""
    t = bc * 0.25
    val = ((nx + t) % 1.0) * ((ny + t * 0.5) % 1.0)
    return int(val * 255 * _ease_pulse(bp))

def bpm_helix(nx, ny, bc, bp, w, h):
    """Double helix steps per beat."""
    t = bc * 0.5
    val = abs(math.sin(ny * 10 + t) - nx) < 0.08 or abs(math.cos(ny * 10 + t) - nx) < 0.08
    return int(255 * val * _ease_pulse(bp))

def bpm_laser(nx, ny, bc, bp, w, h):
    """Wide beam at different position each beat, always visible."""
    positions = [0.15, 0.35, 0.5, 0.65, 0.85]
    beam_y = positions[bc % len(positions)]
    dist = abs(ny - beam_y)
    glow = math.exp(-dist * dist / (2 * 0.08 * 0.08))  # wide gaussian beam
    pulse = _ease_pulse(bp)
    val = glow * (60 + 195 * pulse) + 20  # ambient floor
    return int(max(0, min(255, val)))

def bpm_streak(nx, ny, bc, bp, w, h):
    """Comet flies across on beat."""
    pos = bp
    val = max(0, 1 - abs(nx - pos) * 10)
    return int(val * 255)

def bpm_rotary(nx, ny, bc, bp, w, h):
    """Gear steps by fixed angle each beat."""
    t = bc * math.pi / 3
    val = math.sin(math.atan2(ny-0.5, nx-0.5) * 6 + t) > 0.3
    return int(255 * val * _ease_pulse(bp))

def bpm_ang(nx, ny, bc, bp, w, h):
    """Zigzag shifts per beat."""
    t = bc * 0.3
    val = math.sin((nx + ny) * 20 + t) > 0.5
    return int(255 * val * _ease_pulse(bp))

def bpm_zoom(nx, ny, bc, bp, w, h):
    """Wormhole pulses in/out per beat — speaker cone effect."""
    dx, dy = nx - 0.5, ny - 0.5
    d = math.sqrt(dx*dx + dy*dy) + 0.01
    # Scale distance by beat phase: compress on beat, expand between
    scale = 0.5 + _ease_pulse(bp) * 1.5
    val = math.sin(1 / (d * scale)) > 0
    return int(255 * val)

def bpm_flow(nx, ny, bc, bp, w, h):
    """Nebula2 steps per beat."""
    t = bc * 0.4
    val = (math.sin(nx*10+t) + math.cos(ny*10+t)) * 127 + 127
    return int(min(255, val * _ease_pulse(bp)))

def bpm_ocean(nx, ny, bc, bp, w, h):
    """Wave crests on beat."""
    t = bc * 0.3
    val = (math.sin(nx * 5 + t) + math.sin(ny * 2 + t * 0.5)) * 127 + 127
    return int(min(255, val * _ease_pulse(bp)))

def bpm_lens(nx, ny, bc, bp, w, h):
    """Focus spot jumps per beat."""
    cx = 0.3 + (bc % 3) * 0.2
    cy = 0.3 + ((bc // 3) % 3) * 0.2
    d = math.sqrt((nx-cx)**2 + (ny-cy)**2)
    val = max(0, 255 - d * 500)
    return int(val * _ease_out(bp))

def bpm_lavaflow(nx, ny, bc, bp, w, h):
    """Eruption pulses per beat."""
    t = bc * 0.4
    val = (math.sin(nx*4+t) * math.sin(ny*4-t)) * 127 + 127
    return int(min(255, val * _ease_pulse(bp)))

def bpm_rainbow(nx, ny, bc, bp, w, h):
    """Rainbow shifts one step per beat."""
    val = ((nx + ny + bc * 0.15) % 1.0) * 255
    return int(val * _ease_pulse(bp))

def bpm_ghosting(nx, ny, bc, bp, w, h):
    """Ghost pattern steps per beat."""
    t = bc * 0.3
    val = math.sin(nx * 5 - t) * 100 + 155
    return int(max(0, min(255, val * _ease_pulse(bp))))

def bpm_sun(nx, ny, bc, bp, w, h):
    """Radiate pulses outward on beat."""
    d = math.sqrt((nx-0.5)**2 + (ny-0.5)**2)
    # Pulse size grows from center on beat
    radius = _ease_out(bp) * 0.6
    val = max(0, 1.0 - abs(d - radius * 0.3) * 5)
    val += max(0, 1.0 - d * 3) * _ease_pulse(bp)  # center glow
    return int(min(255, val * 255))

def bpm_drift(nx, ny, bc, bp, w, h):
    """Tides shift per beat."""
    t = bc * 0.3
    val = math.sin(nx * 5 + ny * 2 + t) * 127 + 127
    return int(min(255, val * _ease_pulse(bp)))

def bpm_wave3(nx, ny, bc, bp, w, h):
    """Mirage steps per beat."""
    t = bc * 0.3
    val = math.sin(nx * 10 + math.sin(ny * 10 + t)) * 127 + 127
    return int(min(255, val * _ease_pulse(bp)))

# ── Cymatics BPM functions ──

def bpm_chladni(nx, ny, bc, bp, w, h):
    """Chladni pattern switches mode numbers on each beat."""
    modes = [(2, 3), (3, 4), (4, 5), (5, 3), (3, 2), (4, 3), (5, 4), (2, 5)]
    n, m = modes[bc % len(modes)]
    x, y = nx * math.pi, ny * math.pi
    v = math.sin(n*x) * math.sin(m*y) - math.sin(m*x) * math.sin(n*y)
    val = max(0, 1.0 - abs(v) * 3)
    return int(val * 255 * _ease_pulse(bp))

def bpm_resonance(nx, ny, bc, bp, w, h):
    """Resonance pattern switches mode on beat."""
    modes = [2, 3, 4, 5, 6, 3, 5, 4]
    n = modes[bc % len(modes)]
    dx, dy = nx - 0.5, ny - 0.5
    r = math.sqrt(dx*dx + dy*dy) * 10
    theta = math.atan2(dy, dx)
    val = math.cos(n * theta) * math.sin(r)
    return int(max(0, min(255, (val + 1) * 127 * _ease_pulse(bp))))

def bpm_standing(nx, ny, bc, bp, w, h):
    """Standing wave frequency steps per beat."""
    freq = 3 + (bc % 6)
    val = (math.cos(math.sqrt((nx-0.5)**2 + (ny-0.5)**2) * freq * math.pi * 2) + 1) / 2
    return int(val * 255 * _ease_pulse(bp))

def bpm_harmonics(nx, ny, bc, bp, w, h):
    """Harmonics step through overtones per beat."""
    f = 2 + (bc % 5)
    val = 0
    for i in range(1, f + 1):
        val += math.sin(nx * i * 8) * math.cos(ny * i * 8) / i
    val = (val + 1.5) / 3.0
    return int(max(0, min(255, val * 255 * _ease_pulse(bp))))

def bpm_cymatic_generic(nx, ny, bc, bp, w, h):
    """Generic cymatics BPM — mode pattern rotates per beat."""
    n = 2 + (bc % 4)
    m = 3 + ((bc // 4) % 3)
    x, y = nx * math.pi * 2, ny * math.pi * 2
    v = math.sin(n*x) * math.cos(m*y)
    return int(max(0, min(255, (v + 1) * 127 * _ease_pulse(bp))))


# ─── Pattern Registry ──────────────────────────────────────────────────────
# Each pattern: name, fn (default), audio_fn (sound-driven), bpm_fn (metronome-only)
# Backward compat: ANIMATIONS is an alias for PATTERNS

PATTERNS = [
    # ── BPM-first test pattern ──
    {"name": "Color Cycle",  "fn": anim_tint,      "audio_fn": audio_tint,     "bpm_fn": bpm_color_cycle},
    # ── Core patterns ──
    {"name": "Interference", "fn": anim_wave,     "audio_fn": audio_wave,     "bpm_fn": bpm_wave},
    {"name": "Plasma",       "fn": anim_plasma,    "audio_fn": audio_plasma,   "bpm_fn": bpm_plasma},
    {"name": "Scanner",      "fn": anim_scanner,   "audio_fn": audio_scanner,  "bpm_fn": bpm_scanner},
    {"name": "Orbit",        "fn": anim_circle,    "audio_fn": audio_circle,   "bpm_fn": bpm_circle},
    {"name": "Matrix",       "fn": anim_digital,   "audio_fn": audio_digital,  "bpm_fn": bpm_digital},
    {"name": "Nebula",       "fn": anim_cloud,     "audio_fn": audio_cloud,    "bpm_fn": bpm_cloud},
    {"name": "Lava",         "fn": anim_blob,      "audio_fn": audio_blob,     "bpm_fn": bpm_blob},
    {"name": "Tunnel",       "fn": anim_tunnel,    "audio_fn": audio_tunnel,   "bpm_fn": bpm_tunnel},
    {"name": "Bonfire",      "fn": anim_fire,      "audio_fn": audio_fire,     "bpm_fn": bpm_fire},
    {"name": "Vortex",       "fn": anim_spiral,    "audio_fn": audio_spiral,   "bpm_fn": bpm_spiral},
    {"name": "Stripes",      "fn": anim_bands,     "audio_fn": audio_bands,    "bpm_fn": bpm_bands},
    {"name": "Twister",      "fn": anim_twist,     "audio_fn": audio_twist,    "bpm_fn": bpm_twist},
    {"name": "Bouncer",      "fn": anim_bounce,    "audio_fn": audio_bounce,   "bpm_fn": bpm_bounce},
    {"name": "Falling",      "fn": anim_gravity,   "audio_fn": audio_gravity,  "bpm_fn": bpm_gravity},
    {"name": "Prism",        "fn": anim_tint,      "audio_fn": audio_tint,     "bpm_fn": bpm_tint},
    {"name": "Flow",         "fn": anim_flux,      "audio_fn": audio_flux,     "bpm_fn": bpm_flux},
    {"name": "Diamond",      "fn": anim_shape,     "audio_fn": audio_shape,    "bpm_fn": bpm_shape},
    {"name": "Ripple",       "fn": anim_pond,      "audio_fn": audio_pond,     "bpm_fn": bpm_pond},
    {"name": "Echo",         "fn": anim_trail,     "audio_fn": audio_trail,    "bpm_fn": bpm_trail},
    {"name": "Ghost",        "fn": anim_fade,      "audio_fn": audio_fade,     "bpm_fn": bpm_fade},
    {"name": "DNA",          "fn": anim_helix,     "audio_fn": audio_helix,    "bpm_fn": bpm_helix},
    {"name": "Beams",        "fn": anim_laser,     "audio_fn": audio_laser,    "bpm_fn": bpm_laser},
    {"name": "Comet",        "fn": anim_streak,    "audio_fn": audio_streak,   "bpm_fn": bpm_streak},
    {"name": "Gear",         "fn": anim_rotary,    "audio_fn": audio_rotary,   "bpm_fn": bpm_rotary},
    {"name": "ZigZag",       "fn": anim_ang,       "audio_fn": audio_ang,      "bpm_fn": bpm_ang},
    {"name": "Wormhole",     "fn": anim_zoom,      "audio_fn": audio_zoom,     "bpm_fn": bpm_zoom},
    {"name": "Nebula2",      "fn": anim_flow,      "audio_fn": audio_flow,     "bpm_fn": bpm_flow},
    {"name": "Waves",        "fn": anim_ocean,     "audio_fn": audio_ocean,    "bpm_fn": bpm_ocean},
    {"name": "Focus",        "fn": anim_lens,      "audio_fn": audio_lens,     "bpm_fn": bpm_lens},
    {"name": "Eruption",     "fn": anim_lavaflow,  "audio_fn": audio_lavaflow, "bpm_fn": bpm_lavaflow},
    {"name": "Prism2",       "fn": anim_rainbow,   "audio_fn": audio_rainbow,  "bpm_fn": bpm_rainbow},
    {"name": "Echoes",       "fn": anim_ghosting,  "audio_fn": audio_ghosting, "bpm_fn": bpm_ghosting},
    {"name": "Radiate",      "fn": anim_sun,       "audio_fn": audio_sun,      "bpm_fn": bpm_sun},
    {"name": "Tides",        "fn": anim_drift,     "audio_fn": audio_drift,    "bpm_fn": bpm_drift},
    {"name": "Mirage",       "fn": anim_wave3,     "audio_fn": audio_wave3,    "bpm_fn": bpm_wave3},
    # ── Cymatics ──
    {"name": "Chladni",      "fn": anim_chladni,            "audio_fn": audio_chladni,            "bpm_fn": bpm_chladni},
    {"name": "Resonance",    "fn": anim_resonance,          "audio_fn": audio_resonance,          "bpm_fn": bpm_resonance},
    {"name": "Standing Wave","fn": anim_standing,            "audio_fn": audio_standing,           "bpm_fn": bpm_standing},
    {"name": "Harmonics",    "fn": anim_harmonics,           "audio_fn": audio_harmonics,          "bpm_fn": bpm_harmonics},
    {"name": "Cells",        "fn": anim_cymatic_interference,"audio_fn": audio_cymatic_interference,"bpm_fn": bpm_cymatic_generic},
    {"name": "Bloom",        "fn": anim_cymatic_bloom,       "audio_fn": audio_cymatic_bloom,      "bpm_fn": bpm_cymatic_generic},
    {"name": "Pulse Rings", "fn": anim_cymatic_pulse,       "audio_fn": audio_cymatic_pulse,      "bpm_fn": bpm_cymatic_generic},
    {"name": "Web",         "fn": anim_cymatic_web,         "audio_fn": audio_cymatic_web,        "bpm_fn": bpm_cymatic_generic},
    {"name": "Lotus",       "fn": anim_cymatic_lotus,       "audio_fn": audio_cymatic_lotus,      "bpm_fn": bpm_cymatic_generic},
    {"name": "Fractal",     "fn": anim_cymatic_fractal,     "audio_fn": audio_cymatic_fractal,    "bpm_fn": bpm_cymatic_generic},
    {"name": "Vortex 2",    "fn": anim_cymatic_vortex,      "audio_fn": audio_cymatic_vortex,     "bpm_fn": bpm_cymatic_generic},
    {"name": "Grid",        "fn": anim_cymatic_grid,        "audio_fn": audio_cymatic_grid,       "bpm_fn": bpm_cymatic_generic},
    {"name": "Star",        "fn": anim_cymatic_star,        "audio_fn": audio_cymatic_star,       "bpm_fn": bpm_cymatic_generic},
    {"name": "Multi Ripple","fn": anim_cymatic_ripple,      "audio_fn": audio_cymatic_ripple,     "bpm_fn": bpm_cymatic_generic},
    {"name": "Kaleidoscope","fn": anim_cymatic_kaleidoscope,"audio_fn": audio_cymatic_kaleidoscope,"bpm_fn": bpm_cymatic_generic},
    {"name": "Sand",        "fn": anim_cymatic_sand,        "audio_fn": audio_cymatic_sand,       "bpm_fn": bpm_cymatic_generic},
]

# Backward compatibility alias
ANIMATIONS = PATTERNS
