/* ══════════════════════════════════════════
   APP BOOTSTRAP — Entry Point
   ══════════════════════════════════════════ */

function bootstrap() {
  const isImpersonating = !!sessionStorage.getItem('sx_orig_token');
  
  // Clear any existing intervals first to prevent duplicates
  if (State.bgIntervals) {
    State.bgIntervals.forEach(clearInterval);
    State.bgIntervals = [];
  }

  // Periodic refresh intervals — track handles in State.bgIntervals
  const sync = (fn, ms) => State.bgIntervals.push(setInterval(fn, ms));

  // Common for all roles
  connectSSE();
  sync(updateAlertHeartbeat, 2000);
  sync(checkBackend, 20000);

  if (State.role === 'super_admin' && !isImpersonating) {
    showPage('super-dashboard');
    sync(loadSuperDashboard, 30000);
    return;
  }

  // Initial data load (Standard / Impersonation)
  loadStats();
  loadSightings();
  loadObjects();
  loadCameras();
  pollMeshStatus();

  sync(loadStats,         30000);
  sync(loadSightings,     45000);
  sync(loadObjects,       45000);
  sync(loadCameras,       60000);
  sync(loadWorkers,       25000);
  sync(pollMeshStatus,    15000);
  sync(pollStopRequestsBadge, 30000);

  // Sync global buttons after cameras load
  setTimeout(syncGlobalButtons, 2500);
}

document.addEventListener('DOMContentLoaded', () => {
  // Apply saved theme icons (theme was set in ui.js IIFE, icons need DOM ready)
  const savedTheme = localStorage.getItem('sx-theme') || 'dark';
  applyThemeIcons(savedTheme === 'dark');

  // Apply sidebar collapse
  if (localStorage.getItem('sx-sidebar-collapsed') === '1') {
    document.querySelector('.app-shell')?.classList.add('collapsed');
  }

  // Keyboard shortcuts
  document.getElementById('li-pass').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
  document.getElementById('li-user').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });

  // Check for existing session
  if (State.token && State.me) {
    applyAuthUI();
    bootstrap();
  } else {
    document.getElementById('login-screen').style.display = 'flex';
  }

  // Start clock
  updateClock();
  setInterval(updateClock, 1000);

  // Initial page
  const isImpersonating = !!sessionStorage.getItem('sx_orig_token');
  if (State.role === 'super_admin' && !isImpersonating) {
    showPage('super-dashboard');
  } else {
    showPage('overview');
  }

  // Backend health check (even when not logged in)
  if (!State.token) {
    checkBackend();
    setInterval(checkBackend, 30000);
  }
});
