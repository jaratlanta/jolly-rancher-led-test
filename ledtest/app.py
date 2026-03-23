"""
CLI application: menu-driven test pattern runner for the LED testbed.
"""
import subprocess
import sys
import time

import numpy as np

from . import config
from .mapping import build_mapping, frame_to_pixels
from .patterns import PATTERNS
from .universe import SACNOutput


def ping_check(ip):
    """Quick check if the controller is reachable."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip],
            capture_output=True, timeout=3
        )
        return result.returncode == 0
    except Exception:
        return False


def print_header():
    print()
    print("=" * 50)
    print("  Jolly Rancher LED Testbed")
    print(f"  Matrix: {config.MATRIX_WIDTH}x{config.MATRIX_HEIGHT}  "
          f"({config.MATRIX_WIDTH * config.MATRIX_HEIGHT} pixels)")
    print(f"  Controller: {config.CONTROLLER_IP}")
    print(f"  Brightness cap: {config.BRIGHTNESS_CAP}/255")
    print("=" * 50)


def print_menu():
    print()
    print("Test Patterns:")
    for key, (desc, _) in PATTERNS.items():
        print(f"  {key}) {desc}")
    print()
    print("  b) Send black (all off)")
    print("  q) Quit")
    print()


def main():
    print_header()

    # Check controller reachability
    print(f"\nPinging {config.CONTROLLER_IP}...", end=" ", flush=True)
    if ping_check(config.CONTROLLER_IP):
        print("OK")
    else:
        print("NOT REACHABLE")
        print("  Warning: Controller may be offline or IP is wrong.")
        print(f"  Edit CONTROLLER_IP in ledtest/config.py")
        print("  Continuing anyway (UDP sends will still go out)...\n")

    # Build mapping and output
    mapping = build_mapping(config.MATRIX_WIDTH, config.MATRIX_HEIGHT, config.SERPENTINE)
    num_pixels = config.MATRIX_WIDTH * config.MATRIX_HEIGHT

    output = SACNOutput(
        controller_ip=config.CONTROLLER_IP,
        num_pixels=num_pixels,
        start_universe=config.START_UNIVERSE,
        pixels_per_universe=config.PIXELS_PER_UNIVERSE,
        brightness_cap=config.BRIGHTNESS_CAP,
        fps=config.FPS,
    )

    output.start()
    print("E1.31 sender started.")

    try:
        while True:
            print_menu()
            choice = input("Select pattern: ").strip().lower()

            if choice == "q":
                break
            elif choice == "b":
                output.send_black()
                print("Sent black frame (all off).")
                continue
            elif choice not in PATTERNS:
                print("Invalid choice.")
                continue

            desc, factory = PATTERNS[choice]
            print(f"\nRunning: {desc}")
            print("Press Ctrl+C to stop and return to menu.\n")

            gen = factory(config.MATRIX_WIDTH, config.MATRIX_HEIGHT)
            frame_interval = 1.0 / config.FPS

            try:
                for frame in gen:
                    t0 = time.monotonic()
                    pixels = frame_to_pixels(frame, mapping)
                    output.send_frame(pixels)
                    elapsed = time.monotonic() - t0
                    sleep_time = frame_interval - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)
            except KeyboardInterrupt:
                output.send_black()
                print("\nStopped. Sent black frame.")

    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        print("\nShutting down...")
        output.stop()
        print("Done.")


if __name__ == "__main__":
    main()
