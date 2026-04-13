/* ══════════════════════════════════════════
   UI UTILITIES — Toasts, Modals, Helpers
   ══════════════════════════════════════════ */

/* ─── TOAST NOTIFICATIONS ─── */
const TOAST_TYPES = {
  match:  ['alert-match',  'THREAT MATCH'],
  red:    ['alert-match',  'ERROR'],
  obj:    ['alert-obj',    'OBJECT DETECTED'],
  cyan:   ['alert-obj',    'INFO'],
  sight:  ['alert-sight',  'SIGHTING LOGGED'],
  amber:  ['alert-sight',  'ALERT'],
  green:  ['alert-sight',  'SUCCESS'],
  muted:  ['alert-obj',    'INFO'],
};

function toast(msg, type = 'amber') {
  const [cls, label] = TOAST_TYPES[type] || TOAST_TYPES.amber;
  const el = document.createElement('div');
  el.className = `toast ${cls}`;
  el.innerHTML = `
    <div class="toast-type">${label}</div>
    <div class="toast-msg">${esc(msg)}</div>
    <div class="toast-meta">${new Date().toLocaleTimeString('en-GB', { hour12: false })}</div>`;
  el.onclick = () => el.remove();

  const container = document.getElementById('toasts');
  container.appendChild(el);

  setTimeout(() => {
    el.style.animation = 'toastOut 0.3s ease forwards';
    setTimeout(() => el.remove(), 300);
  }, 4500);
}

/* ─── MODALS ─── */
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('open');
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}

// Close modal on backdrop click
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.classList.remove('open');
  }
});

/* ─── BADGES ─── */
function updateBadge(id, count) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = count > 99 ? '99+' : String(count);
  el.classList.toggle('show', count > 0);
  el.style.display = count > 0 ? '' : 'none';
}

/* ─── FORMAT HELPERS ─── */
function fmtTs(ts) {
  if (!ts) return '—';
  try {
    // Handle ISO strings with or without Z
    const s = typeof ts === 'string' && !ts.endsWith('Z') && !ts.includes('+') ? ts + 'Z' : ts;
    const d = new Date(s);
    if (isNaN(d.getTime())) return ts.toString().slice(0, 16).replace('T', ' ');
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) + ' ' +
           d.toLocaleTimeString('en-GB', { hour12: false }).slice(0, 5);
  } catch {
    return String(ts).slice(0, 16).replace('T', ' ');
  }
}

function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : '';
}

/* ─── CONNECTION STATUS ─── */
function updateConnectionStatus(ok) {
  const dot = document.querySelector('.sb-dot');
  const text = document.querySelector('.sb-status-text');
  if (dot) {
    dot.classList.toggle('offline', !ok);
  }
  if (text) {
    text.textContent = ok ? 'SYSTEM ACTIVE' : 'CONNECTION LOST';
  }
}

/* ─── CLOCK ─── */
function updateClock() {
  const el = document.getElementById('sys-time');
  if (el) el.textContent = new Date().toLocaleTimeString('en-GB', { hour12: false });
}

/* ─── FILE COUNT PREVIEW ─── */
function showFileCount(input, countId) {
  const el = document.getElementById(countId);
  if (el) el.textContent = input.files.length ? `${input.files.length} file(s) selected` : '';
}

/* ─── SYNC ALERT OVERLAY ─── */
function showSyncAlert(type = 'loading') {
  const el = document.getElementById('sync-alert');
  const txt = document.getElementById('sync-alert-text');
  const spinner = el.querySelector('.sync-spinner');

  if (type === 'done') {
    txt.innerHTML = "SYSTEM REFRESHED<br><span style='font-size:0.6rem;color:var(--green);letter-spacing:0.1em'>SYNC COMPLETE</span>";
    spinner.style.borderTopColor = 'var(--green)';
    el.style.borderColor = 'var(--green)';
  } else {
    txt.innerHTML = "SYSTEM REFRESHING<br><span style='font-size:0.6rem;opacity:0.6'>PLEASE WAIT…</span>";
    spinner.style.borderTopColor = 'var(--primary)';
    el.style.borderColor = 'var(--primary)';
  }

  el.style.display = 'flex';
  requestAnimationFrame(() => el.classList.add('show'));
}

function hideSyncAlert() {
  const el = document.getElementById('sync-alert');
  el.classList.remove('show');
  setTimeout(() => { el.style.display = 'none'; }, 400);
}

/* ─── THEME TOGGLE ─── */
function toggleTheme() {
  const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
  const next = isDark ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('sx-theme', next);
  applyThemeIcons(next === 'dark');
}

function applyThemeIcons(isDark) {
  const icon = document.getElementById('theme-icon');
  const label = document.getElementById('theme-label');
  if (icon) {
    icon.innerHTML = isDark 
      ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`
      : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;
  }
  if (label) label.textContent = isDark ? 'DARK' : 'LIGHT';
}

/* ─── SIDEBAR TOGGLE ─── */
function toggleSidebar() {
  const shell = document.querySelector('.app-shell');
  const isCollapsed = shell.classList.toggle('collapsed');
  localStorage.setItem('sx-sidebar-collapsed', isCollapsed ? '1' : '0');
}

/* ─── INIT UI STATE ─── */
(function initUIPreferences() {
  // Theme
  const savedTheme = localStorage.getItem('sx-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
  // Icons are set after DOM ready

  // Sidebar
  if (localStorage.getItem('sx-sidebar-collapsed') === '1') {
    document.querySelector('.app-shell')?.classList.add('collapsed');
  }
})();
