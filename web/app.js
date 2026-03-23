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

// Webcam state
let webcamActive = false;
let webcamStream = null;
let webcamVideo = null;
let webcamSampleCanvas = null;
let webcamSampleCtx = null;
let webcamIntervalId = null;

// ─── Canvas References ──────────────────────────────────────────────────────

const singleCanvas = document.getElementById('matrix-canvas');
const singleCtx = singleCanvas.getContext('2d');
const frontCanvas = document.getElementById('front-canvas');
const frontCtx = frontCanvas.getContext('2d');
const leftCanvas = document.getElementById('left-canvas');
const leftCtx = leftCanvas.getContext('2d');
const rightCanvas = document.getElementById('right-canvas');
const rightCtx = rightCanvas.getContext('2d');

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
            if (brightness > 10 && glow > 1) {
                const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius + glow);
                grad.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.4)`);
                grad.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
                ctx.fillStyle = grad;
                ctx.fillRect(cx - radius - glow, cy - radius - glow,
                    (radius + glow) * 2, (radius + glow) * 2);
            }

            ctx.beginPath();
            ctx.arc(cx, cy, radius / 2, 0, Math.PI * 2);
            ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
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
    const isMulti = panels.length > 1;

    if (isMulti) {
        singleView.classList.add('hidden');
        ushapeView.classList.remove('hidden');
    } else {
        singleView.classList.remove('hidden');
        ushapeView.classList.add('hidden');
    }
}

function renderFrame(frameData) {
    if (panels.length <= 1) {
        const cols = vcWidth;
        const rows = vcHeight;
        const containerW = getContainerWidth() - 42;
        const params = calcLedParams(cols, rows, containerW);
        renderToCanvas(singleCtx, singleCanvas, frameData, cols, rows, 0, params);
    } else {
        const lsFront = panels[0];
        const lsRear = panels[1];
        const front = panels[2];
        const rsRear = panels[3];
        const rsFront = panels[4];

        const leftCols = lsFront.cols + lsRear.cols;
        const rightCols = rsRear.cols + rsFront.cols;
        const frontCols = front.cols;
        const rows = vcHeight;

        // Responsive: each side panel gets ~45% of container, front gets ~30%
        const containerW = getContainerWidth();
        const sideMaxW = (containerW - 40) * 0.45;  // 40 for gap + borders
        const frontMaxW = containerW * 0.35;

        const leftParams = calcLedParams(leftCols, rows, sideMaxW);
        const rightParams = calcLedParams(rightCols, rows, sideMaxW);
        const frontParams = calcLedParams(frontCols, rows, frontMaxW);

        renderToCanvas(frontCtx, frontCanvas, frameData, frontCols, rows, front.col_offset, frontParams);
        renderToCanvas(leftCtx, leftCanvas, frameData, leftCols, rows, lsFront.col_offset, leftParams);
        renderToCanvas(rightCtx, rightCanvas, frameData, rightCols, rows, rsRear.col_offset, rightParams);
    }
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
    document.getElementById('anim-name').textContent = state.animation_name || '—';
    document.getElementById('anim-sub').textContent =
        `Animation ${(state.animation_idx || 0) + 1}/${state.animation_count || 0}`;

    // Palette
    document.getElementById('pal-name').textContent = state.palette_name || '—';
    document.getElementById('pal-sub').textContent =
        `Palette ${(state.palette_idx || 0) + 1}/${state.palette_count || 0}`;

    // Brightness
    const brSlider = document.getElementById('brightness-slider');
    const brValue = document.getElementById('brightness-value');
    brSlider.value = state.brightness || 128;
    brValue.textContent = Math.round((state.brightness || 128) / 255 * 100) + '%';

    // Speed
    const spSlider = document.getElementById('speed-slider');
    const spValue = document.getElementById('speed-value');
    spSlider.value = Math.round((state.speed || 1.0) * 100);
    spValue.textContent = (state.speed || 1.0).toFixed(1) + 'x';

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
    updateFXChips();

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
        const container = document.getElementById('fx-chips');
        container.innerHTML = '';
        fxList.forEach(fx => {
            const chip = document.createElement('button');
            chip.className = 'fx-chip' + (fx.key === 'none' ? ' active' : '');
            chip.textContent = fx.name;
            chip.dataset.key = fx.key;
            chip.addEventListener('click', () => {
                send({ cmd: 'set_fx', key: fx.key });
            });
            container.appendChild(chip);
        });
    } catch (e) {
        console.warn('Failed to load FX:', e);
    }
}

function updateFXChips() {
    const currentFX = state.fx || 'none';
    document.querySelectorAll('.fx-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.key === currentFX);
    });
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
    const animIdx = Math.floor(Math.random() * (state.animation_count || 90));
    const palIdx = Math.floor(Math.random() * (state.palette_count || 32));
    send({ cmd: 'set_animation', idx: animIdx });
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
        state.animation_name || 'Unknown',
        state.palette_name || 'Unknown',
    ];
    if (fx) parts.push(fx.charAt(0).toUpperCase() + fx.slice(1));
    parts.push(Math.round((state.brightness || 128) / 255 * 100) + '%');
    parts.push((state.speed || 1.0).toFixed(1) + 'x');
    const name = parts.join(' / ');

    send({
        cmd: 'save_preset',
        name,
        preset: {
            animation_idx: state.animation_idx,
            palette_idx: state.palette_idx,
            fx: state.fx || 'none',
            fx_intensity: state.fx_intensity || 0.5,
            brightness: state.brightness,
            speed: state.speed,
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
            <div class="preset-detail">${p.preset.animation_name || '?'} &middot; ${p.preset.palette_name || '?'}${p.preset.fx && p.preset.fx !== 'none' ? ' &middot; ' + p.preset.fx : ''}</div>
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

function sampleWebcam() {
    if (!webcamActive || !webcamVideo || webcamVideo.readyState < 2) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    // Downsample video to matrix dimensions
    webcamSampleCanvas.width = vcWidth;
    webcamSampleCanvas.height = vcHeight;

    // Mirror horizontally for selfie-style
    webcamSampleCtx.save();
    webcamSampleCtx.scale(-1, 1);
    webcamSampleCtx.drawImage(webcamVideo, -vcWidth, 0, vcWidth, vcHeight);
    webcamSampleCtx.restore();

    const imageData = webcamSampleCtx.getImageData(0, 0, vcWidth, vcHeight);
    const data = imageData.data; // RGBA

    // Convert to brightness (single byte per pixel)
    const brightness = new Uint8Array(vcWidth * vcHeight);
    for (let i = 0; i < brightness.length; i++) {
        const r = data[i * 4];
        const g = data[i * 4 + 1];
        const b = data[i * 4 + 2];
        // Luminance formula
        brightness[i] = Math.round(r * 0.299 + g * 0.587 + b * 0.114);
    }

    // Send as binary to server
    ws.send(brightness.buffer);
}

function updateSourceUI() {
    const animBtn = document.getElementById('source-anim-btn');
    const wcBtn = document.getElementById('source-webcam-btn');
    const animRow = document.getElementById('anim-nav-row');
    const wcRow = document.getElementById('webcam-nav-row');

    if (webcamActive) {
        animBtn.classList.remove('active');
        wcBtn.classList.add('active', 'webcam-active');
        animRow.classList.add('hidden');
        wcRow.classList.remove('hidden');
    } else {
        animBtn.classList.add('active');
        wcBtn.classList.remove('active', 'webcam-active');
        animRow.classList.remove('hidden');
        wcRow.classList.add('hidden');
    }
}

// ─── Event Handlers ──────────────────────────────────────────────────────────

// Animation nav
document.getElementById('anim-prev').addEventListener('click', () => {
    const idx = ((state.animation_idx || 0) - 1 + (state.animation_count || 90)) % (state.animation_count || 90);
    send({ cmd: 'set_animation', idx });
});
document.getElementById('anim-next').addEventListener('click', () => {
    const idx = ((state.animation_idx || 0) + 1) % (state.animation_count || 90);
    send({ cmd: 'set_animation', idx });
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

// Speed slider
document.getElementById('speed-slider').addEventListener('input', (e) => {
    const val = parseInt(e.target.value) / 100;
    document.getElementById('speed-value').textContent = val.toFixed(1) + 'x';
    send({ cmd: 'set_speed', value: val });
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

// Diagnostics select
document.getElementById('diag-select').addEventListener('change', (e) => {
    const key = e.target.value;
    if (key) {
        send({ cmd: 'set_diagnostic', key });
    } else {
        send({ cmd: 'set_animation', idx: state.animation_idx || 0 });
    }
});

// Save preset button
document.getElementById('save-preset-btn').addEventListener('click', savePreset);

// Source toggle
document.getElementById('source-anim-btn').addEventListener('click', () => {
    if (webcamActive) stopWebcam();
});
document.getElementById('source-webcam-btn').addEventListener('click', () => {
    if (!webcamActive) startWebcam();
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
        case 'w': case 'W':
            e.preventDefault();
            toggleWebcam();
            break;
        case 's': case 'S':
            if (!e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                savePreset();
            }
            break;
    }
});

// ─── Init ────────────────────────────────────────────────────────────────────

initWebcamElements();
loadModels();
loadDiagnostics();
loadFX();
connect();
