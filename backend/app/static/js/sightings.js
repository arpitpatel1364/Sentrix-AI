/* ══════════════════════════════════════════
   SIGHTINGS, OBJECTS & STATS
   ══════════════════════════════════════════ */

/* ─── STATS ─── */
async function loadStats() {
  try {
    const s = await api('/api/system/stats');
    setText('s-sightings', s.total_sightings ?? '—');
    setText('s-matches',   s.total_matches   ?? '—');
    setText('s-objects',   s.total_objects   ?? '—');
    setText('s-wanted',    s.total_wanted    ?? '—');
    setText('s-nodes',     s.total_nodes     ?? '—');
    setText('sb-node-count', `${s.total_nodes || 0} NODES`);
    setText('sys-nodes',   s.total_nodes     ?? '—');
    updateConnectionStatus(true);
  } catch {}
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

/* ─── SIGHTINGS ─── */
async function loadSightings() {
  try {
    const d = await api('/api/sightings?limit=60');
    renderSightingsFeed(d.sightings || [], 'sightings-feed');
    renderSightingsFeed((d.sightings || []).slice(0, 4), 'overview-sightings');
    updateBadge('badge-sightings', State.newSightings);
  } catch {}
}

function renderSightingsFeed(sightings, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;

  if (!sightings.length) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">◎</div><div class="empty-text">No sightings recorded</div><div class="empty-sub">// AWAITING CAMERA INPUT</div></div>`;
    return;
  }

  el.innerHTML = sightings.map(s => {
    const snapData = JSON.stringify({
      snapshot_url: s.snapshot,
      camera_id: s.camera_id,
      location: s.location,
      timestamp: s.timestamp,
      person_name: s.matched ? s.person_name : 'Unknown Person',
      confidence: s.confidence,
      matched: s.matched,
      type: 'face',
    }).replace(/"/g, '&quot;');

    return `
      <div class="card ${s.matched ? 'matched' : ''}" onclick='openSnapshot(${snapData})' style="cursor:pointer">
        <img class="card-thumb" src="${esc(s.snapshot)}" loading="lazy"
             onerror="this.style.background='var(--surface-high)';this.removeAttribute('src')">
        <div class="card-body">
          <div class="card-tag ${s.matched ? 'match' : 'unknown'}">${s.matched ? '⚠ MATCH' : 'UNIDENTIFIED'}</div>
          <div class="card-name">${esc(s.matched ? s.person_name : 'Unknown Person')}</div>
          <div class="card-meta">
            <span>${esc(s.camera_id || '—')}</span>
            <span>${fmtTs(s.timestamp)}</span>
          </div>
          ${s.matched ? `<div class="card-conf">Confidence: ${s.confidence}%</div>` : ''}
          <div class="card-meta" style="margin-top:0.3rem">${esc(s.location || '—')}</div>
        </div>
      </div>`;
  }).join('');
}

/* ─── OBJECTS ─── */
async function loadObjects() {
  try {
    const d = await api('/api/objects/?limit=60');
    renderObjectsFeed(d.objects || [], 'objects-feed');
    renderObjectsFeed((d.objects || []).slice(0, 4), 'overview-objects');
    updateBadge('badge-objects', State.newObjects);
  } catch {}
}

function renderObjectsFeed(objects, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;

  if (!objects.length) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">◈</div><div class="empty-text">No object detections</div><div class="empty-sub">// AWAITING CAMERA INPUT</div></div>`;
    return;
  }

  el.innerHTML = objects.map(o => {
    const conf = Math.round((o.confidence || 0) * 100);
    const snapData = JSON.stringify({
      snapshot_url: o.snapshot,
      camera_id: o.camera_id,
      location: o.location,
      timestamp: o.timestamp,
      person_name: (o.object_label || 'Object').toUpperCase(),
      confidence: conf,
      matched: false,
      type: 'object',
    }).replace(/"/g, '&quot;');

    return `
      <div class="card" onclick='openSnapshot(${snapData})' style="cursor:pointer">
        <img class="card-thumb" src="${esc(o.snapshot)}" loading="lazy"
             onerror="this.style.background='var(--surface-high)';this.removeAttribute('src')">
        <div class="card-body">
          <div class="card-tag object">${esc((o.object_label || 'unknown').toUpperCase())}</div>
          <div class="card-name">${esc(capitalize(o.object_label || 'Unknown'))}</div>
          <div class="card-meta">
            <span>${esc(o.camera_id || '—')}</span>
            <span>${fmtTs(o.timestamp)}</span>
          </div>
          <div class="card-conf">Confidence: ${conf}%</div>
          <div class="card-meta" style="margin-top:0.3rem">${esc(o.location || '—')}</div>
        </div>
      </div>`;
  }).join('');
}

/* ─── SNAPSHOT VIEWER ─── */
function openSnapshot(snap) {
  document.getElementById('snap-modal-img').src = snap.snapshot_url || '';
  document.getElementById('snap-modal-cam').textContent  = snap.camera_id || '—';
  document.getElementById('snap-modal-cam2').textContent = snap.camera_id || '—';
  document.getElementById('snap-modal-name').textContent = snap.person_name || (snap.type === 'object' ? 'Detected Object' : 'Unknown Face');
  document.getElementById('snap-modal-loc').textContent  = snap.location || '—';
  document.getElementById('snap-modal-ts').textContent   = snap.timestamp ? fmtTs(snap.timestamp) : '—';

  const matchLabel = document.getElementById('snap-modal-match-label');
  const matchEl    = document.getElementById('snap-modal-match');
  const confEl     = document.getElementById('snap-modal-conf');

  if (snap.type === 'object') {
    if (matchLabel) matchLabel.textContent = 'DETECTION TYPE';
    matchEl.innerHTML = `<span style="color:var(--cyan);font-weight:600">■ ${esc(snap.person_name)}</span>`;
  } else {
    if (matchLabel) matchLabel.textContent = 'MATCH STATUS';
    matchEl.innerHTML = snap.matched
      ? `<span style="color:var(--red);font-weight:600">⚠ WANTED — ${esc(snap.person_name)}</span>`
      : `<span style="color:var(--on-surface-muted)">Unknown / Unmatched</span>`;
  }

  const confNum = typeof snap.confidence === 'number' ? snap.confidence : parseFloat(snap.confidence);
  confEl.textContent = isNaN(confNum) ? '—' : confNum.toFixed(1) + '%';

  const dl = document.getElementById('snap-modal-download');
  if (dl) {
    dl.href = snap.snapshot_url || '#';
    dl.download = `snapshot_${snap.camera_id}_${(snap.timestamp || '').replace(/[:.T]/g, '')}.jpg`;
  }

  openModal('modal-snapshot');
}
