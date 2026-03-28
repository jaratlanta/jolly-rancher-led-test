#!/usr/bin/env python3
"""Quick test script to see what the Baseline Knob V2.1 sends.
Run this, then press buttons and turn the dial. Press Ctrl+C to stop."""

import hid

VID = 0x4244
PID = 0x4b4e

print("Opening all KNOB V2.1 HID interfaces...")
print("Press buttons and turn the dial. Ctrl+C to stop.\n")

devices = []
seen_paths = set()

for info in hid.enumerate(VID, PID):
    path = info['path']
    if path in seen_paths:
        continue
    seen_paths.add(path)

    iface = info['interface_number']
    usage_page = info['usage_page']
    usage = info['usage']
    label = f"iface={iface} usage_page=0x{usage_page:04x} usage=0x{usage:04x}"

    try:
        d = hid.device()
        d.open_path(path)
        d.set_nonblocking(True)
        devices.append((d, label, path))
        print(f"  Opened: {label}")
    except Exception as e:
        print(f"  FAILED: {label} — {e}")

print(f"\nListening on {len(devices)} interfaces...\n")

try:
    while True:
        for d, label, path in devices:
            data = d.read(64)
            if data:
                hex_str = ' '.join(f'{b:02x}' for b in data)
                print(f"[{label}]  {hex_str}")
except KeyboardInterrupt:
    print("\nDone.")
finally:
    for d, _, _ in devices:
        d.close()
