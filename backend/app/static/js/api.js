/* ══════════════════════════════════════════
   API — Fetch Helpers
   ══════════════════════════════════════════ */

/**
 * Main API wrapper. Handles auth, JSON, errors.
 * @param {string} path - Endpoint path (e.g. '/api/stats')
 * @param {RequestInit} opts - Fetch options
 * @returns {Promise<any>} Parsed JSON response
 */
async function api(path, opts = {}) {
  const headers = {
    'Authorization': `Bearer ${State.token}`,
    ...opts.headers,
  };

  // Auto-set Content-Type for JSON body strings
  if (typeof opts.body === 'string' && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  try {
    const res = await fetch(`${State.api}${path}`, { ...opts, headers });

    if (res.status === 401) {
      if (State.token) {
        toast('Session expired — please log in again', 'red');
        doLogout();
      }
      throw new Error('Unauthorized');
    }

    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { const d = await res.json(); detail = d.detail || detail; } catch {}
      throw new Error(detail);
    }

    // Some endpoints return empty 204
    if (res.status === 204) return null;
    return res.json();

  } catch (err) {
    if (err.message.toLowerCase().includes('fetch') ||
        err.message.toLowerCase().includes('network') ||
        err.name === 'TypeError') {
      updateConnectionStatus(false);
    }
    throw err;
  }
}

/** Check if backend is reachable */
async function checkBackend() {
  try {
    const headers = State.token ? { 'Authorization': `Bearer ${State.token}` } : {};
    const res = await fetch(`${State.api}/api/system/stats`, { headers });
    updateConnectionStatus(res.ok || res.status === 401);
  } catch {
    updateConnectionStatus(false);
  }
}
