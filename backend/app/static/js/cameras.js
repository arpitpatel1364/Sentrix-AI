/* ══════════════════════════════════════════
   CAMERAS, ROI, LIVE MONITORING, MAP
   ══════════════════════════════════════════ */

/* ─── CAMERAS ─── */
async function loadCameras() {
  try {
    const cameras = await api('/api/cameras');
    State.cameras = cameras;
    renderCameraGrid(cameras);
    updateMapCameraList(cameras);
    syncGlobalButtons();
  } catch (e) { console.warn('[cameras]', e); }
}

function renderCameraGrid(cameras) {
  const grid  = document.getElementById('cameras-grid');
  const empty = document.getElementById('cameras-empty');
  if (!grid) return;

  if (!cameras.length) {
    grid.innerHTML = '';
    if (empty) empty.style.display = 'block';
    return;
  }
  if (empty) empty.style.display = 'none';

  grid.innerHTML = cameras.map(c => {
    const online  = c.online;
    const nodeKey = c.node_key || `${c.added_by}:${c.camera_id}`;
    const lastSeen = c.last_seen ? `Last: ${fmtTs(c.last_seen.timestamp || c.last_seen)}` : 'Never active';
    const roiActive = c.roi && (c.roi[0] > 0.05 || c.roi[1] > 0.05);

    return `
    <div class="panel" style="padding:1.25rem">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.875rem">
        <div>
          <div class="td-mono" style="font-size:0.6rem;margin-bottom:0.25rem">CAMERA NODE</div>
          <div style="font-weight:700;font-size:1rem">${esc(c.name)}</div>
          <div style="font-family:var(--font-mono);font-size:0.7rem;color:var(--primary);margin-top:2px">${esc(c.camera_id)}</div>
        </div>
        <span class="badge ${online ? 'online' : 'red'}" style="flex-shrink:0">
          <span style="width:6px;height:6px;border-radius:50%;display:inline-block;background:${online ? 'var(--green)' : 'var(--red)'}"></span>
          ${online ? 'ONLINE' : 'OFFLINE'}
        </span>
      </div>

      <div class="camera-preview-box">
        ${online
          ? `<img class="camera-preview-img" src="/api/stream/${esc(nodeKey)}"
                  onerror="this.style.display='none'" alt="LIVE FEED">`
          : `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:var(--on-surface-muted);font-family:var(--font-mono);font-size:0.65rem">NO SIGNAL</div>`}
        <div class="status-overlay">${online ? '● REC' : 'OFFLINE'}</div>
        <div class="scanline"></div>
      </div>

      <div style="display:flex;flex-direction:column;gap:0.35rem;font-size:0.82rem;margin-bottom:0.875rem">
        ${c.location ? `<div class="result-item"><span class="result-label">Location</span><span>${esc(c.location)}</span></div>` : ''}
        ${c.description ? `<div class="result-item"><span class="result-label">Note</span><span style="color:var(--on-surface-muted)">${esc(c.description)}</span></div>` : ''}
        <div class="result-item">
          <span class="result-label">Today</span>
          <span style="color:var(--primary);font-family:var(--font-mono);font-size:0.78rem">${c.detections_today ?? 0} detections</span>
        </div>
        <div class="result-item">
          <span class="result-label">ROI</span>
          <span style="font-family:var(--font-mono);font-size:0.72rem;color:${roiActive ? 'var(--amber)' : 'var(--cyan)'}">
            ${roiActive ? 'ACTIVE ZONE' : 'FULL FRAME'}
          </span>
        </div>
        <div class="result-item">
          <span class="result-label">Status</span>
          <span class="td-mono">${lastSeen}</span>
        </div>
      </div>

      <div class="td-mono" style="font-size:0.58rem;letter-spacing:0.1em;margin-bottom:0.5rem;padding-bottom:0.5rem;border-bottom:1px solid var(--outline)">RUNTIME SIGNALS</div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.4rem;margin-bottom:1rem">
        <button class="signal-btn signal-btn-sm ${c.face_enabled ? 'active' : ''}"
                onclick="toggleCameraFeature('${esc(c.camera_id)}','face',${c.face_enabled ? 0 : 1})">
          <span class="icon">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          </span>
          <div class="label-box">
            <span class="label">FACE</span>
            <span class="status-text">${c.face_enabled ? 'ON' : 'OFF'}</span>
          </div>
        </button>
        <button class="signal-btn signal-btn-sm ${c.obj_enabled ? 'active' : ''}"
                onclick="toggleCameraFeature('${esc(c.camera_id)}','obj',${c.obj_enabled ? 0 : 1})">
          <span class="icon">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
          </span>
          <div class="label-box">
            <span class="label">OBJ</span>
            <span class="status-text">${c.obj_enabled ? 'ON' : 'OFF'}</span>
          </div>
        </button>
        <button class="signal-btn signal-btn-sm ${c.stream_enabled ? 'active' : ''}"
                onclick="toggleCameraFeature('${esc(c.camera_id)}','stream',${c.stream_enabled ? 0 : 1})">
          <span class="icon">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.58 16.11a7 7 0 0 1 6.84 0"/><circle cx="12" cy="20" r="2"/></svg>
          </span>
          <div class="label-box">
            <span class="label">LIVE</span>
            <span class="status-text">${c.stream_enabled ? 'ON' : 'OFF'}</span>
          </div>
        </button>
      </div>

      <div style="display:flex;gap:0.5rem;flex-wrap:wrap">
        <button class="btn btn-ghost btn-sm" onclick="openEditCamera('${esc(c.camera_id)}')">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="margin-right:2px"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          Edit
        </button>
        <button class="btn btn-ghost btn-sm" onclick="showROI('${esc(c.camera_id)}')">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="margin-right:2px"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/></svg>
          ROI
        </button>
        ${online
          ? `<button class="btn btn-danger btn-sm admin-only" onclick="stopNode('${esc(c.camera_id)}')">
               <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" style="margin-right:3px"><rect x="5" y="5" width="14" height="14" rx="1"/></svg>
               Stop
             </button>`
          : `<button class="btn btn-success btn-sm" onclick="startNode('${esc(c.camera_id)}')">
               <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" style="margin-right:3px"><polygon points="5 3 19 12 5 21 5 3"/></svg>
               Start
             </button>`}
        <button class="btn btn-danger btn-sm admin-only" style="margin-left:auto" onclick="deleteCamera('${esc(c.camera_id)}','${esc(c.name)}')">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
    </div>`;
  }).join('');

  // Apply role visibility
  if (State.role !== 'admin') {
    document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'none');
  }
}

function openAddCamera() {
  ['ac-id','ac-name','ac-location','ac-desc','ac-stream'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  const err = document.getElementById('ac-err');
  if (err) err.style.display = 'none';
  openModal('modal-add-camera');
}

async function addCamera() {
  const btn = document.getElementById('ac-btn');
  const err = document.getElementById('ac-err');
  btn.disabled = true; btn.textContent = 'Registering…'; err.style.display = 'none';
  try {
    await api('/api/cameras', {
      method: 'POST',
      body: JSON.stringify({
        camera_id:   document.getElementById('ac-id').value.trim(),
        name:        document.getElementById('ac-name').value.trim(),
        location:    document.getElementById('ac-location').value.trim(),
        description: document.getElementById('ac-desc').value.trim(),
        stream_url:  document.getElementById('ac-stream').value.trim(),
      }),
    });
    closeModal('modal-add-camera');
    toast('Camera registered', 'green');
    loadCameras();
  } catch (e) { err.textContent = e.message; err.style.display = 'block'; }
  finally { btn.disabled = false; btn.textContent = 'Register Camera'; }
}

function openEditCamera(cameraId) {
  const cam = State.cameras.find(c => c.camera_id === cameraId);
  if (!cam) return;
  document.getElementById('ec-id').value       = cameraId;
  document.getElementById('ec-name').value     = cam.name || '';
  document.getElementById('ec-location').value = cam.location || '';
  document.getElementById('ec-desc').value     = cam.description || '';
  document.getElementById('ec-stream').value   = cam.stream_url || '';
  openModal('modal-edit-camera');
}

async function saveCamera() {
  const btn = document.getElementById('ec-btn');
  btn.disabled = true; btn.textContent = 'Saving…';
  const cameraId = document.getElementById('ec-id').value;
  try {
    await api(`/api/cameras/${cameraId}`, {
      method: 'PUT',
      body: JSON.stringify({
        name:        document.getElementById('ec-name').value.trim(),
        location:    document.getElementById('ec-location').value.trim(),
        description: document.getElementById('ec-desc').value.trim(),
        stream_url:  document.getElementById('ec-stream').value.trim(),
      }),
    });
    closeModal('modal-edit-camera');
    toast('Camera updated', 'green');
    loadCameras();
  } catch (e) { toast(e.message, 'red'); }
  finally { btn.disabled = false; btn.textContent = 'Save Changes'; }
}

async function deleteCamera(cameraId, name) {
  if (!confirm(`Delete camera "${name}" (${cameraId})?`)) return;
  try {
    await api(`/api/cameras/${cameraId}`, { method: 'DELETE' });
    toast('Camera removed', 'amber');
    loadCameras();
  } catch (e) { toast(e.message, 'red'); }
}

/* ─── ROI ─── */
function showROI(nodeKeyOrCamId) {
  const camId  = nodeKeyOrCamId.includes(':') ? nodeKeyOrCamId.split(':')[1] : nodeKeyOrCamId;
  const cam    = State.cameras.find(c => c.camera_id === camId);

  let fullKey = nodeKeyOrCamId;
  if (!nodeKeyOrCamId.includes(':') && cam) {
    fullKey = cam.node_key || `${cam.added_by}:${camId}`;
  }

  State.roi.cid = fullKey;
  document.getElementById('roi-id-label').textContent = `// NODE: ${fullKey}`;

  // Load ROI from camera record
  if (cam?.roi) {
    try {
      const r = typeof cam.roi === 'string' ? JSON.parse(cam.roi) : cam.roi;
      if (Array.isArray(r) && r.length === 4) {
        State.roi.box = { x1: r[0], y1: r[1], x2: r[2], y2: r[3] };
      }
    } catch { State.roi.box = { x1: 0.03, y1: 0.03, x2: 0.97, y2: 0.97 }; }
  } else {
    State.roi.box = { x1: 0.03, y1: 0.03, x2: 0.97, y2: 0.97 };
  }

  const img = document.getElementById('roi-stream');
  img.src = '';
  img.onload = () => { initRoiInteraction(); };
  img.src = `/api/stream/${fullKey}`;
  if (img.complete) initRoiInteraction();

  document.getElementById('roi-save-btn').onclick = saveROISettings;
  openModal('modal-roi');
}

function initRoiInteraction() {
  const container = document.getElementById('roi-container');
  const selector  = document.getElementById('roi-selector');
  const stream    = document.getElementById('roi-stream');
  const display   = document.getElementById('roi-coords-display');

  const updateUI = () => {
    const rect   = stream.getBoundingClientRect();
    const parent = container.getBoundingClientRect();
    if (!rect.width) { selector.style.display = 'none'; return; }

    selector.style.display = 'block';
    const offX = rect.left - parent.left;
    const offY = rect.top  - parent.top;
    const b = State.roi.box;

    const x = offX + b.x1 * rect.width;
    const y = offY + b.y1 * rect.height;
    const w = (b.x2 - b.x1) * rect.width;
    const h = (b.y2 - b.y1) * rect.height;

    selector.style.left   = `${x}px`;
    selector.style.top    = `${y}px`;
    selector.style.width  = `${Math.max(20, w)}px`;
    selector.style.height = `${Math.max(20, h)}px`;

    // Overlays
    const ot = document.getElementById('roi-overlay-top');
    const ob = document.getElementById('roi-overlay-bottom');
    const ol = document.getElementById('roi-overlay-left');
    const or_ = document.getElementById('roi-overlay-right');
    ot.style.cssText  = `left:${offX}px;top:${offY}px;width:${rect.width}px;height:${y - offY}px`;
    ob.style.cssText  = `left:${offX}px;top:${y + h}px;width:${rect.width}px;height:${rect.height - (y - offY + h)}px`;
    ol.style.cssText  = `left:${offX}px;top:${y}px;width:${x - offX}px;height:${h}px`;
    or_.style.cssText = `left:${x + w}px;top:${y}px;width:${rect.width - (x - offX + w)}px;height:${h}px`;

    const p = v => Math.round(v * 100);
    display.innerHTML = `ZONE: <span style="color:var(--amber)">X ${p(b.x1)}%</span> · <span style="color:var(--amber)">Y ${p(b.y1)}%</span> · <span style="color:var(--cyan)">W ${p(b.x2 - b.x1)}%</span> · <span style="color:var(--cyan)">H ${p(b.y2 - b.y1)}%</span>`;

    const isFull = b.x1 <= 0.005 && b.y1 <= 0.005 && b.x2 >= 0.995 && b.y2 >= 0.995;
    const color  = isFull ? 'var(--cyan)' : 'var(--amber)';
    const label  = document.getElementById('roi-inner-label');
    if (label) {
      label.textContent   = isFull ? 'FULL FRAME MONITORING' : 'ACTIVE INTELLIGENCE ZONE';
      label.style.color   = color;
      label.style.borderColor = color;
    }
    selector.style.borderColor = color;
    selector.style.boxShadow   = `0 0 40px ${color}22, inset 0 0 60px ${color}0d`;
  };

  // Init event listeners once
  if (!selector.dataset.roiInit) {
    selector.dataset.roiInit = '1';

    selector.addEventListener('mousedown', e => {
      State.roi.dragging = true;
      State.roi.mode     = e.target.dataset.handle || 'move';
      State.roi.start    = { x: e.clientX, y: e.clientY, b: { ...State.roi.box } };
      e.preventDefault();
    });

    window.addEventListener('mousemove', e => {
      if (!State.roi.dragging) return;
      const rect = stream.getBoundingClientRect();
      const dx = (e.clientX - State.roi.start.x) / rect.width;
      const dy = (e.clientY - State.roi.start.y) / rect.height;
      const sb = State.roi.start.b;

      if (State.roi.mode === 'move') {
        const bw = sb.x2 - sb.x1, bh = sb.y2 - sb.y1;
        State.roi.box.x1 = Math.max(0, Math.min(1 - bw, sb.x1 + dx));
        State.roi.box.y1 = Math.max(0, Math.min(1 - bh, sb.y1 + dy));
        State.roi.box.x2 = State.roi.box.x1 + bw;
        State.roi.box.y2 = State.roi.box.y1 + bh;
      } else {
        const m = State.roi.mode;
        if (m.includes('t')) State.roi.box.y1 = Math.max(0, Math.min(sb.y2 - 0.05, sb.y1 + dy));
        if (m.includes('b')) State.roi.box.y2 = Math.max(sb.y1 + 0.05, Math.min(1, sb.y2 + dy));
        if (m.includes('l')) State.roi.box.x1 = Math.max(0, Math.min(sb.x2 - 0.05, sb.x1 + dx));
        if (m.includes('r')) State.roi.box.x2 = Math.max(sb.x1 + 0.05, Math.min(1, sb.x2 + dx));
      }
      updateUI();
    });

    window.addEventListener('mouseup', () => { State.roi.dragging = false; });

    new ResizeObserver(updateUI).observe(stream);
  }

  stream.onload = updateUI;
  if (stream.complete) updateUI();
  setTimeout(updateUI, 100);
  setTimeout(updateUI, 500);
  window._roiUpdateUI = updateUI;
}

async function saveROISettings() {
  const cid = State.roi.cid;
  const box = [State.roi.box.x1, State.roi.box.y1, State.roi.box.x2, State.roi.box.y2];

  closeModal('modal-roi');
  toast('Synchronizing zone…', 'amber');

  const fd = new FormData();
  fd.append('node_key', cid);
  fd.append('roi', JSON.stringify(box));

  try {
    await api('/api/roi/save', { method: 'POST', body: fd });
    toast('Zone saved', 'green');
    loadCameras();
  } catch (e) { toast('Sync failed: ' + e.message, 'red'); }
}

function resetROI() {
  State.roi.box = { x1: 0, y1: 0, x2: 1, y2: 1 };
  if (window._roiUpdateUI) window._roiUpdateUI();
}

/* ─── LIVE MONITORING ─── */
async function startLiveMonitoring() {
  async function refresh() {
    try {
      const data  = await api('/api/active-users');
      const nodes = data.nodes || [];
      const activeIds = nodes.map(n => n.id);

      // Live feed grid
      const grid  = document.getElementById('live-grid');
      const empty = document.getElementById('no-streams');
      if (grid && empty) {
        empty.style.display = nodes.length ? 'none' : 'block';
        Array.from(grid.children).forEach(el => { if (!activeIds.includes(el.dataset.camId)) el.remove(); });
        nodes.forEach(node => {
          if (grid.querySelector(`[data-cam-id="${node.id}"]`)) return;
          const card = document.createElement('div');
          card.className = 'card';
          card.dataset.camId = node.id;
          card.style.cursor = 'pointer';
          card.onclick = () => showFullScreenStream(node.id);
          card.innerHTML = `
            <div style="position:relative">
              <div style="position:absolute;top:8px;left:8px;z-index:10;background:rgba(0,0,0,0.6);color:var(--cyan);font-family:var(--font-mono);font-size:0.58rem;font-weight:700;padding:3px 8px;border-radius:4px;display:flex;align-items:center;gap:5px">
                <span style="width:6px;height:6px;background:var(--cyan);border-radius:50%;animation:blink 1.5s infinite"></span>
                LIVE: ${esc(node.id)}
              </div>
              <img src="/api/stream/${esc(node.id)}" style="width:100%;aspect-ratio:16/9;object-fit:cover;display:block;background:#000"
                   onerror="this.src=''">
            </div>
            <div class="card-body" style="display:flex;justify-content:space-between;align-items:center">
              <div class="td-mono">CHANNEL: ${esc(node.id)}</div>
              <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();showROI('${esc(node.id)}')">⊞ ROI</button>
            </div>`;
          grid.appendChild(card);
        });
      }

      // Overview matrix
      const matrix = document.getElementById('overview-monitor');
      if (matrix) {
        matrix.style.display = nodes.length ? 'grid' : 'none';
        Array.from(matrix.children).forEach(el => { if (!activeIds.includes(el.dataset.id)) el.remove(); });
        nodes.forEach(node => {
          if (matrix.querySelector(`[data-id="${node.id}"]`)) return;
          const box = document.createElement('div');
          box.className = 'monitor-box';
          box.dataset.id = node.id;
          box.onclick = () => showFullScreenStream(node.id);
          box.innerHTML = `
            <div class="label">${esc(node.id)}</div>
            <div class="status" style="background:var(--cyan);box-shadow:0 0 8px var(--cyan)"></div>
            <img src="/api/stream/${esc(node.id)}" onerror="this.src=''">`;
          matrix.appendChild(box);
        });
      }
    } catch {}
  }

  await refresh();
  if (!State.liveInterval) State.liveInterval = setInterval(refresh, 5000);
}

function stopLiveMonitoring() {
  if (State.liveInterval) { clearInterval(State.liveInterval); State.liveInterval = null; }
  const grid   = document.getElementById('live-grid');
  const matrix = document.getElementById('overview-monitor');
  if (grid) grid.innerHTML = '';
  if (matrix) { matrix.innerHTML = ''; matrix.style.display = 'none'; }
}

function showFullScreenStream(nodeId) {
  document.getElementById('tactical-stream-img').src = `/api/stream/${nodeId}`;
  document.getElementById('tactical-stream-subtitle').textContent = `// CHANNEL: ${nodeId}`;
  openModal('modal-tactical-fullscreen');
}

function closeFullScreenStream() {
  document.getElementById('tactical-stream-img').src = '';
  closeModal('modal-tactical-fullscreen');
}

/* ─── MAP ─── */
function updateMapCameraList(cameras) {
  State.mapCameras = cameras;
  const el = document.getElementById('map-camera-list');
  if (!el) return;

  el.innerHTML = cameras.map(c => `
    <div class="camera-status-item">
      <div style="width:8px;height:8px;border-radius:50%;flex-shrink:0;background:${c.online ? 'var(--green)' : 'var(--red)'}"></div>
      <div style="flex:1;min-width:0">
        <div style="font-size:0.82rem;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(c.name)}</div>
        <div class="td-mono" style="font-size:0.62rem">${esc(c.camera_id)}</div>
      </div>
      <span style="font-size:0.7rem;color:${c.online ? 'var(--green)' : 'var(--on-surface-muted)'}">${c.online ? 'ON' : 'OFF'}</span>
    </div>`).join('') || '<div style="color:var(--on-surface-muted);font-size:0.8rem">No cameras registered</div>';

  const online  = cameras.filter(c => c.online).length;
  const offline = cameras.length - online;
  setText('map-stat-online',  online);
  setText('map-stat-offline', offline);
  renderMapPins(cameras);
}

async function loadMap() {
  const cameras = await api('/api/cameras');
  updateMapCameraList(cameras);
}

function loadFloorplan(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    const img = new Image();
    img.onload = () => {
      State.floorplanImg = img;
      const canvas    = document.getElementById('map-canvas');
      const container = document.getElementById('map-container');
      canvas.width  = container.offsetWidth  || 800;
      canvas.height = container.offsetHeight || 500;
      canvas.style.display = 'block';
      document.getElementById('map-placeholder').style.display = 'none';
      drawFloorplan();
      renderMapPins(State.mapCameras);
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
}

function drawFloorplan() {
  if (!State.floorplanImg) return;
  const canvas = document.getElementById('map-canvas');
  const ctx    = canvas.getContext('2d');
  ctx.drawImage(State.floorplanImg, 0, 0, canvas.width, canvas.height);
}

function renderMapPins(cameras) {
  const svg       = document.getElementById('map-svg');
  const container = document.getElementById('map-container');
  if (!svg || !container) return;
  const W = container.offsetWidth  || 800;
  const H = container.offsetHeight || 500;

  svg.innerHTML = cameras.map(c => {
    const x     = ((c.floor_plan_x || 50) / 100) * W;
    const y     = ((c.floor_plan_y || 50) / 100) * H;
    const color = c.online ? '#56e097' : '#ff8a8a';
    const pulse = c.online
      ? `<circle cx="${x}" cy="${y}" r="12" fill="${color}" fill-opacity="0.12"><animate attributeName="r" from="10" to="22" dur="2s" repeatCount="indefinite"/><animate attributeName="fill-opacity" from="0.25" to="0" dur="2s" repeatCount="indefinite"/></circle>`
      : '';
    const editAttr = State.mapEditMode ? `style="pointer-events:all;cursor:grab" data-cam="${esc(c.camera_id)}"` : '';
    const labelW   = c.name.length * 6.5 + 16;

    return `<g class="map-pin" ${editAttr} onclick="onMapPinClick('${esc(c.camera_id)}')">
      ${pulse}
      <circle cx="${x}" cy="${y}" r="10" fill="${color}" fill-opacity="0.85" stroke="rgba(0,0,0,0.4)" stroke-width="1.5"/>
      <g transform="translate(${x - 5}, ${y - 5}) scale(0.42)">
        <path d="M23 7l-7 5 7 5V7z" fill="white"/>
        <rect x="1" y="5" width="15" height="14" rx="2" ry="2" fill="white"/>
      </g>
      <rect x="${x + 13}" y="${y - 14}" width="${labelW}" height="18" rx="4" fill="rgba(0,0,0,0.7)" stroke="${color}" stroke-width="0.5"/>
      <text x="${x + 21}" y="${y - 2}" fill="white" font-size="9" font-family="monospace">${esc(c.name)}</text>
    </g>`;
  }).join('');
}

function onMapPinClick(cameraId) {
  if (State.mapEditMode) return;
  const cam = State.mapCameras.find(c => c.camera_id === cameraId);
  if (cam) toast(`${cam.name} — ${cam.online ? 'ONLINE' : 'OFFLINE'}`, cam.online ? 'green' : 'red');
}

function toggleMapEdit() {
  State.mapEditMode = !State.mapEditMode;
  const btn = document.getElementById('map-edit-btn');
  const svg = document.getElementById('map-svg');
  if (btn) btn.textContent = State.mapEditMode ? '✓ Done Editing' : '✎ Edit Positions';
  if (svg) svg.style.pointerEvents = State.mapEditMode ? 'all' : 'none';

  if (State.mapEditMode) {
    svg.addEventListener('mousedown', onMapDragStart);
    svg.addEventListener('mousemove', onMapDragMove);
    svg.addEventListener('mouseup',   onMapDragEnd);
  } else {
    svg.removeEventListener('mousedown', onMapDragStart);
    svg.removeEventListener('mousemove', onMapDragMove);
    svg.removeEventListener('mouseup',   onMapDragEnd);
  }
}

function onMapDragStart(e) {
  const pin = e.target.closest('.map-pin');
  if (!pin) return;
  State.dragCam = pin.dataset.cam;
  e.preventDefault();
}

function onMapDragMove(e) {
  if (!State.dragCam) return;
  const svg  = document.getElementById('map-svg');
  const rect = svg.getBoundingClientRect();
  const x    = ((e.clientX - rect.left) / rect.width  * 100).toFixed(1);
  const y    = ((e.clientY - rect.top)  / rect.height * 100).toFixed(1);
  const cam  = State.mapCameras.find(c => c.camera_id === State.dragCam);
  if (cam) { cam.floor_plan_x = parseFloat(x); cam.floor_plan_y = parseFloat(y); }
  renderMapPins(State.mapCameras);
}

async function onMapDragEnd() {
  if (!State.dragCam) return;
  const cam = State.mapCameras.find(c => c.camera_id === State.dragCam);
  if (cam) {
    try {
      await api(`/api/cameras/${State.dragCam}/position`, {
        method: 'PUT',
        body: JSON.stringify({ x: cam.floor_plan_x, y: cam.floor_plan_y }),
      });
    } catch {}
  }
  State.dragCam = null;
}
