/* ═══════════════════════════════════════════════════════════════════════════
   DropOS — core: API, auth, router, shell, shared UI helpers
   Loaded first; page files (home.js, review.js, …) register renderers.
   ═══════════════════════════════════════════════════════════════════════════ */

// The backend serves this SPA, so the API is always same-origin. The only
// exception is opening index.html straight from disk (file://).
const API = window.location.protocol === 'file:' ? 'http://localhost:8000/api' : window.location.origin + '/api';
const APP_VERSION = 'v12';

// ── Utilities ───────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function safeUrl(u) {
  try { const p = new URL(u, window.location.origin); return (p.protocol === 'https:' || p.protocol === 'http:') ? u : '#'; }
  catch { return '#'; }
}
function imageUrl(src) {
  if (!src) return '';
  if (src.startsWith('/')) return src;
  return `/api/image?url=${encodeURIComponent(src)}`;
}
function firstImage(p = {}) {
  const candidates = [p.images, p.image_urls, p.image_url, p.photo_link, p.raw_data?.images, p.raw_data?.image_url];
  for (const value of candidates) {
    if (Array.isArray(value)) { const found = value.find(Boolean); if (found) return String(found); }
    else if (typeof value === 'string' && value.trim()) {
      const t = value.trim();
      if (t.startsWith('[')) { try { const parsed = JSON.parse(t); const f = Array.isArray(parsed) ? parsed.find(Boolean) : ''; if (f) return String(f); } catch(e) {} }
      return t;
    }
  }
  return '';
}
function fmtDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  catch(e) { return iso; }
}
function relTime(iso) {
  if (!iso) return '';
  const d = new Date(iso); const diff = (Date.now() - d.getTime()) / 1000;
  if (isNaN(diff)) return '';
  if (diff < 45) return 'just now';
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  if (diff < 86400 * 7) return `${Math.round(diff / 86400)}d ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
function untilTime(iso) {
  if (!iso) return '';
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  if (isNaN(diff)) return '';
  if (diff <= 0) return 'now';
  if (diff < 3600) return `in ${Math.max(1, Math.round(diff / 60))}m`;
  if (diff < 86400) return `in ${Math.round(diff / 3600)}h`;
  return `in ${Math.round(diff / 86400)}d`;
}
function money(v) { return `₾${Number(v || 0).toFixed(2).replace(/\.00$/, '')}`; }
function pct(v) { return `${Number(v || 0).toFixed(0)}%`; }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// ── Icons ───────────────────────────────────────────────────────────────────
const _svg = (d, extra = '') => `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" ${extra}>${d}</svg>`;
const IC = {
  home:      _svg('<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v10h14V10"/>'),
  review:    _svg('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m8 12 3 3 5-6"/>'),
  posts:     _svg('<path d="M22 2 11 13"/><path d="m22 2-7 20-4-9-9-4 20-7z"/>'),
  inbox:     _svg('<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.8 1.1z"/>'),
  brands:    _svg('<path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>'),
  scans:     _svg('<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>'),
  analytics: _svg('<path d="M18 20V10M12 20V4M6 20v-6"/>'),
  assistant: _svg('<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'),
  settings:  _svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  check:     `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  bolt:      _svg('<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>'),
  spark:     _svg('<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>'),
  // stage icons
  st_scan:   _svg('<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>'),
  st_score:  _svg('<path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.9L12 16.4 6.8 19.2l1-5.9L3.5 9.2l5.9-.9z"/>'),
  st_approve:_svg('<path d="m4 12 5 5L20 6"/>'),
  st_clean:  _svg('<path d="M15 3 5 13l-1 5 5-1L19 7z"/><path d="m14 4 6 6"/>'),
  st_post:   _svg('<path d="M22 2 11 13"/><path d="m22 2-7 20-4-9-9-4 20-7z"/>'),
  st_reply:  _svg('<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.6 8.6 0 0 1-3.8-.9L3 21l2-4.8A8.4 8.4 0 1 1 21 11.5z"/>'),
  warn:      _svg('<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>'),
  x:         _svg('<path d="M18 6 6 18M6 6l12 12"/>'),
  ext:       _svg('<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6M10 14 21 3"/>'),
};

// ── State ───────────────────────────────────────────────────────────────────
let currentPage = 'home';
let currentTab  = null;
let stats = {};
let settingsData = {};
let autopilotData = null;
let selectedProducts = new Set();
let activeJobPoll = null;
let _isLoggedOut = false;

// state used by ported page code
let queueProducts = [], queueTotal = 0, queueSort = 'score';
let approvedProducts = [], approvedTotal = 0;
let textEditProducts = [], textEditTotal = 0;
let rejectedProducts = [], rejectedTotal = 0;
let scanKeywords = [];
let scanSource   = '1688';
let activeJob = null;
let rejectTargetId = null;
let catalogProducts = [], catalogTotal = 0, catalogStage = 'all', catalogSearch = '', catalogPage = 0;
let pipelineJobs = [], pipelineJobId = null, pipelineActiveStage = null, pipelineData = null;
let analyticsTab = 'overview';
let brandsCache = [];          // light list for filters/selectors
let brandFilter = null;        // product-list filter (null = all brands)
let scanBrandId = null;        // brand the New scan form targets

async function loadBrandsCache(force = false) {
  if (brandsCache.length && !force) return brandsCache;
  try { brandsCache = (await api('/brands')).brands || []; } catch(e) { brandsCache = []; }
  return brandsCache;
}
function brandName(id) { return brandsCache.find(b => b.id === id)?.name || `#${id}`; }
function brandFilterChips(onchange) {
  if (brandsCache.length < 2) return '';
  const chip = (id, label) => `<button class="fchip ${brandFilter === id ? 'active' : ''}" onclick="brandFilter=${id === null ? 'null' : id};${onchange}">${escHtml(label)}</button>`;
  return `<span class="muted" style="margin:0 2px">·</span>` + chip(null, 'All brands') + brandsCache.map(b => chip(b.id, b.name)).join('');
}

// ── Toast / modal ────────────────────────────────────────────────────────────
function toast(msg, type = 'success', ms = 3200) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 250); }, ms);
}
function apiErrorMessage(text, status) {
  if (!text) return `HTTP ${status}`;
  try {
    const parsed = JSON.parse(text);
    const detail = parsed.detail ?? parsed.message ?? parsed.error;
    if (typeof detail === 'string') return detail;
    if (detail?.message) return detail.message;
    if (Array.isArray(detail)) return detail.map(item => item.msg || item.message || String(item)).join(', ');
  } catch(e) {}
  return text;
}

// ── API ──────────────────────────────────────────────────────────────────────
const _cache = {};
const CACHE_TTL = { stats: 30000, products: 60000, analytics: 45000, default: 30000 };
function _cacheTtl(path) {
  if (path.includes('/stats')) return CACHE_TTL.stats;
  if (path.includes('/products')) return CACHE_TTL.products;
  if (path.includes('/analytics')) return CACHE_TTL.analytics;
  return CACHE_TTL.default;
}
function _cacheGet(path) { const e = _cache[path]; if (!e) return null; if (Date.now() - e.ts > _cacheTtl(path)) { delete _cache[path]; return null; } return e.data; }
function _cacheSet(path, data) { _cache[path] = { ts: Date.now(), data }; }
function _cacheInvalidate(...patterns) { for (const pat of patterns) Object.keys(_cache).forEach(k => { if (k.includes(pat)) delete _cache[k]; }); }
async function cachedApi(path) { const hit = _cacheGet(path); if (hit !== null) return hit; const data = await api(path); _cacheSet(path, data); return data; }

const TOKEN_KEY = 'dropos_admin_token';
function getToken() { return localStorage.getItem(TOKEN_KEY); }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

async function api(path, method = 'GET', body = null) {
  const headers = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const opts = { method, headers };
  if (body !== null) opts.body = JSON.stringify(body);
  try {
    const r = await fetch(API + path, opts);
    if (r.status === 401) {
      clearToken();
      if (path !== '/auth/login' && !_isLoggedOut) { _isLoggedOut = true; currentPage = 'login'; renderPage(); }
      throw new Error('Unauthorized');
    }
    if (!r.ok) { const text = await r.text().catch(() => r.statusText); throw new Error(apiErrorMessage(text, r.status)); }
    return r.json();
  } catch(e) {
    if (e.message !== 'Unauthorized' && !_isLoggedOut) toast(e.message || 'API error', 'error');
    throw e;
  }
}

async function refreshStats() {
  try { stats = await api('/stats'); } catch(e) { return; }
  try { autopilotData = await api('/autopilot'); } catch(e) {}
  renderSidebar();
}

// ── Pages & router ───────────────────────────────────────────────────────────
// Each page: id, label, icon, tabs (optional), render(tab). Page files add
// themselves with registerPage(). Order here = sidebar order.
const PAGES = [
  { id: 'home',      label: 'Home',      icon: 'home' },
  { id: 'review',    label: 'Review',    icon: 'review',    tabs: [['queue','Needs decision'],['textEdit','Text edit'],['rejected','Rejected']] },
  { id: 'posts',     label: 'Posts',     icon: 'posts',     tabs: [['queue','Queue'],['posted','Posted'],['all','All products']] },
  { id: 'inbox',     label: 'Inbox',     icon: 'inbox' },
  { id: 'brands',    label: 'Brands',    icon: 'brands' },
  { id: 'scans',     label: 'Scans',     icon: 'scans',     tabs: [['new','New scan'],['history','History']] },
  { id: 'analytics', label: 'Analytics', icon: 'analytics', tabs: [['overview','Overview'],['margins','Margins'],['insights','Insights']] },
  { id: 'assistant', label: 'Assistant', icon: 'assistant' },
  { id: 'settings',  label: 'Settings',  icon: 'settings',  tabs: [['setup','Setup'],['connections','Connections'],['curation','Curation'],['automation','Automation'],['advanced','Advanced']] },
];
const PAGE_RENDERERS = {};   // id → async fn(tab)
function registerPage(id, fn) { PAGE_RENDERERS[id] = fn; }

// Legacy view ids used by ported code → (page, tab)
const VIEW_ALIASES = {
  dashboard: ['home'], tools: ['home'],
  queue: ['review','queue'], textEdit: ['review','textEdit'], REJECTED: ['review','rejected'],
  REVIEWED: ['posts','queue'], LIVE: ['posts','posted'], catalog: ['posts','all'],
  scan: ['scans','new'], scans: ['scans','history'], pipeline: ['scans','history'],
  chat: ['assistant'],
};
// Reverse: current (page,tab) → legacy view id (ported code checks curView())
function curView() {
  const t = currentTab;
  if (currentPage === 'review') return t === 'textEdit' ? 'textEdit' : t === 'rejected' ? 'REJECTED' : 'queue';
  if (currentPage === 'posts')  return t === 'posted' ? 'LIVE' : t === 'all' ? 'catalog' : 'REVIEWED';
  if (currentPage === 'scans')  return t === 'history' ? 'scans' : 'scan';
  if (currentPage === 'assistant') return 'chat';
  return currentPage;
}

function pageDef(id) { return PAGES.find(p => p.id === id); }

function navigate(page, tab = null) {
  if (typeof page === 'string' && page.includes(':')) { [page, tab] = page.split(':'); }
  if (VIEW_ALIASES[page]) { const [p, t] = VIEW_ALIASES[page]; page = p; tab = tab || t || null; }
  const def = pageDef(page);
  if (!def) { console.warn('unknown page', page); return; }
  if (def.tabs && !tab) tab = def.tabs[0][0];
  if (def.tabs && !def.tabs.some(([id]) => id === tab)) tab = def.tabs[0][0];
  currentPage = page; currentTab = def.tabs ? tab : null;
  selectedProducts.clear();
  document.getElementById('selection-bar')?.remove();
  closeDetail();
  try { history.replaceState(null, '', `#${page}${currentTab ? '/' + currentTab : ''}`); } catch(e) {}
  renderSidebar();
  renderPage();
}
function switchTab(tab) { navigate(currentPage, tab); }

function setTitle(t, sub = '') {
  const el = document.getElementById('page-title'); if (el) el.textContent = t;
  const s = document.getElementById('page-sub'); if (s) s.textContent = sub || '';
}
function setActions(html) { const el = document.getElementById('topbar-actions'); if (el) el.innerHTML = html || ''; }

function tabBar(pageId) {
  const def = pageDef(pageId); if (!def?.tabs) return '';
  const counts = tabCounts(pageId);
  return `<div class="tabs">${def.tabs.map(([id, label]) => {
    const n = counts[id];
    return `<button class="tab ${id === currentTab ? 'active' : ''}" onclick="switchTab('${id}')">${escHtml(label)}${n ? `<span class="tab-n">${n}</span>` : ''}</button>`;
  }).join('')}</div>`;
}
function tabCounts(pageId) {
  if (pageId === 'review') return { queue: stats.ENRICHED, textEdit: stats.TEXT_REMOVAL, rejected: stats.REJECTED };
  if (pageId === 'posts')  return { queue: stats.REVIEWED, posted: stats.LIVE };
  return {};
}

async function renderPage() {
  const content = document.getElementById('content');
  if (currentPage === 'login') { document.body.classList.add('is-login'); await renderLogin(); return; }
  document.body.classList.remove('is-login');
  const fn = PAGE_RENDERERS[currentPage];
  if (!fn) { content.innerHTML = `<div class="empty"><h3>Page not found</h3></div>`; return; }
  content.classList.remove('fade'); void content.offsetWidth; content.classList.add('fade');
  try { await fn(currentTab); }
  catch(e) {
    console.error(e);
    content.innerHTML = `<div class="empty"><span class="empty-icon">!</span><h3>Something went wrong</h3><p style="font-family:var(--ff-m)">${escHtml(e.message || e)}</p></div>`;
  }
}

// ── Shell ────────────────────────────────────────────────────────────────────
function renderSidebar() {
  const nav = document.getElementById('nav'); if (!nav) return;
  const counts = {
    review: (stats.ENRICHED || 0) + (stats.TEXT_REMOVAL || 0),
    posts:  stats.REVIEWED || 0,
    inbox:  autopilotData?.inbox?.open || 0,
  };
  nav.innerHTML = PAGES.map(p => `
    <button class="nav-item ${p.id === currentPage ? 'active' : ''}" onclick="navigate('${p.id}')" title="${escHtml(p.label)}">
      ${IC[p.icon] || ''}<span class="lbl">${escHtml(p.label)}</span>
      ${counts[p.id] ? `<span class="nav-n ${p.id === 'inbox' && autopilotData?.inbox?.leads ? 'hot' : ''}">${counts[p.id]}</span>` : ''}
    </button>`).join('');

  const ap = document.getElementById('sidebar-autopilot');
  if (ap) {
    const on = !!autopilotData?.enabled;
    const needs = (autopilotData?.needs_you || []).reduce((s, n) => s + (n.count || 0), 0);
    const activeStages = (autopilotData?.stages || []).filter(s => s.active).length;
    ap.innerHTML = `
      <button class="ap-pill ${on ? 'on' : 'off'}" onclick="navigate('home')" title="Autopilot">
        <span class="ap-dot"></span>
        <span class="ap-txt">${on ? `Autopilot on · ${activeStages}/6` : 'Autopilot off'}</span>
      </button>
      ${needs ? `<button class="ap-needs" onclick="navigate('home')">${needs} need${needs === 1 ? 's' : ''} you</button>` : ''}`;
  }
  const scanDot = document.getElementById('status-dot'); const scanLbl = document.getElementById('status-label');
  if (scanDot && scanLbl) {
    const scanning = !!(autopilotData?.stages || []).find(s => s.key === 'scan' && s.running) || !!activeJob;
    scanDot.className = 'status-dot' + (scanning ? ' on' : ''); scanLbl.textContent = scanning ? 'Scanning…' : 'Idle';
  }
}

// ── Login / first-run setup ──────────────────────────────────────────────────
async function renderLogin() {
  const el = document.getElementById('content');
  let needsSetup = false;
  try { const st = await fetch(API + '/auth/status').then(r => r.ok ? r.json() : null); needsSetup = !!(st && st.needs_setup); } catch(e) {}
  el.innerHTML = `
    <div class="login-container">
      <div class="login-box">
        <div class="login-logo">D</div>
        <h2>${needsSetup ? 'Welcome to DropOS' : 'DropOS'}</h2>
        <p class="login-sub">${needsSetup ? 'Create the admin account for this installation — you will sign in with it from now on.' : 'Sign in to your backoffice'}</p>
        <form id="login-form" onsubmit="${needsSetup ? 'handleSetup(event)' : 'handleLogin(event)'}">
          <div class="input-group"><label>Email</label><input type="email" id="login-email" required autocomplete="username"/></div>
          <div class="input-group"><label>Password${needsSetup ? ' <span class="muted">(min 8 characters)</span>' : ''}</label><input type="password" id="login-password" required ${needsSetup ? 'minlength="8" autocomplete="new-password"' : 'autocomplete="current-password"'}/></div>
          <div id="login-error" class="login-error" style="display:none"></div>
          <button type="submit" class="btn btn-primary login-btn" id="login-btn">${needsSetup ? 'Create account' : 'Sign in'}</button>
        </form>
      </div>
    </div>`;
}
function _loginError(msg) {
  const b = document.getElementById('login-btn'); const e = document.getElementById('login-error');
  if (b) { b.disabled = false; b.textContent = b.textContent.replace(/…$/, '') || 'Sign in'; }
  if (e) { e.textContent = msg; e.style.display = 'block'; }
}
async function handleLogin(ev) {
  ev.preventDefault();
  const btn = document.getElementById('login-btn'); if (btn) { btn.textContent = 'Signing in…'; btn.disabled = true; }
  const email = (document.getElementById('login-email')?.value || '').trim();
  const password = document.getElementById('login-password')?.value || '';
  try {
    const data = await api('/auth/login', 'POST', { email, password });
    if (!data?.token) { _loginError('Server error: no token returned.'); return; }
    setToken(data.token);
    if (!(await bootApp())) _loginError('Authenticated but the session failed to load. Please try again.');
  } catch(err) {
    _loginError(err.message === 'Unauthorized' ? 'Invalid email or password.' : (err.message || 'Login failed.'));
    if (btn) btn.textContent = 'Sign in';
  }
}
async function handleSetup(ev) {
  ev.preventDefault();
  const btn = document.getElementById('login-btn'); if (btn) { btn.textContent = 'Creating…'; btn.disabled = true; }
  const email = (document.getElementById('login-email')?.value || '').trim();
  const password = document.getElementById('login-password')?.value || '';
  try {
    const r = await fetch(API + '/auth/setup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
    const text = await r.text();
    if (!r.ok) { _loginError(apiErrorMessage(text, r.status)); if (btn) btn.textContent = 'Create account'; return; }
    setToken(JSON.parse(text).token);
    toast('Admin account created — welcome!', 'success');
    if (!(await bootApp())) _loginError('Account created but the session failed to load. Please sign in.');
  } catch(err) { _loginError(err.message || 'Setup failed.'); if (btn) btn.textContent = 'Create account'; }
}
function logout() { clearToken(); _isLoggedOut = true; currentPage = 'login'; renderPage(); }

// ── Boot ─────────────────────────────────────────────────────────────────────
function _startPageFromHash() {
  const h = (location.hash || '').replace(/^#/, '');
  if (!h) return ['home', null];
  const [p, t] = h.split('/');
  return pageDef(p) ? [p, t || null] : ['home', null];
}
async function bootApp() {
  if (!getToken()) { currentPage = 'login'; await renderPage(); return false; }
  try { stats = await api('/stats'); } catch(e) { clearToken(); currentPage = 'login'; await renderPage(); return false; }
  _isLoggedOut = false;
  document.body.classList.remove('is-login');
  try { settingsData = await api('/settings'); scanSource = String(settingsData.cssbuy_source || '1688'); scanKeywords = [...(settingsData.scan_keywords || [])]; } catch(e) {}
  try { autopilotData = await api('/autopilot'); } catch(e) {}
  const [p, t] = _startPageFromHash();
  navigate(p, t);
  if (!window._statsTimer) window._statsTimer = setInterval(() => { if (currentPage !== 'login') refreshStats(); }, 20000);
  return true;
}

// ── Global keyboard shortcuts (product grids) ───────────────────────────────
let activeRowIndex = 0;
let hotkeysEnabled = true;
function applyActiveRow() {
  document.querySelectorAll('.product-card').forEach(el => el.classList.remove('active-row'));
  const cards = document.querySelectorAll('.product-card');
  if (cards.length > 0 && activeRowIndex >= 0 && activeRowIndex < cards.length) {
    const target = cards[activeRowIndex];
    target.classList.add('active-row');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}
document.addEventListener('keydown', (e) => {
  if (!hotkeysEnabled) return;
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || document.activeElement?.isContentEditable) return;
  if (e.key === 'Escape') { closeDetail(); closeRejectModal(); return; }
  if (e.key === '?') { toast('Hotkeys: j/k move · a approve · r reject · Enter open · Esc close', 'info', 5000); return; }
  const cards = document.querySelectorAll('.product-card');
  if (!cards.length) return;
  const view = curView();
  if (e.key === 'j' || e.key === 'ArrowDown') { activeRowIndex = Math.min(activeRowIndex + 1, cards.length - 1); applyActiveRow(); e.preventDefault(); }
  else if (e.key === 'k' || e.key === 'ArrowUp') { activeRowIndex = Math.max(activeRowIndex - 1, 0); applyActiveRow(); e.preventDefault(); }
  else if (e.key === 'Enter') { const m = cards[activeRowIndex]?.id.match(/card-(\d+)/); if (m) showDetail(parseInt(m[1])); }
  else if (e.key === 'a' || e.key === 'A' || e.key === 'r' || e.key === 'R') {
    if (!['queue', 'textEdit', 'REVIEWED'].includes(view)) return;
    const target = cards[activeRowIndex]; const m = target && target.id.match(/card-(\d+)/); if (!m) return;
    const pid = parseInt(m[1]); const approve = e.key === 'a' || e.key === 'A';
    if (approve && view === 'REVIEWED') { quickPost(pid); return; }
    api('/products/bulk-status', 'POST', { product_ids: [pid], stage: approve ? 'REVIEWED' : 'REJECTED' }).then(res => {
      if (res.skipped?.length) { toast('Nothing changed', 'error'); return; }
      toast(approve ? 'Approved' : 'Rejected', 'success');
      [queueProducts, textEditProducts, approvedProducts].forEach(list => { const i = list.findIndex(p => p.id === pid); if (i >= 0) list.splice(i, 1); });
      selectedProducts.delete(pid); target.remove();
      activeRowIndex = Math.min(activeRowIndex, Math.max(0, document.querySelectorAll('.product-card').length - 1));
      applyActiveRow(); refreshStats();
    }).catch(() => {});
  }
});

// ── Shared small components ──────────────────────────────────────────────────
function emptyState(icon, title, text, actionHtml = '') {
  return `<div class="empty"><span class="empty-icon">${icon}</span><h3>${escHtml(title)}</h3>${text ? `<p>${text}</p>` : ''}${actionHtml}</div>`;
}
function loadingState(text = 'Loading…') { return `<div class="loading">${escHtml(text)}</div>`; }
function toggleHtml(id, on, onchange, small = false) {
  return `<label class="switch ${small ? 'sm' : ''}"><input type="checkbox" id="${id}" ${on ? 'checked' : ''} onchange="${onchange}"/><span class="slider"></span></label>`;
}
