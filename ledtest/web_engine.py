"""
Frame generation engine: renders animations into pixel frames,
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
from .animations import ANIMATIONS, PALETTES, palette_color
from .patterns import PATTERNS
from .fx import FXEngine as FXProcessor, FX_LIST
from .models import get_model, get_model_list


class FrameEngine:
    """Generates frames and distributes to hardware + web clients."""

    def __init__(self, model_key=None):
        self.fps = config.FPS
        self.model_key = model_key or getattr(config, 'DEFAULT_MODEL', 'test_panel')

        # Animation state
        self.animation_idx = 0
        self.palette_idx = 0
        self.brightness = config.BRIGHTNESS_CAP
        self.speed = 1.0
        self.running = False
        self.blackout = False

        # Diagnostic mode (uses original PATTERNS)
        self.diagnostic_mode = False
        self.diagnostic_key = None
        self.diagnostic_gen = None

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

        # Virtual canvas dimensions (all panels side by side)
        self.width = model["total_cols"]
        self.height = model["rows"]
        self.num_pixels = model["total_pixels"]

        # Build mapping
        if len(model["panels"]) == 1 and not model["panels"][0].get("flip_h"):
            # Simple single-panel mode (Test Panel)
            p = model["panels"][0]
            self.mapping = build_mapping(p["cols"], p["rows"], config.SERPENTINE)
        else:
            # Multi-panel mode
            self.mapping = build_multi_panel_mapping(model, config.SERPENTINE)

        # FX processor
        self.fx = FXProcessor(self.width, self.height)

        # sACN output
        self.sacn = SACNOutput(
            controller_ip=config.CONTROLLER_IP,
            num_pixels=self.num_pixels,
            start_universe=config.START_UNIVERSE,
            pixels_per_universe=config.PIXELS_PER_UNIVERSE,
            brightness_cap=self.brightness,
            fps=self.fps,
        )

    def start(self):
        """Start the sACN sender and frame loop."""
        self.sacn.start()
        self.running = True
        self._start_time = time.monotonic()
        self._thread = threading.Thread(target=self._frame_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the frame loop and sACN sender."""
        self.running = False
        if hasattr(self, '_thread'):
            self._thread.join(timeout=2)
        try:
            self.sacn.stop()
        except Exception:
            pass

    def reconfigure(self, model_key):
        """Switch to a different display model at runtime."""
        if model_key == self.model_key:
            return

        was_running = self.running

        # Stop current operation
        if was_running:
            self.running = False
            if hasattr(self, '_thread'):
                self._thread.join(timeout=2)
            try:
                self.sacn.stop()
            except Exception:
                pass

        # Switch model
        self.model_key = model_key
        self._configure_model()
        self.sacn.brightness_cap = self.brightness

        # Reset diagnostic mode (dimensions changed)
        self.diagnostic_mode = False
        self.diagnostic_gen = None
        self.diagnostic_key = None

        # Restart if we were running
        if was_running:
            self.start()

    def set_animation(self, idx):
        """Switch to animation by index."""
        self.diagnostic_mode = False
        self.diagnostic_gen = None
        self.animation_idx = idx % len(ANIMATIONS)

    def set_palette(self, idx):
        """Switch to palette by index."""
        self.palette_idx = idx % len(PALETTES)

    def set_brightness(self, value):
        """Set brightness 0-255."""
        self.brightness = max(0, min(255, int(value)))
        self.sacn.brightness_cap = self.brightness

    def set_speed(self, value):
        """Set animation speed multiplier."""
        self.speed = max(0.1, min(5.0, float(value)))

    def set_blackout(self, on):
        """Toggle blackout mode."""
        self.blackout = on
        if on:
            self.sacn.send_black()

    def set_fx(self, fx_key):
        """Set the active post-processing FX."""
        self.fx.set_fx(fx_key if fx_key != "none" else None)

    def set_fx_intensity(self, value):
        """Set FX intensity 0..1."""
        self.fx.intensity = max(0.0, min(1.0, float(value)))

    def set_diagnostic(self, key):
        """Switch to a diagnostic pattern from the original PATTERNS."""
        if key in PATTERNS:
            self.diagnostic_mode = True
            self.diagnostic_key = key
            _, factory = PATTERNS[key]
            self.diagnostic_gen = factory(self.width, self.height)

    def get_state(self):
        """Return current state for UI sync."""
        return {
            "model_key": self.model_key,
            "model_name": self.model_info["name"],
            "panels": [
                {"name": p["name"], "rows": p["rows"], "cols": p["cols"],
                 "col_offset": p["col_offset"], "pixel_offset": p["pixel_offset"]}
                for p in self.model_info["panels"]
            ],
            "animation_idx": self.animation_idx,
            "animation_name": ANIMATIONS[self.animation_idx]["name"],
            "animation_count": len(ANIMATIONS),
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
        }

    def _generate_animation_frame(self):
        """Generate a frame from the current animation + palette."""
        t = (time.monotonic() - self._start_time) * self.speed
        anim_fn = ANIMATIONS[self.animation_idx]["fn"]
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        for y in range(self.height):
            for x in range(self.width):
                nx = x / max(self.width - 1, 1)
                ny = y / max(self.height - 1, 1)
                val = anim_fn(nx, ny, t, self.width, self.height)
                val = max(0, min(255, int(val)))
                r, g, b = palette_color(val, self.palette_idx)
                frame[y][x] = [r, g, b]

        return frame

    def _frame_loop(self):
        """Main frame generation loop running in a background thread."""
        frame_interval = 1.0 / self.fps

        while self.running:
            t0 = time.monotonic()

            if self.blackout:
                frame_rgb = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            elif self.diagnostic_mode and self.diagnostic_gen:
                try:
                    frame_rgb = next(self.diagnostic_gen)
                except StopIteration:
                    frame_rgb = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            else:
                frame_rgb = self._generate_animation_frame()

            # Apply post-processing FX
            frame_rgb = self.fx.process(frame_rgb, frame_interval)

            # Store for any sync reads
            self.current_frame_rgb = frame_rgb

            # Send to Falcon
            pixels = frame_to_pixels(frame_rgb, self.mapping)
            self.sacn.send_frame(pixels)

            # Stream to WebSocket clients (binary: raw RGB bytes)
            frame_bytes = frame_rgb.tobytes()
            self._broadcast_frame(frame_bytes)

            # Maintain FPS
            elapsed = time.monotonic() - t0
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _broadcast_frame(self, frame_bytes):
        """Send frame data to all connected WebSocket clients."""
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
        """Register a WebSocket client."""
        ws._loop = loop
        with self.ws_lock:
            self.ws_clients.add(ws)

    def remove_client(self, ws):
        """Unregister a WebSocket client."""
        with self.ws_lock:
            self.ws_clients.discard(ws)
