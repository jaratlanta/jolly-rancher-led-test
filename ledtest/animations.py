"""
Visual animations ported from the /jollyrancher Three.js project.
Each animation is a function: (nx, ny, time) -> brightness 0-255
where nx, ny are normalized 0..1 coordinates.

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


# ─── Animation Registry ─────────────────────────────────────────────────────

ANIMATIONS = [
    {"name": "Interference", "fn": anim_wave},
    {"name": "Plasma",       "fn": anim_plasma},
    {"name": "Scanner",      "fn": anim_scanner},
    {"name": "Rain",         "fn": anim_rain},
    {"name": "Pixels",       "fn": anim_noise},
    {"name": "Hyperdrive",   "fn": anim_stars},
    {"name": "Orbit",        "fn": anim_circle},
    {"name": "Pulse",        "fn": anim_pulse},
    {"name": "Matrix",       "fn": anim_digital},
    {"name": "Blizzard",     "fn": anim_snow},
    {"name": "Nebula",       "fn": anim_cloud},
    {"name": "Lava",         "fn": anim_blob},
    {"name": "Sparkle",      "fn": anim_sparkle},
    {"name": "Tunnel",       "fn": anim_tunnel},
    {"name": "Bonfire",      "fn": anim_fire},
    {"name": "Lightning",    "fn": anim_bolt},
    {"name": "Vortex",       "fn": anim_spiral},
    {"name": "Stripes",      "fn": anim_bands},
    {"name": "Checker",      "fn": anim_grid},
    {"name": "Radar",        "fn": anim_sweep},
    {"name": "Twister",      "fn": anim_twist},
    {"name": "Bouncer",      "fn": anim_bounce},
    {"name": "Falling",      "fn": anim_gravity},
    {"name": "Zebra",        "fn": anim_stripe2},
    {"name": "Glitch",       "fn": anim_glitch},
    {"name": "Mirror",       "fn": anim_kaleido},
    {"name": "Prism",        "fn": anim_tint},
    {"name": "Flow",         "fn": anim_flux},
    {"name": "Zenith",       "fn": anim_top},
    {"name": "Horizon",      "fn": anim_side},
    {"name": "Cells",        "fn": anim_voronoi},
    {"name": "Bloom",        "fn": anim_glow},
    {"name": "Spark",        "fn": anim_point},
    {"name": "Strobe",       "fn": anim_flash},
    {"name": "Cross",        "fn": anim_sweep2},
    {"name": "Diamond",      "fn": anim_shape},
    {"name": "Ripple",       "fn": anim_pond},
    {"name": "Echo",         "fn": anim_trail},
    {"name": "Quartz",       "fn": anim_crystal},
    {"name": "Ghost",        "fn": anim_fade},
    {"name": "DNA",          "fn": anim_helix},
    {"name": "Wavelet",      "fn": anim_sinus},
    {"name": "Beams",        "fn": anim_laser},
    {"name": "Comet",        "fn": anim_streak},
    {"name": "Bubble",       "fn": anim_float},
    {"name": "Swarm",        "fn": anim_boids},
    {"name": "Clock",        "fn": anim_time},
    {"name": "Gear",         "fn": anim_rotary},
    {"name": "Pulse2",       "fn": anim_heart},
    {"name": "ZigZag",       "fn": anim_ang},
    {"name": "Static",       "fn": anim_fuzz},
    {"name": "Scanline",     "fn": anim_crt},
    {"name": "Wormhole",     "fn": anim_zoom},
    {"name": "Nebula2",      "fn": anim_flow},
    {"name": "Particles",    "fn": anim_dust},
    {"name": "Fireworks",    "fn": anim_pop},
    {"name": "Waves",        "fn": anim_ocean},
    {"name": "Binary",       "fn": anim_bits},
    {"name": "Aurora2",      "fn": anim_sky},
    {"name": "Circuit",      "fn": anim_tech},
    {"name": "Glitch2",      "fn": anim_shiver},
    {"name": "Focus",        "fn": anim_lens},
    {"name": "Phase",        "fn": anim_shift},
    {"name": "Eruption",     "fn": anim_lavaflow},
    {"name": "Prism2",       "fn": anim_rainbow},
    {"name": "Spiral2",      "fn": anim_twist2},
    {"name": "Echoes",       "fn": anim_ghosting},
    {"name": "Radiate",      "fn": anim_sun},
    {"name": "Pixels2",      "fn": anim_block},
    {"name": "Tides",        "fn": anim_drift},
    {"name": "Signals",      "fn": anim_ping},
    {"name": "Grid2",        "fn": anim_wire},
    {"name": "Cyber",        "fn": anim_run},
    {"name": "Static2",      "fn": anim_grain},
    {"name": "Mirage",       "fn": anim_wave3},
    {"name": "Orbit2",       "fn": anim_moon},
    {"name": "Flow2",        "fn": anim_wind},
    {"name": "Pulse3",       "fn": anim_beat},
    {"name": "Rain2",        "fn": anim_storm},
    {"name": "Bolt2",        "fn": anim_shock},
    {"name": "Void2",        "fn": anim_dark},
    {"name": "Star2",        "fn": anim_nova},
    {"name": "Pulse4",       "fn": anim_breath},
    {"name": "Warp",         "fn": anim_speed},
    {"name": "Glitch3",      "fn": anim_digital2},
    {"name": "Neon",         "fn": anim_glow2},
    {"name": "Synth",        "fn": anim_retro},
    {"name": "Flicker",      "fn": anim_candle},
    {"name": "Beam2",        "fn": anim_shaft},
    {"name": "Aura3",        "fn": anim_halo},
]
