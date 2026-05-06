/* ══════════════════════════════════════════
   INTELLIGENCE FEATURES
   Person Trail · Crowd Density · Notifications
   ══════════════════════════════════════════ */

/* ─── PERSON TRAIL (Modal — triggered from snapshot viewer) ─── */

async function showPersonTrail(trackId) {
  const el = document.getElementById('trail-timeline');
  if (el) el.innerHTML = '<div class="empty-state" style="padding:2rem"><div class="empty-text">LOADING TRAIL...</div></div>';
  openModal('modal-trail');
  try {
    const data = await api(`/api/sightings/trail/${trackId}`);
    renderTrailTimeline(data.trail || [], 'trail-timeline');
    const header = document.getElementById('trail-modal-header');
    if (header) header.textContent = `PERSON TRAIL — ${(data.count || 0)} SIGHTINGS`;
  } catch (err) {
    toast(`Failed to load trail: ${err.message}`, 'red');
    if (el) el.innerHTML = `<div class="empty-state"><div class="empty-text" style="color:var(--red)">ERROR: ${esc(err.message)}</div></div>`;
  }
}

function renderTrailTimeline(trail, containerId) {
  const el = document.getElementById(containerId || 'trail-timeline');
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

/* ─── PERSON TRAIL PAGE ─── */

async function loadPersonTrailPage() {
  // Load recent sightings that have a track_id assigned
  const grid = document.getElementById('trail-page-grid');
  if (!grid) return;
  try {
    const d = await api('/api/sightings?limit=100');
    const tracked = (d.sightings || []).filter(s => s.track_id);

    // Deduplicate by track_id — show only the latest sighting per track
    const seen = new Map();
    tracked.forEach(s => {
      if (!seen.has(s.track_id) || s.timestamp > seen.get(s.track_id).timestamp) {
        seen.set(s.track_id, s);
      }
    });

    const unique = [...seen.values()].sort((a, b) => b.timestamp.localeCompare(a.timestamp));

    if (!unique.length) {
      grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;padding:2rem">
        <div class="empty-icon">◎</div>
        <div class="empty-text">No tracked individuals yet</div>
        <div class="empty-sub">// Run sightings with Re-ID enabled to populate</div>
      </div>`;
      return;
    }

    grid.innerHTML = unique.map(s => `
      <div class="panel" style="cursor:pointer;transition:all 0.2s" onclick="searchTrailById('${esc(s.track_id)}')"
           onmouseover="this.style.borderColor='var(--primary)'" onmouseout="this.style.borderColor=''">
        <img src="${esc(s.snapshot || '')}" style="width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:var(--radius-sm);margin-bottom:0.75rem"
             onerror="this.style.background='var(--surface-high)';this.removeAttribute('src')">
        <div style="font-size:0.65rem;font-family:var(--font-mono);color:var(--primary);margin-bottom:4px">TRACK ID</div>
        <div style="font-size:0.6rem;font-family:var(--font-mono);color:var(--on-surface-muted);word-break:break-all;margin-bottom:0.5rem">${esc(s.track_id)}</div>
        <div class="result-item"><span class="result-label">Camera</span><span style="font-family:var(--font-mono);font-size:0.7rem">${esc(s.camera_id || '—')}</span></div>
        <div class="result-item"><span class="result-label">Last Seen</span><span style="font-size:0.7rem">${fmtTs(s.timestamp)}</span></div>
        <button class="btn btn-primary btn-sm" style="width:100%;margin-top:0.75rem" onclick="event.stopPropagation();searchTrailById('${esc(s.track_id)}')">View Trail →</button>
      </div>
    `).join('');
  } catch (e) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><div class="empty-text" style="color:var(--red)">Error: ${esc(e.message)}</div></div>`;
  }
}

function searchTrail() {
  const input = document.getElementById('trail-search-input');
  const id = (input?.value || '').trim();
  if (!id) { toast('Enter a Track ID', 'red'); return; }
  searchTrailById(id);
}

async function searchTrailById(trackId) {
  const panel = document.getElementById('trail-result-panel');
  const header = document.getElementById('trail-result-header');
  const timeline = document.getElementById('trail-page-timeline');

  if (panel) panel.style.display = 'block';
  if (timeline) timeline.innerHTML = '<div class="empty-state" style="padding:2rem"><div class="empty-text">LOADING...</div></div>';
  if (header) header.textContent = 'LOADING TRAIL...';

  // Scroll to result
  panel?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  try {
    const data = await api(`/api/sightings/trail/${trackId}`);
    if (header) header.textContent = `TRAIL — ${data.count || 0} SIGHTINGS ACROSS ${[...new Set((data.trail || []).map(s => s.camera_id))].length} CAMERAS`;
    renderTrailTimeline(data.trail || [], 'trail-page-timeline');
  } catch (err) {
    toast(`Trail not found: ${err.message}`, 'red');
    if (panel) panel.style.display = 'none';
  }
}

/* ─── CROWD DENSITY PAGE ─── */

async function loadCrowdDensityPage() {
  const grid    = document.getElementById('crowd-page-grid');
  const updated = document.getElementById('crowd-last-updated');
  if (!grid) return;

  try {
    const health = await api('/api/system/health');
    const peaks  = health.crowd_peaks || [];

    if (updated) updated.textContent = `Updated ${fmtTs(new Date().toISOString())}`;

    // Summary stats
    const totalCams  = peaks.length;
    const peakMax    = peaks.reduce((m, p) => Math.max(m, p.peak || 0), 0);
    const highAlerts = peaks.filter(p => (p.peak || 0) > 10).length;
    setText('crowd-stat-cameras', totalCams);
    setText('crowd-stat-peak',    peakMax);
    setText('crowd-stat-alerts',  highAlerts);

    if (!peaks.length) {
      grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;padding:2rem">
        <div class="empty-icon">◎</div>
        <div class="empty-text">Awaiting telemetry</div>
        <div class="empty-sub">// Workers must call /api/camera-heartbeat with headcount data</div>
      </div>`;
      document.getElementById('crowd-history-list').innerHTML = '';
      return;
    }

    // Live cards
    grid.innerHTML = peaks.map(p => {
      const isHigh = (p.peak || 0) > 10;
      const pct = Math.min(100, Math.round(((p.peak || 0) / Math.max(peakMax, 1)) * 100));
      return `
        <div class="crowd-card" style="border-left-color: ${isHigh ? 'var(--red)' : 'var(--purple)'}">
          <div class="crowd-label">${esc(p.camera_id || '—')}</div>
          <div class="crowd-count" style="color: ${isHigh ? 'var(--red)' : 'var(--on-surface)'}">${p.peak ?? '—'}</div>
          <div class="crowd-peak">PEAK TODAY${isHigh ? ' ⚠ HIGH' : ''}</div>
          <div style="height:4px;background:var(--surface-high);border-radius:2px;overflow:hidden;margin-top:8px">
            <div style="height:100%;width:${pct}%;background:${isHigh ? 'var(--red)' : 'var(--purple)'};border-radius:2px;transition:width 0.5s"></div>
          </div>
        </div>
      `;
    }).join('');

    // History bar list
    const histEl = document.getElementById('crowd-history-list');
    if (histEl) {
      histEl.innerHTML = peaks
        .sort((a, b) => (b.peak || 0) - (a.peak || 0))
        .map(p => {
          const pct = Math.min(100, Math.round(((p.peak || 0) / Math.max(peakMax, 1)) * 100));
          const isHigh = (p.peak || 0) > 10;
          return `
            <div>
              <div style="display:flex;justify-content:space-between;font-size:0.75rem;margin-bottom:3px">
                <span style="font-family:var(--font-mono)">${esc(p.camera_id)}</span>
                <span style="color:${isHigh ? 'var(--red)' : 'var(--on-surface-muted)'}">Peak: ${p.peak}</span>
              </div>
              <div style="height:6px;background:var(--surface-high);border-radius:3px;overflow:hidden">
                <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,var(--purple),${isHigh ? 'var(--red)' : 'var(--cyan)'});border-radius:3px;transition:width 0.6s"></div>
              </div>
            </div>
          `;
        }).join('');
    }
  } catch (e) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><div class="empty-text" style="color:var(--red)">Error: ${esc(e.message)}</div></div>`;
  }
}

/* ─── CROWD DENSITY (Overview Widget — called by cameras.js polling) ─── */

async function pollCrowdDensity() {
  if (State.activePage !== 'overview') return;
  const grid = document.getElementById('crowd-monitor-grid');
  if (!grid) return;
  try {
    const health = await api('/api/system/health');
    const peaks  = health.crowd_peaks || [];
    if (!peaks.length) {
      grid.innerHTML = '<div class="empty-state" style="padding:1rem;grid-column:1/-1"><div class="empty-text" style="font-size:0.7rem">AWAITING TELEMETRY...</div></div>';
      return;
    }
    grid.innerHTML = peaks.map(p => {
      const isHigh = (p.peak || 0) > 10;
      return `
        <div class="crowd-card" style="border-left-color:${isHigh ? 'var(--red)' : 'var(--purple)'}">
          <div class="crowd-label">${esc(p.camera_id || '—')}</div>
          <div class="crowd-count" style="color:${isHigh ? 'var(--red)' : 'var(--on-surface)'}">${p.peak ?? '—'}</div>
          <div class="crowd-peak">PEAK TODAY${isHigh ? ' ⚠' : ''}</div>
        </div>
      `;
    }).join('');
  } catch (e) { console.warn('[crowd-density]', e); }
}

/* ─── CSV EXPORT ─── */

async function doSightingsExport(e) {
  if (e) e.preventDefault();
  toast('Generating CSV report...', 'cyan');
  try {
    const url = `${State.api}/api/sightings/export`;
    const res = await fetch(url, { headers: { 'Authorization': `Bearer ${State.token}` } });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = window.URL.createObjectURL(blob);
    a.download = `sentrix_sightings_${new Date().toISOString().split('T')[0]}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    window.URL.revokeObjectURL(a.href);
    toast('✓ Report downloaded', 'green');
  } catch (err) { toast(`Export failed: ${err.message}`, 'red'); }
}

/* ─── NOTIFICATIONS PAGE ─── */

async function loadNotificationsPage() {
  try {
    const [cfg, history] = await Promise.all([
      api('/api/notifications/config'),
      api('/api/notifications/history?limit=50')
    ]);

    // Email status card
    const emailConfigured = !!cfg.smtp_host;
    setText('notif-email-status', emailConfigured ? '✓ Configured' : 'Not configured');
    const emailStatusEl = document.getElementById('notif-email-status');
    if (emailStatusEl) emailStatusEl.style.color = emailConfigured ? 'var(--green)' : 'var(--on-surface-muted)';
    setText('notif-email-host', emailConfigured ? `${cfg.smtp_host}:${cfg.smtp_port || 587}` : '—');

    // Telegram status card
    const tgConfigured = !!cfg.telegram_bot_token;
    setText('notif-tg-status', tgConfigured ? '✓ Configured' : 'Not configured');
    const tgStatusEl = document.getElementById('notif-tg-status');
    if (tgStatusEl) tgStatusEl.style.color = tgConfigured ? 'var(--green)' : 'var(--on-surface-muted)';
    setText('notif-tg-chat', tgConfigured ? `Chat ID: ${cfg.telegram_chat_id || '—'}` : '—');

    // Stats
    const today = new Date().toISOString().split('T')[0];
    const total  = history.length;
    const todayN = history.filter(h => h.sent_at?.startsWith(today)).length;
    const failed = history.filter(h => h.status === 'failed').length;
    setText('notif-count-today',  todayN);
    setText('notif-count-total',  total);
    setText('notif-count-failed', failed);

    // History table
    const tbody = document.getElementById('notif-history-table');
    if (!tbody) return;

    const channelColors = { email: 'var(--cyan)', telegram: 'var(--purple)', webhook: 'var(--amber)' };
    const statusColors  = { sent: 'var(--green)', failed: 'var(--red)' };

    tbody.innerHTML = history.length
      ? history.map(h => `
        <tr>
          <td class="td-mono" style="white-space:nowrap">${fmtTs(h.sent_at)}</td>
          <td><span style="font-family:var(--font-mono);font-size:0.65rem;padding:0.2rem 0.5rem;border-radius:4px;background:${channelColors[h.channel]||'var(--surface-high)'}18;color:${channelColors[h.channel]||'var(--on-surface)'}">${esc((h.channel||'—').toUpperCase())}</span></td>
          <td style="font-size:0.78rem;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(h.recipient||'')}">${esc(h.recipient || '—')}</td>
          <td style="font-size:0.78rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(h.subject||'')}">${esc(h.subject || '—')}</td>
          <td><span style="font-family:var(--font-mono);font-size:0.65rem;color:${statusColors[h.status]||'var(--on-surface-muted)'}">${esc((h.status||'—').toUpperCase())}</span></td>
        </tr>`).join('')
      : '<tr><td colspan="5" style="text-align:center;color:var(--on-surface-muted);padding:2rem">No notifications sent yet</td></tr>';

  } catch (e) {
    toast('Failed to load notification data: ' + e.message, 'red');
  }
}
