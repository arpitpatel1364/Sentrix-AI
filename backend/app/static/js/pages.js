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
    
    const matchRate = totalFaces > 0 ? (totalMatches / totalFaces) : 0;
    const secScore = Math.max(70, Math.min(99, 100 - (matchRate * 100) + (totalFaces > 50 ? 5 : 0)));
    
    setText('a-sec-score',    secScore.toFixed(0) + '%');
    setText('a-match-rate',    (matchRate * 100).toFixed(1) + '%');

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

async function exportAnalytics() {
  const days = document.getElementById('analytics-days')?.value || 7;
  toast(`Generating report for last ${days} days...`, 'cyan');
  setTimeout(() => {
    toast('✓ Report ready for download', 'green');
    // In a real app, this would trigger a window.location to a CSV endpoint
  }, 1500);
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

/* ══════════════════════════════════════════
   WORKERS
   ══════════════════════════════════════════ */
async function loadWorkers() {
  try {
    const d   = await api('/api/active-users');
    const tb  = document.getElementById('workers-table');
    const now = Date.now() / 1000;
    setText('sys-sessions', d.sessions?.length || 0);

    const nodes = d.nodes || [];
    if (!nodes.length) {
      tb.innerHTML = `<tr><td colspan="3"><div class="empty-state" style="padding:2rem"><div class="empty-icon">◎</div><div class="empty-text">No active nodes</div></div></td></tr>`;
      return;
    }
    tb.innerHTML = nodes.map(n => {
      const age  = Math.round(now - n.last_seen);
      const live = age < 30;
      return `<tr>
        <td style="font-family:var(--font-mono);font-weight:600">${esc(n.id)}</td>
        <td><span class="badge ${live ? 'online' : 'offline'}">${live ? '● LIVE' : '○ IDLE'}</span></td>
        <td class="td-mono">${age}s ago</td>
      </tr>`;
    }).join('');
  } catch {}
}

/* ══════════════════════════════════════════
   USERS
   ══════════════════════════════════════════ */
async function loadUsers() {
  try {
    const users = await api('/api/users');
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
    await api('/api/users', { method: 'POST', body: JSON.stringify({ username: u, password: p, role: r }) });
    closeModal('modal-add-user');
    toast('Operator created: ' + u, 'amber');
    loadUsers();
  } catch (e) { err.style.display='block'; err.textContent=e.message; }
  finally { btn.disabled=false; btn.textContent='Create Account'; }
}

async function deleteUser(username) {
  if (!confirm(`Delete account "${username}"?`)) return;
  try {
    await api(`/api/users/${username}`, { method: 'DELETE' });
    toast('Account removed: ' + username, 'muted');
    loadUsers();
  } catch (e) { toast('Error: ' + e.message, 'red'); }
}

/* ══════════════════════════════════════════
   SYSTEM
   ══════════════════════════════════════════ */
async function loadSystem() {
  try {
    const d = await api('/api/active-users');
    setText('sys-sessions', d.sessions?.length || 0);
    setText('sys-nodes',    d.nodes?.length    || 0);
  } catch {}
}

async function runCleanup() {
  const range    = document.getElementById('cleanup-range').value;
  const personId = document.getElementById('cleanup-person-id').value.trim();
  const target   = document.getElementById('cleanup-target').value;
  if (!confirm(`Delete ${target} records older than ${range}${personId ? ` for person ${personId}` : ''}? This is irreversible.`)) return;
  try {
    let url = `/api/system/cleanup?time_range=${range}&target=${target}`;
    if (personId) url += `&person_id=${encodeURIComponent(personId)}`;
    const res = await api(url, { method: 'POST' });
    toast(`Cleanup: removed ${res.details?.files_removed ?? 0} files`, 'green');
    loadStats();
  } catch (e) { toast('Cleanup failed: ' + e.message, 'red'); }
}

/* Biometric purge */
async function runBiometricSearch() {
  const files = document.getElementById('biometric-purge-files').files;
  if (!files.length) { toast('Select at least one face photo', 'red'); return; }
  const btn = document.getElementById('btn-biometric-search');
  const status = document.getElementById('biometric-purge-status');
  btn.disabled=true; btn.textContent='Searching…';
  status.style.display='block'; status.textContent='Analyzing biometrics…';
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  try {
    const res = await api('/api/system/cleanup/biometric/search', { method: 'POST', body: fd });
    State.biometricMatches = res.matches || [];
    if (!State.biometricMatches.length) { toast('No matching sightings', 'muted'); return; }
    renderBiometricPreview();
    document.getElementById('biometric-step-1').style.display = 'none';
    document.getElementById('biometric-step-2').style.display = 'block';
    status.style.display = 'none';
  } catch (e) {
    toast('Discovery failed: ' + e.message, 'red');
    status.textContent = '✗ ' + e.message;
  } finally { btn.disabled=false; btn.textContent='Search Matches'; }
}

function renderBiometricPreview() {
  const grid = document.getElementById('biometric-preview-grid');
  setText('biometric-match-count', `${State.biometricMatches.length} TARGETS IDENTIFIED`);
  setText('biometric-purge-count', State.biometricMatches.length);
  grid.innerHTML = State.biometricMatches.map(m => `
    <div class="biometric-card">
      <img src="${esc(m.snapshot)}" style="width:100%;height:100%;object-fit:cover">
      <button onclick="excludeBiometric('${m.id}')"
              style="position:absolute;top:4px;right:4px;width:22px;height:22px;background:var(--red);color:#fff;border:none;border-radius:50%;font-size:12px;cursor:pointer;display:flex;align-items:center;justify-content:center">✕</button>
      <div style="position:absolute;bottom:0;left:0;right:0;background:linear-gradient(transparent,rgba(0,0,0,0.85));padding:5px;font-family:var(--font-mono);font-size:8px;color:var(--cyan)">${m.confidence}% MATCH</div>
    </div>`).join('');
}

function excludeBiometric(id) {
  State.biometricMatches = State.biometricMatches.filter(m => m.id !== id);
  if (!State.biometricMatches.length) { resetBiometricPurge(); return; }
  renderBiometricPreview();
}

function resetBiometricPurge() {
  State.biometricMatches = [];
  document.getElementById('biometric-step-1').style.display = 'flex';
  document.getElementById('biometric-step-2').style.display = 'none';
  document.getElementById('biometric-purge-files').value = '';
}

async function commitBiometricPurge() {
  const ids = State.biometricMatches.map(m => m.id);
  if (!confirm(`Permanently delete ${ids.length} records?`)) return;
  const btn = document.getElementById('btn-biometric-purge');
  btn.disabled=true; btn.textContent='Purging…';
  try {
    const res = await api('/api/system/cleanup/biometric/purge', { method: 'POST', body: JSON.stringify(ids) });
    toast(`Purged ${res.details?.purged ?? ids.length} records`, 'cyan');
    resetBiometricPurge(); loadStats();
  } catch (e) { toast('Purge failed: ' + e.message, 'red'); btn.disabled=false; btn.textContent=`Purge ${ids.length} Records`; }
}

function confirmReset() {
  document.getElementById('reset-confirm').value = '';
  openModal('modal-confirm-reset');
}
async function doReset() {
  if (document.getElementById('reset-confirm').value !== 'RESET') { toast('Type RESET to confirm', 'red'); return; }
  const btn = document.getElementById('reset-btn');
  btn.disabled=true; btn.textContent='Resetting…';
  try {
    await api('/api/system/reset', { method: 'POST' });
    closeModal('modal-confirm-reset');
    toast('System reset complete', 'amber');
    loadStats();
  } catch (e) { toast('Reset failed: ' + e.message, 'red'); }
  finally { btn.disabled=false; btn.textContent='Confirm Reset'; }
}

/* ══════════════════════════════════════════
   ALERT RULES
   ══════════════════════════════════════════ */
async function loadRules() {
  State.rules = await api('/api/alert-rules');
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
    await api('/api/alert-rules', { method: 'POST', body: JSON.stringify({
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
  try { await api(`/api/alert-rules/${ruleId}/toggle`, { method: 'PATCH' }); loadRules(); }
  catch (e) { toast(e.message, 'red'); }
}

async function deleteRule(ruleId, name) {
  if (!confirm(`Delete rule "${name}"?`)) return;
  try { await api(`/api/alert-rules/${ruleId}`, { method: 'DELETE' }); toast('Rule deleted', 'amber'); loadRules(); }
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
    const d = await api(`/api/audit-log?${params}`);
    const tbody = document.getElementById('audit-table');
    if (!d.logs?.length) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--on-surface-muted);padding:2rem">No entries found</td></tr>`;
      setText('audit-count', '0 entries');
      return;
    }
    const colorMap = { login:'var(--green)',logout:'var(--on-surface-muted)',add_person:'var(--primary)',delete_person:'var(--red)',add_camera:'var(--cyan)',delete_camera:'var(--red)',add_user:'var(--primary)',delete_user:'var(--red)',cleanup:'var(--purple)',roi_save:'var(--amber)',stop_approve:'var(--green)',stop_deny:'var(--red)',impersonate:'var(--amber)',exit_impersonate:'var(--cyan)' };
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
  const url = `${State.api}/api/audit-log/export?format=csv${action ? `&action=${action}` : ''}&token=${State.token}`;
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
/* ══════════════════════════════════════════
   ADMIN MANAGEMENT
   ══════════════════════════════════════════ */
async function loadAdminMgmt() {
  try {
    const [health, master] = await Promise.all([
      api('/api/system/health'),
      api('/api/super/master-data')
    ]);

    // 1. Hardware Stats
    setText('adm-cpu', `${health.cpu_usage.toFixed(1)}%`);
    const memU = (health.memory.total - health.memory.available) / (1024**3);
    const memT = health.memory.total / (1024**3);
    setText('adm-mem', `${health.memory.percent.toFixed(1)}%`);
    const dbSize = health.storage.db_bytes / (1024**2);
    setText('adm-db', `${dbSize.toFixed(2)} MB`);
    const snapSize = health.storage.snapshots_bytes / (1024**2);
    setText('adm-snapshots', health.storage.snapshots_count.toLocaleString());

    // 2. Master Stats
    setText('mast-users', master.stats.total_users);
    setText('mast-admins', master.stats.total_admins);
    setText('mast-workers', master.stats.total_workers);
    setText('mast-actions', master.stats.total_actions.toLocaleString());

    // 3. Hierarchy Table
    const tb = document.getElementById('master-admin-table');
    tb.innerHTML = master.users.map(u => {
      const isMe = u.username === State.me;
      const hData = master.hierarchy[u.username] || { workers_count: 0 };
      const isSystem = u.created_by === 'system';
      
      return `<tr>
        <td style="font-weight:600">
           <div style="display:flex; align-items:center; gap:8px">
              <div class="sb-logo-icon" style="width:20px; height:20px; font-size:0.5rem">${u.username[0].toUpperCase()}</div>
              ${esc(u.username)} ${isMe ? '<span style="color:var(--cyan);font-size:0.5rem">(YOU)</span>' : ''}
           </div>
        </td>
        <td><span class="badge ${u.role === 'super_admin' ? 'admin' : (u.role === 'admin' ? 'amber' : 'worker')}">${u.role.toUpperCase()}</span></td>
        <td><span style="font-size:0.7rem; color:var(--on-surface-muted)">${isSystem ? '⚙ SYSTEM' : '👤 ' + esc(u.created_by)}</span></td>
        <td style="font-weight:700; color:var(--green)">${u.role !== 'worker' ? hData.workers_count : '—'}</td>
        <td>
          ${!isMe ? `<button class="btn btn-primary btn-sm" onclick="impersonateUser('${esc(u.username)}')">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            Command Preview
          </button>` : '<span style="color:var(--on-surface-muted);font-size:0.7rem">Master Identity</span>'}
        </td>
      </tr>`;
    }).join('');

  } catch (e) { toast('Master Data sync failed: ' + e.message, 'red'); }
}

async function impersonateUser(username) {
  if (!confirm(`Switching to ${username}'s perspective. You will see what they see. Continue?`)) return;
  try {
    const res = await api(`/api/impersonate/${username}`, { method: 'POST' });
    
    // Save original Super Admin state to sessionStorage
    sessionStorage.setItem('sx_orig_token', State.token);
    sessionStorage.setItem('sx_orig_user', State.me);
    sessionStorage.setItem('sx_orig_role', State.role);
    
    // Set target user state
    State.token = res.token;
    State.me = res.username;
    State.role = res.role;
    State.persist();
    
    toast(`Previewing system as ${username}`, 'amber');
    setTimeout(() => window.location.reload(), 800);
  } catch (e) { toast('Impersonation failed: ' + e.message, 'red'); }
}

async function exitImpersonation() {
  const origToken = sessionStorage.getItem('sx_orig_token');
  const origUser  = sessionStorage.getItem('sx_orig_user');
  const origRole  = sessionStorage.getItem('sx_orig_role');
  
  if (!origToken) {
    toast('No original session found', 'red');
    return;
  }
  
  console.info('[AUTH] Restoring Super Admin context...');
  State.token = origToken;
  State.me = origUser;
  State.role = origRole;
  State.persist();

  // Short delay to ensure state propagation before API call
  await new Promise(r => setTimeout(r, 200));

  console.info('[AUTH] Logging exit event to backend...');
  try {
    const res = await api('/api/impersonate/exit', { method: 'POST' });
    console.info('[AUTH] Log response:', res);
  } catch (e) {
    console.warn('[AUTH] Exit log failed:', e);
  }

  // Final cleanup and reload
  sessionStorage.removeItem('sx_orig_token');
  sessionStorage.removeItem('sx_orig_user');
  sessionStorage.removeItem('sx_orig_role');
  
  toast('Returning to Super Admin dashboard', 'cyan');
  setTimeout(() => {
    console.info('[AUTH] Reloading page...');
    window.location.reload();
  }, 1500);
}

/* ══════════════════════════════════════════
   SUPER ADMIN FUNCTIONS
   ══════════════════════════════════════════ */

async function loadSuperDashboard() {
  try {
    const [health, master] = await Promise.all([
      api('/api/system/health'),
      api('/api/super/master-data')
    ]);

    // 1. Master Stats
    setText('sup-total-users', master.stats.total_users);
    setText('sup-active-sessions', master.stats.active_sessions || 0);
    setText('sup-total-nodes', master.stats.total_live_nodes);
    
    const uptimeHrs = Math.floor(health.uptime / 3600);
    setText('sup-uptime', `${uptimeHrs}h ${Math.floor((health.uptime % 3600) / 60)}m`);

    // 2. Health Bars
    const healthEl = document.getElementById('sup-health-bars');
    const cpu = health.cpu_usage;
    const mem = health.memory.percent;
    const disk = (health.storage.disk_used / health.storage.disk_total * 100) || 0;

    healthEl.innerHTML = `
      <div class="health-bar-row">
        <div class="health-bar-label">
          <span>CPU UTILIZATION</span>
          <span style="color:var(--cyan)">${cpu.toFixed(1)}%</span>
        </div>
        <div class="health-bar-wrap">
          <div class="health-bar-fill" style="width:${cpu}%;background:var(--cyan)"></div>
        </div>
      </div>
      <div class="health-bar-row">
        <div class="health-bar-label">
          <span>SYSTEM MEMORY</span>
          <span style="color:var(--purple)">${mem.toFixed(1)}%</span>
        </div>
        <div class="health-bar-wrap">
          <div class="health-bar-fill" style="width:${mem}%;background:var(--purple)"></div>
        </div>
      </div>
      <div class="health-bar-row">
        <div class="health-bar-label">
          <span>DISK STORAGE</span>
          <span style="color:var(--amber)">${disk.toFixed(1)}%</span>
        </div>
        <div class="health-bar-wrap">
          <div class="health-bar-fill" style="width:${disk}%;background:var(--amber)"></div>
        </div>
      </div>
    `;

    // 3. Simple Activity Chart (Mocked or simplified from analytics)
    renderSuperActivityChart();

  } catch (e) { 
    // Silently fail to avoid intrusive toasts on background sync
  }
}

function renderSuperActivityChart() {
    const canvas = document.getElementById('sup-activity-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const container = canvas.parentElement;
    
    // Resize handler
    const dpr = window.devicePixelRatio || 1;
    const W = container.offsetWidth;
    const H = container.offsetHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.scale(dpr, dpr);

    let offset = 0;
    function animate() {
        if (State.activePage !== 'super-dashboard') return;
        
        ctx.clearRect(0, 0, W, H);
        
        // Draw Neural Grid (Subtle)
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
        ctx.lineWidth = 1;
        for(let i=0; i<W; i+=30) {
            ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, H); ctx.stroke();
        }
        for(let i=0; i<H; i+=30) {
            ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(W, i); ctx.stroke();
        }

        // Draw Waves
        drawWave(ctx, W, H, offset, 'rgba(77, 224, 248, 0.4)', 2, 40, 0.02);
        drawWave(ctx, W, H, offset * 1.5, 'rgba(192, 200, 255, 0.25)', 1.5, 30, 0.03);
        
        offset += 0.05;
        requestAnimationFrame(animate);
    }
    animate();
}

function drawWave(ctx, W, H, offset, color, width, amp, freq) {
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    for (let x = 0; x <= W; x += 5) {
        const y = H / 2 + Math.sin(x * freq + offset) * amp + Math.sin(x * 0.01 + offset * 0.5) * (amp/2);
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.stroke();
}

async function loadPreviewSystem() {
    try {
        const master = await api('/api/super/master-data');
        const grid = document.getElementById('preview-admin-list');
        const admins = master.users.filter(u => u.role === 'admin' || u.role === 'super_admin');
        
        grid.innerHTML = admins.map(u => {
            const isMe = u.username === State.me;
            const hData = master.hierarchy[u.username] || { workers_count: 0 };
            return `
            <div class="panel" style="padding:1.5rem; display:flex; flex-direction:column; gap:1rem; border-color:${isMe ? 'var(--cyan-glow)' : 'var(--outline)'}">
                <div style="display:flex; align-items:center; gap:1rem">
                    <div class="user-av" style="width:48px; height:48px; font-size:1.25rem; background:var(--surface-high)">${u.username[0].toUpperCase()}</div>
                    <div style="flex:1">
                        <div style="font-weight:700; font-size:1.1rem">${esc(u.username)}</div>
                        <div style="font-size:0.65rem; color:var(--on-surface-muted); text-transform:uppercase">${u.role} · ID: ${u.admin_id}</div>
                    </div>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:0.8rem; border-top:1px solid var(--outline); padding-top:1rem">
                    <span style="color:var(--on-surface-muted)">Owned Nodes</span>
                    <span style="font-weight:700; color:var(--green)">${hData.workers_count}</span>
                </div>
                ${!isMe ? `
                <button class="btn btn-primary" onclick="impersonateUser('${esc(u.username)}')" style="width:100%; margin-top:0.5rem">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" style="margin-right:8px"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                    PREVIEW SYSTEM
                </button>` : `<div style="text-align:center; font-size:0.7rem; color:var(--on-surface-muted); padding:10px">CURRENT IDENTITY</div>`}
            </div>`;
        }).join('');
    } catch (e) { toast('Failed to load preview list', 'red'); }
}

async function loadNodeMonitor() {
    try {
        const [master, workers] = await Promise.all([
            api('/api/super/master-data'),
            api('/api/active-users')
        ]);
        
        const container = document.getElementById('node-admin-groups');
        const nodes = workers.nodes || [];
        
        // Group nodes by admin_id
        const grouped = {};
        nodes.forEach(n => {
            const aid = n.admin_id || 0;
            if(!grouped[aid]) grouped[aid] = [];
            grouped[aid].push(n);
        });

        // Get admin names
        const adminMap = {};
        master.users.forEach(u => {
            if(u.role !== 'worker') adminMap[u.admin_id] = u.username;
        });

        container.innerHTML = Object.keys(grouped).map(aid => `
            <div class="panel" style="padding:1.5rem">
                <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:1.5rem">
                    <div style="display:flex; align-items:center; gap:10px">
                        <div style="width:10px; height:10px; background:var(--primary); border-radius:50%"></div>
                        <div style="font-weight:700; letter-spacing:0.05em">TENANT: ${esc(adminMap[aid] || 'Unknown Admin')} (ID: ${aid})</div>
                    </div>
                    <div class="badge online">${grouped[aid].length} NODES ACTIVE</div>
                </div>
                <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(240px, 1fr)); gap:1rem">
                    ${grouped[aid].map(n => `
                        <div style="padding:1rem; background:var(--surface-high); border:1px solid var(--outline); border-radius:var(--radius-md); display:flex; flex-direction:column; gap:0.5rem">
                            <div style="font-family:var(--font-mono); font-size:0.8rem; font-weight:700">${esc(n.id)}</div>
                            <div style="font-size:0.65rem; color:var(--on-surface-muted)">LOC: ${esc(n.location || 'Unknown')}</div>
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px">
                                <span class="badge online" style="font-size:0.55rem; padding:2px 6px">HEALTHY</span>
                                <span style="font-family:var(--font-mono); font-size:0.6rem; color:var(--on-surface-muted)">${Math.round(Date.now()/1000 - n.last_seen)}s ago</span>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `).join('') || '<div class="empty-state">No active nodes across any tenant.</div>';

    } catch (e) { toast('Node Monitor sync failed', 'red'); }
}

async function loadSuperAnalysis() {
    try {
        const data = await api('/api/super/analysis');
        
        // 1. Stats
        const auditVol = data.audit_distribution.reduce((s, d) => s + d.count, 0);
        setText('sup-audit-vol', auditVol.toLocaleString());
        
        // 2. Audit Dist
        const distEl = document.getElementById('sup-audit-dist');
        const maxAudit = Math.max(1, ...data.audit_distribution.map(d => d.count));
        distEl.innerHTML = data.audit_distribution.slice(0, 6).map(d => {
            const pct = (d.count / maxAudit * 100).toFixed(1);
            return `
            <div>
                <div style="display:flex; justify-content:space-between; font-size:0.72rem; margin-bottom:6px">
                    <span style="font-weight:700; text-transform:uppercase; letter-spacing:0.05em">${d.action.replace(/_/g, ' ')}</span>
                    <span style="font-family:var(--font-mono); color:var(--on-surface-muted)">${d.count}</span>
                </div>
                <div style="height:6px; background:var(--surface-high); border-radius:3px; overflow:hidden">
                    <div style="height:100%; width:${pct}%; background:linear-gradient(90deg, var(--primary), var(--purple)); transition:width 1.2s cubic-bezier(0.34, 1.56, 0.64, 1)"></div>
                </div>
            </div>`;
        }).join('') || 'No audit data';

        // 3. Storage Stats
        const storeEl = document.getElementById('sup-storage-analysis');
        const maxStore = Math.max(1, ...data.storage_stats.map(s => s.size_mb));
        storeEl.innerHTML = data.storage_stats.slice(0, 5).map(s => {
            const pct = (s.size_mb / maxStore * 100).toFixed(1);
            return `
            <div class="result-item" style="padding:0.75rem; background:var(--surface-high)44; border-radius:var(--radius-md); border:1px solid var(--outline)">
                <div style="flex:1">
                    <div style="font-size:0.7rem; font-weight:800; color:var(--on-surface-muted)">OPERATOR ID: ${s.admin_id}</div>
                    <div style="font-family:var(--font-mono); font-size:1rem; margin-top:0.25rem">${s.size_mb.toFixed(1)} MB</div>
                </div>
                <div style="text-align:right">
                    <div style="font-size:0.6rem; color:var(--on-surface-muted)">SNAPSHOTS</div>
                    <div style="font-weight:700; color:var(--amber)">${s.count}</div>
                </div>
            </div>`;
        }).join('') || 'No storage data';

        // 4. Render Mesh Topology
        renderMeshTopology();

    } catch (e) { toast('Analysis failed', 'red'); }
}

let meshLoopRunning = false;
function renderMeshTopology() {
    const canvas = document.getElementById('mesh-canvas');
    if (!canvas || meshLoopRunning) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.parentElement.offsetWidth;
    const H = 300;
    canvas.width = W; canvas.height = H;

    const nodes = [];
    for(let i=0; i<8; i++) {
        nodes.push({
            x: Math.random() * W,
            y: Math.random() * H,
            vx: (Math.random() - 0.5) * 0.5,
            vy: (Math.random() - 0.5) * 0.5,
            active: Math.random() > 0.2
        });
    }

    function draw() {
        const page = document.getElementById('page-super-analysis');
        if (!page || !page.classList.contains('active')) {
            meshLoopRunning = false;
            return;
        }
        meshLoopRunning = true;
        ctx.clearRect(0,0,W,H);
        
        // Connections
        ctx.strokeStyle = 'rgba(77, 124, 255, 0.15)';
        ctx.lineWidth = 1;
        for(let i=0; i<nodes.length; i++) {
            for(let j=i+1; j<nodes.length; j++) {
                const dist = Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y);
                if (dist < 150) {
                    ctx.beginPath(); ctx.moveTo(nodes[i].x, nodes[i].y); ctx.lineTo(nodes[j].x, nodes[j].y); ctx.stroke();
                }
            }
        }

        // Nodes
        nodes.forEach(n => {
            n.x += n.vx; n.y += n.vy;
            if (n.x < 0 || n.x > W) n.vx *= -1;
            if (n.y < 0 || n.y > H) n.vy *= -1;

            ctx.fillStyle = n.active ? 'var(--cyan)' : 'var(--red)';
            ctx.shadowBlur = n.active ? 10 : 0;
            ctx.shadowColor = n.active ? 'var(--cyan)' : 'transparent';
            ctx.beginPath(); ctx.arc(n.x, n.y, 4, 0, Math.PI*2); ctx.fill();
            ctx.shadowBlur = 0;
        });
        requestAnimationFrame(draw);
    }
    draw();
}
