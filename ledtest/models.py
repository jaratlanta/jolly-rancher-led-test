"""
Model definitions for different LED display configurations.

Two model types:
  - "grid": 2D panel matrices (Test Panel, Jolly Rancher Panels)
  - "strands": 1D LED strands with physical path coordinates (Bull's Head)
  - "composite": combines grid + strand models (Jolly Rancher Complete)
"""


MODELS = {
    "test_panel": {
        "name": "Test Panel",
        "type": "grid",
        "panels": [
            {"name": "Matrix", "rows": 12, "cols": 24, "flip_h": False, "surface": "matrix"},
        ],
    },
    "jr_panels": {
        "name": "JR Panels",
        "type": "grid",
        # "surface" groups panels that share one continuous animation space.
        # Left Side (LS Front + LS Rear) = one animation across 220 cols
        # Front = independent animation across 72 cols
        # Right Side (RS Rear + RS Front) = one animation across 220 cols
        "panels": [
            {"name": "LS Front", "rows": 24, "cols": 110, "flip_h": False, "surface": "left"},
            {"name": "LS Rear",  "rows": 24, "cols": 110, "flip_h": False, "surface": "left"},
            {"name": "Front",    "rows": 24, "cols": 72,  "flip_h": False, "surface": "front"},
            {"name": "RS Rear",  "rows": 24, "cols": 110, "flip_h": True,  "surface": "right"},
            {"name": "RS Front", "rows": 24, "cols": 110, "flip_h": True,  "surface": "right"},
        ],
    },
    "bulls_head": {
        "name": "Bull's Head",
        "type": "strands",
        # 8 strands from bullshead.svg (viewBox 612x792).
        # Normalized: x/612, y/792. Straight polylines only.
        "strands": [
            {
                "name": "Left Inner",   # Cyan #00aeef (st0)
                "pixel_count": 100,
                "path": [
                    (0.489, 0.426), (0.489, 0.303), (0.373, 0.303), (0.327, 0.340),
                    (0.338, 0.382), (0.398, 0.427), (0.359, 0.474), (0.411, 0.578),
                    (0.397, 0.633), (0.475, 0.633),
                ],
            },
            {
                "name": "Left Outer",   # Gold #fbb040 (st2)
                "pixel_count": 100,
                "path": [
                    (0.316, 0.332), (0.135, 0.308), (0.051, 0.239), (0.107, 0.343),
                    (0.304, 0.390), (0.285, 0.405), (0.286, 0.474), (0.312, 0.520),
                    (0.262, 0.556), (0.392, 0.647), (0.419, 0.691), (0.475, 0.692),
                ],
            },
            {
                "name": "Lower Left",   # Purple #7f3f98 (st6)
                "pixel_count": 80,
                "path": [
                    (0.251, 0.565), (0.255, 0.632), (0.392, 0.719), (0.392, 0.752),
                    (0.475, 0.769),
                ],
            },
            {
                "name": "Right Inner",  # Orange #f7941d (st1)
                "pixel_count": 100,
                "path": [
                    (0.512, 0.426), (0.512, 0.303), (0.629, 0.303), (0.674, 0.340),
                    (0.664, 0.382), (0.604, 0.427), (0.642, 0.474), (0.590, 0.578),
                    (0.605, 0.633), (0.528, 0.633),
                ],
            },
            {
                "name": "Right Outer",  # Purple #7f3f98 (st6)
                "pixel_count": 100,
                "path": [
                    (0.685, 0.332), (0.866, 0.308), (0.951, 0.239), (0.895, 0.343),
                    (0.698, 0.390), (0.716, 0.405), (0.715, 0.474), (0.689, 0.520),
                    (0.739, 0.556), (0.609, 0.647), (0.582, 0.691), (0.528, 0.692),
                ],
            },
            {
                "name": "Lower Right",  # Yellow #ffde17 (st4)
                "pixel_count": 80,
                "path": [
                    (0.750, 0.565), (0.746, 0.632), (0.609, 0.719), (0.609, 0.752),
                    (0.528, 0.769),
                ],
            },
            {
                "name": "Center Left",  # Navy #2e3192 (st5)
                "pixel_count": 90,
                "path": [
                    (0.497, 0.769), (0.495, 0.436), (0.415, 0.436),
                ],
            },
            {
                "name": "Center Right", # Red #ef4136 (st3)
                "pixel_count": 90,
                "path": [
                    (0.593, 0.436), (0.508, 0.436), (0.508, 0.574),
                    (0.508, 0.584), (0.508, 0.769),
                ],
            },
        ],
    },
    "jr_complete": {
        "name": "JR Complete",
        "type": "composite",
        "includes": ["jr_panels", "bulls_head"],
    },
}

# Backward compatibility: keep "jolly_rancher" pointing to "jr_panels"
MODELS["jolly_rancher"] = MODELS["jr_panels"]


def get_model(key):
    """Get a model definition with computed fields."""
    model = MODELS[key]
    model_type = model.get("type", "grid")

    if model_type == "composite":
        return _get_composite_model(key, model)
    elif model_type == "strands":
        return _get_strand_model(key, model)
    else:
        return _get_grid_model(key, model)


def _get_grid_model(key, model):
    """Build a grid model with computed panel offsets."""
    panels = model["panels"]
    rows = panels[0]["rows"]
    total_cols = sum(p["cols"] for p in panels)
    total_pixels = sum(p["rows"] * p["cols"] for p in panels)

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

    surfaces = {}
    for p in panel_info:
        s = p.get("surface", p["name"])
        if s not in surfaces:
            surfaces[s] = {"col_start": p["col_offset"], "total_cols": 0, "rows": p["rows"]}
        surfaces[s]["total_cols"] += p["cols"]

    return {
        "key": key,
        "name": model["name"],
        "type": "grid",
        "panels": panel_info,
        "surfaces": surfaces,
        "rows": rows,
        "total_cols": total_cols,
        "total_pixels": total_pixels,
    }


def _get_strand_model(key, model):
    """Build a strand model with computed offsets."""
    strands = model["strands"]
    total_pixels = sum(s["pixel_count"] for s in strands)

    strand_info = []
    pixel_offset = 0
    for s in strands:
        strand_info.append({
            **s,
            "pixel_offset": pixel_offset,
        })
        pixel_offset += s["pixel_count"]

    return {
        "key": key,
        "name": model["name"],
        "type": "strands",
        "strands": strand_info,
        "total_pixels": total_pixels,
        "num_strands": len(strands),
        # For compatibility with grid-based code paths:
        "panels": [],
        "surfaces": {},
        "rows": len(strands),           # treat strand count as "rows"
        "total_cols": max(s["pixel_count"] for s in strands),  # longest strand
    }


def _get_composite_model(key, model):
    """Build a composite model from sub-models."""
    sub_models = [get_model(k) for k in model["includes"]]

    # Combine all sub-models
    all_panels = []
    all_strands = []
    total_pixels = 0
    grid_pixels = 0

    for sub in sub_models:
        if sub["type"] == "grid":
            # Offset panel pixels past any previous models
            for p in sub["panels"]:
                all_panels.append({
                    **p,
                    "pixel_offset": p["pixel_offset"] + total_pixels,
                })
            grid_pixels = sub["total_pixels"]
        elif sub["type"] == "strands":
            for s in sub["strands"]:
                all_strands.append({
                    **s,
                    "pixel_offset": s["pixel_offset"] + total_pixels,
                })
        total_pixels += sub["total_pixels"]

    # Use the grid model's dimensions for the virtual canvas
    grid_sub = next((s for s in sub_models if s["type"] == "grid"), None)
    strand_sub = next((s for s in sub_models if s["type"] == "strands"), None)

    return {
        "key": key,
        "name": model["name"],
        "type": "composite",
        "panels": all_panels,
        "strands": all_strands,
        "surfaces": grid_sub["surfaces"] if grid_sub else {},
        "rows": grid_sub["rows"] if grid_sub else (strand_sub["rows"] if strand_sub else 1),
        "total_cols": grid_sub["total_cols"] if grid_sub else 1,
        "total_pixels": total_pixels,
        "grid_pixels": grid_pixels,
        "includes": model["includes"],
    }


def get_model_list():
    """Return list of available models for UI (excluding backward-compat aliases)."""
    # Specific ordering for tabs
    order = ["test_panel", "jr_panels", "bulls_head", "jr_complete"]
    result = []
    for k in order:
        if k in MODELS:
            result.append({"key": k, "name": MODELS[k]["name"]})
    return result
