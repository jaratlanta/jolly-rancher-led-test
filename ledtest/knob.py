"""
Baseline Knob V2.1 USB HID controller integration.

Maps the physical knob's buttons and rotary encoder to app controls:
  - Left button (Prev Track 0xB6): previous preset
  - Right button (Next Track 0xB5): next preset
  - Center button (Play/Pause 0xCD): randomize animation + palette
  - Dial clockwise (Vol Up 0xE9): speed up
  - Dial counter-clockwise (Vol Down 0xEA): speed down

Runs a background thread polling the HID device. Gracefully handles
the knob being disconnected or not present.
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
VENDOR_ID = 0x4244
PRODUCT_ID = 0x4B4E

# HID Consumer Control usage codes (byte[1] of 3-byte reports)
VOL_UP = 0xE9       # Dial clockwise
VOL_DOWN = 0xEA     # Dial counter-clockwise
NEXT_TRACK = 0xB5   # Right button
PREV_TRACK = 0xB6   # Left button
PLAY_PAUSE = 0xCD   # Center button

# Speed step per dial click
SPEED_STEP = 0.1
SPEED_MIN = 0.1
SPEED_MAX = 5.0


class KnobController:
    """Reads the Baseline Knob V2.1 and dispatches actions to the FrameEngine."""

    def __init__(self, engine, presets_getter):
        """
        Args:
            engine: FrameEngine instance
            presets_getter: callable that returns the current presets list
        """
        self.engine = engine
        self.get_presets = presets_getter
        self._preset_index = -1  # current position in presets list
        self._running = False
        self._device = None
        self._thread = None
        self._ws_broadcast = None  # optional: callable to broadcast state to WS clients

    def set_ws_broadcast(self, fn):
        """Set a function to call after knob actions to sync WebSocket clients."""
        self._ws_broadcast = fn

    def start(self):
        """Start the knob listener thread."""
        if not HID_AVAILABLE:
            print("  Knob: hidapi not installed (pip install hidapi)")
            return False

        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """Stop the knob listener."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._close_device()

    def _close_device(self):
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

    def _open_device(self):
        """Try to open the knob HID device. Returns True on success."""
        self._close_device()
        try:
            # Find the consumer control interface (usage_page 0x000c)
            target_path = None
            for info in hid.enumerate(VENDOR_ID, PRODUCT_ID):
                if info['usage_page'] == 0x000C or info['usage'] == 0x0002:
                    target_path = info['path']
                    break

            if not target_path:
                # Fall back to any interface
                for info in hid.enumerate(VENDOR_ID, PRODUCT_ID):
                    target_path = info['path']
                    break

            if not target_path:
                return False

            self._device = hid.device()
            self._device.open_path(target_path)
            self._device.set_nonblocking(True)
            return True
        except Exception:
            self._device = None
            return False

    def _listen_loop(self):
        """Main polling loop — runs in a background thread."""
        connected = False
        reconnect_interval = 3.0
        last_reconnect = 0

        while self._running:
            # Try to connect if not connected
            if not connected:
                now = time.monotonic()
                if now - last_reconnect > reconnect_interval:
                    last_reconnect = now
                    if self._open_device():
                        connected = True
                        print("  Knob: CONNECTED ✓ (Baseline Knob V2.1)")
                    else:
                        # Don't spam — just quietly retry
                        pass
                if not connected:
                    time.sleep(0.5)
                    continue

            # Read HID reports
            try:
                data = self._device.read(64)
                if data:
                    self._handle_report(data)
                else:
                    time.sleep(0.005)  # ~200Hz polling when idle
            except Exception:
                # Device disconnected
                connected = False
                self._close_device()
                print("  Knob: disconnected — will reconnect...")
                time.sleep(1)

    def _handle_report(self, data):
        """Parse a 3-byte consumer control HID report and dispatch action."""
        if len(data) < 2:
            return

        # Report format: [report_id, usage_code, ...]
        # The knob sends: [0x04, code, 0x00] for press, [0x04, 0x00, 0x00] for release
        code = data[1]

        if code == 0x00:
            return  # key release, ignore

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
