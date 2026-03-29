"""
USB HID controller integration:
  1. Baseline Knob V2.1 — rotary encoder + 3 buttons (consumer control HID)
  2. SayoDevice 2x6V numpad — 12 keys mapped as keyboard numbers 1-12

Knob controls:
  - Left button (Prev Track): previous preset
  - Right button (Next Track): next preset
  - Center button (Play/Pause): randomize animation + palette
  - Dial CW (Vol Up): speed up
  - Dial CCW (Vol Down): speed down

Numpad controls:
  - Key 1: Toggle preset cycle on/off
  - Key 2: Previous pattern
  - Key 3: Next pattern
  - Keys 4-12: Jump to specific patterns (first 9 patterns, indices 0-8)
"""
import threading
import time
import random

try:
    import hid
    HID_AVAILABLE = True
except ImportError:
    HID_AVAILABLE = False

# Baseline Knob V2.1 USB IDs
KNOB_VID = 0x4244
KNOB_PID = 0x4B4E

# Note: SayoDevice 2x6V numpad is handled in the browser (app.js)
# because macOS blocks raw HID access to keyboard devices.

# HID Consumer Control usage codes (knob)
VOL_UP = 0xE9
VOL_DOWN = 0xEA
NEXT_TRACK = 0xB5
PREV_TRACK = 0xB6
PLAY_PAUSE = 0xCD

# Speed step per dial click
SPEED_STEP = 0.1
SPEED_MIN = 0.1
SPEED_MAX = 5.0


class KnobController:
    """Reads USB HID devices (knob + numpad) and dispatches actions to FrameEngine."""

    def __init__(self, engine, presets_getter):
        self.engine = engine
        self.get_presets = presets_getter
        self._preset_index = -1
        self._running = False
        self._knob_device = None
        self._thread = None
        self._ws_broadcast = None
        self._cycle_active = False  # for numpad key 1 toggle

    def set_ws_broadcast(self, fn):
        self._ws_broadcast = fn

    def start(self):
        if not HID_AVAILABLE:
            print("  HID: hidapi not installed (pip install hidapi)")
            return False
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._close_all()

    def _close_all(self):
        if self._knob_device:
            try:
                self._knob_device.close()
            except Exception:
                pass
        self._knob_device = None

    def _open_knob(self):
        try:
            if self._knob_device:
                self._knob_device.close()
        except Exception:
            pass
        self._knob_device = None
        try:
            target_path = None
            for info in hid.enumerate(KNOB_VID, KNOB_PID):
                if info['usage_page'] == 0x000C or info['usage'] == 0x0002:
                    target_path = info['path']
                    break
            if not target_path:
                for info in hid.enumerate(KNOB_VID, KNOB_PID):
                    target_path = info['path']
                    break
            if not target_path:
                return False
            self._knob_device = hid.device()
            self._knob_device.open_path(target_path)
            self._knob_device.set_nonblocking(True)
            return True
        except Exception:
            self._knob_device = None
            return False

    def _listen_loop(self):
        knob_connected = False
        last_reconnect = 0

        while self._running:
            now = time.monotonic()

            # Reconnect knob periodically
            if now - last_reconnect > 3.0:
                last_reconnect = now
                if not knob_connected:
                    if self._open_knob():
                        knob_connected = True
                        print("  Knob: CONNECTED ✓ (Baseline Knob V2.1)")

            if not knob_connected:
                time.sleep(0.5)
                continue

            # Poll knob
            if self._knob_device:
                try:
                    data = self._knob_device.read(64)
                    if data:
                        self._handle_knob_report(data)
                except Exception:
                    knob_connected = False
                    try:
                        self._knob_device.close()
                    except Exception:
                        pass
                    self._knob_device = None
                    print("  Knob: disconnected")

            time.sleep(0.005)

    def _handle_knob_report(self, data):
        """Parse knob consumer control HID report."""
        if len(data) < 2:
            return
        code = data[1]
        if code == 0x00:
            return

        if code == VOL_UP:
            self._on_dial_cw()
        elif code == VOL_DOWN:
            self._on_dial_ccw()
        elif code == NEXT_TRACK:
            self._on_right_button()
        elif code == PREV_TRACK:
            self._on_left_button()
        elif code == PLAY_PAUSE:
            self._on_center_button()

    # ─── Knob actions ────────────────────────────────────────────────────

    def _on_dial_cw(self):
        """Dial turned clockwise — increase speed."""
        new_speed = min(SPEED_MAX, self.engine.speed + SPEED_STEP)
        self.engine.set_speed(round(new_speed, 1))
        self._notify()

    def _on_dial_ccw(self):
        """Dial turned counter-clockwise — decrease speed."""
        new_speed = max(SPEED_MIN, self.engine.speed - SPEED_STEP)
        self.engine.set_speed(round(new_speed, 1))
        self._notify()

    def _on_right_button(self):
        """Right button — next preset."""
        presets = self.get_presets()
        if not presets:
            return
        self._preset_index = (self._preset_index + 1) % len(presets)
        self._load_current_preset(presets)

    def _on_left_button(self):
        """Left button — previous preset."""
        presets = self.get_presets()
        if not presets:
            return
        self._preset_index = (self._preset_index - 1) % len(presets)
        self._load_current_preset(presets)

    def _on_center_button(self):
        """Center button — randomize animation + palette."""
        from .animations import PATTERNS, PALETTES
        self.engine.set_pattern(random.randint(0, len(PATTERNS) - 1))
        self.engine.set_palette(random.randint(0, len(PALETTES) - 1))
        self._notify()

    def _load_current_preset(self, presets):
        """Load the preset at the current index."""
        if 0 <= self._preset_index < len(presets):
            p = presets[self._preset_index]
            pd = p.get("preset", {})
            pidx = pd.get("pattern_idx", pd.get("animation_idx"))
            if pidx is not None and not self.engine.webcam_mode:
                self.engine.set_pattern(pidx)
            if "palette_idx" in pd:
                self.engine.set_palette(pd["palette_idx"])
            if "fx" in pd:
                self.engine.set_fx(pd["fx"])
            if "fx_intensity" in pd:
                self.engine.set_fx_intensity(pd["fx_intensity"])
            if "brightness" in pd:
                self.engine.set_brightness(pd["brightness"])
            if "speed" in pd:
                self.engine.set_speed(pd["speed"])
        self._notify()

    def _notify(self):
        """Broadcast updated state to WebSocket clients."""
        if self._ws_broadcast:
            try:
                self._ws_broadcast()
            except Exception:
                pass
