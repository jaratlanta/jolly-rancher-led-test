"""
Model definitions for different LED display configurations.
Each model describes a set of panels with their geometry and wiring.
"""


MODELS = {
    "test_panel": {
        "name": "Test Panel",
        "panels": [
            {"name": "Matrix", "rows": 12, "cols": 24, "flip_h": False},
        ],
    },
    "jolly_rancher": {
        "name": "Jolly Rancher",
        "panels": [
            {"name": "LS Front", "rows": 24, "cols": 110, "flip_h": False},
            {"name": "LS Rear",  "rows": 24, "cols": 110, "flip_h": False},
            {"name": "Front",    "rows": 24, "cols": 72,  "flip_h": False},
            {"name": "RS Rear",  "rows": 24, "cols": 110, "flip_h": True},
            {"name": "RS Front", "rows": 24, "cols": 110, "flip_h": True},
        ],
    },
}


def get_model(key):
    """Get a model definition with computed fields."""
    model = MODELS[key]
    panels = model["panels"]

    # All panels must share the same row count
    rows = panels[0]["rows"]

    # Virtual canvas = all panels side by side
    total_cols = sum(p["cols"] for p in panels)
    total_pixels = sum(p["rows"] * p["cols"] for p in panels)

    # Compute pixel offset for each panel (where its pixels start in the linear output)
    panel_info = []
    pixel_offset = 0
    col_offset = 0
    for p in panels:
        panel_info.append({
            **p,
            "pixel_offset": pixel_offset,
            "col_offset": col_offset,
        })
        pixel_offset += p["rows"] * p["cols"]
        col_offset += p["cols"]

    return {
        "key": key,
        "name": model["name"],
        "panels": panel_info,
        "rows": rows,
        "total_cols": total_cols,
        "total_pixels": total_pixels,
    }


def get_model_list():
    """Return list of available models for UI."""
    return [
        {"key": k, "name": v["name"]}
        for k, v in MODELS.items()
    ]
