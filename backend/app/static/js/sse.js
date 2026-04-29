/* ══════════════════════════════════════════
   SSE — Server-Sent Events
   ══════════════════════════════════════════ */

function connectSSE() {
  if (State.sseConn) State.sseConn.close();

  const badge = document.getElementById('sse-status-badge');
  if (badge) {
    badge.textContent = 'Connecting…';
    badge.style.cssText = 'background:var(--surface-high);color:var(--on-surface-muted)';
  }

  State.sseConn = new EventSource(`${State.api}/api/stream?token=${State.token}`);

  State.sseConn.addEventListener('connected', () => {
    if (badge) {
      badge.textContent = '● Live';
      badge.style.cssText = 'background:var(--green-dim);color:var(--green);border:1px solid var(--green-dim)';
    }
  });

  State.sseConn.addEventListener('alert', e => {
    try { handleAlert(JSON.parse(e.data)); } catch {}
  });

  State.sseConn.onerror = () => {
    if (badge) {
      badge.textContent = '○ Disconnected';
      badge.style.cssText = 'background:var(--surface-high);color:var(--on-surface-muted)';
    }
    // Reconnect after 5s
    setTimeout(() => { if (State.token) connectSSE(); }, 5000);
  };
}

function handleAlert(data) {
  State.alertCount++;
  updateBadge('bell-count', State.alertCount);

  // Add to recent events list
  const event = {
    id: data.person_id || data.object_id || `evt-${Date.now()}-${Math.random()}`,
    type: data.type,
    name: data.person_name || data.object_label || 'Unknown',
    location: data.location || data.camera_id || 'Remote',
    node: data.camera_id || 'Remote',
    lastSeen: Date.now(),
    snapshot: data.snapshot,
    inVision: true,
    isMatch: data.type === 'wanted_match'
  };

  if (data.type === 'wanted_match') {
    State.newSightings++;
    updateBadge('badge-sightings', State.newSightings);
    toast(`⚠ MATCH: ${data.person_name} — ${data.location || data.camera_id}`, 'match');
    State.activeAlerts[event.id] = event;
    renderActiveAlerts();
    loadSightings();
    loadStats();

  } else if (data.type === 'new_sighting') {
    State.newSightings++;
    updateBadge('badge-sightings', State.newSightings);

    const existing = data.person_id && State.activeAlerts[data.person_id];
    if (existing) {
      Object.assign(existing, {
        lastSeen: Date.now(),
        location: data.location || existing.location,
        node: data.camera_id || existing.node,
        snapshot: data.snapshot || existing.snapshot,
        inVision: true,
      });
    } else {
      // Also add non-matches to the active list if they are recent
      State.activeAlerts[event.id] = event;
    }
    renderActiveAlerts();
    toast(`New sighting — ${data.camera_id || data.location}`, 'sight');
    loadSightings();
    loadStats();

  } else if (data.type === 'new_object') {
    State.newObjects++;
    updateBadge('badge-objects', State.newObjects);
    toast(`Object: ${capitalize(data.object_label || 'unknown')} — ${data.camera_id}`, 'obj');
    
    // Add object detection to active alerts
    State.activeAlerts[event.id] = event;
    renderActiveAlerts();
    
    loadObjects();
    loadStats();
  }
}

/* ─── ACTIVE ALERTS MONITOR (wanted person banner) ─── */
function updateAlertHeartbeat() {
  const TIMEOUT = 8000; // 8s without update = vision lost
  let changed = false;

  for (const id in State.activeAlerts) {
    const alert = State.activeAlerts[id];
    if (alert.inVision && (Date.now() - alert.lastSeen) > TIMEOUT) {
      alert.inVision = false;
      changed = true;
    }
  }
  if (changed) renderActiveAlerts();
}

function renderActiveAlerts() {
  const monitor = document.getElementById('active-alerts-monitor');
  if (!monitor) return;

  const alerts = Object.values(State.activeAlerts).sort((a, b) => b.lastSeen - a.lastSeen);
  
  if (!alerts.length) { 
    monitor.innerHTML = ''; 
    monitor.classList.remove('has-alerts');
    return; 
  }

  monitor.classList.add('has-alerts');

  // Filter alerts based on state
  const filter = State.alertFilter || 'matches';
  const filtered = filter === 'all' ? alerts : alerts.filter(a => a.isMatch);

  const filterHtml = `
    <div class="alert-bar-header">
      <div class="alert-bar-tabs">
        <button class="tab-btn ${filter === 'matches' ? 'active' : ''}" onclick="setAlertFilter('matches')">Watchlist Hits</button>
        <button class="tab-btn ${filter === 'all' ? 'active' : ''}" onclick="setAlertFilter('all')">All Detections</button>
      </div>
      <button class="btn btn-ghost btn-sm" onclick="clearAllAlerts()">Dismiss All</button>
    </div>
  `;

  if (filtered.length === 0) {
    monitor.innerHTML = filterHtml + `<div class="alert-banner-empty">No ${filter === 'matches' ? 'watchlist hits' : 'detections'} active</div>`;
    return;
  }

  monitor.innerHTML = filterHtml + filtered.map(a => `
    <div class="alert-banner ${a.inVision ? '' : 'lost'} ${a.isMatch ? 'match' : ''}">
      <div style="display:flex;align-items:center;gap:1.25rem;flex:1;min-width:0">
        <img src="${esc(a.snapshot)}" style="width:48px;height:48px;border-radius:8px;object-fit:cover;border:2px solid ${a.isMatch ? 'var(--red)' : (a.inVision ? 'var(--cyan)' : 'var(--outline)')}">
        <div class="alert-info">
          <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.15rem">
            <h4>${esc(capitalize(a.name))}</h4>
            <span class="alert-tag ${a.inVision ? (a.isMatch ? 'tag-live' : 'tag-info') : 'tag-lost'}">
              ${a.inVision ? (a.isMatch ? 'WATCHLIST MATCH' : 'DETECTED') : 'VISION LOST'}
            </span>
          </div>
          <div style="font-family:var(--font-mono);font-size:0.72rem;color:var(--on-surface-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
            At <strong>${esc(a.location)}</strong> via <strong>${esc(a.node)}</strong>
          </div>
        </div>
      </div>
      <button class="alert-close-btn" onclick="deactivateAlert('${esc(a.id)}')" title="Dismiss Alert">×</button>
    </div>`).join('');
}

function setAlertFilter(filter) {
  State.alertFilter = filter;
  renderActiveAlerts();
}

function clearAllAlerts() {
  State.activeAlerts = {};
  renderActiveAlerts();
}

function deactivateAlert(id) {
  delete State.activeAlerts[id];
  renderActiveAlerts();
}
