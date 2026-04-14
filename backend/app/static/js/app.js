/* ══════════════════════════════════════════
   APP BOOTSTRAP — Entry Point
   ══════════════════════════════════════════ */

function bootstrap() {
  // Initial data load
  loadStats();
  loadSightings();
  loadObjects();
  loadCameras();
  connectSSE();
  pollMeshStatus();

  // Periodic refresh intervals
  setInterval(loadStats,         30000);
  setInterval(loadSightings,     45000);
  setInterval(loadObjects,       45000);
  setInterval(loadCameras,       60000);
  setInterval(loadWorkers,       25000);
  setInterval(pollMeshStatus,    15000);
  setInterval(pollStopRequestsBadge, 30000);
  setInterval(updateAlertHeartbeat,   2000);
  setInterval(checkBackend,      20000);

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
  document.getElementById('li-pass')?.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
  document.getElementById('li-user')?.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });

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
  showPage('overview');

  // Backend health check (even when not logged in)
  if (!State.token) {
    checkBackend();
    setInterval(checkBackend, 30000);
  }
});
