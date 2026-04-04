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

        # Persistent state — existing FX
        self._trail_buffer = np.zeros((height, width, 3), dtype=np.float32)
        self._trail_hue_shift = np.zeros((height, width), dtype=np.float32)
        self._ripple_buf1 = np.zeros((height, width), dtype=np.float32)
        self._ripple_buf2 = np.zeros((height, width), dtype=np.float32)
        self._ripple_energy = np.zeros((height, width), dtype=np.float32)
        self._prev_frame = None
        self._glow_accum = np.zeros((height, width, 3), dtype=np.float32)
        self._time = 0.0

        # Phosphor FX state
        self._phosphor_buffer = np.zeros((height, width, 3), dtype=np.float32)
        self._phosphor_age = np.zeros((height, width), dtype=np.float32)

    def reset(self):
        """Clear all FX state buffers."""
        self._trail_buffer[:] = 0
        self._trail_hue_shift[:] = 0
        self._ripple_buf1[:] = 0
        self._ripple_buf2[:] = 0
        self._ripple_energy[:] = 0
        self._prev_frame = None
        self._glow_accum[:] = 0
        self._phosphor_buffer[:] = 0
        self._phosphor_age[:] = 0

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

    # ── Energy injection: 3 continuous sources keep ripple alive forever ──

    bright = f.max(axis=2)

    # 1. Motion detection (big burst on pattern switch, smaller during animation)
    if engine._prev_frame is not None:
        diff = np.abs(f.mean(axis=2) - engine._prev_frame.astype(np.float32).mean(axis=2))
        motion_mask = diff > 10
        engine._ripple_buf1[motion_mask] += diff[motion_mask] * 0.08 * strength

    # 2. Edge energy — where bright meets dark creates "surface tension".
    #    Keeps ripple alive permanently along animation edges.
    grad_bx = np.zeros((h, w), dtype=np.float32)
    grad_by = np.zeros((h, w), dtype=np.float32)
    grad_bx[:, 1:-1] = bright[:, 2:] - bright[:, :-2]
    grad_by[1:-1, :] = bright[2:, :] - bright[:-2, :]
    edge_energy = np.sqrt(grad_bx**2 + grad_by**2) / 255.0
    # Gentler continuous injection (reduced from 0.12)
    engine._ripple_buf1 += edge_energy * 0.04 * strength

    # 3. Sparse random drops at bright areas
    bright_ys, bright_xs = np.where(bright > 80)
    if len(bright_ys) > 0:
        num_drops = max(1, int(1 + engine.intensity * 2))  # 1-3 drops (was 3-8)
        indices = np.random.choice(len(bright_ys), min(num_drops, len(bright_ys)), replace=False)
        for idx in indices:
            dy, dx = int(bright_ys[idx]), int(bright_xs[idx])
            engine._ripple_buf1[dy, dx] += (0.2 + engine.intensity * 0.3) * strength

    # Propagate wave equation (vectorized for speed)
    # wave[y,x] = avg(neighbors) * 2 - prev[y,x], with damping
    damping = 0.96 - engine.intensity * 0.03  # 0.96 to 0.93 (higher = longer sustain)
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

    # Saturation-preserving brightness modulation:
    # Scale brightness up/down, then re-normalize to prevent clipping desaturation
    edge_strength = np.sqrt(grad_x**2 + grad_y**2)
    edge_boost = np.clip(edge_strength * 8 * strength, 0, 2.0)
    trough_dim = np.clip(-ripple * 4 * strength, 0, 0.5)

    brightness_mod = (1.0 + edge_boost - trough_dim)[:, :, np.newaxis]
    result *= brightness_mod

    # Re-normalize: if any channel exceeds 255, scale whole pixel down
    max_ch = result.max(axis=2, keepdims=True)
    overflow = np.where(max_ch > 255, 255.0 / np.maximum(max_ch, 1), 1.0)
    result *= overflow

    return np.clip(result, 0, 255).astype(np.uint8)


# ─── FX: Liquid ──────────────────────────────────────────────────────────────

def fx_liquid(engine, frame, dt):
    """Glowing water — motion injects luminous dye that diffuses outward and
    fades, like ink spreading through illuminated water.

    Each frame, motion areas inject color into the dye buffer. The dye then
    diffuses via neighbor averaging (spreading outward) while slowly fading.
    The result is soft organic halos that bleed outward from any movement.
    """
    f = frame.astype(np.float32)
    strength = 0.5 + engine.intensity * 2.0

    # Detect motion
    if engine._prev_frame is not None:
        diff = np.abs(f - engine._prev_frame.astype(np.float32))
        motion = diff.max(axis=2)
        motion_mask = motion > 12

        # Inject dye where motion occurs — use the frame color
        inject = f * motion_mask[:, :, np.newaxis] * 0.15 * strength
        engine._liquid_dye += inject

    # Also inject from bright pixels (subtle, so animations feed the liquid)
    bright = f.max(axis=2)
    bright_mask = (bright > 100)[:, :, np.newaxis].astype(np.float32)
    engine._liquid_dye += f * bright_mask * 0.008 * strength

    # Diffuse: each pixel averages with neighbors (spread outward)
    diffuse_passes = 1 + int(engine.intensity * 2)
    for _ in range(diffuse_passes):
        padded = np.pad(engine._liquid_dye, ((1, 1), (1, 1), (0, 0)), mode='edge')
        engine._liquid_dye = (
            padded[:-2, 1:-1] + padded[2:, 1:-1] +
            padded[1:-1, :-2] + padded[1:-1, 2:] +
            padded[1:-1, 1:-1] * 2
        ) / 6.0

    # Fade the dye
    fade_rate = 0.92 + engine.intensity * 0.06  # 0.92 to 0.98
    engine._liquid_dye *= fade_rate

    # Cap dye brightness
    engine._liquid_dye = np.clip(engine._liquid_dye, 0, 300)

    # Combine: original + glowing dye halo
    result = f + engine._liquid_dye * 0.8

    return np.clip(result, 0, 255).astype(np.uint8)


# ─── FX: Echo Rings ──────────────────────────────────────────────────────────

def fx_echo_rings(engine, frame, dt):
    """Stones in a pond — motion spawns expanding concentric rings that
    radiate outward with fading amplitude. Multiple ring sources interfere
    to create beautiful overlapping patterns.
    """
    f = frame.astype(np.float32)
    h, w = engine.height, engine.width
    strength = 0.5 + engine.intensity * 2.0
    t = engine._time

    # Detect motion to spawn new ring sources
    if engine._prev_frame is not None:
        diff = np.abs(f.mean(axis=2) - engine._prev_frame.astype(np.float32).mean(axis=2))

        # Decay cooldown
        engine._echo_cooldown = np.maximum(0, engine._echo_cooldown - dt)

        # Find strong motion points not on cooldown
        candidates = (diff > 25) & (engine._echo_cooldown < 0.01)
        if candidates.any():
            # Sample up to 3 new ring sources per frame
            ys, xs = np.where(candidates)
            if len(ys) > 3:
                indices = np.random.choice(len(ys), 3, replace=False)
                ys, xs = ys[indices], xs[indices]
            for cy, cx in zip(ys, xs):
                s = float(diff[cy, cx]) / 255.0
                engine._echo_rings.append((float(cy), float(cx), t, s * strength))
                # Set cooldown in neighborhood to avoid ring spam
                y_lo = max(0, cy - 2)
                y_hi = min(h, cy + 3)
                x_lo = max(0, cx - 2)
                x_hi = min(w, cx + 3)
                engine._echo_cooldown[y_lo:y_hi, x_lo:x_hi] = 0.3

    # Prune old rings (max age 4 seconds)
    engine._echo_rings = [(cy, cx, bt, s) for cy, cx, bt, s in engine._echo_rings
                          if t - bt < 4.0]
    # Cap total ring count
    if len(engine._echo_rings) > 40:
        engine._echo_rings = engine._echo_rings[-40:]

    # Render rings into a displacement/brightness field
    ring_field = np.zeros((h, w), dtype=np.float32)
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing='ij')

    for cy, cx, birth, s in engine._echo_rings:
        age = t - birth
        radius = age * (6.0 + engine.intensity * 8.0)  # expansion speed
        decay = math.exp(-age * 1.2)  # rings fade over time
        dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
        # Ring shape: sin wave with thickness
        ring = np.sin((dist - radius) * 2.0) * decay * s
        # Only show near the ring edge
        ring *= np.exp(-((dist - radius) ** 2) / (2.0 + age * 0.5))
        ring_field += ring

    # Apply ring field as brightness modulation
    ring_boost = ring_field[:, :, np.newaxis] * 80 * strength
    result = f + ring_boost

    # Also add subtle displacement for refraction effect
    grad_x = np.zeros((h, w), dtype=np.float32)
    grad_y = np.zeros((h, w), dtype=np.float32)
    grad_x[:, 1:-1] = ring_field[:, 2:] - ring_field[:, :-2]
    grad_y[1:-1, :] = ring_field[2:, :] - ring_field[:-2, :]

    disp = 0.5 + engine.intensity * 1.5
    src_x = np.clip((xx + grad_x * disp).astype(int), 0, w - 1)
    src_y = np.clip((yy + grad_y * disp).astype(int), 0, h - 1)
    result = result[src_y, src_x]

    return np.clip(result, 0, 255).astype(np.uint8)


# ─── FX: Phosphor ────────────────────────────────────────────────────────────

def fx_phosphor(engine, frame, dt):
    """CRT burn-in — bright areas persist with very long decay, shifting to
    warm amber/green as they age. Creates layered ghostly afterimages where
    you see several seconds of animation history simultaneously.
    """
    f = frame.astype(np.float32)
    strength = 0.5 + engine.intensity * 1.5

    # Stamp new bright pixels into the phosphor buffer
    current_brightness = f.max(axis=2)
    buffer_brightness = engine._phosphor_buffer.max(axis=2)

    # Pixels brighter than what's in the buffer get stamped
    new_pixels = current_brightness > buffer_brightness * 0.7
    engine._phosphor_buffer[new_pixels] = f[new_pixels] * 0.9

    # Also always blend in current frame weakly (keeps buffer alive)
    engine._phosphor_buffer = np.maximum(
        engine._phosphor_buffer * (0.95 + engine.intensity * 0.04),  # slow decay
        f * 0.15
    )

    # Age tracking
    engine._phosphor_age += dt
    engine._phosphor_age[new_pixels] = 0  # reset age for fresh pixels

    # Apply color shift: warm amber → green as phosphor ages
    aged = engine._phosphor_buffer.copy()
    age_factor = np.clip(engine._phosphor_age * 0.3, 0, 1)

    # Shift toward amber/green: boost green, warm red, reduce blue
    aged[:, :, 0] *= (1.0 - age_factor * 0.3)   # red dims slightly
    aged[:, :, 1] *= (1.0 + age_factor * 0.4)    # green boosts (phosphor glow)
    aged[:, :, 2] *= (1.0 - age_factor * 0.7)    # blue fades fast

    # Combine: current frame + phosphor afterimage
    result = np.maximum(f, aged * strength * 0.7)

    # Add a subtle scanline flicker for CRT feel
    scanline = np.ones((engine.height, 1, 1), dtype=np.float32)
    scanline[::2] = 0.92  # every other row slightly dimmer
    result *= scanline

    return np.clip(result, 0, 255).astype(np.uint8)


# ─── FX: Smear ───────────────────────────────────────────────────────────────

def fx_smear(engine, frame, dt):
    """Finger painting — detects motion direction and smears pixels along
    that vector. Creates dynamic directional streaks that follow the flow
    of animation movement, like dragging paint across a canvas.
    """
    f = frame.astype(np.float32)
    h, w = engine.height, engine.width
    strength = 0.5 + engine.intensity * 2.0

    if engine._prev_frame is not None:
        prev = engine._prev_frame.astype(np.float32)
        diff = f - prev
        motion_mag = np.sqrt((diff ** 2).mean(axis=2))

        # Compute motion direction using brightness centroid shift
        curr_bright = f.mean(axis=2)
        prev_bright = prev.mean(axis=2)

        # Horizontal motion: compare shifted versions
        vx = np.zeros((h, w), dtype=np.float32)
        vy = np.zeros((h, w), dtype=np.float32)
        vx[:, 1:-1] = curr_bright[:, 2:] - curr_bright[:, :-2] - (prev_bright[:, 2:] - prev_bright[:, :-2])
        vy[1:-1, :] = curr_bright[2:, :] - curr_bright[:-2, :] - (prev_bright[2:, :] - prev_bright[:-2, :])

        # Smooth the velocity field
        engine._motion_vx = engine._motion_vx * 0.6 + vx * 0.4
        engine._motion_vy = engine._motion_vy * 0.6 + vy * 0.4

    # Build smear by displacing pixels along the motion vectors
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing='ij')
    smear_scale = strength * 2.0

    src_x = np.clip((xx - engine._motion_vx * smear_scale).astype(int), 0, w - 1)
    src_y = np.clip((yy - engine._motion_vy * smear_scale).astype(int), 0, h - 1)

    smeared = f[src_y, src_x]

    # Accumulate smear over time for longer streaks
    decay = 0.7 + engine.intensity * 0.25
    engine._smear_buffer = engine._smear_buffer * decay + smeared * (1 - decay)

    # Blend: current frame dominant, smear fills in behind
    motion_amount = np.sqrt(engine._motion_vx ** 2 + engine._motion_vy ** 2)
    blend = np.clip(motion_amount * 0.5, 0, 0.8)[:, :, np.newaxis]

    result = f * (1 - blend * 0.5) + engine._smear_buffer * blend

    return np.clip(result, 0, 255).astype(np.uint8)


# ─── FX: Fireflies ───────────────────────────────────────────────────────────

def fx_fireflies(engine, frame, dt):
    """Disturbed particles — motion and brightness spawn small glowing particles
    that drift with slight randomness and fade over time. Like fireflies
    disturbed from rest, each carrying the color from where it spawned.
    """
    f = frame.astype(np.float32)
    h, w = engine.height, engine.width
    strength = 0.5 + engine.intensity * 1.5

    # Spawn new fireflies from motion areas
    if engine._prev_frame is not None:
        diff = np.abs(f - engine._prev_frame.astype(np.float32))
        motion = diff.max(axis=2)

        # Find hot spots
        hot_ys, hot_xs = np.where(motion > 30)
        if len(hot_ys) > 0:
            # Spawn up to 8 fireflies per frame
            count = min(8, len(hot_ys))
            indices = np.random.choice(len(hot_ys), count, replace=False)
            for idx in indices:
                py, px = int(hot_ys[idx]), int(hot_xs[idx])
                r, g, b = f[py, px]
                # Brighten the color
                boost = 1.5
                r, g, b = min(255, r * boost), min(255, g * boost), min(255, b * boost)
                # Random velocity (slow drift)
                vy = (np.random.random() - 0.5) * 1.5
                vx = (np.random.random() - 0.5) * 1.5
                max_life = 1.5 + np.random.random() * 2.5 * (0.5 + engine.intensity)
                engine._fireflies.append([
                    float(py), float(px), vy, vx,
                    float(r), float(g), float(b),
                    0.0, max_life
                ])

    # Also spawn from bright areas (less frequently)
    bright = f.max(axis=2)
    bright_ys, bright_xs = np.where(bright > 160)
    if len(bright_ys) > 0 and np.random.random() < 0.3:
        count = min(3, len(bright_ys))
        indices = np.random.choice(len(bright_ys), count, replace=False)
        for idx in indices:
            py, px = int(bright_ys[idx]), int(bright_xs[idx])
            r, g, b = f[py, px]
            vy = (np.random.random() - 0.5) * 0.8
            vx = (np.random.random() - 0.5) * 0.8
            max_life = 2.0 + np.random.random() * 2.0
            engine._fireflies.append([
                float(py), float(px), vy, vx,
                float(r), float(g), float(b),
                0.0, max_life
            ])

    # Cap total fireflies
    if len(engine._fireflies) > 200:
        engine._fireflies = engine._fireflies[-200:]

    # Update and render fireflies
    engine._firefly_buffer *= 0.85  # fade old renders

    alive = []
    for fly in engine._fireflies:
        py, px, vy, vx, r, g, b, life, max_life = fly
        life += dt
        if life >= max_life:
            continue

        # Update position with drift + slight random jitter
        py += vy * dt * 3
        px += vx * dt * 3
        vy += (np.random.random() - 0.5) * 0.3 * dt
        vx += (np.random.random() - 0.5) * 0.3 * dt

        # Wrap around edges
        py = py % h
        px = px % w

        # Brightness based on life curve: fade in quickly, fade out slowly
        life_frac = life / max_life
        if life_frac < 0.1:
            alpha = life_frac / 0.1
        else:
            alpha = 1.0 - ((life_frac - 0.1) / 0.9) ** 0.5

        alpha *= strength

        # Render to buffer (with soft glow — hit neighboring pixels too)
        iy, ix = int(py) % h, int(px) % w
        glow_val = np.array([r, g, b], dtype=np.float32) * alpha
        engine._firefly_buffer[iy, ix] = np.maximum(engine._firefly_buffer[iy, ix], glow_val)

        # Adjacent pixels (softer glow halo)
        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ny, nx = (iy + dy) % h, (ix + dx) % w
            engine._firefly_buffer[ny, nx] = np.maximum(
                engine._firefly_buffer[ny, nx], glow_val * 0.4
            )

        fly[0], fly[1], fly[2], fly[3], fly[7] = py, px, vy, vx, life
        alive.append(fly)

    engine._fireflies = alive

    # Combine: original + firefly overlay
    result = f + engine._firefly_buffer

    return np.clip(result, 0, 255).astype(np.uint8)


# ─── Ripple Variants ──────────────────────────────────────────────────────

def _ripple_core(engine, frame, dt, damping, edge_mult_scale, trough_scale,
                 inject_edge=0.04, inject_drops=1, drop_strength=0.2,
                 disp_scale_base=1.0, motion_thresh=10):
    """Shared ripple physics engine. Variants just tune parameters."""
    f = frame.astype(np.float32)
    h, w = engine.height, engine.width
    strength = 0.3 + engine.intensity * 1.2  # gentler: was 0.5 + 2.5

    bright = f.max(axis=2)

    # Motion injection (reduced)
    if engine._prev_frame is not None:
        diff = np.abs(f.mean(axis=2) - engine._prev_frame.astype(np.float32).mean(axis=2))
        motion_mask = diff > motion_thresh
        engine._ripple_buf1[motion_mask] += diff[motion_mask] * 0.03 * strength  # was 0.06

    # Edge energy (reduced)
    grad_bx = np.zeros((h, w), dtype=np.float32)
    grad_by = np.zeros((h, w), dtype=np.float32)
    grad_bx[:, 1:-1] = bright[:, 2:] - bright[:, :-2]
    grad_by[1:-1, :] = bright[2:, :] - bright[:-2, :]
    edge_energy = np.sqrt(grad_bx**2 + grad_by**2) / 255.0
    engine._ripple_buf1 += edge_energy * inject_edge * strength * 0.5  # halved

    # Random drops (fewer, gentler)
    bright_ys, bright_xs = np.where(bright > 100)  # higher threshold
    if len(bright_ys) > 0:
        num = min(inject_drops, len(bright_ys))
        indices = np.random.choice(len(bright_ys), num, replace=False)
        for idx in indices:
            dy, dx = int(bright_ys[idx]), int(bright_xs[idx])
            engine._ripple_buf1[dy, dx] += drop_strength * strength * 0.5  # halved

    # Wave equation
    padded = np.pad(engine._ripple_buf1, 1, mode='edge')
    neighbors = (padded[:-2, 1:-1] + padded[2:, 1:-1] +
                 padded[1:-1, :-2] + padded[1:-1, 2:]) / 2.0
    engine._ripple_buf2 = (neighbors - engine._ripple_buf2) * damping
    engine._ripple_buf1, engine._ripple_buf2 = engine._ripple_buf2, engine._ripple_buf1

    ripple = engine._ripple_buf1

    # Displacement
    grad_x = np.zeros((h, w), dtype=np.float32)
    grad_y = np.zeros((h, w), dtype=np.float32)
    grad_x[:, 1:-1] = ripple[:, 2:] - ripple[:, :-2]
    grad_y[1:-1, :] = ripple[2:, :] - ripple[:-2, :]

    disp = disp_scale_base + engine.intensity * 1.5
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing='ij')
    src_x = np.clip((xx + grad_x * disp).astype(int), 0, w - 1)
    src_y = np.clip((yy + grad_y * disp).astype(int), 0, h - 1)
    result = f[src_y, src_x]

    # Saturation-preserving brightness modulation:
    # Instead of multiplying RGB (which desaturates on clip),
    # scale toward white for brightening and toward black for darkening,
    # then re-normalize so the max channel never exceeds 255.
    edge_strength = np.sqrt(grad_x**2 + grad_y**2)
    edge_boost = np.clip(edge_strength * edge_mult_scale * strength, 0, 2.0)
    trough_dim = np.clip(-ripple * trough_scale * strength, 0, 0.5)

    # Combined brightness factor: >1 = brighter, <1 = dimmer
    brightness_mod = (1.0 + edge_boost - trough_dim)[:, :, np.newaxis]
    result *= brightness_mod

    # Re-normalize per pixel to prevent clipping desaturation:
    # If any channel exceeds 255, scale the whole pixel down proportionally
    max_ch = result.max(axis=2, keepdims=True)
    overflow = np.where(max_ch > 255, 255.0 / np.maximum(max_ch, 1), 1.0)
    result *= overflow

    return np.clip(result, 0, 255).astype(np.uint8)


def fx_ripple_soft(engine, frame, dt):
    """Soft Ripple — gentle, dreamy water surface with minimal distortion."""
    return _ripple_core(engine, frame, dt,
                        damping=0.97, edge_mult_scale=4, trough_scale=2,
                        inject_edge=0.02, inject_drops=1, drop_strength=0.15,
                        disp_scale_base=0.5)

def fx_ripple_deep(engine, frame, dt):
    """Deep Ripple — heavy, slow waves with moderate displacement like deep water."""
    return _ripple_core(engine, frame, dt,
                        damping=0.98, edge_mult_scale=4, trough_scale=3,
                        inject_edge=0.04, inject_drops=2, drop_strength=0.2,
                        disp_scale_base=1.0)

def fx_ripple_rain(engine, frame, dt):
    """Rain Ripple — many small drops constantly hitting the surface."""
    return _ripple_core(engine, frame, dt,
                        damping=0.94, edge_mult_scale=5, trough_scale=3,
                        inject_edge=0.03, inject_drops=6, drop_strength=0.4,
                        disp_scale_base=1.0)

def fx_ripple_glass(engine, frame, dt):
    """Glass Ripple — frosted glass refraction with moderate displacement, minimal edge glow."""
    return _ripple_core(engine, frame, dt,
                        damping=0.95, edge_mult_scale=1, trough_scale=1,
                        inject_edge=0.04, inject_drops=2, drop_strength=0.2,
                        disp_scale_base=1.2)

def fx_ripple_cymatics(engine, frame, dt):
    """Cymatics Ripple — standing wave patterns with sustained resonance."""
    return _ripple_core(engine, frame, dt,
                        damping=0.985, edge_mult_scale=8, trough_scale=4,
                        inject_edge=0.08, inject_drops=3, drop_strength=0.35,
                        disp_scale_base=1.5)

def fx_ripple_shatter(engine, frame, dt):
    """Shatter Ripple — sharp, angular distortion like cracked glass."""
    return _ripple_core(engine, frame, dt,
                        damping=0.92, edge_mult_scale=6, trough_scale=3,
                        inject_edge=0.03, inject_drops=1, drop_strength=0.3,
                        disp_scale_base=1.2, motion_thresh=5)


# ─── Gentle Cymatics variants (less disruption than Cymatics Ripple) ─────────

def fx_cymatics_whisper(engine, frame, dt):
    """Cymatics Whisper — very subtle standing wave shimmer."""
    return _ripple_core(engine, frame, dt,
                        damping=0.988, edge_mult_scale=3, trough_scale=1.5,
                        inject_edge=0.03, inject_drops=1, drop_strength=0.12,
                        disp_scale_base=0.4)

def fx_cymatics_breath(engine, frame, dt):
    """Cymatics Breath — gentle organic breathing distortion."""
    return _ripple_core(engine, frame, dt,
                        damping=0.987, edge_mult_scale=4, trough_scale=2,
                        inject_edge=0.04, inject_drops=2, drop_strength=0.15,
                        disp_scale_base=0.6)

def fx_cymatics_flow(engine, frame, dt):
    """Cymatics Flow — moderate standing wave with smooth movement."""
    return _ripple_core(engine, frame, dt,
                        damping=0.986, edge_mult_scale=5, trough_scale=2.5,
                        inject_edge=0.05, inject_drops=2, drop_strength=0.20,
                        disp_scale_base=0.8)

def fx_cymatics_pulse(engine, frame, dt):
    """Cymatics Pulse — noticeable standing wave patterns, still controlled."""
    return _ripple_core(engine, frame, dt,
                        damping=0.986, edge_mult_scale=6, trough_scale=3,
                        inject_edge=0.06, inject_drops=2, drop_strength=0.25,
                        disp_scale_base=1.0)


# ─── FX Registry ─────────────────────────────────────────────────────────────

FX_REGISTRY = {
    "glow":              fx_glow,
    "trails":            fx_trails,
    "phosphor":          fx_phosphor,
    "ripple":            fx_ripple,
    "ripple_soft":       fx_ripple_soft,
    "ripple_deep":       fx_ripple_deep,
    "ripple_rain":       fx_ripple_rain,
    "ripple_glass":      fx_ripple_glass,
    "ripple_cymatics":   fx_ripple_cymatics,
    "ripple_shatter":    fx_ripple_shatter,
    "cymatics_whisper":  fx_cymatics_whisper,
    "cymatics_breath":   fx_cymatics_breath,
    "cymatics_flow":     fx_cymatics_flow,
    "cymatics_pulse":    fx_cymatics_pulse,
}

# Ordered list for UI display
FX_LIST = [
    {"key": "none",              "name": "None"},
    {"key": "glow",              "name": "Glow"},
    {"key": "trails",            "name": "Trails"},
    {"key": "phosphor",          "name": "Phosphor"},
    {"key": "ripple",            "name": "Ripple"},
    {"key": "ripple_soft",       "name": "Soft Ripple"},
    {"key": "ripple_deep",       "name": "Deep Ripple"},
    {"key": "ripple_rain",       "name": "Rain Ripple"},
    {"key": "ripple_glass",      "name": "Glass Ripple"},
    {"key": "ripple_cymatics",   "name": "Cymatics Ripple"},
    {"key": "ripple_shatter",    "name": "Shatter Ripple"},
    {"key": "cymatics_whisper",  "name": "Cymatics Whisper"},
    {"key": "cymatics_breath",   "name": "Cymatics Breath"},
    {"key": "cymatics_flow",     "name": "Cymatics Flow"},
    {"key": "cymatics_pulse",    "name": "Cymatics Pulse"},
]
