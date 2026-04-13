/* ══════════════════════════════════════════
   AUTH — Login, Logout, Session
   ══════════════════════════════════════════ */

async function doLogin() {
  const u = document.getElementById('li-user').value.trim();
  const p = document.getElementById('li-pass').value;
  const btn = document.getElementById('login-btn');
  const err = document.getElementById('login-err');

  if (!u || !p) {
    err.style.display = 'block';
    err.textContent = '⚠ Please enter your credentials';
    return;
  }

  btn.textContent = 'AUTHENTICATING…';
  btn.disabled = true;
  err.style.display = 'none';

  try {
    const res = await fetch(`${State.api}/api/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p }),
    });
    const data = await res.json();

    if (!res.ok) throw new Error(data.detail || 'Authentication failed');

    State.token = data.token;
    State.me = data.username;
    State.role = data.role;
    State.persist();

    applyAuthUI();
    bootstrap();
    toast(`Welcome back, ${State.me}`, 'cyan');

  } catch (e) {
    const box = document.querySelector('.login-box');
    box.classList.remove('shake');
    void box.offsetWidth; // reflow
    box.classList.add('shake');
    err.style.display = 'block';
    err.innerHTML = `<strong>ACCESS DENIED</strong> — ${esc(e.message).toUpperCase()}`;
  } finally {
    btn.textContent = '▶ AUTHENTICATE';
    btn.disabled = false;
  }
}

function applyAuthUI() {
  if (!State.me || !State.role) return;
  document.getElementById('user-name').textContent = State.me;
  document.getElementById('user-role-label').textContent = State.role.toUpperCase();
  document.getElementById('user-av').textContent = (State.me[0] || '?').toUpperCase();

  // Show/hide admin-only elements
  document.querySelectorAll('.admin-only').forEach(el => {
    el.style.display = State.role === 'admin' ? '' : 'none';
  });

  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('app').style.display = 'block';
}

function doLogout() {
  // Close SSE
  if (State.sseConn) { State.sseConn.close(); State.sseConn = null; }
  // Stop live monitoring
  stopLiveMonitoring();

  State.clear();
  document.getElementById('app').style.display = 'none';
  document.getElementById('login-screen').style.display = 'flex';
  // Reset UI
  document.getElementById('li-user').value = '';
  document.getElementById('li-pass').value = '';
}
