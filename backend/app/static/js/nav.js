/* ══════════════════════════════════════════
   NAVIGATION — Page Routing
   ══════════════════════════════════════════ */

function showPage(id, navEl) {
  const isImpersonating = !!sessionStorage.getItem('sx_orig_token');

  // Redirect Super Admin 'users' requests to the specialized 'admin-mgmt' page
  if (id === 'users' && State.role === 'super_admin') {
    id = 'admin-mgmt';
  }

  // Super Admin Default Landing Page
  if ((id === 'overview' || id === 'live-feed') && State.role === 'super_admin' && !isImpersonating) {
    id = 'super-dashboard';
  }

  // Deactivate all pages
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  // Activate target page
  const page = document.getElementById('page-' + id);
  if (page) page.classList.add('active');

  // Activate nav item
  if (navEl) {
    navEl.classList.add('active');
  } else {
    document.querySelectorAll('.nav-item').forEach(n => {
      if (n.getAttribute('onclick')?.includes(`'${id}'`)) n.classList.add('active');
    });
  }

  // Update topbar
  const meta = PAGE_META[id] || [id.toUpperCase(), ''];
  document.getElementById('topbar-title').textContent = meta[0];
  document.getElementById('topbar-sub').textContent = meta[1];

  State.activePage = id;

  // Reset badges on visit
  if (id === 'sightings') { State.newSightings = 0; updateBadge('badge-sightings', 0); }
  if (id === 'objects') { State.newObjects = 0; updateBadge('badge-objects', 0); }

  // Lazy-load data for specific pages
  const loaders = {
    watchlist: loadWatchlist,
    workers: loadWorkers,
    users: loadUsers,
    system: loadSystem,
    analytics: loadAnalytics,
    cameras: loadCameras,
    map: loadMap,
    'alert-rules': () => { loadRules(); if (!State.cameras.length) loadCameras(); },
    audit: loadAuditLog,
    'stop-requests': loadStopRequests,
    'admin-mgmt': loadAdminMgmt,
    'super-dashboard': loadSuperDashboard,
    'node-monitor': loadNodeMonitor,
    'super-analysis': loadSuperAnalysis,
    'preview-system': loadPreviewSystem,
    'business-report': initBusinessReport,
  };
  if (loaders[id]) loaders[id]();

  // Live monitoring pages
  if (id === 'live-feed' || id === 'overview') {
    startLiveMonitoring();
  } else {
    stopLiveMonitoring();
  }
}
