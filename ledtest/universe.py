"""
E1.31 (sACN) output: splits pixel buffer into universes and sends to Falcon controller.
"""
import math
import numpy as np
import sacn


class SACNOutput:
    def __init__(self, controller_ip, num_pixels, start_universe=1,
                 pixels_per_universe=170, brightness_cap=255, fps=30):
        self.controller_ip = controller_ip
        self.num_pixels = num_pixels
        self.start_universe = start_universe
        self.pixels_per_universe = pixels_per_universe
        self.brightness_cap = brightness_cap
        self.num_universes = math.ceil(num_pixels / pixels_per_universe)
        self.sender = sacn.sACNsender(source_name="LED Testbed", fps=fps)

    def start(self):
        self.sender.start()
        for i in range(self.num_universes):
            uni = self.start_universe + i
            self.sender.activate_output(uni)
            self.sender[uni].destination = self.controller_ip
            self.sender[uni].multicast = False

    def stop(self):
        self.send_black()
        self.sender.stop()

    def send_frame(self, pixels):
        """Send a frame of pixel data.

        Args:
            pixels: np.ndarray of shape (num_pixels, 3), dtype uint8
        """
        capped = np.clip(pixels, 0, self.brightness_cap).astype(np.uint8)
        flat = capped.flatten()  # R0,G0,B0,R1,G1,B1,...

        for i in range(self.num_universes):
            start_ch = i * self.pixels_per_universe * 3
            end_ch = min(start_ch + self.pixels_per_universe * 3, len(flat))
            chunk = flat[start_ch:end_ch]
            uni = self.start_universe + i
            # sacn expects a tuple of ints, 1-512 channels
            self.sender[uni].dmx_data = tuple(int(v) for v in chunk)

    def send_black(self):
        """Send all-black (off) frame."""
        black = np.zeros((self.num_pixels, 3), dtype=np.uint8)
        self.send_frame(black)
