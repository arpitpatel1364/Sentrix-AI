/* ══════════════════════════════════════════
   NAVIGATION — Page Routing
   ══════════════════════════════════════════ */

function showPage(id, navEl) {
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
  if (id === 'objects')   { State.newObjects   = 0; updateBadge('badge-objects',   0); }

  // Lazy-load data for specific pages
  const loaders = {
    watchlist:       'loadWatchlist',
    workers:         'loadWorkers',
    users:           'loadUsers',
    system:          'loadSystem',
    analytics:       'loadAnalytics',
    cameras:         'loadCameras',
    map:             'loadMap',
    'alert-rules':   () => { if (typeof loadRules === 'function') loadRules(); if (!State.cameras.length && typeof loadCameras === 'function') loadCameras(); },
    audit:           'loadAuditLog',
    'stop-requests': 'loadStopRequests',
  };

  const loader = loaders[id];
  if (typeof loader === 'function') {
    loader();
  } else if (typeof loader === 'string' && typeof window[loader] === 'function') {
    window[loader]();
  }

  // Live monitoring pages
  if (id === 'live-feed' || id === 'overview') {
    startLiveMonitoring();
  } else {
    stopLiveMonitoring();
  }
}
