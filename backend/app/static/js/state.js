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

  // Save to localStorage
  persist() {
    localStorage.setItem('sx_token', this.token || '');
    localStorage.setItem('sx_user', this.me || '');
    localStorage.setItem('sx_role', this.role || '');
  },

  clear() {
    this.token = null;
    this.me = null;
    this.role = null;
    ['sx_token','sx_user','sx_role'].forEach(k => localStorage.removeItem(k));
  }
};

// Clean up null/undefined strings from storage
if (State.token === 'null' || State.token === 'undefined' || !State.token) State.token = null;
if (State.me === 'null' || State.me === 'undefined' || !State.me) State.me = null;
if (State.role === 'null' || State.role === 'undefined' || !State.role) State.role = null;

/* Page titles map */
const PAGE_META = {
  overview:       ['OPERATIONAL OVERVIEW', '// REAL-TIME SYSTEM INTELLIGENCE'],
  'live-feed':    ['MESH LIVE MONITOR',    '// DIRECT NEURAL LINK TO NODES'],
  sightings:      ['SIGHTING HISTORY',     '// BIOMETRIC ACTIVITY LOG'],
  objects:        ['OBJECT RECOGNITION',    '// CLASSIFIED DETECTION FEED'],
  analytics:      ['TACTICAL ANALYTICS',   '// TRENDS & PERFORMANCE METRICS'],
  watchlist:      ['WATCHLIST AUDIT',      '// HIGH-VALUE TARGET REGISTRY'],
  search:         ['BIOMETRIC LOOKUP',     '// REVERSE FACE IDENTIFICATION'],
  analysis:       ['FRAME ANALYSIS',       '// COGNITIVE INFERENCE ENGINE'],
  cameras:        ['NODE TOPOLOGY',        '// FIELD SENSORS & CAMERAS'],
  map:            ['LIVE MAP',             '// CAMERA POSITIONS & STATUS'],
  'alert-rules':  ['ALERT RULES ENGINE',   '// AUTOMATED DETECTION TRIGGERS'],
  workers:        ['WORKER NODES',         '// ACTIVE FIELD INTEL NODES'],
  users:          ['OPERATOR ACCOUNTS',    '// USER ACCESS REGISTRY'],
  system:         ['SYSTEM CONTROL',       '// CONFIGURATION & MAINTENANCE'],
  audit:          ['AUDIT LOG',            '// SYSTEM ACTIVITY TRAIL'],
  'stop-requests':['STOP REQUESTS',        '// WORKER CAMERA SHUTDOWN APPROVALS'],
  settings:       ['SYSTEM CONFIG',       '// CLIENT PERMISSIONS & ACCESS']
};
