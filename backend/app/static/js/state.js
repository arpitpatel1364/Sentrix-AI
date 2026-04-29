/* ══════════════════════════════════════════
   STATE — Global Application State
   ══════════════════════════════════════════ */

const State = {
  // Auth
  token: localStorage.getItem('sx_token'),
  me: localStorage.getItem('sx_user'),
  role: localStorage.getItem('sx_role'),

  // API base URL
  api: (() => {
    if (window.location.port === '8000') return '';
    return 'http://localhost:8000';
  })(),

  // UI
  activePage: 'overview',
  alertCount: 0,
  newSightings: 0,
  newObjects: 0,
  alertFilter: 'matches',

  // Live monitoring
  liveInterval: null,
  mmActive: false,
  mmInterval: null,
  sseConn: null,

  // Data caches
  cameras: [],
  rules: [],
  dossierPersonId: null,
  activeAlerts: {},    // { personId: { id, name, location, node, lastSeen, snapshot, inVision } }

  // ROI
  roi: {
    cid: null,
    box: { x1: 0.03, y1: 0.03, x2: 0.97, y2: 0.97 },
    dragging: false,
    mode: null,
    start: { x: 0, y: 0, b: {} }
  },

  // Map
  mapEditMode: false,
  floorplanImg: null,
  mapCameras: [],
  dragCam: null,

  // Biometric purge
  biometricMatches: [],

  // Audit
  auditOffset: 0,
  auditLimit: 50,

  // Background tasks
  bgIntervals: [],

  persist() {
    localStorage.setItem('sx_token', this.token || '');
    localStorage.setItem('sx_user', this.me || '');
    localStorage.setItem('sx_role', this.role || '');
  },

  clear() {
    // Stop all background polling
    this.bgIntervals.forEach(clearInterval);
    this.bgIntervals = [];

    this.token = null;
    this.me = null;
    this.role = null;
    ['sx_token', 'sx_user', 'sx_role'].forEach(k => localStorage.removeItem(k));
    // Clear impersonation data
    ['sx_orig_token', 'sx_orig_user', 'sx_orig_role'].forEach(k => sessionStorage.removeItem(k));
    // Reset CSS states
    document.body.removeAttribute('data-role');
    document.body.removeAttribute('data-impersonating');
  }
};

// Clean up null/undefined strings from storage
if (State.token === 'null' || State.token === 'undefined' || !State.token) State.token = null;
if (State.me === 'null' || State.me === 'undefined' || !State.me) State.me = null;
if (State.role === 'null' || State.role === 'undefined' || !State.role) State.role = null;

/* Page titles map */
const PAGE_META = {
  overview: ['OVERVIEW', '// TACTICAL INTELLIGENCE DASHBOARD'],
  'live-feed': ['LIVE MONITOR', '// DIRECT NEURAL LINK TO CAMERA NODES'],
  sightings: ['FACE SIGHTINGS', '// BIOMETRIC ACTIVITY LOG'],
  objects: ['OBJECT DETECTIONS', '// AUTOMATED ITEM RECOGNITION LOG'],
  analytics: ['ANALYTICS', '// DETECTION TRENDS & METRICS'],
  watchlist: ['INTELLIGENCE ARCHIVE', '// SUBJECT REGISTRY'],
  search: ['BIOMETRIC LOOKUP', '// REVERSE FACE IDENTIFICATION'],
  analysis: ['FRAME ANALYSIS', '// COGNITIVE INFERENCE ENGINE'],
  cameras: ['CAMERA MANAGEMENT', '// REGISTER & CONFIGURE NODES'],
  map: ['LIVE MAP', '// CAMERA POSITIONS & STATUS'],
  'alert-rules': ['ALERT RULES ENGINE', '// AUTOMATED DETECTION TRIGGERS'],
  workers: ['WORKER NODES', '// ACTIVE FIELD INTELLIGENCE NODES'],
  users: ['OPERATOR MANAGEMENT', '// MANAGE SYSTEM ACCOUNTS & ACCESS'],
  system: ['SYSTEM CONTROL', '// CONFIGURATION & MAINTENANCE'],
  audit: ['AUDIT LOG', '// SYSTEM ACTIVITY TRAIL'],
  'stop-requests': ['STOP REQUESTS', '// WORKER CAMERA SHUTDOWN APPROVALS'],
  'admin-mgmt': ['OPERATOR MANAGEMENT', '// MASTER SYSTEM OVERRIDE & HIERARCHY'],
  'super-dashboard': ['MASTER DASHBOARD', '// GLOBAL SYSTEM OVERSIGHT'],
  'node-monitor': ['GLOBAL NODE MAP', '// REAL-TIME TENANT WORKER STATUS'],
  'super-analysis': ['SYSTEM ANALYSIS', '// DEEP SEARCH & AUDIT LOG TRENDS'],
  'preview-system': ['PREVIEW SYSTEM', '// DIRECT ACCESS TO ADMIN PERSPECTIVES'],
  'business-report': ['BUSINESS INTELLIGENCE', '// STRATEGIC METRICS & REVENUE CALCULATOR'],
};
