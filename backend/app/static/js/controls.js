/* ══════════════════════════════════════════
   CONTROLS — Mesh, Runtime, Mini Monitor
   ══════════════════════════════════════════ */

/* ─── MESH STATUS ─── */
async function pollMeshStatus() {
  try {
    const d = await api('/api/mesh/status');
    const active    = d.mesh_active;
    const statusTxt = document.getElementById('mesh-status-text');
    const startBtn  = document.getElementById('mesh-start-btn');
    const stopBtn   = document.getElementById('mesh-stop-btn');

    if (statusTxt) {
      const pulse = statusTxt.querySelector('.mesh-pulse');
      if (pulse) pulse.style.display = active ? '' : 'none';
      // Update text node (third child after icon and pulse)
      const textNodes = Array.from(statusTxt.childNodes).filter(n => n.nodeType === 3);
      if (textNodes.length) textNodes[0].nodeValue = ` MESH STATUS: ${active ? 'ACTIVE' : 'OFFLINE'}`;
      statusTxt.style.color = active ? 'var(--green)' : 'var(--on-surface-muted)';
    }

    if (startBtn) { startBtn.disabled = active; startBtn.style.opacity = active ? '0.5' : '1'; }
    if (stopBtn)  {
      if (State.role !== 'admin' && State.role !== 'super_admin') { stopBtn.style.display = 'none'; }
      else { stopBtn.disabled = !active; stopBtn.style.opacity = active ? '1' : '0.5'; }
    }
  } catch {}
}

async function startMesh() {
  showSyncAlert('loading');
  try {
    await api('/api/mesh/start', { method: 'POST' });
    setTimeout(async () => {
      await pollMeshStatus();
      showSyncAlert('done');
      setTimeout(hideSyncAlert, 2000);
    }, 3000);
  } catch (e) { hideSyncAlert(); toast('Startup failed: ' + e.message, 'red'); }
}

async function stopMesh() {
  if (!confirm('SHUTDOWN PROTOCOL: Stop all mesh operations?')) return;
  showSyncAlert('loading');
  try {
    await api('/api/mesh/stop', { method: 'POST' });
    setTimeout(async () => {
      await pollMeshStatus();
      showSyncAlert('done');
      setTimeout(hideSyncAlert, 2000);
    }, 2000);
  } catch (e) { hideSyncAlert(); toast('Shutdown failed: ' + e.message, 'red'); }
}

async function startNode(nodeId) {
  try {
    await api(`/api/mesh/nodes/${nodeId}/start`, { method: 'POST' });
    toast(`Starting node: ${nodeId}`, 'green');
    setTimeout(loadCameras, 1500);
  } catch (e) { toast('Failed: ' + e.message, 'red'); }
}

async function stopNode(nodeId) {
  try {
    await api(`/api/mesh/nodes/${nodeId}/stop`, { method: 'POST' });
    toast(`Stopping node: ${nodeId}`, 'muted');
    setTimeout(loadCameras, 1000);
  } catch (e) { toast('Failed: ' + e.message, 'red'); }
}

/* ─── FEATURE TOGGLES ─── */
async function toggleCameraFeature(cameraId, feature, enabled) {
  try {
    await api(`/api/cameras/config/${cameraId}?${feature}=${enabled}`, { method: 'POST' });
    toast(`${feature.toUpperCase()} ${enabled ? 'ENABLED' : 'DISABLED'} for ${cameraId}`, enabled ? 'cyan' : 'muted');
    loadCameras();
  } catch (e) { toast('Toggle failed: ' + e.message, 'red'); }
}

function toggleGlobalBtn(feature) {
  const btn = document.getElementById(`sbtn-${feature}`);
  if (!btn) return;
  const isActive = btn.classList.contains('active');
  toggleGlobalFeature(feature, !isActive);
}

async function toggleGlobalFeature(feature, enabled) {
  try {
    await api(`/api/system/global-toggle?feature=${feature}&enabled=${enabled ? 1 : 0}`, { method: 'POST' });
    toast(`GLOBAL ${feature.toUpperCase()}: ${enabled ? 'ON' : 'OFF'}`, enabled ? 'green' : 'red');
    syncGlobalButtons();
    if (State.activePage === 'cameras') loadCameras();
  } catch (e) { toast('Global toggle failed: ' + e.message, 'red'); }
}

function syncGlobalButtons() {
  if (!State.cameras.length) return;
  const cam = State.cameras[0];
  ['face', 'obj', 'stream'].forEach(f => {
    const btn = document.getElementById(`sbtn-${f}`);
    if (!btn) return;
    const enabled = cam[`${f}_enabled`];
    btn.classList.toggle('active', !!enabled);
    const st = btn.querySelector('.status-text');
    if (st) st.textContent = enabled ? 'ACTIVE' : 'INACTIVE';
  });
}

/* ─── MINI MONITOR ─── */
function toggleMiniMonitor() {
  const mm     = document.getElementById('mini-monitor');
  const toggle = document.getElementById('mm-toggle');
  State.mmActive = !State.mmActive;

  if (State.mmActive) {
    mm.classList.add('open');
    toggle.classList.add('active');
    _startMMUpdates();
  } else {
    mm.classList.remove('open');
    toggle.classList.remove('active');
    _stopMMUpdates();
  }
}

function _startMMUpdates() {
  if (State.mmInterval) clearInterval(State.mmInterval);
  _refreshMM();
  State.mmInterval = setInterval(_refreshMM, 5000);
}

function _stopMMUpdates() {
  if (State.mmInterval) { clearInterval(State.mmInterval); State.mmInterval = null; }
  const grid = document.getElementById('mm-grid');
  if (grid) grid.innerHTML = '';
}

async function _refreshMM() {
  if (!State.mmActive) return;
  try {
    const data = await api('/api/active-users');
    const grid = document.getElementById('mm-grid');
    if (!grid) return;

    if (!data.nodes?.length) {
      grid.innerHTML = '<div style="grid-column:span 2;padding:2rem;text-align:center;font-family:var(--font-mono);font-size:0.6rem;color:var(--on-surface-muted)">NO ACTIVE NODES</div>';
      return;
    }

    const activeIds = data.nodes.map(n => n.id);
    Array.from(grid.children).forEach(el => { if (!activeIds.includes(el.dataset.id)) el.remove(); });

    data.nodes.forEach(node => {
      if (grid.querySelector(`[data-id="${node.id}"]`)) return;
      const div = document.createElement('div');
      div.className = 'mm-cam';
      div.dataset.id = node.id;
      div.innerHTML = `
        <div class="mm-cam-label">${esc(node.id)}</div>
        <img src="/api/stream/${esc(node.id)}?token=${State.token}" onerror="this.style.opacity='0.3'">`;
      grid.appendChild(div);
    });
  } catch {}
}

// Also called from bootstrap for background sync
async function syncMiniMonitor() { await _refreshMM(); }
