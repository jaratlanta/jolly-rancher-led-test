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

        self.width = model["total_cols"]
        self.height = model["rows"]
        self.num_pixels = model["total_pixels"]

        if len(model["panels"]) == 1 and not model["panels"][0].get("flip_h"):
            p = model["panels"][0]
            self.mapping = build_mapping(p["cols"], p["rows"], config.SERPENTINE)
        else:
            self.mapping = build_multi_panel_mapping(model, config.SERPENTINE)

        self._build_panel_coords()
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
            "panels": [
                {"name": p["name"], "rows": p["rows"], "cols": p["cols"],
                 "col_offset": p["col_offset"], "pixel_offset": p["pixel_offset"]}
                for p in self.model_info["panels"]
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
            "webcam_mode": self.webcam_mode,
            "audio_mode": "audio" if self.audio.audio_on else "none",
            "audio_sensitivity": self.audio.sensitivity,
            "audio_enabled": self.audio.enabled,
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

    # ─── Frame generation ──────────────────────────────────────────────────

    def _generate_animation_frame(self):
        """Generate a frame from the current pattern + palette.

        When audio is active, uses the pattern's audio_fn with live
        bass/mid/treble values. Otherwise uses the default fn.
        """
        t = (time.monotonic() - self._start_time) * self.speed
        pattern = PATTERNS[self.pattern_idx]
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        use_audio = self.audio.is_active() and "audio_fn" in pattern

        if use_audio:
            audio_fn = pattern["audio_fn"]
            bass = self.audio.bass_smooth
            mid = self.audio.mid_smooth
            treble = self.audio.treble_smooth
            at = self.audio.audio_time  # accumulated audio-driven time

            for y in range(self.height):
                for x in range(self.width):
                    nx = float(self._nx_map[y][x])
                    ny = float(self._ny_map[y][x])
                    pw = self._pw_map[y][x]
                    ph = self._ph_map[y][x]
                    val = audio_fn(nx, ny, at, pw, ph, bass, mid, treble)
                    val = max(0, min(255, int(val)))
                    r, g, b = palette_color(val, self.palette_idx)
                    frame[y][x] = [r, g, b]
        else:
            anim_fn = pattern["fn"]
            for y in range(self.height):
                for x in range(self.width):
                    nx = float(self._nx_map[y][x])
                    ny = float(self._ny_map[y][x])
                    pw = self._pw_map[y][x]
                    ph = self._ph_map[y][x]
                    val = anim_fn(nx, ny, t, pw, ph)
                    val = max(0, min(255, int(val)))
                    r, g, b = palette_color(val, self.palette_idx)
                    frame[y][x] = [r, g, b]

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

            # Crossfade
            if self._crossfade_active and self._crossfade_from_frame is not None:
                elapsed_cf = time.monotonic() - self._crossfade_start
                alpha = min(1.0, elapsed_cf / self._crossfade_duration)
                if alpha < 1.0:
                    old = self._crossfade_from_frame.astype(np.float32)
                    new = frame_rgb.astype(np.float32)
                    frame_rgb = (old * (1.0 - alpha) + new * alpha).astype(np.uint8)
                else:
                    self._crossfade_active = False
                    self._crossfade_from_frame = None

            # Post-processing FX
            frame_rgb = self.fx.process(frame_rgb, frame_interval)

            # Advance audio state
            self.audio.tick(frame_interval)

            self.current_frame_rgb = frame_rgb

            # Send to Falcon
            pixels = frame_to_pixels(frame_rgb, self.mapping)
            self.sacn.send_frame(pixels)

            # Stream to WebSocket clients
            frame_bytes = frame_rgb.tobytes()
            self._broadcast_frame(frame_bytes)

            # Maintain FPS
            elapsed = time.monotonic() - t0
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

          except Exception:
            time.sleep(0.5)

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
