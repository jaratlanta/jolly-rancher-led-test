"""
E1.31 (sACN) output: splits pixel buffer into universes and sends to Falcon controller.
Resilient to network drops (sleep/wake, ethernet disconnect) — auto-recovers.
"""
import math
import time
import logging
import numpy as np
import sacn
import sacn.sending.sender_socket_udp as _sacn_udp

logger = logging.getLogger(__name__)

# Patch the sacn library's internal send loop to not crash on network errors.
# The library's sender thread calls send_packet() which raises OSError when
# the network goes down (sleep, ethernet disconnect). We wrap it to swallow
# those errors so the thread survives and can resume when the network returns.
_original_send_packet = _sacn_udp.SenderSocketUDP.send_packet

def _safe_send_packet(self, data_raw, destination):
    try:
        _original_send_packet(self, data_raw, destination)
    except OSError:
        pass  # network down — silently skip until it comes back

_sacn_udp.SenderSocketUDP.send_packet = _safe_send_packet


class SACNOutput:
    def __init__(self, controller_ip, num_pixels, start_universe=1,
                 pixels_per_universe=170, brightness_cap=255, fps=30):
        self.controller_ip = controller_ip
        self.num_pixels = num_pixels
        self.start_universe = start_universe
        self.pixels_per_universe = pixels_per_universe
        self.brightness_cap = brightness_cap
        self.fps = fps
        self.num_universes = math.ceil(num_pixels / pixels_per_universe)
        self._sender = None
        self._healthy = False
        self._last_error_time = 0

    def start(self):
        """Start the sACN sender."""
        self._create_sender()

    def _create_sender(self):
        """Create and configure the sACN sender."""
        try:
            if self._sender:
                try:
                    self._sender.stop()
                except Exception:
                    pass

            self._sender = sacn.sACNsender(source_name="LED Testbed", fps=self.fps)
            self._sender.start()
            for i in range(self.num_universes):
                uni = self.start_universe + i
                self._sender.activate_output(uni)
                self._sender[uni].destination = self.controller_ip
                self._sender[uni].multicast = False
            self._healthy = True
            logger.info("sACN sender started")
        except Exception as e:
            logger.warning(f"sACN sender failed to start: {e}")
            self._healthy = False
            self._sender = None

    def stop(self):
        """Stop the sACN sender."""
        if self._sender:
            try:
                self.send_black()
            except Exception:
                pass
            try:
                self._sender.stop()
            except Exception:
                pass
            self._sender = None
            self._healthy = False

    def send_frame(self, pixels):
        """Send a frame of pixel data. Recovers automatically from network errors.

        Args:
            pixels: np.ndarray of shape (num_pixels, 3), dtype uint8
        """
        if not self._healthy:
            # Try to recover, but not more than once every 5 seconds
            now = time.monotonic()
            if now - self._last_error_time > 5.0:
                logger.info("Attempting sACN reconnect...")
                self._create_sender()
                self._last_error_time = now
            if not self._healthy:
                return

        try:
            capped = np.clip(pixels, 0, self.brightness_cap).astype(np.uint8)
            flat = capped.flatten()

            for i in range(self.num_universes):
                start_ch = i * self.pixels_per_universe * 3
                end_ch = min(start_ch + self.pixels_per_universe * 3, len(flat))
                chunk = flat[start_ch:end_ch]
                uni = self.start_universe + i
                self._sender[uni].dmx_data = tuple(int(v) for v in chunk)

        except (OSError, AttributeError) as e:
            # Network went down (sleep, ethernet disconnect, etc.)
            if self._healthy:
                logger.warning(f"sACN send failed (network down?): {e}")
            self._healthy = False
            self._last_error_time = time.monotonic()

    def send_black(self):
        """Send all-black (off) frame."""
        black = np.zeros((self.num_pixels, 3), dtype=np.uint8)
        self.send_frame(black)
