/**
 * TEST PANEL / JOLLY RANCHER — Frontend
 * Connects to the Python server via WebSocket, renders LED matrix previews,
 * and sends control commands. Supports runtime model switching and presets.
 */

// ─── State ───────────────────────────────────────────────────────────────────

let ws = null;
let state = {};
let connected = false;
let modelList = [];
let presets = [];

// Virtual canvas dimensions (all panels combined)
let vcWidth = 24;
let vcHeight = 12;
let panels = [];

// Cycle state
let cycleActive = false;
let cycleTimerId = null;
let cycleCountdownId = null;
let cycleNextTime = 0;
let cyclePrevPresetIdx = -1;

// Webcam state
let webcamActive = false;
let waveformActive = false;
let waveformAudioMode = false;
let wfFftArray = null;
let wfTdArray = null;
let webcamStream = null;
let webcamVideo = null;
let webcamSampleCanvas = null;
let webcamSampleCtx = null;
let webcamIntervalId = null;

// Model type
let modelType = 'grid';
let strandInfo = [];  // strand paths + pixel counts for bull's head rendering

// ─── Canvas References ──────────────────────────────────────────────────────

const singleCanvas = document.getElementById('matrix-canvas');
const singleCtx = singleCanvas.getContext('2d');
const frontCanvas = document.getElementById('front-canvas');
const frontCtx = frontCanvas.getContext('2d');
const leftCanvas = document.getElementById('left-canvas');
const leftCtx = leftCanvas.getContext('2d');
const rightCanvas = document.getElementById('right-canvas');
const rightCtx = rightCanvas.getContext('2d');
const bullheadCanvas = document.getElementById('bullhead-canvas');
const bullheadCtx = bullheadCanvas.getContext('2d');
const completeBullheadCanvas = document.getElementById('complete-bullhead-canvas');
const completeBullheadCtx = completeBullheadCanvas.getContext('2d');
const completeFrontCanvas = document.getElementById('complete-front-canvas');
const completeFrontCtx = completeFrontCanvas.getContext('2d');
const completeLeftCanvas = document.getElementById('complete-left-canvas');
const completeLeftCtx = completeLeftCanvas.getContext('2d');
const completeRightCanvas = document.getElementById('complete-right-canvas');
const completeRightCtx = completeRightCanvas.getContext('2d');

// ─── Responsive Sizing ─────────────────────────────────────────────────────

function getContainerWidth() {
    const main = document.querySelector('.main');
    if (!main) return 900;
    // Account for padding on the .main and .matrix-container/.panel-wrap
    return main.clientWidth - 2;  // 2px for borders
}

function calcLedParams(cols, rows, maxWidth) {
    maxWidth = maxWidth || getContainerWidth() - 42;  // subtract container padding
    const padding = Math.max(8, Math.min(16, maxWidth * 0.02));
    const available = maxWidth - padding * 2;
    let spacing = available / cols;
    spacing = Math.max(2, Math.min(28, spacing));
    const radius = Math.max(1, spacing * 0.36);
    const glow = Math.max(0.5, spacing * 0.29);
    return { spacing, radius, glow, padding };
}

// ─── LED Rendering ──────────────────────────────────────────────────────────

function renderToCanvas(ctx, canvas, frameData, cols, rows, colOffset, params) {
    const { spacing, radius, glow, padding } = params;
    const w = Math.ceil(cols * spacing + padding * 2);
    const h = Math.ceil(rows * spacing + padding * 2);

    // Only resize if dimensions changed (avoids flicker)
    if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
    }

    ctx.fillStyle = '#050508';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    for (let y = 0; y < rows; y++) {
        for (let x = 0; x < cols; x++) {
            const srcX = colOffset + x;
            const idx = (y * vcWidth + srcX) * 3;
            const r = frameData[idx] || 0;
            const g = frameData[idx + 1] || 0;
            const b = frameData[idx + 2] || 0;

            const cx = padding + x * spacing + spacing / 2;
            const cy = padding + y * spacing + spacing / 2;

            const brightness = (r + g + b) / 3;
            // Large bright glow halo
            if (brightness > 5 && glow > 0.5) {
                const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius + glow * 1.5);
                grad.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.7)`);
                grad.addColorStop(0.5, `rgba(${r}, ${g}, ${b}, 0.3)`);
                grad.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
                ctx.fillStyle = grad;
                ctx.fillRect(cx - radius - glow * 1.5, cy - radius - glow * 1.5,
                    (radius + glow * 1.5) * 2, (radius + glow * 1.5) * 2);
            }

            // Larger LED dot (fills more space between pixels)
            ctx.beginPath();
            ctx.arc(cx, cy, radius * 0.75, 0, Math.PI * 2);
            ctx.fillStyle = `rgb(${Math.min(255, r)}, ${Math.min(255, g)}, ${Math.min(255, b)})`;
            ctx.fill();

            if (brightness < 10) {
                ctx.strokeStyle = 'rgba(255,255,255,0.04)';
                ctx.lineWidth = 0.5;
                ctx.stroke();
            }
        }
    }
}

// ─── Layout Management ──────────────────────────────────────────────────────

function updateLayout() {
    const singleView = document.getElementById('single-view');
    const ushapeView = document.getElementById('ushape-view');
    const bullheadView = document.getElementById('bullhead-view');
    const completeView = document.getElementById('complete-view');

    // Hide all views
    singleView.classList.add('hidden');
    ushapeView.classList.add('hidden');
    bullheadView.classList.add('hidden');
    completeView.classList.add('hidden');

    if (modelType === 'strands') {
        bullheadView.classList.remove('hidden');
    } else if (modelType === 'composite') {
        completeView.classList.remove('hidden');
    } else if (panels.length > 1) {
        ushapeView.classList.remove('hidden');
    } else {
        singleView.classList.remove('hidden');
    }

    // Show symmetry toggle only for strand/composite models
    const symRow = document.getElementById('symmetry-row');
    if (modelType === 'strands' || modelType === 'composite') {
        symRow.style.display = '';
    } else {
        symRow.style.display = 'none';
    }
}

function renderFrame(frameData) {
    if (modelType === 'strands') {
        renderStrandsToCanvas(bullheadCtx, bullheadCanvas, frameData, strandInfo);
    } else if (modelType === 'composite') {
        // Render panels to complete-view canvases
        if (panels.length >= 5) {
            renderPanelsToCanvases(frameData, completeFrontCtx, completeFrontCanvas,
                completeLeftCtx, completeLeftCanvas, completeRightCtx, completeRightCanvas);
        }
        // Render strands to complete-bullhead canvas
        // Strand pixels come after the grid pixels in the frame data
        const gridPixels = panels.reduce((sum, p) => sum + p.rows * p.cols, 0);
        const strandData = frameData.slice(gridPixels * 3);

        // Size bull head relative to front panel: bull = 84" (7ft), front panel = 24"
        // So bull head height = 3.5× front panel height
        // Front panel height in pixels = rows * spacing
        const containerW = getContainerWidth() - 42;
        const sideParams = calcLedParams(220, vcHeight, containerW);
        const frontPanelH = vcHeight * sideParams.spacing;
        const bullTargetH = frontPanelH * 3.5;

        // Content aspect ratio
        const PAD = 0.02;
        const RANGE_X = (0.96 + PAD) - (0.04 - PAD);
        const RANGE_Y = (0.78 + PAD) - (0.22 - PAD);
        const bullCanvasW = Math.round(bullTargetH * (RANGE_X / RANGE_Y));

        // Match dot size to panel LED size
        const bullDot = sideParams.radius * 0.4;
        const bullGlow = sideParams.radius * 0.6;

        renderStrandsToCanvas(completeBullheadCtx, completeBullheadCanvas, strandData, strandInfo,
            { canvasW: bullCanvasW, dotSize: bullDot, glowSize: bullGlow });
    } else if (panels.length > 1) {
        renderPanelsToCanvases(frameData, frontCtx, frontCanvas,
            leftCtx, leftCanvas, rightCtx, rightCanvas);
    } else {
        const cols = vcWidth;
        const rows = vcHeight;
        const containerW = getContainerWidth() - 42;
        const params = calcLedParams(cols, rows, containerW);
        renderToCanvas(singleCtx, singleCanvas, frameData, cols, rows, 0, params);
    }
}

function renderPanelsToCanvases(frameData, fCtx, fCanvas, lCtx, lCanvas, rCtx, rCanvas) {
    const lsFront = panels[0];
    const lsRear = panels[1];
    const front = panels[2];
    const rsRear = panels[3];
    const rsFront = panels[4];

    const leftCols = lsFront.cols + lsRear.cols;
    const rightCols = rsRear.cols + rsFront.cols;
    const frontCols = front.cols;
    const rows = vcHeight;

    const containerW = getContainerWidth() - 42;

    // Use the widest panel (side) as the reference for consistent dot sizing.
    // All panels share the same spacing so dots are the same size everywhere.
    const maxCols = Math.max(leftCols, rightCols);
    const refParams = calcLedParams(maxCols, rows, containerW);
    const spacing = refParams.spacing;
    const radius = refParams.radius;
    const glow = refParams.glow;
    const padding = refParams.padding;

    // Front uses same dot size but is narrower (fewer cols)
    const sharedParams = { spacing, radius, glow, padding };

    renderToCanvas(fCtx, fCanvas, frameData, frontCols, rows, front.col_offset, sharedParams);
    renderToCanvas(lCtx, lCanvas, frameData, leftCols, rows, lsFront.col_offset, sharedParams);
    renderToCanvas(rCtx, rCanvas, frameData, rightCols, rows, rsRear.col_offset, sharedParams);
}

function renderStrandsToCanvas(ctx, canvas, pixelData, strands, opts) {
    // Draw strands as colored dots along straight-line polyline paths.
    // Crop to actual content bounds (SVG content spans y=0.22 to y=0.78, x=0.04 to 0.96)
    const PAD = 0.02;
    const MIN_X = 0.04 - PAD, MAX_X = 0.96 + PAD;
    const MIN_Y = 0.22 - PAD, MAX_Y = 0.78 + PAD;
    const RANGE_X = MAX_X - MIN_X;
    const RANGE_Y = MAX_Y - MIN_Y;

    // opts.canvasW overrides default width; opts.dotSize/glowSize override dot sizes
    const canvasW = (opts && opts.canvasW) || 600;
    const canvasH = Math.round(canvasW * (RANGE_Y / RANGE_X));
    canvas.width = canvasW;
    canvas.height = canvasH;

    ctx.fillStyle = '#0a0a0f';
    ctx.fillRect(0, 0, canvasW, canvasH);

    let pixelIdx = 0;
    const dotSize = (opts && opts.dotSize) || 1.5;
    const glowSize = (opts && opts.glowSize) || 4;

    // Remap normalized coord to canvas pixel
    const toX = (nx) => ((nx - MIN_X) / RANGE_X) * canvasW;
    const toY = (ny) => ((ny - MIN_Y) / RANGE_Y) * canvasH;

    for (const strand of strands) {
        const path = strand.path || [];
        const pc = strand.pixel_count || 0;
        if (path.length < 2) { pixelIdx += pc; continue; }

        // Compute cumulative distance along polyline segments (in canvas pixels)
        const segLengths = [];
        let totalLen = 0;
        for (let i = 1; i < path.length; i++) {
            const dx = toX(path[i][0]) - toX(path[i-1][0]);
            const dy = toY(path[i][1]) - toY(path[i-1][1]);
            const len = Math.sqrt(dx*dx + dy*dy);
            segLengths.push(len);
            totalLen += len;
        }

        // Place each pixel at evenly-spaced distance along the polyline
        for (let pi = 0; pi < pc; pi++) {
            const targetDist = (pi / Math.max(pc - 1, 1)) * totalLen;

            // Walk segments to find position
            let walked = 0;
            let px = toX(path[0][0]);
            let py = toY(path[0][1]);

            for (let si = 0; si < segLengths.length; si++) {
                const segLen = segLengths[si];
                if (walked + segLen >= targetDist || si === segLengths.length - 1) {
                    const remaining = targetDist - walked;
                    const frac = segLen > 0 ? remaining / segLen : 0;
                    const nx = path[si][0] + (path[si+1][0] - path[si][0]) * frac;
                    const ny = path[si][1] + (path[si+1][1] - path[si][1]) * frac;
                    px = toX(nx);
                    py = toY(ny);
                    break;
                }
                walked += segLen;
            }

            // Get pixel color
            const dataIdx = pixelIdx * 3;
            const r = pixelData[dataIdx] || 0;
            const g = pixelData[dataIdx + 1] || 0;
            const b = pixelData[dataIdx + 2] || 0;

            // Draw glow
            if (r > 10 || g > 10 || b > 10) {
                ctx.globalAlpha = 0.3;
                ctx.fillStyle = `rgb(${r},${g},${b})`;
                ctx.beginPath();
                ctx.arc(px, py, glowSize, 0, Math.PI * 2);
                ctx.fill();
            }

            // Draw dot
            ctx.globalAlpha = 1.0;
            ctx.fillStyle = `rgb(${r},${g},${b})`;
            ctx.beginPath();
            ctx.arc(px, py, dotSize, 0, Math.PI * 2);
            ctx.fill();

            pixelIdx++;
        }
    }
    ctx.globalAlpha = 1.0;
}

// Debounced resize handler
let resizeTimeout;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
        // Re-render with new dimensions on next frame
    }, 100);
});

// Render blank on load
renderFrame(new Uint8Array(vcWidth * vcHeight * 3));

// ─── WebSocket Connection ────────────────────────────────────────────────────

function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws`);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
        connected = true;
        updateConnectionStatus();
    };

    ws.onclose = () => {
        connected = false;
        updateConnectionStatus();
        setTimeout(connect, 2000);
    };

    ws.onerror = () => { ws.close(); };

    ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
            renderFrame(new Uint8Array(event.data));
        } else {
            const msg = JSON.parse(event.data);
            if (msg.type === 'state') {
                state = msg.data;
                vcWidth = state.width || 24;
                vcHeight = state.height || 12;
                panels = state.panels || [];
                modelType = state.model_type || 'grid';
                strandInfo = state.strands || [];
                updateLayout();
                updateUI();
            } else if (msg.type === 'presets') {
                presets = msg.data || [];
                renderPresetsList();
            }
        }
    };
}

function send(cmd) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(cmd));
    }
}

// ─── UI Updates ──────────────────────────────────────────────────────────────

function updateConnectionStatus() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    if (connected) {
        dot.classList.add('connected');
        text.textContent = state.controller_ip || 'Connected';
    } else {
        dot.classList.remove('connected');
        text.textContent = 'Reconnecting...';
    }
}

function updateUI() {
    // Model toggle
    document.querySelectorAll('.model-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.key === state.model_key);
    });

    document.title = state.model_name || 'TEST PANEL';

    // Animation
    document.getElementById('anim-name').textContent = state.pattern_name || '—';
    document.getElementById('anim-sub').textContent =
        `Pattern ${(state.pattern_idx || 0) + 1}/${state.pattern_count || 0}`;

    // Palette
    document.getElementById('pal-name').textContent = state.palette_name || '—';
    document.getElementById('pal-sub').textContent =
        `Palette ${(state.palette_idx || 0) + 1}/${state.palette_count || 0}`;

    // Waveform labels (always update so they're current when switching sources)
    document.getElementById('wf-name').textContent = state.waveform_name || '—';
    document.getElementById('wf-sub').textContent = `Visualizer ${(state.waveform_idx || 0) + 1}/${state.waveform_count || 20}`;
    document.getElementById('wf-pal-name').textContent = state.palette_name || '—';
    document.getElementById('wf-pal-sub').textContent = `Palette ${(state.palette_idx || 0) + 1}/${state.palette_count || 0}`;

    // Sync waveform active state from server
    if (state.waveform_mode && !waveformActive) {
        waveformActive = true;
        updateSourceUI();
    } else if (!state.waveform_mode && waveformActive && !webcamActive) {
        // Don't auto-deactivate if we just set it locally
    }

    // Brightness
    const brSlider = document.getElementById('brightness-slider');
    const brValue = document.getElementById('brightness-value');
    brSlider.value = state.brightness || 128;
    brValue.textContent = Math.round((state.brightness || 128) / 255 * 100) + '%';

    // Manual BPM
    const spSlider = document.getElementById('speed-slider');
    const spValue = document.getElementById('speed-value');
    const manualBpm = state.manual_bpm || 120;
    spSlider.value = manualBpm;
    spValue.textContent = manualBpm;

    // Blackout
    const blackoutBtn = document.getElementById('blackout-btn');
    if (state.blackout) {
        blackoutBtn.classList.add('active');
        blackoutBtn.textContent = 'LIGHTS OFF';
    } else {
        blackoutBtn.classList.remove('active');
        blackoutBtn.textContent = 'All Off';
    }

    // Webcam palette row sync
    document.getElementById('pal-name-wc').textContent = state.palette_name || '—';
    document.getElementById('pal-sub-wc').textContent =
        `Palette ${(state.palette_idx || 0) + 1}/${state.palette_count || 0}`;

    // Diagnostic mode
    const diagSelect = document.getElementById('diag-select');
    if (state.diagnostic_mode && state.diagnostic_key) {
        diagSelect.value = state.diagnostic_key;
    } else {
        diagSelect.value = '';
    }

    // FX
    updateFXDisplay();

    // Symmetry toggle sync
    const symOn = state.symmetry !== false; // default true
    const symOnEl = document.getElementById('sym-on-btn');
    const symOffEl = document.getElementById('sym-off-btn');
    if (symOnEl) symOnEl.classList.toggle('active', symOn);
    if (symOffEl) symOffEl.classList.toggle('active', !symOn);

    // Audio / animation mode
    updateAnimModeUI();

    // Status bar
    document.getElementById('fps-display').textContent = `${state.fps || 30} fps`;
    document.getElementById('pixel-display').textContent =
        `${(state.num_pixels || 288).toLocaleString()} pixels`;
    document.getElementById('size-display').textContent =
        panels.length > 1
            ? `${panels.length} panels`
            : `${vcWidth} x ${vcHeight}`;
    document.getElementById('ip-display').textContent = state.controller_ip || '—';

    updateConnectionStatus();
}

// ─── Load Models ─────────────────────────────────────────────────────────────

async function loadModels() {
    try {
        const resp = await fetch('/api/models');
        modelList = await resp.json();
        const container = document.getElementById('model-toggle');
        container.innerHTML = '';
        modelList.forEach(m => {
            const btn = document.createElement('button');
            btn.className = 'model-btn';
            btn.textContent = m.name;
            btn.dataset.key = m.key;
            btn.addEventListener('click', () => {
                send({ cmd: 'set_model', key: m.key });
            });
            container.appendChild(btn);
        });
    } catch (e) {
        console.warn('Failed to load models:', e);
    }
}

function cycleModel() {
    if (modelList.length < 2) return;
    const currentKey = state.model_key || 'test_panel';
    const currentIdx = modelList.findIndex(m => m.key === currentKey);
    const nextIdx = (currentIdx + 1) % modelList.length;
    send({ cmd: 'set_model', key: modelList[nextIdx].key });
}

// ─── Load Diagnostics ────────────────────────────────────────────────────────

async function loadDiagnostics() {
    try {
        const resp = await fetch('/api/diagnostics');
        const items = await resp.json();
        const select = document.getElementById('diag-select');
        items.forEach(item => {
            const opt = document.createElement('option');
            opt.value = item.key;
            opt.textContent = item.name;
            select.appendChild(opt);
        });
    } catch (e) {
        console.warn('Failed to load diagnostics:', e);
    }
}

// ─── Load FX ─────────────────────────────────────────────────────────────────

let fxList = [];

async function loadFX() {
    try {
        const resp = await fetch('/api/fx');
        fxList = await resp.json();
    } catch (e) {
        console.warn('Failed to load FX:', e);
    }
}

function updateFXDisplay() {
    const currentFX = state.fx || 'none';
    const fxObj = fxList.find(f => f.key === currentFX);
    const fxName = fxObj ? fxObj.name : 'None';

    // Update all FX name displays (pattern row and waveform row)
    ['fx-name', 'wf-fx-name'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = fxName;
    });
    ['fx-sub', 'wf-fx-sub'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = 'FX';
    });

    // FX intensity row
    const intensityRow = document.getElementById('fx-intensity-row');
    if (currentFX !== 'none') {
        intensityRow.style.display = '';
        document.getElementById('fx-intensity-slider').value =
            Math.round((state.fx_intensity || 0.5) * 100);
        document.getElementById('fx-intensity-value').textContent =
            Math.round((state.fx_intensity || 0.5) * 100) + '%';
    } else {
        intensityRow.style.display = 'none';
    }
}

function cycleFX(direction) {
    if (fxList.length === 0) return;
    const currentKey = state.fx || 'none';
    const currentIdx = fxList.findIndex(f => f.key === currentKey);
    const nextIdx = (currentIdx + direction + fxList.length) % fxList.length;
    send({ cmd: 'set_fx', key: fxList[nextIdx].key });
}

// ─── Presets ─────────────────────────────────────────────────────────────────

let currentPresetIdx = -1;

function randomize() {
    const animIdx = Math.floor(Math.random() * (state.pattern_count || 90));
    const palIdx = Math.floor(Math.random() * (state.palette_count || 32));
    send({ cmd: 'set_pattern', idx: animIdx });
    send({ cmd: 'set_palette', idx: palIdx });
    currentPresetIdx = -1;
}

function cyclePreset(direction) {
    if (presets.length === 0) return;
    currentPresetIdx = (currentPresetIdx + direction + presets.length) % presets.length;
    loadPreset(presets[currentPresetIdx].id);
    highlightPreset();
}

function highlightPreset() {
    document.querySelectorAll('.preset-row').forEach((row, i) => {
        row.classList.toggle('preset-active', i === currentPresetIdx);
    });
}

function savePreset() {
    const fx = (state.fx && state.fx !== 'none') ? state.fx : null;
    const parts = [
        state.pattern_name || 'Unknown',
        state.palette_name || 'Unknown',
    ];
    if (fx) parts.push(fx.charAt(0).toUpperCase() + fx.slice(1));
    parts.push(Math.round((state.brightness || 128) / 255 * 100) + '%');
    parts.push((state.manual_bpm || 120) + 'bpm');
    const name = parts.join(' / ');

    send({
        cmd: 'save_preset',
        name,
        preset: {
            pattern_idx: state.pattern_idx,
            palette_idx: state.palette_idx,
            fx: state.fx || 'none',
            fx_intensity: state.fx_intensity || 0.5,
            brightness: state.brightness,
            manual_bpm: state.manual_bpm || 120,
        }
    });
}

function loadPreset(id) {
    send({ cmd: 'load_preset', id });
}

function deletePreset(id) {
    send({ cmd: 'delete_preset', id });
}

function renderPresetsList() {
    const list = document.getElementById('presets-list');
    if (!list) return;

    if (presets.length === 0) {
        list.innerHTML = '<div class="preset-empty">No saved presets</div>';
        return;
    }

    list.innerHTML = '';
    presets.forEach(p => {
        const row = document.createElement('div');
        row.className = 'preset-row';

        const info = document.createElement('div');
        info.className = 'preset-info';
        info.addEventListener('click', () => loadPreset(p.id));
        info.innerHTML = `
            <div class="preset-name">${p.name}</div>
            <div class="preset-detail">${p.preset.pattern_name || '?'} &middot; ${p.preset.palette_name || '?'}${p.preset.fx && p.preset.fx !== 'none' ? ' &middot; ' + p.preset.fx : ''}</div>
        `;

        const del = document.createElement('button');
        del.className = 'preset-delete';
        del.textContent = '\u00d7';
        del.title = 'Delete preset';
        del.addEventListener('click', (e) => {
            e.stopPropagation();
            deletePreset(p.id);
        });

        row.appendChild(info);
        row.appendChild(del);
        list.appendChild(row);
    });
}

// ─── Preset Cycle ────────────────────────────────────────────────────────────

function toggleCycle() {
    if (cycleActive) {
        stopCycle();
    } else {
        startCycle();
    }
}

function startCycle() {
    if (presets.length === 0) return;
    cycleActive = true;
    cyclePrevPresetIdx = currentPresetIdx;

    updateCycleUI();
    cycleNext();  // load first one immediately
    scheduleCycle();
}

function stopCycle() {
    cycleActive = false;
    if (cycleTimerId) { clearTimeout(cycleTimerId); cycleTimerId = null; }
    if (cycleCountdownId) { clearInterval(cycleCountdownId); cycleCountdownId = null; }
    updateCycleUI();
}

function getCycleInterval() {
    return parseInt(document.getElementById('cycle-interval').value) * 1000;
}

function scheduleCycle() {
    if (!cycleActive) return;
    const interval = getCycleInterval();
    cycleNextTime = Date.now() + interval;

    // Update countdown every second
    if (cycleCountdownId) clearInterval(cycleCountdownId);
    cycleCountdownId = setInterval(updateCountdown, 1000);
    updateCountdown();

    if (cycleTimerId) clearTimeout(cycleTimerId);
    cycleTimerId = setTimeout(() => {
        if (!cycleActive) return;
        cycleNext();
        scheduleCycle();
    }, interval);
}

function cycleNext() {
    if (presets.length === 0) { stopCycle(); return; }
    currentPresetIdx = (currentPresetIdx + 1) % presets.length;
    loadPreset(presets[currentPresetIdx].id);
    highlightPreset();
}

function updateCountdown() {
    const el = document.getElementById('cycle-countdown');
    if (!cycleActive) { el.textContent = ''; return; }
    const remaining = Math.max(0, Math.ceil((cycleNextTime - Date.now()) / 1000));
    el.textContent = remaining + 's';
}

function updateCycleUI() {
    const btn = document.getElementById('cycle-btn');
    const countdown = document.getElementById('cycle-countdown');
    if (cycleActive) {
        btn.classList.add('active');
        btn.textContent = 'Stop';
        countdown.classList.remove('hidden');
    } else {
        btn.classList.remove('active');
        btn.textContent = 'Cycle';
        countdown.classList.add('hidden');
        countdown.textContent = '';
    }
}

// ─── Webcam ──────────────────────────────────────────────────────────────────

function initWebcamElements() {
    // Create hidden video + canvas for sampling
    webcamVideo = document.createElement('video');
    webcamVideo.id = 'webcam-video';
    webcamVideo.autoplay = true;
    webcamVideo.playsInline = true;
    webcamVideo.muted = true;
    document.body.appendChild(webcamVideo);

    webcamSampleCanvas = document.createElement('canvas');
    webcamSampleCanvas.id = 'webcam-sample-canvas';
    document.body.appendChild(webcamSampleCanvas);
    webcamSampleCtx = webcamSampleCanvas.getContext('2d', { willReadFrequently: true });
}

async function startWebcam() {
    try {
        webcamStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'user', width: { ideal: 320 }, height: { ideal: 240 } }
        });
        webcamVideo.srcObject = webcamStream;
        await webcamVideo.play();
        webcamActive = true;

        send({ cmd: 'set_webcam', on: true });

        // Start sampling loop
        webcamIntervalId = setInterval(sampleWebcam, 1000 / 30); // 30fps

        updateSourceUI();
    } catch (err) {
        console.error('Webcam access denied:', err);
        alert('Could not access webcam. Check browser permissions.');
    }
}

function stopWebcam() {
    webcamActive = false;

    if (webcamIntervalId) {
        clearInterval(webcamIntervalId);
        webcamIntervalId = null;
    }

    if (webcamStream) {
        webcamStream.getTracks().forEach(t => t.stop());
        webcamStream = null;
    }

    if (webcamVideo) {
        webcamVideo.srcObject = null;
    }

    send({ cmd: 'set_webcam', on: false });
    updateSourceUI();
}

function toggleWebcam() {
    if (webcamActive) {
        stopWebcam();
    } else {
        startWebcam();
    }
}

// ─── Waveform Mode ──────────────────────────────────────────────────────────

let wfAudioCtx = null;
let wfAnalyser = null;
let wfStream = null;
let wfAnimFrameId = null;

function startWaveform() {
    waveformActive = true;
    send({ cmd: 'set_waveform', on: true });
    updateSourceUI();
}

function stopWaveform() {
    waveformActive = false;
    waveformAudioMode = false;
    stopWaveformAudio();
    send({ cmd: 'set_waveform', on: false });
    send({ cmd: 'set_waveform_audio', on: false });
    updateSourceUI();
}

async function startWaveformAudio() {
    try {
        wfStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        wfAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const source = wfAudioCtx.createMediaStreamSource(wfStream);
        wfAnalyser = wfAudioCtx.createAnalyser();
        wfAnalyser.fftSize = 256;  // 128 frequency bins
        source.connect(wfAnalyser);
        wfFftArray = new Uint8Array(wfAnalyser.frequencyBinCount);  // 128
        wfTdArray = new Uint8Array(wfAnalyser.frequencyBinCount);   // 128

        // Also enable the main audio engine for beat detection
        send({ cmd: 'set_audio_enabled', on: true });

        wfSendLoop();
    } catch (err) {
        console.error('Waveform mic denied:', err);
        waveformAudioMode = false;
        updateSourceUI();
    }
}

function stopWaveformAudio() {
    if (wfAnimFrameId) {
        cancelAnimationFrame(wfAnimFrameId);
        wfAnimFrameId = null;
    }
    if (wfStream) {
        wfStream.getTracks().forEach(t => t.stop());
        wfStream = null;
    }
    if (wfAudioCtx) {
        wfAudioCtx.close().catch(() => {});
        wfAudioCtx = null;
        wfAnalyser = null;
    }
}

function wfSendLoop() {
    if (!waveformAudioMode || !wfAnalyser) return;

    wfAnalyser.getByteFrequencyData(wfFftArray);
    wfAnalyser.getByteTimeDomainData(wfTdArray);

    // Send as binary: 1 type byte (0x02) + 128 FFT + 128 TD = 257 bytes
    if (ws && ws.readyState === WebSocket.OPEN) {
        const buf = new Uint8Array(257);
        buf[0] = 0x02;  // type marker
        buf.set(wfFftArray, 1);
        buf.set(wfTdArray, 129);
        ws.send(buf.buffer);
    }

    // Also send band values for the main audio engine (beat detection etc.)
    let bass = 0;
    for (let i = 1; i < 8; i++) bass += wfFftArray[i];
    bass = (bass / 7) / 255;
    let mid = 0;
    for (let i = 10; i < 30; i++) mid += wfFftArray[i];
    mid = (mid / 20) / 255;
    let treble = 0;
    for (let i = 35; i < 128; i++) treble += wfFftArray[i];
    treble = (treble / (128 - 35)) / 255;
    send({ cmd: 'audio_data', bass, mid, treble });

    wfAnimFrameId = requestAnimationFrame(wfSendLoop);
}

function sampleWebcam() {
    if (!webcamActive || !webcamVideo || webcamVideo.readyState < 2) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    const vidW = webcamVideo.videoWidth;
    const vidH = webcamVideo.videoHeight;
    if (!vidW || !vidH) return;

    webcamSampleCanvas.width = vcWidth;
    webcamSampleCanvas.height = vcHeight;

    // For multi-panel models, draw the webcam into each panel's region independently
    // so each panel gets a properly aspect-ratio-fitted webcam image.
    // For single-panel (test panel), just fit the whole canvas.
    if (panels.length > 1) {
        // Draw webcam fitted into each panel's region
        for (const p of panels) {
            _drawWebcamFitted(webcamSampleCtx, webcamVideo, vidW, vidH,
                p.col_offset, 0, p.cols, vcHeight);
        }
    } else {
        // Single panel — fit webcam to full canvas
        _drawWebcamFitted(webcamSampleCtx, webcamVideo, vidW, vidH,
            0, 0, vcWidth, vcHeight);
    }

    const imageData = webcamSampleCtx.getImageData(0, 0, vcWidth, vcHeight);
    const data = imageData.data;

    const brightness = new Uint8Array(vcWidth * vcHeight);
    for (let i = 0; i < brightness.length; i++) {
        const r = data[i * 4];
        const g = data[i * 4 + 1];
        const b = data[i * 4 + 2];
        brightness[i] = Math.round(r * 0.299 + g * 0.587 + b * 0.114);
    }

    ws.send(brightness.buffer);
}

function _drawWebcamFitted(ctx, video, vidW, vidH, destX, destY, destW, destH) {
    // "Cover" fit: crop the webcam to fill the destination region
    // without stretching. Maintains aspect ratio, center-crops the excess.
    const destAspect = destW / destH;
    const vidAspect = vidW / vidH;

    let srcX, srcY, srcW, srcH;
    if (vidAspect > destAspect) {
        // Video is wider than dest — crop sides
        srcH = vidH;
        srcW = vidH * destAspect;
        srcX = (vidW - srcW) / 2;
        srcY = 0;
    } else {
        // Video is taller than dest — crop top/bottom
        srcW = vidW;
        srcH = vidW / destAspect;
        srcX = 0;
        srcY = (vidH - srcH) / 2;
    }

    // Mirror horizontally for selfie-style
    ctx.save();
    ctx.translate(destX + destW, destY);
    ctx.scale(-1, 1);
    ctx.drawImage(video, srcX, srcY, srcW, srcH, 0, 0, destW, destH);
    ctx.restore();
}

function updateSourceUI() {
    const animBtn = document.getElementById('source-anim-btn');
    const wfBtn = document.getElementById('source-waveform-btn');
    const wcBtn = document.getElementById('source-webcam-btn');
    const animRow = document.getElementById('anim-nav-row');
    const wfRow = document.getElementById('waveform-nav-row');
    const wfModeRow = document.getElementById('waveform-mode-row');
    const wcRow = document.getElementById('webcam-nav-row');
    const animModeRow = document.getElementById('anim-mode-row');

    // Reset all
    animBtn.classList.remove('active');
    wfBtn.classList.remove('active');
    wcBtn.classList.remove('active', 'webcam-active');
    animRow.classList.add('hidden');
    wfRow.classList.add('hidden');
    wfModeRow.classList.add('hidden');
    wcRow.classList.add('hidden');
    if (animModeRow) animModeRow.classList.add('hidden');

    if (waveformActive) {
        wfBtn.classList.add('active');
        wfRow.classList.remove('hidden');
        wfModeRow.classList.remove('hidden');
        // Update waveform nav labels
        document.getElementById('wf-name').textContent = state.waveform_name || '—';
        document.getElementById('wf-sub').textContent = `Visualizer ${(state.waveform_idx || 0) + 1}/${state.waveform_count || 20}`;
        document.getElementById('wf-pal-name').textContent = state.palette_name || '—';
        document.getElementById('wf-pal-sub').textContent = `Palette ${(state.palette_idx || 0) + 1}/${state.palette_count || 32}`;
        // Update sub-mode buttons
        const defBtn = document.getElementById('wf-mode-default-btn');
        const audBtn = document.getElementById('wf-mode-audio-btn');
        if (waveformAudioMode) {
            defBtn.classList.remove('active');
            audBtn.classList.add('active');
        } else {
            defBtn.classList.add('active');
            audBtn.classList.remove('active');
        }
    } else if (webcamActive) {
        wcBtn.classList.add('active', 'webcam-active');
        wcRow.classList.remove('hidden');
    } else {
        animBtn.classList.add('active');
        animRow.classList.remove('hidden');
        if (animModeRow) animModeRow.classList.remove('hidden');
    }
}

// ─── Event Handlers ──────────────────────────────────────────────────────────

// Animation nav
document.getElementById('anim-prev').addEventListener('click', () => {
    const idx = ((state.pattern_idx || 0) - 1 + (state.pattern_count || 90)) % (state.pattern_count || 90);
    send({ cmd: 'set_pattern', idx });
});
document.getElementById('anim-next').addEventListener('click', () => {
    const idx = ((state.pattern_idx || 0) + 1) % (state.pattern_count || 90);
    send({ cmd: 'set_pattern', idx });
});

// Palette nav
document.getElementById('pal-prev').addEventListener('click', () => {
    const idx = ((state.palette_idx || 0) - 1 + (state.palette_count || 32)) % (state.palette_count || 32);
    send({ cmd: 'set_palette', idx });
});
document.getElementById('pal-next').addEventListener('click', () => {
    const idx = ((state.palette_idx || 0) + 1) % (state.palette_count || 32);
    send({ cmd: 'set_palette', idx });
});

// Brightness slider
document.getElementById('brightness-slider').addEventListener('input', (e) => {
    const val = parseInt(e.target.value);
    document.getElementById('brightness-value').textContent = Math.round(val / 255 * 100) + '%';
    send({ cmd: 'set_brightness', value: val });
});

// Manual BPM slider (DEFAULT mode)
document.getElementById('speed-slider').addEventListener('input', (e) => {
    const bpm = parseInt(e.target.value);
    document.getElementById('speed-value').textContent = bpm;
    send({ cmd: 'set_manual_bpm', value: bpm });
});

// FX intensity slider
document.getElementById('fx-intensity-slider').addEventListener('input', (e) => {
    const val = parseInt(e.target.value) / 100;
    document.getElementById('fx-intensity-value').textContent = Math.round(val * 100) + '%';
    send({ cmd: 'set_fx_intensity', value: val });
});

// Blackout
document.getElementById('blackout-btn').addEventListener('click', () => {
    send({ cmd: 'blackout', on: !state.blackout });
});

// Symmetry toggle
const symOnBtn = document.getElementById('sym-on-btn');
const symOffBtn = document.getElementById('sym-off-btn');
if (symOnBtn) symOnBtn.addEventListener('click', () => {
    send({ cmd: 'set_symmetry', on: true });
});
if (symOffBtn) symOffBtn.addEventListener('click', () => {
    send({ cmd: 'set_symmetry', on: false });
});

// Diagnostics select
document.getElementById('diag-select').addEventListener('change', (e) => {
    const key = e.target.value;
    if (key) {
        send({ cmd: 'set_diagnostic', key });
    } else {
        send({ cmd: 'set_pattern', idx: state.pattern_idx || 0 });
    }
});

// Save preset button
document.getElementById('save-preset-btn').addEventListener('click', savePreset);

// Cycle controls
document.getElementById('cycle-btn').addEventListener('click', toggleCycle);
document.getElementById('cycle-interval').addEventListener('change', () => {
    if (cycleActive) {
        // Restart timer with new interval
        if (cycleTimerId) clearTimeout(cycleTimerId);
        scheduleCycle();
    }
});

// Source toggle
document.getElementById('source-anim-btn').addEventListener('click', () => {
    if (webcamActive) stopWebcam();
    if (waveformActive) stopWaveform();
});
document.getElementById('source-waveform-btn').addEventListener('click', () => {
    if (webcamActive) stopWebcam();
    if (!waveformActive) startWaveform();
});
document.getElementById('source-webcam-btn').addEventListener('click', () => {
    if (waveformActive) stopWaveform();
    if (!webcamActive) startWebcam();
});

// Waveform nav
document.getElementById('wf-prev').addEventListener('click', () => {
    const idx = ((state.waveform_idx || 0) - 1 + (state.waveform_count || 6)) % (state.waveform_count || 6);
    send({ cmd: 'set_waveform_idx', idx });
});
document.getElementById('wf-next').addEventListener('click', () => {
    const idx = ((state.waveform_idx || 0) + 1) % (state.waveform_count || 6);
    send({ cmd: 'set_waveform_idx', idx });
});
document.getElementById('wf-pal-prev').addEventListener('click', () => {
    const idx = ((state.palette_idx || 0) - 1 + (state.palette_count || 32)) % (state.palette_count || 32);
    send({ cmd: 'set_palette', idx });
});
document.getElementById('wf-pal-next').addEventListener('click', () => {
    const idx = ((state.palette_idx || 0) + 1) % (state.palette_count || 32);
    send({ cmd: 'set_palette', idx });
});

// FX nav buttons (pattern row)
document.getElementById('fx-prev').addEventListener('click', () => cycleFX(-1));
document.getElementById('fx-next').addEventListener('click', () => cycleFX(1));

// FX nav buttons (waveform row)
document.getElementById('wf-fx-prev').addEventListener('click', () => cycleFX(-1));
document.getElementById('wf-fx-next').addEventListener('click', () => cycleFX(1));

// Waveform sub-mode toggle
document.getElementById('wf-mode-default-btn').addEventListener('click', () => {
    waveformAudioMode = false;
    send({ cmd: 'set_waveform_audio', on: false });
    stopWaveformAudio();
    updateSourceUI();
});
document.getElementById('wf-mode-audio-btn').addEventListener('click', () => {
    waveformAudioMode = true;
    send({ cmd: 'set_waveform_audio', on: true });
    startWaveformAudio();
    updateSourceUI();
});

// Webcam palette nav (duplicates for the webcam row)
document.getElementById('pal-prev-wc').addEventListener('click', () => {
    const idx = ((state.palette_idx || 0) - 1 + (state.palette_count || 32)) % (state.palette_count || 32);
    send({ cmd: 'set_palette', idx });
});
document.getElementById('pal-next-wc').addEventListener('click', () => {
    const idx = ((state.palette_idx || 0) + 1) % (state.palette_count || 32);
    send({ cmd: 'set_palette', idx });
});

// ─── Keyboard Controls ──────────────────────────────────────────────────────

document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

    switch (e.key) {
        case 'ArrowLeft':
            e.preventDefault();
            cyclePreset(-1);
            break;
        case 'ArrowRight':
            e.preventDefault();
            cyclePreset(1);
            break;
        case 'ArrowUp':
            e.preventDefault();
            document.getElementById('pal-prev').click();
            break;
        case 'ArrowDown':
            e.preventDefault();
            document.getElementById('pal-next').click();
            break;
        case ' ':
            e.preventDefault();
            randomize();
            break;
        case 'f': case 'F':
            e.preventDefault();
            cycleFX(1);
            break;
        case 'g': case 'G':
            e.preventDefault();
            cycleFX(-1);
            break;
        case 'm': case 'M':
            e.preventDefault();
            cycleModel();
            break;
        case 'c': case 'C':
            e.preventDefault();
            toggleCycle();
            break;
        case 'v': case 'V':
            e.preventDefault();
            if (waveformActive) stopWaveform(); else startWaveform();
            break;
        case 'w': case 'W':
            e.preventDefault();
            toggleWebcam();
            break;
        // 'a' key removed — conflicts with numpad. Use UI button instead.
        case 's': case 'S':
            if (!e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                savePreset();
            }
            break;

        // ─── Numpad keys (SayoDevice 2x6V) ─────────────────────────
        // Layout: 1,2,3,4,5,6,7,8,9,0,a,b
        //   1 = toggle preset cycle on/off
        //   a = previous preset (←)
        //   b = next preset (→)
        //   2-9, 0 = jump to saved preset by slot (1-9)
        case '1':
            e.preventDefault();
            toggleCycle();
            break;
        case 'a': case 'A':
            e.preventDefault();
            cyclePreset(-1);
            break;
        case 'b': case 'B':
            e.preventDefault();
            cyclePreset(1);
            break;
        case '2': case '3': case '4': case '5': case '6':
        case '7': case '8': case '9': case '0':
            e.preventDefault();
            // 2→slot 0, 3→slot 1, ... 9→slot 7, 0→slot 8
            const slotMap = {'2':0,'3':1,'4':2,'5':3,'6':4,'7':5,'8':6,'9':7,'0':8};
            const slot = slotMap[e.key];
            if (slot !== undefined && presets && slot < presets.length) {
                send({ cmd: 'load_preset', id: presets[slot].id });
            }
            break;
    }
});

// ─── Audio (BEAT mode) ─────────────────────────────────────────────────────

let audioCtx = null;
let audioAnalyser = null;
let audioDataArray = null;
let audioStream = null;
let audioEnabled = false;
let audioAnimFrameId = null;

async function startAudio() {
    try {
        audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioCtx.createMediaStreamSource(audioStream);
        audioAnalyser = audioCtx.createAnalyser();
        audioAnalyser.fftSize = 256;
        source.connect(audioAnalyser);
        audioDataArray = new Uint8Array(audioAnalyser.frequencyBinCount);
        audioEnabled = true;
        send({ cmd: 'set_audio_enabled', on: true });
        audioLoop();
    } catch (err) {
        console.error('Microphone access denied:', err);
        alert('Could not access microphone. Check browser permissions.');
        // Revert to default mode on failure
        send({ cmd: 'set_audio_mode', key: 'none' });
    }
}

function stopAudio() {
    audioEnabled = false;
    if (audioAnimFrameId) {
        cancelAnimationFrame(audioAnimFrameId);
        audioAnimFrameId = null;
    }
    if (audioStream) {
        audioStream.getTracks().forEach(t => t.stop());
        audioStream = null;
    }
    if (audioCtx) {
        audioCtx.close().catch(() => {});
        audioCtx = null;
        audioAnalyser = null;
    }
    send({ cmd: 'set_audio_enabled', on: false });
}

// ─── Client-side beat detection ────────────────────────────────────────────
// Uses energy flux: compare current bass energy to a rolling average.
// When current energy exceeds the average by a threshold, it's a beat.
let _beatHistory = [];        // rolling window of bass energy values
let _beatHistorySize = 43;    // ~0.7 seconds at 60fps
let _beatCooldown = 0;
let _beatTimes = [];          // timestamps of recent beats for BPM
let _clientBPM = 0;
let _bpmCalcTimer = 0;
let _lastAudioLoopTime = 0;

function audioLoop() {
    if (!audioEnabled || !audioAnalyser) return;

    const now = performance.now() / 1000;
    const dt = _lastAudioLoopTime > 0 ? now - _lastAudioLoopTime : 0.016;
    _lastAudioLoopTime = now;

    audioAnalyser.getByteFrequencyData(audioDataArray);

    // ── Extract frequency bands ────────────────────────────────────────
    // Bass: bins 1-8 (sub-bass + bass, ~40Hz to ~350Hz)
    let bass = 0;
    for (let i = 1; i < 8; i++) bass += audioDataArray[i];
    bass = (bass / 7) / 255;

    // Mid: bins 10-30
    let mid = 0;
    for (let i = 10; i < 30; i++) mid += audioDataArray[i];
    mid = (mid / 20) / 255;

    // Treble: bins 35-80
    let treble = 0;
    for (let i = 35; i < 80; i++) treble += audioDataArray[i];
    treble = (treble / 45) / 255;

    // ── Beat detection via energy flux ─────────────────────────────────
    // Use low-frequency energy (bins 1-12) for kick detection
    let kickEnergy = 0;
    for (let i = 1; i < 12; i++) kickEnergy += audioDataArray[i];
    kickEnergy /= 11;  // 0-255 range

    _beatHistory.push(kickEnergy);
    if (_beatHistory.length > _beatHistorySize) _beatHistory.shift();

    // Rolling average
    let avg = 0;
    for (let i = 0; i < _beatHistory.length; i++) avg += _beatHistory[i];
    avg /= _beatHistory.length;

    // Variance for adaptive threshold
    let variance = 0;
    for (let i = 0; i < _beatHistory.length; i++) {
        const d = _beatHistory[i] - avg;
        variance += d * d;
    }
    variance /= _beatHistory.length;
    const stddev = Math.sqrt(variance);

    // Beat = current energy significantly above the rolling average
    // Adaptive: threshold scales with how dynamic the signal is
    const threshold = Math.max(15, avg + stddev * 1.2);

    _beatCooldown = Math.max(0, _beatCooldown - dt);

    let beatDetected = false;
    if (kickEnergy > threshold && kickEnergy > 25 && _beatCooldown <= 0) {
        beatDetected = true;
        _beatCooldown = 0.15; // minimum 150ms between beats
        _beatTimes.push(now);
        if (_beatTimes.length > 20) _beatTimes = _beatTimes.slice(-20);
    }

    // ── BPM estimation (every 4 seconds for smoother average) ──────────
    _bpmCalcTimer += dt;
    if (_bpmCalcTimer > 4.0) {
        _bpmCalcTimer = 0;

        // Remove stale beats (older than 8 seconds — wider window)
        const cutoff = now - 8;
        _beatTimes = _beatTimes.filter(t => t > cutoff);

        if (_beatTimes.length >= 4) {
            // Compute intervals
            const intervals = [];
            for (let i = 1; i < _beatTimes.length; i++) {
                const iv = _beatTimes[i] - _beatTimes[i - 1];
                if (iv > 0.2 && iv < 1.5) intervals.push(iv); // 40-300 BPM range
            }

            if (intervals.length >= 3) {
                // Median interval (robust to outliers)
                intervals.sort((a, b) => a - b);
                const median = intervals[Math.floor(intervals.length / 2)];
                const newBPM = 60 / median;

                // Heavier smoothing: 70% previous + 30% new
                if (_clientBPM > 0) {
                    _clientBPM = _clientBPM * 0.7 + newBPM * 0.3;
                } else {
                    _clientBPM = newBPM;
                }
                _clientBPM = Math.max(40, Math.min(220, _clientBPM));
            }
        } else {
            _clientBPM *= 0.7; // fade out if no beats
            if (_clientBPM < 30) _clientBPM = 0;
        }
    }

    // ── Send to server ─────────────────────────────────────────────────
    const msg = { cmd: 'audio_data', bass, mid, treble };
    if (beatDetected) {
        msg.beat = true;
        msg.bpm = Math.round(_clientBPM);
    }
    send(msg);

    // ── Update UI meters ───────────────────────────────────────────────
    const bassMeter = document.getElementById('meter-bass');
    const midMeter = document.getElementById('meter-mid');
    const trebleMeter = document.getElementById('meter-treble');
    if (bassMeter) bassMeter.style.height = (bass * 100) + '%';
    if (midMeter) midMeter.style.height = (mid * 100) + '%';
    if (trebleMeter) trebleMeter.style.height = (treble * 100) + '%';

    // Flash BPM display on beat
    const bpmEl = document.getElementById('bpm-display');
    if (bpmEl) {
        const bpm = Math.round(_clientBPM);
        bpmEl.textContent = bpm > 0 ? `${bpm} BPM` : '-- BPM';
        if (beatDetected) {
            bpmEl.style.color = '#fff';
            bpmEl.style.background = 'rgba(0, 174, 239, 0.3)';
            setTimeout(() => {
                bpmEl.style.color = bpm > 0 ? 'var(--accent)' : 'rgba(255,255,255,0.3)';
                bpmEl.style.background = 'rgba(0, 174, 239, 0.08)';
            }, 100);
        }
    }

    audioAnimFrameId = requestAnimationFrame(audioLoop);
}

function updateAnimModeUI() {
    const mode = state.audio_mode || 'none';
    const defaultBtn = document.getElementById('mode-default-btn');
    const audioBtn = document.getElementById('mode-audio-btn');
    const bpmBtn = document.getElementById('mode-bpm-btn');
    const beatControls = document.getElementById('audio-beat-controls');
    const speedRow = document.getElementById('speed-row');
    const animModeRow = document.getElementById('anim-mode-row');

    // Update active button (3-way toggle)
    if (defaultBtn) defaultBtn.classList.toggle('active', mode === 'none');
    if (audioBtn) audioBtn.classList.toggle('active', mode === 'audio');
    if (bpmBtn) bpmBtn.classList.toggle('active', mode === 'bpm');

    // Show audio controls for audio or bpm modes
    const showControls = mode !== 'none';
    if (beatControls) beatControls.classList.toggle('hidden', !showControls);

    // In BPM mode: hide frequency meters (only show BPM display + sensitivity)
    const bassBar = document.getElementById('meter-bass-bar');
    const midBar = document.getElementById('meter-mid-bar');
    const trebleBar = document.getElementById('meter-treble-bar');
    if (bassBar) bassBar.style.display = mode === 'bpm' ? 'none' : '';
    if (midBar) midBar.style.display = mode === 'bpm' ? 'none' : '';
    if (trebleBar) trebleBar.style.display = mode === 'bpm' ? 'none' : '';

    // Hide BPM slider when any audio mode is active OR waveform audio sub-mode
    const hideSpeed = showControls || (waveformActive && waveformAudioMode);
    if (speedRow) speedRow.style.display = hideSpeed ? 'none' : '';

    // Hide animation mode row when webcam is active
    if (animModeRow) animModeRow.style.display = state.webcam_mode ? 'none' : '';

    // Show sensitivity in Audio mode, Half/Full toggle in BPM mode
    const sensRow = document.getElementById('audio-sensitivity-row');
    const rateRow = document.getElementById('bpm-rate-row');
    if (sensRow) sensRow.style.display = mode === 'audio' ? '' : 'none';
    if (rateRow) rateRow.style.display = mode === 'bpm' ? '' : 'none';

    // Update sensitivity slider
    const sensSlider = document.getElementById('audio-sensitivity-slider');
    const sensValue = document.getElementById('audio-sensitivity-value');
    if (sensSlider && sensValue) {
        sensSlider.value = Math.round((state.audio_sensitivity || 1.0) * 100);
        sensValue.textContent = (state.audio_sensitivity || 1.0).toFixed(1) + 'x';
    }

    // Update Half/Full BPM toggle
    const halfBtn = document.getElementById('bpm-half-btn');
    const fullBtn = document.getElementById('bpm-full-btn');
    if (halfBtn && fullBtn) {
        const isHalf = state.bpm_half !== false; // default to half
        halfBtn.classList.toggle('active', isHalf);
        fullBtn.classList.toggle('active', !isHalf);
    }

    // Update BPM display
    const bpmEl = document.getElementById('bpm-display');
    if (bpmEl) {
        const bpm = state.bpm || 0;
        bpmEl.textContent = bpm > 0 ? `${bpm} BPM` : '-- BPM';
        bpmEl.style.color = bpm > 0 ? 'var(--accent)' : 'rgba(255,255,255,0.3)';
    }
}

function toggleAnimMode() {
    // Cycle: none → audio → bpm → none
    const mode = state.audio_mode || 'none';
    if (mode === 'none') {
        send({ cmd: 'set_audio_mode', key: 'audio' });
        if (!audioEnabled) startAudio();
    } else if (mode === 'audio') {
        send({ cmd: 'set_audio_mode', key: 'bpm' });
        if (!audioEnabled) startAudio();
    } else {
        send({ cmd: 'set_audio_mode', key: 'none' });
        stopAudio();
    }
}

// Animation mode toggle handlers
document.getElementById('mode-default-btn').addEventListener('click', () => {
    send({ cmd: 'set_audio_mode', key: 'none' });
    stopAudio();
});
document.getElementById('mode-audio-btn').addEventListener('click', () => {
    send({ cmd: 'set_audio_mode', key: 'audio' });
    if (!audioEnabled) startAudio();
});
document.getElementById('mode-bpm-btn').addEventListener('click', () => {
    send({ cmd: 'set_audio_mode', key: 'bpm' });
    if (!audioEnabled) startAudio();
});

document.getElementById('audio-sensitivity-slider').addEventListener('input', (e) => {
    const val = parseInt(e.target.value) / 100;
    document.getElementById('audio-sensitivity-value').textContent = val.toFixed(1) + 'x';
    send({ cmd: 'set_audio_sensitivity', value: val });
});

// Half/Full BPM toggle
document.getElementById('bpm-half-btn').addEventListener('click', () => {
    send({ cmd: 'set_bpm_rate', half: true });
    document.getElementById('bpm-half-btn').classList.add('active');
    document.getElementById('bpm-full-btn').classList.remove('active');
});
document.getElementById('bpm-full-btn').addEventListener('click', () => {
    send({ cmd: 'set_bpm_rate', half: false });
    document.getElementById('bpm-full-btn').classList.add('active');
    document.getElementById('bpm-half-btn').classList.remove('active');
});

// ─── Diffuser ───────────────────────────────────────────────────────────────

document.getElementById('diffuser-slider').addEventListener('input', (e) => {
    const val = parseInt(e.target.value) / 100;  // 0 to 1
    const blurPx = val * 12;
    const canvases = document.querySelectorAll('canvas');
    canvases.forEach(c => {
        c.style.filter = blurPx > 0.1 ? `blur(${blurPx}px)` : 'none';
    });
});

// ─── Init ────────────────────────────────────────────────────────────────────

initWebcamElements();
loadModels();
loadDiagnostics();
loadFX();
// Audio mode is handled by DEFAULT/AUDIO(BEAT) toggle
connect();
