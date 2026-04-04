"""
Configuration for the LED testbed.
Edit CONTROLLER_IP to match your Falcon's IP (shown on its OLED display).
"""

# --- Edit these to match your hardware ---

CONTROLLER_IP = "192.168.8.196"  # Falcon F16v5 ethernet IP

MATRIX_WIDTH = 24       # columns
MATRIX_HEIGHT = 12      # rows
SERPENTINE = True        # odd rows wired right-to-left
PIXELS_PER_UNIVERSE = 170  # E1.31 standard (510 channels / 3)

START_UNIVERSE = 1       # first E1.31 universe number
FPS = 30                 # frames per second
BRIGHTNESS_CAP = 200     # max channel value (0-255), limits power draw

DEFAULT_MODEL = "test_panel"  # "test_panel" or "jolly_rancher"
