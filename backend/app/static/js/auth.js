/**
 * Auth guard — include this script on EVERY page.
 * Handles: token storage, expiry, role routing, permission checking.
 */

const Auth = {

  // Store JWT in sessionStorage (clears on tab close — more secure than localStorage)
  setToken(token) {
    localStorage.setItem('sentrix_jwt', token);
  },

  getToken() {
    return localStorage.getItem('sentrix_jwt');
  },

  clearToken() {
    localStorage.removeItem('sentrix_jwt');
  },

  // Decode JWT payload (no signature verification — server handles that)
  getPayload() {
    const token = this.getToken();
    if (!token) return null;
    try {
      const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      return JSON.parse(atob(base64));
    } catch { return null; }
  },

  isExpired() {
    const payload = this.getPayload();
    if (!payload) return true;
    return payload.exp * 1000 < Date.now();
  },

  getRole() {
    return this.getPayload()?.role;
  },

  getClientId() {
    return this.getPayload()?.client_id;
  },

  getPermissions() {
    const payload = this.getPayload();
    return payload?.permissions || {};
  },

  getRoleLabel() {
    const payload = this.getPayload();
    return payload?.permissions?.role_label || 'Client';
  },

  // Check a single permission key
  can(permission) {
    if (this.getRole() === 'admin') return true;
    return this.getPermissions()[permission] === true;
  },

  // Call on every protected page load
  guard(requiredRole = null) {
    if (!this.getToken() || this.isExpired()) {
      this.clearToken();
      window.location.href = '/login';
      return false;
    }
    const role = this.getRole();
    if (requiredRole && role !== requiredRole) {
      window.location.href = role === 'admin' ? '/admin' : '/dashboard';
      return false;
    }
    return true;
  },

  // Build Authorization header for fetch calls
  headers() {
    return {
      'Authorization': `Bearer ${this.getToken()}`,
      'Content-Type': 'application/json'
    };
  },

  logout() {
    this.clearToken();
    window.location.href = '/login';
  }
};
