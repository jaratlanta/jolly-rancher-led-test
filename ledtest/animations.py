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
]


def palette_color(brightness, palette_idx):
    """Map a brightness value (0-255) to an RGB tuple using a palette.

    Palette has 3 colors: [highlight, mid, shadow].
    The palette sets the hue, and the brightness value scales the overall
    intensity so that 0 = truly black (LEDs off).
    """
    pal = PALETTES[palette_idx % len(PALETTES)]
    colors = pal["colors"]
    b = max(0.0, min(1.0, brightness / 255.0))

    # Map brightness to palette color (hue selection)
    if b <= 0.5:
        t = b * 2.0
        c0, c1 = colors[2], colors[1]
    else:
        t = (b - 0.5) * 2.0
        c0, c1 = colors[1], colors[0]

    r = c0[0] + (c1[0] - c0[0]) * t
    g = c0[1] + (c1[1] - c0[1]) * t
    b_ch = c0[2] + (c1[2] - c0[2]) * t

    # Scale by brightness so 0 = black (LEDs fully off)
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
    v = (math.sin(nx*2+t) + math.sin(ny*3-t) + math.sin(nx+ny+t)) / 3 * 255
    return int(max(0, min(255, v)))

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
    return int(max(0, (1 - d*4) * 255 * max(0, math.sin(t))))

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


# ─── Pattern Registry ──────────────────────────────────────────────────────
# Each pattern has: name, default fn (auto-movement), audio_fn (sound-driven)
# Backward compat: ANIMATIONS is an alias for PATTERNS

PATTERNS = [
    {"name": "Interference", "fn": anim_wave,     "audio_fn": audio_wave},
    {"name": "Plasma",       "fn": anim_plasma,    "audio_fn": audio_plasma},
    {"name": "Scanner",      "fn": anim_scanner,   "audio_fn": audio_scanner},
    {"name": "Pixels",       "fn": anim_noise,     "audio_fn": audio_noise},
    {"name": "Orbit",        "fn": anim_circle,    "audio_fn": audio_circle},
    {"name": "Matrix",       "fn": anim_digital,   "audio_fn": audio_digital},
    {"name": "Blizzard",     "fn": anim_snow,      "audio_fn": audio_snow},
    {"name": "Nebula",       "fn": anim_cloud,     "audio_fn": audio_cloud},
    {"name": "Lava",         "fn": anim_blob,      "audio_fn": audio_blob},
    {"name": "Sparkle",      "fn": anim_sparkle,   "audio_fn": audio_sparkle},
    {"name": "Tunnel",       "fn": anim_tunnel,    "audio_fn": audio_tunnel},
    {"name": "Bonfire",      "fn": anim_fire,      "audio_fn": audio_fire},
    {"name": "Vortex",       "fn": anim_spiral,    "audio_fn": audio_spiral},
    {"name": "Stripes",      "fn": anim_bands,     "audio_fn": audio_bands},
    {"name": "Twister",      "fn": anim_twist,     "audio_fn": audio_twist},
    {"name": "Bouncer",      "fn": anim_bounce,    "audio_fn": audio_bounce},
    {"name": "Falling",      "fn": anim_gravity,   "audio_fn": audio_gravity},
    {"name": "Prism",        "fn": anim_tint,      "audio_fn": audio_tint},
    {"name": "Flow",         "fn": anim_flux,      "audio_fn": audio_flux},
    {"name": "Diamond",      "fn": anim_shape,     "audio_fn": audio_shape},
    {"name": "Ripple",       "fn": anim_pond,      "audio_fn": audio_pond},
    {"name": "Echo",         "fn": anim_trail,     "audio_fn": audio_trail},
    {"name": "Ghost",        "fn": anim_fade,      "audio_fn": audio_fade},
    {"name": "DNA",          "fn": anim_helix,     "audio_fn": audio_helix},
    {"name": "Beams",        "fn": anim_laser,     "audio_fn": audio_laser},
    {"name": "Comet",        "fn": anim_streak,    "audio_fn": audio_streak},
    {"name": "Gear",         "fn": anim_rotary,    "audio_fn": audio_rotary},
    {"name": "ZigZag",       "fn": anim_ang,       "audio_fn": audio_ang},
    {"name": "Wormhole",     "fn": anim_zoom,      "audio_fn": audio_zoom},
    {"name": "Nebula2",      "fn": anim_flow,      "audio_fn": audio_flow},
    {"name": "Waves",        "fn": anim_ocean,     "audio_fn": audio_ocean},
    {"name": "Focus",        "fn": anim_lens,      "audio_fn": audio_lens},
    {"name": "Eruption",     "fn": anim_lavaflow,  "audio_fn": audio_lavaflow},
    {"name": "Prism2",       "fn": anim_rainbow,   "audio_fn": audio_rainbow},
    {"name": "Echoes",       "fn": anim_ghosting,  "audio_fn": audio_ghosting},
    {"name": "Radiate",      "fn": anim_sun,       "audio_fn": audio_sun},
    {"name": "Tides",        "fn": anim_drift,     "audio_fn": audio_drift},
    {"name": "Mirage",       "fn": anim_wave3,     "audio_fn": audio_wave3},
]

# Backward compatibility alias
ANIMATIONS = PATTERNS
