/* ══════════════════════════════════════════
   ANALYTICS
   ══════════════════════════════════════════ */
async function loadAnalytics() {
  const days = document.getElementById('analytics-days')?.value || 7;
  try {
    const [overview, hourly, perCam, topObj, hits] = await Promise.all([
      api(`/api/analytics/overview?days=${days}`),
      api(`/api/analytics/hourly?days=${days}`),
      api(`/api/analytics/per-camera?days=${days}`),
      api(`/api/analytics/top-objects?days=${days}`),
      api(`/api/analytics/watchlist-hits?days=${days}`),
    ]);

    const totalFaces   = overview.reduce((s, d) => s + d.faces, 0);
    const totalMatches = overview.reduce((s, d) => s + d.matches, 0);
    const totalObjects = overview.reduce((s, d) => s + d.objects, 0);
    setText('a-total-faces',   totalFaces.toLocaleString());
    setText('a-total-matches', totalMatches.toLocaleString());
    setText('a-total-objects', totalObjects.toLocaleString());
    setText('a-match-rate',    totalFaces > 0 ? (totalMatches / totalFaces * 100).toFixed(1) + '%' : '0%');

    renderDailyChart(overview);
    renderHeatmap(hourly);

    // Per-camera
    const camEl  = document.getElementById('analytics-cameras');
    const maxCam = Math.max(1, ...perCam.map(c => c.faces + c.objects));
    if (camEl) camEl.innerHTML = perCam.slice(0, 8).map(c => {
      const pct = ((c.faces + c.objects) / maxCam * 100).toFixed(1);
      return `<div>
        <div style="display:flex;justify-content:space-between;font-size:0.78rem;margin-bottom:3px">
          <span style="font-family:var(--font-mono)">${esc(c.camera_id)}</span>
          <span style="color:var(--on-surface-muted)">${c.faces}F / ${c.objects}O / <span style="color:var(--red)">${c.matches}M</span></span>
        </div>
        <div style="height:4px;background:var(--surface-high);border-radius:2px;overflow:hidden">
          <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,var(--primary),var(--cyan));border-radius:2px;transition:width 0.6s"></div>
        </div></div>`;
    }).join('') || '<div style="color:var(--on-surface-muted);font-size:0.8rem">No data</div>';

    // Top objects
    const objEl  = document.getElementById('analytics-objects');
    const maxObj = Math.max(1, ...topObj.map(o => o.count));
    if (objEl) objEl.innerHTML = topObj.slice(0, 8).map(o => {
      const pct = (o.count / maxObj * 100).toFixed(1);
      return `<div>
        <div style="display:flex;justify-content:space-between;font-size:0.78rem;margin-bottom:3px">
          <span style="font-family:var(--font-mono);text-transform:capitalize">${esc(o.object_label)}</span>
          <span style="color:var(--on-surface-muted)">${o.count}</span>
        </div>
        <div style="height:4px;background:var(--surface-high);border-radius:2px;overflow:hidden">
          <div style="height:100%;width:${pct}%;background:var(--cyan);border-radius:2px;transition:width 0.6s"></div>
        </div></div>`;
    }).join('') || '<div style="color:var(--on-surface-muted);font-size:0.8rem">No data</div>';

    // Watchlist hits
    const wlEl = document.getElementById('analytics-watchlist-hits');
    if (wlEl) wlEl.innerHTML = hits.length
      ? hits.map((h, i) => `
        <div class="result-item">
          <span style="font-family:var(--font-mono);font-size:0.62rem;color:var(--on-surface-muted);width:24px">#${i+1}</span>
          <span style="flex:1">${esc(h.person_name)}</span>
          <span style="font-family:var(--font-mono);font-size:0.72rem;color:var(--red)">${h.hits} hits</span>
          <span style="font-family:var(--font-mono);font-size:0.68rem;color:var(--on-surface-muted);margin-left:0.75rem">${h.avg_conf.toFixed(1)}% avg</span>
        </div>`).join('')
      : '<div style="color:var(--on-surface-muted);font-size:0.8rem">No wanted matches in this period</div>';
  } catch (e) { console.warn('[analytics]', e); }
}

function renderDailyChart(data) {
  const canvas = document.getElementById('chart-daily');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W   = canvas.parentElement.offsetWidth || 400;
  const H   = 180;
  canvas.width = W; canvas.height = H;
  ctx.clearRect(0, 0, W, H);
  if (!data.length) return;

  const isDark  = document.documentElement.getAttribute('data-theme') === 'dark';
  const maxVal  = Math.max(1, ...data.map(d => d.faces + d.objects));
  const padL    = 28, padB = 26, padT = 12;
  const chartH  = H - padB - padT;
  const barW    = (W - padL) / data.length;

  // Grid lines
  ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padT + (chartH / 4) * i;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W, y); ctx.stroke();
  }

  data.forEach((d, i) => {
    const x     = padL + i * barW + barW * 0.1;
    const bw    = barW * 0.8;
    const faceH = (d.faces   / maxVal) * chartH;
    const objH  = (d.objects / maxVal) * chartH;
    const matH  = (d.matches / maxVal) * chartH;

    ctx.fillStyle = isDark ? 'rgba(77,224,248,0.3)' : 'rgba(0,107,138,0.25)';
    ctx.fillRect(x, padT + chartH - objH, bw, objH);

    ctx.fillStyle = isDark ? 'rgba(192,200,255,0.6)' : 'rgba(31,51,170,0.65)';
    ctx.fillRect(x, padT + chartH - faceH, bw, faceH);

    if (d.matches > 0) {
      ctx.fillStyle = isDark ? 'rgba(255,138,138,0.9)' : 'rgba(192,24,42,0.85)';
      ctx.fillRect(x, padT + chartH - matH, bw, matH);
    }

    if (data.length <= 14) {
      ctx.fillStyle = 'rgba(130,140,170,0.7)';
      ctx.font = '8px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(d.date?.slice(5) || '', x + bw / 2, H - 5);
    }
  });
}

function renderHeatmap(hourly) {
  const el     = document.getElementById('hourly-heatmap');
  if (!el) return;
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const maxC   = Math.max(1, ...hourly.map(h => h.count));

  el.innerHTML = hourly.map(h => {
    const i  = h.count / maxC;
    const bg = i < 0.01
      ? (isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)')
      : (isDark ? `rgba(192,200,255,${(0.12 + i * 0.85).toFixed(2)})` : `rgba(31,51,170,${(0.12 + i * 0.85).toFixed(2)})`);
    return `<div title="${h.hour}: ${h.count}"
      style="height:28px;border-radius:3px;background:${bg};cursor:default;transition:background 0.3s"
      onmouseover="this.style.outline='1px solid var(--primary)'"
      onmouseout="this.style.outline='none'"></div>`;
  }).join('');
}

async function loadWatchlist() {
  try {
    const d = await api('/api/watchlist');
    const grid = document.getElementById('watchlist-grid');
    if (!grid) return;
    if (!d.length) {
      grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:5rem;color:var(--on-surface-muted)">No subjects enrolled.</div>`;
      return;
    }
    grid.innerHTML = d.map(p => `
      <div class="panel" style="padding:1.25rem;cursor:pointer" onclick="openDossier('${esc(p.person_id)}')">
        <div style="display:flex;align-items:center;gap:1rem;margin-bottom:1rem">
          ${p.photos?.length 
            ? `<img src="${esc(p.photos[0].photo_path)}" style="width:50px;height:50px;border-radius:var(--radius-sm);object-fit:cover;border:1px solid var(--primary-dim)">`
            : `<div style="width:50px;height:50px;border-radius:var(--radius-sm);background:var(--surface-high);display:flex;align-items:center;justify-content:center;font-size:1.2rem;font-weight:700">${p.name[0]}</div>`}
          <div>
            <div style="font-weight:700;font-size:0.95rem">${esc(p.name)}</div>
            <div class="td-mono" style="font-size:0.6rem;color:var(--primary)">ID: ${esc(p.person_id)}</div>
          </div>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;padding-top:0.75rem;border-top:1px solid var(--outline)">
          <span class="td-mono" style="font-size:0.6rem;color:var(--on-surface-muted)">${p.photos?.length || 0} SAMPLES</span>
          <span style="font-size:0.75rem;color:var(--primary)">View Dossier →</span>
        </div>
      </div>`).join('');
  } catch (e) { console.warn('[watchlist]', e); }
}

/* ══════════════════════════════════════════
   FRAME ANALYSIS
   ══════════════════════════════════════════ */
async function analyzeFrame(file) {
  if (!file) return;
  const zone = document.getElementById('analysis-drop');
  const wrap = document.getElementById('analysis-preview-wrap');
  const res  = document.getElementById('analysis-results');
  const img  = document.getElementById('analysis-preview');

  zone.style.display = 'none';
  wrap.style.display = 'block';
  res.innerHTML = '<div style="text-align:center;padding:2rem"><div class="sync-spinner" style="margin:0 auto 1rem"></div><div class="td-mono" style="font-size:0.7rem">RUNNING NEURAL INFERENCE…</div></div>';

  const formData = new FormData();
  formData.append('file', file);

  try {
    const d = await api('/api/inference/analyze', { method: 'POST', body: formData });
    img.src = d.preview;
    
    if (!d.detections.length) {
      res.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--on-surface-muted);font-family:var(--font-mono);font-size:0.75rem">// NO ENTITIES DETECTED</div>';
      return;
    }

    res.innerHTML = d.detections.map(det => {
      const isMatch = det.matched;
      const color = det.type === 'object' ? 'var(--cyan)' : (isMatch ? 'var(--red)' : 'var(--primary)');
      return `
        <div class="panel" style="padding:0.75rem; border-left:3px solid ${color}">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:0.25rem">
            <span class="td-mono" style="font-size:0.55rem; color:${color}">${det.type.toUpperCase()}</span>
            <span class="td-mono" style="font-size:0.65rem; color:var(--on-surface-muted)">${det.confidence}%</span>
          </div>
          <div style="font-weight:700; font-size:0.85rem">${esc(det.label)}</div>
          ${isMatch ? '<div style="font-size:0.6rem; color:var(--red); font-weight:700; margin-top:0.25rem">⚠ ALERT: WATCHLIST MATCH</div>' : ''}
        </div>`;
    }).join('');

    toast(`Analysis complete: ${d.count} detections`, 'green');
  } catch (e) {
    res.innerHTML = `<div style="color:var(--red);padding:1rem;font-size:0.8rem">Error: ${esc(e.message)}</div>`;
    toast(e.message, 'red');
  }
}

function resetAnalysis() {
  document.getElementById('analysis-drop').style.display = 'flex';
  document.getElementById('analysis-preview-wrap').style.display = 'none';
  document.getElementById('analysis-results').innerHTML = '<div style="text-align:center;padding:3rem;color:var(--on-surface-muted);font-size:0.75rem;font-family:var(--font-mono)">// AWAITING DATA...</div>';
  document.getElementById('analysis-file').value = '';
}

function handleAnalysisDrop(e) {
  const file = e.dataTransfer.files[0];
  if (file) analyzeFrame(file);
}

/* ══════════════════════════════════════════
   LIVE MAP
   ══════════════════════════════════════════ */
function loadMap() {
  const list = document.getElementById('map-cam-list');
  if (!list) return;
  if (!State.cameras.length) {
    list.innerHTML = '<div style="color:var(--on-surface-muted);font-size:0.7rem">No cameras registered</div>';
    return;
  }
  list.innerHTML = State.cameras.map(c => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:0.5rem;background:var(--surface-high);border-radius:4px">
      <div style="font-size:0.75rem;font-weight:600">${esc(c.name)}</div>
      <span class="badge ${c.online ? 'online' : 'offline'}" style="font-size:0.5rem">${c.online ? 'LIVE' : 'IDLE'}</span>
    </div>`).join('');
}

function updateMapCameraList(cameras) {
  if (State.activePage === 'map') loadMap();
}

/* ══════════════════════════════════════════
   ALERT RULES
   ══════════════════════════════════════════ */
async function loadRules() {
  try {
    const rules = await api('/api/alerts/alert-rules');
    const tb = document.getElementById('rules-table');
    if (!tb) return;
    if (!rules.length) {
      tb.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--on-surface-muted);padding:3rem">No active rules. Automated surveillance is not looking for specific triggers.</td></tr>';
      return;
    }
    tb.innerHTML = rules.map(r => {
      const cond = r.conditions || {};
      const acts = [];
      if (r.actions.popup) acts.push('Popup');
      if (r.actions.email) acts.push('Email');
      if (r.actions.webhook_url) acts.push('Webhook');
      
      let condTxt = 'Generic';
      if (r.rule_type === 'wanted_match') condTxt = 'Match on Watchlist';
      if (r.rule_type === 'object_detected') condTxt = `Detect: ${cond.object_label || 'Any'}`;
      if (r.rule_type === 'high_confidence') condTxt = `Conf > ${cond.min_confidence}%`;
      
      return `
        <tr>
          <td><div style="font-weight:700">${esc(r.name)}</div><div class="td-mono" style="font-size:0.6rem;color:var(--primary)">${esc(r.rule_type.toUpperCase())}</div></td>
          <td class="td-mono" style="font-size:0.75rem">${esc(r.camera_id || 'Global / All')}</td>
          <td>${esc(condTxt)}</td>
          <td style="font-size:0.75rem;color:var(--on-surface-muted)">${acts.join(', ')}</td>
          <td><span class="badge ${r.enabled ? 'online' : 'offline'}">${r.enabled ? 'ACTIVE' : 'MUTED'}</span></td>
          <td>
            <div style="display:flex;gap:0.4rem">
              <button class="btn btn-ghost btn-sm" onclick="toggleRule('${r.id}')">${r.enabled ? 'Mute' : 'Enable'}</button>
              <button class="btn btn-danger btn-sm" onclick="deleteRule('${r.id}','${esc(r.name)}')">✕</button>
            </div>
          </td>
        </tr>`;
    }).join('');
  } catch (e) { console.warn('[rules]', e); }
}

function onRuleTypeChange() {
  const type = document.getElementById('ar-type').value;
  document.getElementById('ar-obj-field').style.display  = type === 'object_detected' ? 'block' : 'none';
  document.getElementById('ar-conf-field').style.display = type === 'high_confidence'  ? 'block' : 'none';
}

function openAddRule() {
  const sel = document.getElementById('ar-camera');
  if (sel) {
    sel.innerHTML = '<option value="">All Cameras (Global)</option>' +
      State.cameras.map(c => `<option value="${esc(c.camera_id)}">${esc(c.name)} (${esc(c.camera_id)})</option>`).join('');
  }
  onRuleTypeChange();
  openModal('modal-add-rule');
}

async function saveRule() {
  const btn = document.getElementById('ar-btn');
  const err = document.getElementById('ar-err');
  const type = document.getElementById('ar-type').value;
  const conditions = {};
  if (type === 'object_detected') conditions.object_label = document.getElementById('ar-obj-label').value.trim();
  if (type === 'high_confidence') conditions.min_confidence = parseFloat(document.getElementById('ar-min-conf').value) || 90;

  const actions = {
    popup: document.getElementById('ar-act-popup').checked,
    email: document.getElementById('ar-act-email').checked,
    webhook_url: document.getElementById('ar-webhook').value.trim() || null
  };

  btn.disabled=true; btn.textContent='Creating…'; err.style.display='none';
  try {
    await api('/api/alerts/alert-rules', {
      method: 'POST',
      body: JSON.stringify({
        name: document.getElementById('ar-name').value.trim() || 'Untitled Rule',
        rule_type: type,
        camera_id: document.getElementById('ar-camera').value,
        conditions, actions
      })
    });
    closeModal('modal-add-rule');
    toast('Rule applied successfully', 'green');
    loadRules();
  } catch (e) { err.textContent=e.message; err.style.display='block'; }
  finally { btn.disabled=false; btn.textContent='Create Rule'; }
}

async function toggleRule(id) {
  try { await api(`/api/alerts/alert-rules/${id}/toggle`, { method: 'PATCH' }); loadRules(); }
  catch (e) { toast(e.message, 'red'); }
}

async function deleteRule(id, name) {
  if (!confirm(`Delete rule "${name}"?`)) return;
  try { await api(`/api/alerts/alert-rules/${id}`, { method: 'DELETE' }); toast('Rule removed', 'muted'); loadRules(); }
  catch (e) { toast(e.message, 'red'); }
}

/* ══════════════════════════════════════════
   WORKERS
   ══════════════════════════════════════════ */
async function loadWorkers() {
  try {
    const d   = await api('/api/system/active-users');
    const tb  = document.getElementById('workers-table');
    const now = Date.now() / 1000;
    setText('sys-sessions', d.sessions?.length || 0);

    const nodes = d.nodes || [];
    if (!nodes.length) {
      tb.innerHTML = `<tr><td colspan="3"><div class="empty-state" style="padding:2rem"><div class="empty-icon">◎</div><div class="empty-text">No active nodes</div></div></td></tr>`;
      return;
    }
    tb.innerHTML = nodes.map(n => {
        const live = n.age_s < 60;
        const statusClass = live ? 'online' : 'offline';
        const label = n.worker_label ? `${esc(n.worker_label)}` : 'External';
        
        return `
          <tr>
            <td>
              <div style="font-weight:700">${esc(n.name || n.camera_id)}</div>
              <div class="td-mono" style="font-size:0.65rem;color:var(--primary)">${esc(n.db_location || 'REMOTE NODE')}</div>
            </td>
            <td>
              <div style="display:flex;align-items:center;gap:0.5rem">
                <span class="badge ${statusClass}">${live ? '● LIVE' : '○ IDLE'}</span>
                <span class="td-mono" style="font-size:0.7rem;color:var(--on-surface-muted)">[${label}]</span>
              </div>
            </td>
            <td class="td-mono">${n.age_s}s latency</td>
          </tr>
        `;
    }).join('');
  } catch {}
}

/* ══════════════════════════════════════════
   USERS
   ══════════════════════════════════════════ */
async function loadUsers() {
  try {
    const users = await api('/api/auth/users');
    const tb = document.getElementById('users-table');
    tb.innerHTML = users.map(u => `
      <tr>
        <td>
          <div style="display:flex;align-items:center;gap:0.75rem">
            <div style="width:32px;height:32px;background:${u.role === 'admin' ? 'var(--primary-dim)' : 'var(--cyan-dim)'};border:1px solid ${u.role === 'admin' ? 'var(--primary-glow)' : 'var(--cyan-dim)'};border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;font-family:var(--font-display);font-size:0.7rem;font-weight:700;color:${u.role === 'admin' ? 'var(--primary)' : 'var(--cyan)'}">${u.username[0].toUpperCase()}</div>
            <span style="font-weight:600">${esc(u.username)}</span>
          </div>
        </td>
        <td><span class="badge ${u.role === 'admin' ? 'admin' : 'worker'}">${u.role.toUpperCase()}</span></td>
        <td>
          ${u.username !== 'admin'
            ? `<button class="btn btn-danger btn-sm" onclick="deleteUser('${esc(u.username)}')">Remove</button>`
            : '<span class="td-mono" style="opacity:0.4">protected</span>'}
        </td>
      </tr>`).join('');
  } catch {}
}

function openAddUser() {
  ['au-user','au-pass'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  const err = document.getElementById('au-err');
  if (err) err.style.display = 'none';
  openModal('modal-add-user');
}

async function addUser() {
  const u   = document.getElementById('au-user').value.trim();
  const p   = document.getElementById('au-pass').value;
  const r   = document.getElementById('au-role').value;
  const btn = document.getElementById('au-btn');
  const err = document.getElementById('au-err');
  if (!u || !p) { err.style.display='block'; err.textContent='All fields required'; return; }
  btn.disabled=true; btn.textContent='Creating…'; err.style.display='none';
  try {
    await api('/api/auth/users', { method: 'POST', body: JSON.stringify({ username: u, password: p, role: r }) });
    closeModal('modal-add-user');
    toast('Operator created: ' + u, 'amber');
    loadUsers();
  } catch (e) { err.style.display='block'; err.textContent=e.message; }
  finally { btn.disabled=false; btn.textContent='Create Account'; }
}

async function deleteUser(username) {
  if (!confirm(`Delete account "${username}"?`)) return;
  try {
    await api(`/api/auth/users/${username}`, { method: 'DELETE' });
    toast('Account removed: ' + username, 'muted');
    loadUsers();
  } catch (e) { toast('Error: ' + e.message, 'red'); }
}

/* ══════════════════════════════════════════
   SYSTEM / CLEANUP
   ══════════════════════════════════════════ */
async function loadSystem() {
  await loadSystemStats();
  // Update other dynamic info here if needed
}

async function loadSystemStats() {
  if (State.activePage !== 'system') return;
  try {
    const stats = await api('/api/system/stats');
    setText('sys-sessions', stats.active_sessions || 0);
    setText('sys-nodes', stats.total_nodes || 0);
  } catch {}
}

async function runCleanup() {
  const range = document.getElementById('cleanup-range').value;
  const target = document.getElementById('cleanup-target').value;
  const pid = document.getElementById('cleanup-pid').value.trim();
  
  if (!confirm(`CONFIRM: PURGE ${target.toUpperCase()} RECORDS OLDER THAN ${range.toUpperCase()}?`)) return;
  
  try {
    const res = await api(`/api/system/cleanup?time_range=${range}&target=${target}${pid ? `&person_id=${pid}` : ''}`, { method: 'POST' });
    toast(`Cleanup complete: Removed ${res.details.sightings + res.details.objects} entries`, 'green');
    loadSystemStats();
  } catch (e) { toast('Cleanup failed: ' + e.message, 'red'); }
}

async function discoverAndPurge() {
  const fileInput = document.getElementById('discovery-files');
  if (!fileInput.files.length) return toast('Select face photos first', 'amber');
  
  const formData = new FormData();
  for (const f of fileInput.files) formData.append('files', f);
  
  toast('Discovery started...', 'blue');
  try {
    const res = await api('/api/system/cleanup/biometric/search', {
      method: 'POST',
      body: formData
    });
    
    if (!res.matches.length) {
      return toast('No matches found for these photos', 'on-surface-muted');
    }
    
    if (confirm(`FOUND ${res.total_matches} MATCHES. PERMANENTLY PURGE ALL RECORDED SIGHTINGS FOR THIS SUBJECT?`)) {
      const ids = res.matches.map(m => m.id);
      await api('/api/system/cleanup/biometric/purge', {
        method: 'POST',
        body: JSON.stringify(ids)
      });
      toast('Subject records purged successfully', 'green');
    }
  } catch (e) { toast('Discovery failed: ' + e.message, 'red'); }
}

async function factoryReset() {
  const code = prompt('DANGER: TYPE "FACTORY-RESET" TO WIPE EVERYTHING');
  if (code !== 'FACTORY-RESET') return;
  
  try {
    // Calling cleanup with max range as a proxy for reset if dedicated reset is missing
    await api('/api/system/cleanup?time_range=1y&target=all', { method: 'POST' });
    toast('System has been reset', 'red');
    location.reload();
  } catch (e) { toast('Reset failed: ' + e.message, 'red'); }
}

/* ══════════════════════════════════════════
   ALERT RULES
   ══════════════════════════════════════════ */
async function loadRules() {
  try {
    State.rules = await api('/api/alerts/alert-rules');
  } catch (e) { console.warn('[rules]', e); return; }
  const listEl  = document.getElementById('rules-list');
  const emptyEl = document.getElementById('rules-empty');

  if (!State.rules.length) {
    listEl.innerHTML = '';
    if (emptyEl) emptyEl.style.display = 'block';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';

  const typeMap = {
    wanted_match:    ['var(--red)',    'rgba(192,24,42,0.1)',   'WANTED MATCH'],
    any_face:        ['var(--primary)','var(--primary-dim)',    'ANY FACE'],
    object_detected: ['var(--cyan)',   'var(--cyan-dim)',       'OBJECT DETECTED'],
    high_confidence: ['var(--purple)', 'rgba(92,66,160,0.1)',   'HIGH CONFIDENCE'],
  };

  listEl.innerHTML = State.rules.map(r => {
    const [tc, bgc, tlabel] = typeMap[r.rule_type] || ['var(--on-surface-muted)', 'var(--surface-high)', r.rule_type];
    const condStr = r.conditions?.object_label ? ` → ${r.conditions.object_label}`
                  : r.conditions?.min_confidence ? ` ≥ ${r.conditions.min_confidence}%` : '';
    const acts = [];
    if (r.actions?.popup !== false) acts.push('🔔 Popup');
    if (r.actions?.email)           acts.push('📧 Email');
    if (r.actions?.webhook_url)     acts.push('🔗 Webhook');

    return `<div class="panel" style="padding:1rem;display:flex;align-items:center;gap:1rem;border-color:${r.enabled ? tc + '40' : 'var(--outline)'}">
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;margin-bottom:0.35rem">
          <span style="font-weight:600">${esc(r.name)}</span>
          <span style="font-family:var(--font-mono);font-size:0.58rem;padding:0.2rem 0.55rem;border-radius:20px;background:${bgc};color:${tc}">
            ${tlabel}${esc(condStr)}
          </span>
          <span style="font-family:var(--font-mono);font-size:0.58rem;color:var(--on-surface-muted)">${r.camera_id ? `CAM: ${esc(r.camera_id)}` : 'ALL CAMERAS'}</span>
        </div>
        <div style="font-size:0.72rem;color:var(--on-surface-muted)">${acts.join(' · ') || 'No actions'}</div>
      </div>
      <div style="display:flex;align-items:center;gap:0.5rem;flex-shrink:0">
        <button class="btn btn-ghost btn-sm" onclick="toggleRule('${r.id}')" style="color:${r.enabled ? 'var(--green)' : 'var(--on-surface-muted)'}">${r.enabled ? '● ON' : '○ OFF'}</button>
        <button class="btn btn-danger btn-sm" onclick="deleteRule('${r.id}','${esc(r.name)}')">✕</button>
      </div>
    </div>`;
  }).join('');
}

function openAddRule() {
  const sel = document.getElementById('ar-camera');
  if (sel) sel.innerHTML = '<option value="">All Cameras</option>' +
    State.cameras.map(c => `<option value="${esc(c.camera_id)}">${esc(c.name)} (${esc(c.camera_id)})</option>`).join('');
  onRuleTypeChange();
  openModal('modal-add-rule');
}

function onRuleTypeChange() {
  const type = document.getElementById('ar-type').value;
  document.getElementById('ar-obj-field').style.display  = type === 'object_detected' ? '' : 'none';
  document.getElementById('ar-conf-field').style.display = type === 'high_confidence'  ? '' : 'none';
}

async function saveRule() {
  const btn = document.getElementById('ar-btn');
  const err = document.getElementById('ar-err');
  btn.disabled=true; btn.textContent='Creating…'; err.style.display='none';
  const type = document.getElementById('ar-type').value;
  const conditions = {};
  if (type === 'object_detected') { const lbl = document.getElementById('ar-obj-label').value.trim(); if (lbl) conditions.object_label = lbl; }
  if (type === 'high_confidence') { conditions.min_confidence = parseFloat(document.getElementById('ar-min-conf').value) || 90; }
  const actions = {};
  if (document.getElementById('ar-act-popup').checked) actions.popup = true;
  if (document.getElementById('ar-act-email').checked) actions.email = true;
  const wh = document.getElementById('ar-webhook').value.trim();
  if (wh) actions.webhook_url = wh;
  try {
    await api('/api/alerts/alert-rules', { method: 'POST', body: JSON.stringify({
      name: document.getElementById('ar-name').value.trim(),
      rule_type: type,
      camera_id: document.getElementById('ar-camera').value,
      conditions, actions,
    }) });
    closeModal('modal-add-rule');
    toast('Alert rule created', 'green');
    loadRules();
  } catch (e) { err.textContent=e.message; err.style.display='block'; }
  finally { btn.disabled=false; btn.textContent='Create Rule'; }
}

async function toggleRule(ruleId) {
  try { await api(`/api/alerts/alert-rules/${ruleId}/toggle`, { method: 'PATCH' }); loadRules(); }
  catch (e) { toast(e.message, 'red'); }
}

async function deleteRule(ruleId, name) {
  if (!confirm(`Delete rule "${name}"?`)) return;
  try { await api(`/api/alerts/alert-rules/${ruleId}`, { method: 'DELETE' }); toast('Rule deleted', 'amber'); loadRules(); }
  catch (e) { toast(e.message, 'red'); }
}

/* ══════════════════════════════════════════
   AUDIT LOG
   ══════════════════════════════════════════ */
async function loadAuditLog() { State.auditOffset = 0; await _fetchAuditLog(); }

async function auditPage(dir) {
  State.auditOffset = Math.max(0, State.auditOffset + dir * State.auditLimit);
  await _fetchAuditLog();
}

async function _fetchAuditLog() {
  const action = document.getElementById('audit-filter-action')?.value || '';
  const params = new URLSearchParams({ limit: State.auditLimit, offset: State.auditOffset });
  if (action) params.set('action', action);
  try {
    const d = await api(`/api/audit/audit-log?${params}`);
    const tbody = document.getElementById('audit-table');
    if (!d.logs?.length) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--on-surface-muted);padding:2rem">No entries found</td></tr>`;
      setText('audit-count', '0 entries');
      return;
    }
    const colorMap = { login:'var(--green)',logout:'var(--on-surface-muted)',add_person:'var(--primary)',delete_person:'var(--red)',add_camera:'var(--cyan)',delete_camera:'var(--red)',add_user:'var(--primary)',delete_user:'var(--red)',cleanup:'var(--purple)',roi_save:'var(--amber)',stop_approve:'var(--green)',stop_deny:'var(--red)' };
    tbody.innerHTML = d.logs.map(row => `
      <tr>
        <td class="td-mono" style="white-space:nowrap">${fmtTs(row.timestamp)}</td>
        <td style="font-weight:500">${esc(row.username || '—')}</td>
        <td><span style="font-family:var(--font-mono);font-size:0.7rem;color:${colorMap[row.action]||'var(--on-surface)'};background:${colorMap[row.action]||'var(--on-surface)'}18;padding:0.2rem 0.5rem;border-radius:4px">${esc(row.action)}</span></td>
        <td class="td-mono">${esc(row.target || '—')}</td>
        <td style="font-size:0.75rem;color:var(--on-surface-muted);max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(row.detail || '')}">${esc(row.detail || '—')}</td>
        <td class="td-mono" style="font-size:0.7rem">${esc(row.ip || '—')}</td>
      </tr>`).join('');
    setText('audit-count', `Showing ${State.auditOffset+1}–${State.auditOffset+d.logs.length} of ${d.total}`);
    const prevBtn = document.getElementById('audit-prev');
    const nextBtn = document.getElementById('audit-next');
    if (prevBtn) prevBtn.disabled = State.auditOffset === 0;
    if (nextBtn) nextBtn.disabled = (State.auditOffset + State.auditLimit) >= d.total;
  } catch (e) {
    document.getElementById('audit-table').innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--red);padding:2rem">Error: ${esc(e.message)}</td></tr>`;
  }
}

async function exportAuditLog() {
  const action = document.getElementById('audit-filter-action')?.value || '';
  const url = `${State.api}/api/audit/audit-log/export?format=csv${action ? `&action=${action}` : ''}&token=${State.token}`;
  const a = document.createElement('a');
  a.href = url; a.download = 'audit_log.csv';
  document.body.appendChild(a); a.click(); a.remove();
}

/* ══════════════════════════════════════════
   STOP REQUESTS
   ══════════════════════════════════════════ */
async function loadStopRequests() {
  try {
    const d = await api('/api/stop-requests');
    const tbody = document.getElementById('stop-requests-table');
    const empty = document.getElementById('stop-requests-empty');
    const wrap  = document.getElementById('stop-requests-wrap');

    const pending = (d.requests || []).filter(r => r.status === 'pending').length;
    updateBadge('badge-stop-requests', pending);

    if (!d.requests?.length) {
      if (empty) empty.style.display='block';
      if (wrap)  wrap.style.display='none';
      return;
    }
    if (empty) empty.style.display='none';
    if (wrap)  wrap.style.display='';

    const sc = { pending:'var(--amber)',approved:'var(--green)',denied:'var(--red)' };
    tbody.innerHTML = d.requests.map(r => `
      <tr>
        <td class="td-mono">${fmtTs(r.requested_at)}</td>
        <td style="font-weight:500">${esc(r.worker_username)}</td>
        <td class="td-mono">${esc(r.camera_id)}</td>
        <td>${esc(r.location || '—')}</td>
        <td style="font-size:0.75rem;color:var(--on-surface-muted);max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(r.reason || '')}">${esc(r.reason || 'No reason')}</td>
        <td><span style="font-family:var(--font-mono);font-size:0.65rem;color:${sc[r.status]||'var(--on-surface-muted)'};background:${sc[r.status]||'var(--on-surface-muted)'}18;padding:0.2rem 0.5rem;border-radius:4px;text-transform:uppercase">${esc(r.status)}</span></td>
        <td>
          ${r.status === 'pending'
            ? `<div style="display:flex;gap:0.4rem">
                <button class="btn btn-ghost btn-sm" style="color:var(--green)" onclick="respondStop('${r.id}','approve')">✓ Approve</button>
                <button class="btn btn-ghost btn-sm" style="color:var(--red)"   onclick="respondStop('${r.id}','deny')">✕ Deny</button>
              </div>`
            : `<span style="font-size:0.72rem;color:var(--on-surface-muted)">By ${esc(r.resolved_by||'—')}</span>`}
        </td>
      </tr>`).join('');
  } catch (e) {
    document.getElementById('stop-requests-table').innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--red);padding:2rem">Error: ${esc(e.message)}</td></tr>`;
  }
}

async function respondStop(id, action) {
  try {
    await api(`/api/stop-requests/${id}/${action}`, { method: 'POST' });
    toast(action === 'approve' ? 'Request approved' : 'Request denied', action === 'approve' ? 'green' : 'red');
    loadStopRequests();
  } catch (e) { toast('Error: ' + e.message, 'red'); }
}

function pollStopRequestsBadge() {
  if (!State.token) return;
  api('/api/stop-requests')
    .then(d => updateBadge('badge-stop-requests', (d.requests||[]).filter(r => r.status === 'pending').length))
    .catch(() => {});
}

/* ══════════════════════════════════════════
   NOTIFICATIONS
   ══════════════════════════════════════════ */
async function openNotifConfig() {
  try {
    const cfg = await api('/api/notifications/config');
    document.getElementById('nc-host').value = cfg.smtp_host  || '';
    document.getElementById('nc-port').value = cfg.smtp_port  || '587';
    document.getElementById('nc-user').value = cfg.smtp_user  || '';
    document.getElementById('nc-from').value = cfg.smtp_from  || '';
    document.getElementById('nc-to').value   = cfg.smtp_to    || '';
    document.getElementById('nc-pass').value = '';
  } catch {}
  openModal('modal-notif-config');
}

async function saveNotifConfig() {
  const btn = document.getElementById('nc-btn');
  const msg = document.getElementById('nc-msg');
  btn.disabled=true; btn.textContent='Saving…'; msg.style.display='none';
  const body = {
    smtp_host: document.getElementById('nc-host').value.trim(),
    smtp_port: document.getElementById('nc-port').value.trim(),
    smtp_user: document.getElementById('nc-user').value.trim(),
    smtp_from: document.getElementById('nc-from').value.trim(),
    smtp_to:   document.getElementById('nc-to').value.trim(),
  };
  const pass = document.getElementById('nc-pass').value;
  if (pass) body.smtp_password = pass;
  try {
    await api('/api/notifications/config', { method: 'POST', body: JSON.stringify(body) });
    msg.textContent='✓ Config saved'; msg.style.color='var(--green)'; msg.style.display='block';
  } catch (e) {
    msg.textContent='✗ ' + e.message; msg.style.color='var(--red)'; msg.style.display='block';
  } finally { btn.disabled=false; btn.textContent='Save Config'; }
}

async function testEmail() {
  const msg = document.getElementById('nc-msg');
  msg.textContent='Sending test email…'; msg.style.color='var(--on-surface-muted)'; msg.style.display='block';
  try {
    await api('/api/notifications/test-email', { method: 'POST' });
    msg.textContent='✓ Test email sent!'; msg.style.color='var(--green)';
  } catch (e) { msg.textContent='✗ ' + e.message; msg.style.color='var(--red)'; }
}
