"""
Frame generation engine: renders patterns into pixel frames,
sends to Falcon via E1.31, and streams to WebSocket clients.
Supports runtime switching between different display models.
"""
import asyncio
import json
import time
import threading
import numpy as np

from . import config
from .mapping import build_mapping, build_multi_panel_mapping, frame_to_pixels
from .universe import SACNOutput
from .animations import PATTERNS, PALETTES, palette_color
from .patterns import PATTERNS as DIAG_PATTERNS
from .fx import FXEngine as FXProcessor, FX_LIST
from .audio_fx import AudioEngine, AUDIO_MODES
from .models import get_model, get_model_list


class FrameEngine:
    """Generates frames and distributes to hardware + web clients."""

    def __init__(self, model_key=None):
        self.fps = config.FPS
        self.model_key = model_key or getattr(config, 'DEFAULT_MODEL', 'test_panel')

        # Pattern state
        self.pattern_idx = 0
        self.palette_idx = 0
        self.brightness = config.BRIGHTNESS_CAP
        self.speed = 1.0
        self.running = False
        self.blackout = False

        # Crossfade transition
        self._crossfade_active = False
        self._crossfade_start = 0.0
        self._crossfade_duration = 1.5  # seconds
        self._crossfade_from_frame = None

        # Diagnostic mode (uses original diagnostic PATTERNS)
        self.diagnostic_mode = False
        self.diagnostic_key = None
        self.diagnostic_gen = None

        # Symmetry mode for bull's head (left mirrors right)
        self.symmetry = True

        # Webcam mode
        self.webcam_mode = False
        self._webcam_brightness = None
        self._webcam_lock = threading.Lock()

        # WebSocket clients
        self.ws_clients = set()
        self.ws_lock = threading.Lock()

        # Frame data for preview
        self.current_frame_rgb = None
        self._start_time = 0

        # Configure for the initial model
        self._configure_model()

    def _configure_model(self):
        """Set up mapping, sACN output, and FX for the current model."""
        model = get_model(self.model_key)
        self.model_info = model
        self.model_type = model.get("type", "grid")

        self.width = model["total_cols"]
        self.height = model["rows"]
        self.num_pixels = model["total_pixels"]

        # Grid mapping (for grid and composite models that have panels)
        if model["panels"]:
            if len(model["panels"]) == 1 and not model["panels"][0].get("flip_h"):
                p = model["panels"][0]
                self.mapping = build_mapping(p["cols"], p["rows"], config.SERPENTINE)
            else:
                self.mapping = build_multi_panel_mapping(model, config.SERPENTINE)
            self._build_panel_coords()
        else:
            self.mapping = None

        # Strand mapping (for strand and composite models)
        self._strand_coords = None
        strands = model.get("strands", [])
        if strands:
            self._build_strand_coords(strands)

        self.fx = FXProcessor(self.width, self.height)
        # Preserve audio state across model switches
        if not hasattr(self, 'audio'):
            self.audio = AudioEngine()

        self.sacn = SACNOutput(
            controller_ip=config.CONTROLLER_IP,
            num_pixels=self.num_pixels,
            start_universe=config.START_UNIVERSE,
            pixels_per_universe=config.PIXELS_PER_UNIVERSE,
            brightness_cap=self.brightness,
            fps=self.fps,
        )

    def start(self):
        self.sacn.start()
        self.running = True
        self._start_time = time.monotonic()
        self._thread = threading.Thread(target=self._frame_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if hasattr(self, '_thread'):
            self._thread.join(timeout=2)
        try:
            self.sacn.stop()
        except Exception:
            pass

    def reconfigure(self, model_key):
        if model_key == self.model_key:
            return
        was_running = self.running
        if was_running:
            self.running = False
            if hasattr(self, '_thread'):
                self._thread.join(timeout=2)
            try:
                self.sacn.stop()
            except Exception:
                pass
        self.model_key = model_key
        self._configure_model()
        self.sacn.brightness_cap = self.brightness
        self.diagnostic_mode = False
        self.diagnostic_gen = None
        self.diagnostic_key = None
        if was_running:
            self.start()

    def _start_crossfade(self):
        if self.current_frame_rgb is not None:
            self._crossfade_from_frame = self.current_frame_rgb.copy()
            self._crossfade_active = True
            self._crossfade_start = time.monotonic()

    # ─── Pattern / animation controls ──────────────────────────────────────

    def set_pattern(self, idx):
        """Switch to pattern by index."""
        new_idx = idx % len(PATTERNS)
        if new_idx != self.pattern_idx:
            self._start_crossfade()
        self.diagnostic_mode = False
        self.diagnostic_gen = None
        self.pattern_idx = new_idx

    # Backward compat alias
    def set_animation(self, idx):
        self.set_pattern(idx)

    def set_palette(self, idx):
        new_idx = idx % len(PALETTES)
        if new_idx != self.palette_idx:
            self._start_crossfade()
        self.palette_idx = new_idx

    def set_brightness(self, value):
        self.brightness = max(0, min(255, int(value)))
        self.sacn.brightness_cap = self.brightness

    def set_speed(self, value):
        self.speed = max(0.1, min(5.0, float(value)))

    def set_blackout(self, on):
        self.blackout = on
        if on:
            self.sacn.send_black()

    def set_symmetry(self, on):
        """Toggle symmetry mode for bull's head."""
        self.symmetry = bool(on)

    def set_fx(self, fx_key):
        self.fx.set_fx(fx_key if fx_key != "none" else None)

    def set_fx_intensity(self, value):
        self.fx.intensity = max(0.0, min(1.0, float(value)))

    # ─── Audio controls ────────────────────────────────────────────────────

    def set_audio_mode(self, mode):
        """Set audio mode: 'none' = off, 'audio' = per-pattern audio."""
        self.audio.set_mode(mode)

    def set_audio_sensitivity(self, value):
        self.audio.sensitivity = max(0.1, min(3.0, float(value)))

    def set_audio_enabled(self, on):
        self.audio.enabled = bool(on)
        if not on:
            self.audio.reset()

    def update_audio_data(self, bass, mid, treble):
        self.audio.update_audio(float(bass), float(mid), float(treble))

    # ─── Webcam ────────────────────────────────────────────────────────────

    def set_webcam(self, on):
        self.webcam_mode = bool(on)
        if not on:
            with self._webcam_lock:
                self._webcam_brightness = None

    def receive_webcam_frame(self, brightness_data):
        expected = self.width * self.height
        if len(brightness_data) != expected:
            return
        with self._webcam_lock:
            self._webcam_brightness = np.frombuffer(brightness_data, dtype=np.uint8).reshape(
                (self.height, self.width)
            ).copy()

    def _generate_webcam_frame(self):
        with self._webcam_lock:
            brightness = self._webcam_brightness
        if brightness is None:
            return np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        for y in range(self.height):
            for x in range(self.width):
                val = int(brightness[y][x])
                r, g, b = palette_color(val, self.palette_idx)
                frame[y][x] = [r, g, b]
        return frame

    # ─── Diagnostics ───────────────────────────────────────────────────────

    def set_diagnostic(self, key):
        if key in DIAG_PATTERNS:
            self.diagnostic_mode = True
            self.diagnostic_key = key
            _, factory = DIAG_PATTERNS[key]
            self.diagnostic_gen = factory(self.width, self.height)

    # ─── State ─────────────────────────────────────────────────────────────

    def get_state(self):
        return {
            "model_key": self.model_key,
            "model_name": self.model_info["name"],
            "model_type": self.model_type,
            "panels": [
                {"name": p["name"], "rows": p["rows"], "cols": p["cols"],
                 "col_offset": p["col_offset"], "pixel_offset": p["pixel_offset"]}
                for p in self.model_info["panels"]
            ],
            "strands": [
                {"name": s["name"], "pixel_count": s["pixel_count"],
                 "pixel_offset": s["pixel_offset"], "path": s["path"]}
                for s in self.model_info.get("strands", [])
            ],
            # Pattern state (with backward-compat animation_ fields)
            "pattern_idx": self.pattern_idx,
            "pattern_name": PATTERNS[self.pattern_idx]["name"],
            "pattern_count": len(PATTERNS),
            "animation_idx": self.pattern_idx,      # backward compat
            "animation_name": PATTERNS[self.pattern_idx]["name"],
            "animation_count": len(PATTERNS),
            "palette_idx": self.palette_idx,
            "palette_name": PALETTES[self.palette_idx]["name"],
            "palette_count": len(PALETTES),
            "brightness": self.brightness,
            "speed": self.speed,
            "blackout": self.blackout,
            "diagnostic_mode": self.diagnostic_mode,
            "diagnostic_key": self.diagnostic_key,
            "width": self.width,
            "height": self.height,
            "num_pixels": self.num_pixels,
            "fps": self.fps,
            "controller_ip": config.CONTROLLER_IP,
            "fx": self.fx.active_fx or "none",
            "fx_intensity": self.fx.intensity,
            "symmetry": self.symmetry,
            "webcam_mode": self.webcam_mode,
            "audio_mode": "audio" if self.audio.audio_on else "none",
            "audio_sensitivity": self.audio.sensitivity,
            "audio_enabled": self.audio.enabled,
            "bpm": self.audio.get_state().get("bpm", 0),
        }

    # ─── Panel coordinates ─────────────────────────────────────────────────

    def _build_panel_coords(self):
        """Precompute per-pixel surface-local normalized coordinates."""
        panels = self.model_info["panels"]
        surfaces = self.model_info.get("surfaces", {})

        self._nx_map = np.zeros((self.height, self.width), dtype=np.float32)
        self._ny_map = np.zeros((self.height, self.width), dtype=np.float32)
        self._pw_map = np.zeros((self.height, self.width), dtype=np.int32)
        self._ph_map = np.zeros((self.height, self.width), dtype=np.int32)

        for p in panels:
            surface_key = p.get("surface", p["name"])
            surface = surfaces.get(surface_key, {
                "col_start": p["col_offset"],
                "total_cols": p["cols"],
                "rows": p["rows"],
            })
            surf_col_start = surface["col_start"]
            surf_total_cols = surface["total_cols"]
            surf_rows = surface["rows"]
            panel_col_start = p["col_offset"]
            p_cols = p["cols"]
            p_rows = p["rows"]

            for y in range(p_rows):
                ny = y / max(surf_rows - 1, 1)
                for x in range(p_cols):
                    gx = panel_col_start + x
                    sx = (panel_col_start - surf_col_start) + x
                    self._nx_map[y][gx] = sx / max(surf_total_cols - 1, 1)
                    self._ny_map[y][gx] = ny
                    self._pw_map[y][gx] = surf_total_cols
                    self._ph_map[y][gx] = surf_rows

    # ─── Strand coordinates ───────────────────────────────────────────────

    def _build_strand_coords(self, strands):
        """Precompute normalized (nx, ny) for each pixel on each strand.

        nx = position along strand (0..1)
        ny = strand index normalized (0..1)
        """
        num_strands = len(strands)
        coords = []  # list of (nx, ny, strand_pixel_count, num_strands)
        for si, strand in enumerate(strands):
            ny = si / max(num_strands - 1, 1)
            pc = strand["pixel_count"]
            for pi in range(pc):
                nx = pi / max(pc - 1, 1)
                coords.append((nx, ny, pc, num_strands))
        self._strand_coords = coords

    # ─── Frame generation ──────────────────────────────────────────────────

    def _generate_animation_frame(self):
        """Generate a frame from the current pattern + palette.

        Handles grid models, strand models, and composites.
        Returns pixel data as flat RGB array for strand/composite models,
        or 2D grid for grid models.
        """
        t = (time.monotonic() - self._start_time) * self.speed
        pattern = PATTERNS[self.pattern_idx]
        use_audio = self.audio.is_active() and "audio_fn" in pattern

        if self.model_type == "strands":
            return self._generate_strand_frame(t, pattern, use_audio)
        elif self.model_type == "composite":
            return self._generate_composite_frame(t, pattern, use_audio)
        else:
            return self._generate_grid_frame(t, pattern, use_audio)

    def _generate_grid_frame(self, t, pattern, use_audio):
        """Generate frame for grid (panel) models."""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        if use_audio:
            audio_fn = pattern["audio_fn"]
            bass, mid, treble = self.audio.bass_smooth, self.audio.mid_smooth, self.audio.treble_smooth
            at = self.audio.audio_time
            for y in range(self.height):
                for x in range(self.width):
                    nx = float(self._nx_map[y][x])
                    ny = float(self._ny_map[y][x])
                    pw, ph = self._pw_map[y][x], self._ph_map[y][x]
                    try:
                        val = max(0, min(255, int(audio_fn(nx, ny, at, pw, ph, bass, mid, treble))))
                    except Exception:
                        val = 0
                    r, g, b = palette_color(val, self.palette_idx)
                    frame[y][x] = [r, g, b]
        else:
            anim_fn = pattern["fn"]
            for y in range(self.height):
                for x in range(self.width):
                    nx = float(self._nx_map[y][x])
                    ny = float(self._ny_map[y][x])
                    pw, ph = self._pw_map[y][x], self._ph_map[y][x]
                    try:
                        val = max(0, min(255, int(anim_fn(nx, ny, t, pw, ph))))
                    except Exception:
                        val = 0
                    r, g, b = palette_color(val, self.palette_idx)
                    frame[y][x] = [r, g, b]

        return frame

    def _generate_strand_frame(self, t, pattern, use_audio):
        """Generate frame for strand models. Returns 1D pixel array.

        In symmetry mode, left-side strands are rendered normally, then
        right-side strands mirror the corresponding left-side strand (reversed).
        """
        if not self._strand_coords:
            return np.zeros((1, 1, 3), dtype=np.uint8)

        num_pixels = len(self._strand_coords)
        frame = np.zeros((1, num_pixels, 3), dtype=np.uint8)

        strands = self.model_info.get("strands", [])

        # Build symmetry pairs by name: right strand mirrors left strand
        # reverse=True means the strands traverse in opposite directions
        # (Center strands: CL goes bottom→up→left, CR goes right→center→down)
        sym_name_map = {
            "Right Inner":  ("Left Inner",  False),
            "Right Outer":  ("Left Outer",  False),
            "Lower Right":  ("Lower Left",  False),
            "Center Right": ("Center Left", True),  # opposite traversal
        }
        sym_pairs = {}  # right_idx → (left_idx, reverse)
        if self.symmetry:
            name_to_idx = {s["name"]: i for i, s in enumerate(strands)}
            for right_name, (left_name, reverse) in sym_name_map.items():
                ri = name_to_idx.get(right_name)
                li = name_to_idx.get(left_name)
                if ri is not None and li is not None:
                    sym_pairs[ri] = (li, reverse)

        if use_audio:
            fn = pattern["audio_fn"]
            bass, mid, treble = self.audio.bass_smooth, self.audio.mid_smooth, self.audio.treble_smooth
            at = self.audio.audio_time
        else:
            fn = pattern["fn"]

        # Render each strand
        pixel_offset = 0
        strand_pixels = {}  # cache per-strand pixel data for symmetry

        for si, strand in enumerate(strands):
            pc = strand["pixel_count"]

            if self.symmetry and si in sym_pairs:
                src_si, reverse = sym_pairs[si]
                if src_si in strand_pixels:
                    src = strand_pixels[src_si]
                    src_pc = len(src)
                    for pi in range(pc):
                        frac = pi / max(pc - 1, 1)
                        if reverse:
                            frac = 1.0 - frac
                        src_pi = min(src_pc - 1, int(frac * (src_pc - 1)))
                        frame[0][pixel_offset + pi] = src[src_pi]
                    pixel_offset += pc
                    continue

            # Normal render
            pixels = []
            for pi in range(pc):
                idx = pixel_offset + pi
                if idx < len(self._strand_coords):
                    nx, ny, pw, ph = self._strand_coords[idx]
                    try:
                        if use_audio:
                            val = max(0, min(255, int(fn(nx, ny, at, pw, ph, bass, mid, treble))))
                        else:
                            val = max(0, min(255, int(fn(nx, ny, t, pw, ph))))
                    except Exception:
                        val = 0
                    r, g, b = palette_color(val, self.palette_idx)
                    frame[0][pixel_offset + pi] = [r, g, b]
                    pixels.append([r, g, b])

            strand_pixels[si] = pixels
            pixel_offset += pc

        return frame

    def _generate_composite_frame(self, t, pattern, use_audio):
        """Generate frame for composite models (grid + strands combined).

        Grid pixels are rendered as a 2D frame, strand pixels are appended
        as a flat row at the bottom. The frontend knows how to split them.
        Reuses _generate_strand_frame for symmetry support.
        """
        # Generate grid portion
        grid_frame = self._generate_grid_frame(t, pattern, use_audio)

        # Generate strand portion using the same method as Bull's Head
        # (includes symmetry logic)
        if self._strand_coords:
            strand_frame = self._generate_strand_frame(t, pattern, use_audio)
            # strand_frame is (1, num_strand_pixels, 3) — pack into grid width
            num_strand_px = strand_frame.shape[1]
            strand_row = np.zeros((1, self.width, 3), dtype=np.uint8)
            copy_count = min(num_strand_px, self.width)
            strand_row[0, :copy_count] = strand_frame[0, :copy_count]

            frame = np.vstack([grid_frame, strand_row])
        else:
            frame = grid_frame

        return frame

    # ─── Frame loop ────────────────────────────────────────────────────────

    def _frame_loop(self):
        frame_interval = 1.0 / self.fps

        while self.running:
          try:
            t0 = time.monotonic()

            if self.blackout:
                frame_rgb = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            elif self.webcam_mode:
                frame_rgb = self._generate_webcam_frame()
            elif self.diagnostic_mode and self.diagnostic_gen:
                try:
                    frame_rgb = next(self.diagnostic_gen)
                except StopIteration:
                    frame_rgb = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            else:
                frame_rgb = self._generate_animation_frame()

            # Crossfade (shape must match; cancel if dimensions changed)
            if self._crossfade_active and self._crossfade_from_frame is not None:
                if self._crossfade_from_frame.shape != frame_rgb.shape:
                    self._crossfade_active = False
                    self._crossfade_from_frame = None
                else:
                    elapsed_cf = time.monotonic() - self._crossfade_start
                    alpha = min(1.0, elapsed_cf / self._crossfade_duration)
                    if alpha < 1.0:
                        old = self._crossfade_from_frame.astype(np.float32)
                        new = frame_rgb.astype(np.float32)
                        frame_rgb = (old * (1.0 - alpha) + new * alpha).astype(np.uint8)
                    else:
                        self._crossfade_active = False
                        self._crossfade_from_frame = None

            # Post-processing FX — reinit if frame shape changed
            fh, fw = frame_rgb.shape[0], frame_rgb.shape[1]
            if self.fx.width != fw or self.fx.height != fh:
                active = self.fx.active_fx
                intensity = self.fx.intensity
                self.fx = FXProcessor(fw, fh)
                self.fx.active_fx = active
                self.fx.intensity = intensity
            try:
                frame_rgb = self.fx.process(frame_rgb, frame_interval)
            except Exception:
                pass  # skip FX this frame rather than crash

            # Advance audio state
            self.audio.tick(frame_interval)

            # Apply brightness cap to frame (affects both preview and hardware)
            if self.brightness < 255:
                frame_rgb = np.clip(frame_rgb, 0, self.brightness).astype(np.uint8)

            self.current_frame_rgb = frame_rgb

            # Send to Falcon — grid uses mapping, strands are linear
            if self.mapping is not None:
                pixels = frame_to_pixels(frame_rgb, self.mapping)
            else:
                # Strand model: pixels are already in linear order
                pixels = frame_rgb.reshape(-1, 3)
            self.sacn.send_frame(pixels)

            # Stream to WebSocket clients
            frame_bytes = frame_rgb.tobytes()
            self._broadcast_frame(frame_bytes)

            # Maintain FPS
            elapsed = time.monotonic() - t0
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

          except Exception as e:
            import traceback, sys
            print(f"\n⚠️  Frame loop error: {e}", file=sys.stderr)
            traceback.print_exc()
            time.sleep(0.033)  # skip one frame, don't freeze

    def _broadcast_frame(self, frame_bytes):
        with self.ws_lock:
            dead = set()
            for ws in self.ws_clients:
                try:
                    loop = ws._loop if hasattr(ws, '_loop') else None
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            ws.send_bytes(frame_bytes), loop
                        )
                except Exception:
                    dead.add(ws)
            self.ws_clients -= dead

    def add_client(self, ws, loop):
        ws._loop = loop
        with self.ws_lock:
            self.ws_clients.add(ws)

    def remove_client(self, ws):
        with self.ws_lock:
            self.ws_clients.discard(ws)
