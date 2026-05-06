/* ══════════════════════════════════════════
   INTELLIGENCE FEATURES
   Person Trail · Crowd Density · CSV Export
   ══════════════════════════════════════════ */

/* ─── PERSON TRAIL ─── */

async function showPersonTrail(trackId) {
  const el = document.getElementById('trail-timeline');
  if (el) el.innerHTML = '<div class="empty-state" style="padding:2rem"><div class="empty-text">LOADING TRAIL...</div></div>';
  openModal('modal-trail');
  try {
    const data = await api(`/api/sightings/trail/${trackId}`);
    renderTrailTimeline(data.trail || []);
    const header = document.getElementById('trail-modal-header');
    if (header) header.textContent = `PERSON TRAIL — ${(data.count || 0)} SIGHTINGS`;
  } catch (err) {
    toast(`Failed to load trail: ${err.message}`, 'red');
    if (el) el.innerHTML = `<div class="empty-state"><div class="empty-text" style="color:var(--red)">ERROR: ${esc(err.message)}</div></div>`;
  }
}

function renderTrailTimeline(trail) {
  const el = document.getElementById('trail-timeline');
  if (!el) return;

  if (!trail || !trail.length) {
    el.innerHTML = '<div class="empty-state" style="padding:2rem"><div class="empty-icon">◎</div><div class="empty-text">No movement history found</div></div>';
    return;
  }

  el.innerHTML = trail.map((s, idx) => `
    <div class="trail-item">
      <div class="trail-dot"></div>
      ${idx < trail.length - 1 ? '<div class="trail-line"></div>' : ''}
      <div class="trail-time">${fmtTs(s.timestamp)}</div>
      <div class="trail-card">
        <img src="${esc(s.snapshot || '')}" class="trail-img"
             onerror="this.style.background='var(--surface-high)';this.removeAttribute('src')">
        <div class="trail-info">
          <div class="trail-cam">${esc(s.camera_id || '—')}</div>
          <div class="trail-loc">${esc(s.location || '—')}</div>
          ${s.matched ? `<div class="badge-mini" style="background:var(--red-dim);color:var(--red);border:1px solid var(--red);margin-top:4px">⚠ MATCH: ${esc(s.person_name || '')}</div>` : ''}
        </div>
      </div>
    </div>
  `).join('');
}

/* ─── CROWD DENSITY ─── */

async function pollCrowdDensity() {
  if (State.activePage !== 'overview') return;
  const grid = document.getElementById('crowd-monitor-grid');
  if (!grid) return;

  try {
    const health = await api('/api/system/health');
    const peaks = health.crowd_peaks || [];

    if (!peaks.length) {
      grid.innerHTML = '<div class="empty-state" style="padding:1rem;grid-column:1/-1"><div class="empty-text" style="font-size:0.7rem">AWAITING TELEMETRY...</div></div>';
      return;
    }

    grid.innerHTML = peaks.map(p => {
      const isHigh = (p.peak || 0) > 10;
      return `
        <div class="crowd-card" style="border-left-color: ${isHigh ? 'var(--red)' : 'var(--purple)'}">
          <div class="crowd-label">${esc(p.camera_id || '—')}</div>
          <div class="crowd-count" style="color: ${isHigh ? 'var(--red)' : 'var(--on-surface)'}">${p.peak ?? '—'}</div>
          <div class="crowd-peak">PEAK TODAY</div>
        </div>
      `;
    }).join('');
  } catch (e) {
    console.warn('[crowd-density]', e);
  }
}

/* ─── CSV EXPORT ─── */

async function doSightingsExport(e) {
  if (e) e.preventDefault();
  toast('Generating CSV report...', 'cyan');
  try {
    const url = `${State.api}/api/sightings/export`;
    const res = await fetch(url, {
      headers: { 'Authorization': `Bearer ${State.token}` }
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = `sentrix_sightings_${new Date().toISOString().split('T')[0]}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(downloadUrl);
    toast('✓ Report downloaded', 'green');
  } catch (err) {
    toast(`Export failed: ${err.message}`, 'red');
  }
}
