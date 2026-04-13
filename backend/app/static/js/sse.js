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

  if (data.type === 'wanted_match') {
    State.newSightings++;
    updateBadge('badge-sightings', State.newSightings);
    toast(`⚠ MATCH: ${data.person_name} — ${data.location || data.camera_id}`, 'match');

    // Register active alert
    State.activeAlerts[data.person_id] = {
      id: data.person_id,
      name: data.person_name,
      location: data.location || 'Unknown',
      node: data.camera_id || 'Remote',
      lastSeen: Date.now(),
      snapshot: data.snapshot,
      inVision: true,
    };
    renderActiveAlerts();
    loadSightings();
    loadStats();

  } else if (data.type === 'new_sighting') {
    State.newSightings++;
    updateBadge('badge-sightings', State.newSightings);

    // Update existing alert heartbeat
    const existing = data.person_id && State.activeAlerts[data.person_id];
    if (existing) {
      Object.assign(existing, {
        lastSeen: Date.now(),
        location: data.location || existing.location,
        node: data.camera_id || existing.node,
        snapshot: data.snapshot || existing.snapshot,
        inVision: true,
      });
      renderActiveAlerts();
    }

    toast(`New sighting — ${data.camera_id || data.location}`, 'sight');
    loadSightings();
    loadStats();

  } else if (data.type === 'new_object') {
    State.newObjects++;
    updateBadge('badge-objects', State.newObjects);
    toast(`Object: ${capitalize(data.object_label || 'unknown')} — ${data.camera_id}`, 'obj');
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

  const alerts = Object.values(State.activeAlerts);
  if (!alerts.length) { monitor.innerHTML = ''; return; }

  monitor.innerHTML = alerts.map(a => `
    <div class="alert-banner ${a.inVision ? '' : 'lost'}">
      <div style="display:flex;align-items:center;gap:1.25rem">
        <img src="${esc(a.snapshot)}" style="width:48px;height:48px;border-radius:8px;object-fit:cover;border:1px solid ${a.inVision ? 'var(--red)' : 'var(--outline)'}">
        <div class="alert-info">
          <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.15rem">
            <h4>${esc(a.name)}</h4>
            <span class="alert-tag ${a.inVision ? 'tag-live' : 'tag-lost'}">${a.inVision ? 'IN VISION' : 'VISION LOST'}</span>
          </div>
          <div style="font-family:var(--font-mono);font-size:0.72rem;color:var(--on-surface-muted)">
            Last seen at <strong>${esc(a.location)}</strong> via <strong>${esc(a.node)}</strong>
          </div>
        </div>
      </div>
      <button class="btn btn-ghost btn-sm" onclick="deactivateAlert('${esc(a.id)}')">Dismiss</button>
    </div>`).join('');
}

function deactivateAlert(id) {
  delete State.activeAlerts[id];
  renderActiveAlerts();
}
