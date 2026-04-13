/* ══════════════════════════════════════════
   WATCHLIST, FACE SEARCH, FRAME ANALYSIS
   ══════════════════════════════════════════ */

/* ─── WATCHLIST ─── */
async function loadWatchlist() {
  try {
    const persons = await api('/api/wanted');
    const tb = document.getElementById('watchlist-table');

    if (!persons.length) {
      tb.innerHTML = `<tr><td colspan="6"><div class="empty-state" style="padding:2rem">
        <div class="empty-icon">◎</div><div class="empty-text">Watchlist empty</div>
      </div></td></tr>`;
      return;
    }

    tb.innerHTML = persons.map(p => {
      const initials = p.name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
      const thumbSrc = p.primary_photo ? `/api/intel-photos/${p.primary_photo}` : null;

      return `<tr>
        <td>
          ${thumbSrc
            ? `<img class="td-img" src="${thumbSrc}"
                onerror="this.outerHTML='<div class=\\'td-img\\' style=\\'background:var(--primary-dim);display:flex;align-items:center;justify-content:center;font-family:var(--font-display);font-size:0.7rem;color:var(--primary)\\'>${initials}</div>'">`
            : `<div class="td-img" style="background:var(--primary-dim);display:flex;align-items:center;justify-content:center;font-family:var(--font-display);font-size:0.7rem;color:var(--primary)">${initials}</div>`}
        </td>
        <td>
          <div style="font-weight:600">${esc(p.name)}</div>
          <div class="td-mono">${p.id.slice(0, 8)}…</div>
        </td>
        <td class="td-mono">${esc(p.added_by || '—')}</td>
        <td class="td-mono">${fmtTs(p.added_at)}</td>
        <td><span class="badge worker">${p.photo_count} photo${p.photo_count !== 1 ? 's' : ''}</span></td>
        <td>
          <button class="btn btn-ghost btn-sm" style="margin-right:0.4rem" onclick="openDossier(${JSON.stringify(p).replace(/"/g, '&quot;')})">Dossier</button>
          <button class="btn btn-danger btn-sm" onclick="deletePerson('${esc(p.id)}','${esc(p.name)}')">Remove</button>
        </td>
      </tr>`;
    }).join('');
  } catch (e) { console.warn('[watchlist]', e); }
}

function openAddPerson() {
  ['ap-name','ap-files'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  setText('ap-count', '');
  const err = document.getElementById('ap-err');
  if (err) err.style.display = 'none';
  openModal('modal-add-person');
}

async function addWatchlistPerson() {
  const name  = document.getElementById('ap-name').value.trim();
  const files = document.getElementById('ap-files').files;
  const btn   = document.getElementById('ap-btn');
  const err   = document.getElementById('ap-err');

  if (!name)         { err.style.display='block'; err.textContent='Name required'; return; }
  if (!files.length) { err.style.display='block'; err.textContent='At least one photo required'; return; }

  btn.disabled = true; btn.textContent = 'Processing…'; err.style.display = 'none';
  try {
    const fd = new FormData();
    fd.append('name', name);
    for (const f of files) fd.append('files', f);
    await api('/api/wanted', { method: 'POST', body: fd });
    closeModal('modal-add-person');
    toast('Target added: ' + name, 'amber');
    loadWatchlist(); loadStats();
  } catch (e) { err.style.display='block'; err.textContent=e.message; }
  finally { btn.disabled=false; btn.textContent='Add to Watchlist'; }
}

async function deletePerson(id, name) {
  if (!confirm(`Remove "${name}" from watchlist?`)) return;
  try {
    await api(`/api/wanted/${id}`, { method: 'DELETE' });
    toast('Removed: ' + name, 'muted');
    loadWatchlist(); loadStats();
    // Close dossier if open for this person
    if (State.dossierPersonId === id) closeDossier();
  } catch (e) { toast('Error: ' + e.message, 'red'); }
}

/* ─── DOSSIER ─── */
async function openDossier(person) {
  State.dossierPersonId = person.id;
  document.getElementById('dossier-name').textContent = person.name;
  document.getElementById('dossier-id').textContent   = `ID: ${person.id}`;
  document.getElementById('dossier-enlisted-by').textContent = person.added_by || 'System';
  document.getElementById('dossier-created-at').textContent  = fmtTs(person.added_at);
  updateDossierSync(person.photo_count || 0);
  openModal('modal-dossier');

  try {
    const photos = await api(`/api/wanted/${person.id}/photos`);
    renderDossierGallery(photos || []);
  } catch {}
}

function updateDossierSync(count) {
  const pct = Math.min(100, Math.round((count / 15) * 100));
  setText('dossier-sync-txt', `${pct}%`);
  const bar = document.getElementById('dossier-sync-bar');
  if (bar) bar.style.width = `${pct}%`;
}

function renderDossierGallery(photos) {
  const gallery = document.getElementById('dossier-gallery');
  let html = '';
  for (let i = 0; i < 15; i++) {
    if (photos[i]) {
      html += `<div class="gallery-slot">
        <img src="/api/intel-photos/${photos[i].id}" loading="lazy">
        <button class="slot-delete-btn" onclick="deletePhoto('${photos[i].id}')" title="Remove">✕</button>
      </div>`;
    } else {
      html += `<div class="gallery-slot slot-empty" onclick="document.getElementById('dossier-add-file').click()">
        <div style="pointer-events:none">Slot ${i+1}<br>+ Add</div>
      </div>`;
    }
  }
  gallery.innerHTML = html;
}

async function uploadToDossier() {
  const files = document.getElementById('dossier-add-file').files;
  if (!files.length || !State.dossierPersonId) return;

  const fd = new FormData();
  fd.append('name', document.getElementById('dossier-name').textContent);
  for (const f of files) fd.append('files', f);

  toast(`Injecting ${files.length} neural sample(s)…`, 'amber');
  try {
    await api('/api/wanted', { method: 'POST', body: fd });
    const photos = await api(`/api/wanted/${State.dossierPersonId}/photos`);
    renderDossierGallery(photos || []);
    updateDossierSync(photos.length);
    loadWatchlist();
  } catch (e) { toast('Upload error: ' + e.message, 'red'); }
}

async function deletePhoto(photoId) {
  if (!confirm('Remove this biometric sample?')) return;
  try {
    await api(`/api/wanted/${State.dossierPersonId}/photos/${photoId}`, { method: 'DELETE' });
    const photos = await api(`/api/wanted/${State.dossierPersonId}/photos`);
    renderDossierGallery(photos || []);
    updateDossierSync(photos.length);
    loadWatchlist();
  } catch (e) { toast('Error: ' + e.message, 'red'); }
}

function closeDossier() {
  closeModal('modal-dossier');
  State.dossierPersonId = null;
}

/* ─── FACE SEARCH ─── */
function previewSearchFiles(input) {
  const prev = document.getElementById('search-preview');
  if (!prev) return;
  prev.innerHTML = '';
  Array.from(input.files).slice(0, 6).forEach(f => {
    const img = document.createElement('img');
    img.src = URL.createObjectURL(f);
    img.style.cssText = 'width:60px;height:60px;object-fit:cover;border-radius:6px;border:1px solid var(--outline)';
    prev.appendChild(img);
  });
}

function handleSearchDrop(e) {
  e.preventDefault();
  document.getElementById('search-zone').classList.remove('drag');
  const files = e.dataTransfer.files;
  if (!files.length) return;
  const input = document.getElementById('search-files');
  const dt = new DataTransfer();
  for (const f of files) dt.items.add(f);
  input.files = dt.files;
  previewSearchFiles(input);
}

async function runFaceSearch() {
  const files = document.getElementById('search-files').files;
  const btn = document.getElementById('search-btn');
  if (!files.length) { toast('Select at least one face image', 'red'); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="loader"></span> Searching…';
  try {
    const fd = new FormData();
    for (const f of files) fd.append('files', f);
    const d = await api('/api/search-face', { method: 'POST', body: fd });
    renderSearchResults(d);
  } catch (e) { toast('Search failed: ' + e.message, 'red'); }
  finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> Run Biometric Search`;
  }
}

function renderSearchResults(d) {
  const wrap  = document.getElementById('search-results-wrap');
  const title = document.getElementById('search-result-title');
  const res   = document.getElementById('search-results');
  if (wrap) wrap.style.display = 'block';
  if (title) {
    title.textContent = d.found ? `⚠ MATCH: ${d.person}` : 'NO WATCHLIST MATCH';
    title.style.color = d.found ? 'var(--red)' : 'var(--cyan)';
  }

  if (!d.matches?.length) {
    res.innerHTML = `<div class="empty-state" style="padding:1.5rem"><div class="empty-text">No matching sightings in history</div></div>`;
    return;
  }

  res.innerHTML = d.matches.map(m => `
    <div class="result-item" id="search-res-${m.id}" style="gap:0.875rem;align-items:center;flex-wrap:nowrap">
      <img src="${esc(m.snapshot)}" style="width:48px;height:48px;object-fit:cover;border-radius:6px;border:1px solid var(--outline);flex-shrink:0">
      <div style="flex:1;min-width:0">
        <div style="font-weight:600;font-size:0.82rem">${fmtTs(m.timestamp)}</div>
        <div class="td-mono" style="font-size:0.65rem">${esc(m.camera_id || '—')} · ${esc(m.location || '—')}</div>
      </div>
      <span class="badge ${m.matched ? 'match' : 'cyan'}" style="flex-shrink:0">${Math.round(m.confidence)}%</span>
      <button class="btn btn-ghost btn-sm" style="color:var(--red);padding:4px;flex-shrink:0"
              onclick="deleteSightingFromSearch('${m.id}',event)" title="Delete sighting">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
        </svg>
      </button>
    </div>`).join('');
}

async function deleteSightingFromSearch(id, e) {
  if (e) e.stopPropagation();
  if (!confirm('Permanently delete this sighting record?')) return;
  const el = document.getElementById(`search-res-${id}`);
  if (el) { el.style.opacity = '0.4'; el.style.pointerEvents = 'none'; }
  try {
    await api('/api/system/cleanup/biometric/purge', {
      method: 'POST',
      body: JSON.stringify([id]),
    });
    if (el) { el.style.transition = 'all 0.3s'; el.style.transform = 'translateX(20px)'; el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }
    toast('Sighting deleted', 'cyan');
    loadStats();
  } catch (err) {
    if (el) { el.style.opacity = '1'; el.style.pointerEvents = 'all'; }
    toast('Failed: ' + err.message, 'red');
  }
}

/* ─── FRAME ANALYSIS ─── */
function previewAnalysis(input) {
  if (!input.files.length) return;
  const url = URL.createObjectURL(input.files[0]);
  const zone = document.getElementById('analysis-zone');
  if (zone) {
    const icon = zone.querySelector('.upload-icon');
    const text = zone.querySelector('.upload-text');
    if (icon) icon.textContent = '✓';
    if (text) text.textContent = input.files[0].name;
  }
  const prev = document.getElementById('analysis-preview');
  if (prev) { prev.src = url; prev.style.display = 'block'; }
  const wrap = document.getElementById('analysis-results-wrap');
  if (wrap) { wrap.style.display = 'block'; }
  const results = document.getElementById('analysis-results');
  if (results) results.innerHTML = '<div style="color:var(--on-surface-muted);font-family:var(--font-mono);font-size:0.75rem">Run analysis to see results…</div>';
}

async function runAnalysis() {
  const file = document.getElementById('analysis-file').files[0];
  const btn  = document.getElementById('analysis-btn');
  if (!file) { toast('Select a snapshot first', 'red'); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="loader"></span> Analyzing…';
  try {
    const fd = new FormData();
    fd.append('file', file);
    const d = await api('/api/analyze-snapshot', { method: 'POST', body: fd });
    const prev = document.getElementById('analysis-preview');
    if (prev) { prev.src = d.preview; prev.style.display = 'block'; }
    renderAnalysisResults(d);
    const wrap = document.getElementById('analysis-results-wrap');
    if (wrap) wrap.style.display = 'block';
  } catch (e) { toast('Analysis failed: ' + e.message, 'red'); }
  finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg> Run Full Analysis`;
  }
}

function renderAnalysisResults(d) {
  const el = document.getElementById('analysis-results');
  let html = '';

  if (d.face) {
    html += `<div style="margin-bottom:1rem;padding:0.875rem;background:var(--red-dim);border:1px solid var(--red-dim);border-radius:var(--radius-md)">
      <div style="font-family:var(--font-mono);font-size:0.6rem;color:var(--red);letter-spacing:0.1em;margin-bottom:0.4rem">⚠ FACE MATCH</div>
      <div style="font-weight:600">${esc(d.face.person.name)}</div>
      <div class="td-mono">${d.face.confidence}% confidence</div>
    </div>`;
  }

  if (d.objects?.length) {
    html += `<div style="font-family:var(--font-mono);font-size:0.6rem;color:var(--on-surface-muted);letter-spacing:0.1em;margin-bottom:0.5rem">DETECTED OBJECTS (${d.objects.length})</div>`;
    html += d.objects.map(o => `
      <div class="result-item" style="margin-bottom:0.35rem">
        <span class="result-label">${esc(capitalize(o.label))}</span>
        <div class="conf-bar-wrap" style="flex:1;margin-left:1rem">
          <div class="conf-bar"><div class="conf-fill" style="width:${Math.round(o.confidence * 100)}%"></div></div>
          <span class="td-mono" style="white-space:nowrap">${Math.round(o.confidence * 100)}%</span>
        </div>
      </div>`).join('');
  }

  if (!d.face && !d.objects?.length) {
    html = `<div class="empty-state" style="padding:1rem"><div class="empty-text">Nothing detected</div><div class="empty-sub">// No faces or objects above threshold</div></div>`;
  }

  if (el) el.innerHTML = html;
}
