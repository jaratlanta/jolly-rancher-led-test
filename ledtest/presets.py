"""
Preset management — saves/loads animation+palette+FX combos to a JSON file.
"""
import json
import os
import time
import uuid

from .animations import ANIMATIONS, PALETTES

PRESETS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "presets.json")


def _load_file():
    """Load presets from disk."""
    if os.path.exists(PRESETS_FILE):
        try:
            with open(PRESETS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save_file(presets):
    """Save presets to disk."""
    with open(PRESETS_FILE, "w") as f:
        json.dump(presets, f, indent=2)


def get_presets():
    """Return all presets with resolved names for display."""
    presets = _load_file()
    # Enrich with current animation/palette names
    for p in presets:
        data = p.get("preset", {})
        ai = data.get("animation_idx", 0)
        pi = data.get("palette_idx", 0)
        if ai < len(ANIMATIONS):
            data["animation_name"] = ANIMATIONS[ai]["name"]
        if pi < len(PALETTES):
            data["palette_name"] = PALETTES[pi]["name"]
    return presets


def save_preset(name, preset_data):
    """Save a new preset. Returns the full presets list."""
    presets = _load_file()
    entry = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "created": time.time(),
        "preset": preset_data,
    }
    presets.append(entry)
    _save_file(presets)
    return get_presets()


def delete_preset(preset_id):
    """Delete a preset by ID. Returns the full presets list."""
    presets = _load_file()
    presets = [p for p in presets if p.get("id") != preset_id]
    _save_file(presets)
    return get_presets()


def get_preset(preset_id):
    """Get a single preset by ID."""
    presets = _load_file()
    for p in presets:
        if p.get("id") == preset_id:
            return p
    return None
