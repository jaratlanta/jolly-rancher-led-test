#!/usr/bin/env python3
"""
TEST PANEL — Web server for the LED testbed.
Serves the dark-mode UI, streams frames via WebSocket, and drives the Falcon controller.

Usage:
    python server.py
    # Opens http://localhost:8080
"""
import asyncio
import json
import os
import subprocess
import sys
import webbrowser

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from ledtest.web_engine import FrameEngine
from ledtest.presets import get_presets, save_preset, delete_preset, get_preset

# ─── App Setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="TEST PANEL")
engine = FrameEngine()

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

# Serve static files
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/api/state")
async def get_state():
    return JSONResponse(engine.get_state())


@app.get("/api/animations")
async def get_animations():
    from ledtest.animations import ANIMATIONS
    return JSONResponse([{"idx": i, "name": a["name"]} for i, a in enumerate(ANIMATIONS)])


@app.get("/api/palettes")
async def get_palettes():
    from ledtest.animations import PALETTES
    return JSONResponse([{"idx": i, "name": p["name"]} for i, p in enumerate(PALETTES)])


@app.get("/api/diagnostics")
async def get_diagnostics():
    from ledtest.patterns import PATTERNS
    return JSONResponse([{"key": k, "name": desc} for k, (desc, _) in PATTERNS.items()])


@app.get("/api/fx")
async def get_fx():
    from ledtest.fx import FX_LIST
    return JSONResponse(FX_LIST)


@app.get("/api/models")
async def get_models():
    from ledtest.models import get_model_list
    return JSONResponse(get_model_list())


@app.get("/api/presets")
async def get_presets_api():
    return JSONResponse(get_presets())


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    loop = asyncio.get_event_loop()
    engine.add_client(ws, loop)

    # Send initial state + presets
    await ws.send_text(json.dumps({"type": "state", "data": engine.get_state()}))
    await ws.send_text(json.dumps({"type": "presets", "data": get_presets()}))

    try:
        while True:
            raw = await ws.receive()
            # Binary messages are webcam brightness frames
            if raw.get("type") == "websocket.receive" and "bytes" in raw and raw["bytes"]:
                engine.receive_webcam_frame(raw["bytes"])
                continue

            msg = raw.get("text", "")
            if not msg:
                continue
            data = json.loads(msg)
            cmd = data.get("cmd")

            if cmd == "set_animation":
                engine.set_animation(data["idx"])
            elif cmd == "set_palette":
                engine.set_palette(data["idx"])
            elif cmd == "set_brightness":
                engine.set_brightness(data["value"])
            elif cmd == "set_speed":
                engine.set_speed(data["value"])
            elif cmd == "blackout":
                engine.set_blackout(data.get("on", True))
            elif cmd == "set_diagnostic":
                engine.set_diagnostic(data["key"])
            elif cmd == "set_fx":
                engine.set_fx(data["key"])
            elif cmd == "set_fx_intensity":
                engine.set_fx_intensity(data["value"])
            elif cmd == "set_webcam":
                engine.set_webcam(data.get("on", False))
            elif cmd == "set_model":
                engine.reconfigure(data["key"])
            elif cmd == "save_preset":
                presets_list = save_preset(data["name"], data["preset"])
                await ws.send_text(json.dumps({"type": "presets", "data": presets_list}))
            elif cmd == "delete_preset":
                presets_list = delete_preset(data["id"])
                await ws.send_text(json.dumps({"type": "presets", "data": presets_list}))
            elif cmd == "load_preset":
                p = get_preset(data["id"])
                if p and "preset" in p:
                    pd = p["preset"]
                    # Skip animation when webcam is active
                    if "animation_idx" in pd and not engine.webcam_mode:
                        engine.set_animation(pd["animation_idx"])
                    if "palette_idx" in pd:
                        engine.set_palette(pd["palette_idx"])
                    if "fx" in pd:
                        engine.set_fx(pd["fx"])
                    if "fx_intensity" in pd:
                        engine.set_fx_intensity(pd["fx_intensity"])
                    if "brightness" in pd:
                        engine.set_brightness(pd["brightness"])
                    if "speed" in pd:
                        engine.set_speed(pd["speed"])
            elif cmd == "get_state":
                pass  # just respond with state below

            # Always respond with current state after a command
            await ws.send_text(json.dumps({"type": "state", "data": engine.get_state()}))

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        engine.remove_client(ws)


# ─── Lifecycle ────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    print("\n" + "=" * 50)
    print("  TEST PANEL — LED Testbed Controller")
    print(f"  Matrix: {engine.width}x{engine.height} ({engine.num_pixels} pixels)")
    print(f"  Controller: {engine.sacn.controller_ip}")
    print(f"  Brightness: {engine.brightness}/255")
    print("=" * 50)

    # Ping controller
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", engine.sacn.controller_ip],
            capture_output=True, timeout=3
        )
        if result.returncode == 0:
            print(f"  Controller: ONLINE ✓")
        else:
            print(f"  Controller: NOT REACHABLE ✗")
            print(f"  (UDP will still send — check IP/network)")
    except Exception:
        print(f"  Controller: ping failed")

    print()
    engine.start()
    print(f"  E1.31 sender started")
    print(f"  Open http://localhost:8080")
    print("=" * 50 + "\n")


@app.on_event("shutdown")
async def shutdown():
    print("\nShutting down...")
    engine.stop()
    print("Done.")


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Auto-open browser after a short delay
    import threading
    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open("http://localhost:8080")
    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
