// The backend serves this SPA, so the API is always same-origin. The only
// exception is opening index.html straight from disk (file://), which has no
// origin — fall back to the default local backend port in that case.
const API = window.location.protocol === 'file:'
  ? 'http://localhost:8000/api'
  : window.location.origin + '/api';

function escHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function safeUrl(u) {
  try { const p = new URL(u); return (p.protocol === 'https:' || p.protocol === 'http:') ? u : '#'; }
  catch { return '#'; }
}

// ── Icons (SVG strings) ────────────────────────────────────────────────────
const IC = {
  dashboard: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>`,
  scan: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>`,
  queue: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>`,
  approved: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  posted: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>`,
  rejected: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
  settings: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
  check: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  analytics: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>`,
  chat: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
  catalog: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 10h16M4 14h16M4 18h16"/></svg>`,
};

// ── State ──────────────────────────────────────────────────────────────────
let currentPage = 'queue';
let stats = {};
let selectedProducts = new Set();
let activeJobPoll = null;

let queueProducts = [], queueTotal = 0, queueSort = 'score';
let approvedProducts = [], approvedTotal = 0;
let textEditProducts = [], textEditTotal = 0;
let rejectedProducts = [], rejectedTotal = 0;
let scanKeywords = ['romantic gift'];
let scanSource   = 'taobao';
let activeJob = null;
let settingsData = {};
let rejectTargetId = null;
let catalogProducts = [], catalogTotal = 0, catalogStage = 'REVIEWED', catalogSearch = '', catalogPage = 0;

// ── Nav ────────────────────────────────────────────────────────────────────
const NAV_PAGES = [
  { id:'dashboard', label:'Today',        icon:'dashboard'},
  { id:'pipeline',  label:'Pipeline',     icon:'queue'    },
  { id:'analytics', label:'Analytics',    icon:'analytics'},
  { id:'settings',  label:'Settings',     icon:'settings' },
  { id:'chat',      label:'AI',           icon:'chat'     },
];

// Pages that live under the "Pipeline" nav entry and share the stage sub-nav
const PIPELINE_STAGE_PAGES = new Set(['queue','textEdit','REVIEWED','LIVE','REJECTED','catalog','scan','scans']);

function resetSelectionState() {
  selectedProducts.clear();
}

function resetCatalogState() {
  queueProducts = [];
  approvedProducts = [];
  textEditProducts = [];
}

function resetPipelineState() {
  pipelineJobs = [];
  pipelineJobId = null;
  pipelineActiveStage = null;
  pipelineData = null;
}

function buildNav() {
  const navEl = document.getElementById('nav');
  if (!navEl) return;
  let html = '';
  for (const p of NAV_PAGES) {
    const isActive = p.id === currentPage || (p.id === 'pipeline' && PIPELINE_STAGE_PAGES.has(currentPage));
    html += `
      <button class="nav-item${isActive ? ' active' : ''}" onclick="navigate('${p.id}')" title="${p.label}">
        ${IC[p.icon] || ''}
        <span class="lbl">${escHtml(p.label)}</span>
      </button>`;
  }
  navEl.innerHTML = html;
}

function navigate(page) {
  if (page === 'pipeline') page = 'queue';
  currentPage = page;
  resetSelectionState();
  resetCatalogState();
  resetPipelineState();
  buildNav();
  renderPage();
}

function imageUrl(src) {
  if (src && src.startsWith('/')) return src;
  return src ? `/api/image?url=${encodeURIComponent(src)}` : '';
}

function firstImage(p = {}) {
  const candidates = [p.images, p.image_urls, p.image_url, p.photo_link, p.raw_data?.images, p.raw_data?.image_url];
  for (const value of candidates) {
    if (Array.isArray(value)) {
      const found = value.find(Boolean);
      if (found) return String(found);
    } else if (typeof value === 'string' && value.trim()) {
      const trimmed = value.trim();
      if (trimmed.startsWith('[')) {
        try {
          const parsed = JSON.parse(trimmed);
          const found = Array.isArray(parsed) ? parsed.find(Boolean) : '';
          if (found) return String(found);
        } catch(e) {}
      }
      return trimmed;
    }
  }
  return '';
}

function setTitle(t, sub = '') {
  document.getElementById('page-title').textContent = t;
  document.getElementById('page-sub').textContent = sub ? '· ' + sub : '';
}

// ── Toast ──────────────────────────────────────────────────────────────────
function toast(msg, type = 'success', ms = 3200) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), ms);
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

// ── API ────────────────────────────────────────────────────────────────────
// ── Client-side cache ─────────────────────────────────────────────────────────
const _cache = {};
const CACHE_TTL = { stats: 30000, products: 60000, analytics: 45000, default: 30000 };

function _cacheKey(path) { return path; }
function _cacheTtl(path) {
  if (path.includes('/stats')) return CACHE_TTL.stats;
  if (path.includes('/products')) return CACHE_TTL.products;
  if (path.includes('/analytics')) return CACHE_TTL.analytics;
  return CACHE_TTL.default;
}
function _cacheGet(path) {
  const e = _cache[_cacheKey(path)];
  if (!e) return null;
  if (Date.now() - e.ts > _cacheTtl(path)) { delete _cache[_cacheKey(path)]; return null; }
  return e.data;
}
function _cacheSet(path, data) { _cache[_cacheKey(path)] = { ts: Date.now(), data }; }
function _cacheInvalidate(...patterns) {
  for (const pat of patterns)
    Object.keys(_cache).forEach(k => { if (k.includes(pat)) delete _cache[k]; });
}

async function cachedApi(path) {
  const hit = _cacheGet(path);
  if (hit !== null) return hit;
  const data = await api(path);
  _cacheSet(path, data);
  return data;
}

// ── Auth token (localStorage, no cookies) ─────────────────────────────────
const TOKEN_KEY = 'dropos_admin_token';
function getToken() { return localStorage.getItem(TOKEN_KEY); }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

let _isLoggedOut = false;

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
      if (path !== '/auth/login' && !_isLoggedOut) {
        _isLoggedOut = true;
        currentPage = 'login';
        renderPage();
      }
      throw new Error('Unauthorized');
    }
    if (!r.ok) {
      const text = await r.text().catch(() => r.statusText);
      throw new Error(apiErrorMessage(text, r.status));
    }
    return r.json();
  } catch(e) {
    if (e.message !== 'Unauthorized' && !_isLoggedOut) toast(e.message || 'API error', 'error');
    throw e;
  }
}

function refreshStats() {
  return api('/stats').then(s => { stats = s; buildNav(); }).catch(() => {});
}

// ── Dashboard ──────────────────────────────────────────────────────────────
async function renderDashboard() {
  setTitle('Today');
  document.getElementById('topbar-actions').innerHTML = '';
  document.getElementById('content').innerHTML = '<div style="color:var(--t3);font-size:12px;padding:40px 0;text-align:center">Loading…</div>';

  const [s, jobs] = await Promise.all([
    api('/stats').catch(() => ({})),
    api('/jobs?limit=5').catch(() => []),
  ]);
  stats = s; buildNav();

  const scraped     = jobs[0]?.scraped      ?? 0;
  const afterFilter = jobs[0]?.after_basic  ?? 0;
  const afterProfit = jobs[0]?.after_profit ?? 0;
  const afterDedup  = jobs[0]?.after_dedup  ?? 0;
  const afterAI     = jobs[0]?.after_ai     ?? 0;
  const maxVal = scraped || 1;

  const pipeStages = [
    { label: 'Scraped raw',      val: scraped,     color: '#606060' },
    { label: 'After filter',     val: afterFilter, color: 'var(--blue)' },
    { label: 'Margin threshold', val: afterProfit, color: 'var(--amber)' },
    { label: 'After dedup',      val: afterDedup,  color: '#a78bfa' },
    { label: 'AI passed',        val: afterAI,     color: 'var(--green)' },
  ];

  document.getElementById('content').innerHTML = `
    <div class="dash-stat-grid">
      <div class="dash-stat-card">
        <div class="dash-stat-label">Ready to review</div>
        <div class="dash-stat-val" style="color:var(--blue)">${s.ENRICHED ?? 0}</div>
        <div class="dash-stat-actions">
          <button class="dash-stat-btn" onclick="navigate('queue')">Review now</button>
          <button class="dash-stat-btn" onclick="navigate('scan')">Find products</button>
        </div>
      </div>
      <div class="dash-stat-card">
        <div class="dash-stat-label">Approved</div>
        <div class="dash-stat-val" style="color:var(--green)">${s.REVIEWED ?? 0}</div>
        <div class="dash-stat-actions">
          <button class="dash-stat-btn" onclick="navigate('REVIEWED')">Post next</button>
          <button class="dash-stat-btn" onclick="navigate('LIVE')">Posted: ${s.LIVE ?? 0}</button>
        </div>
      </div>
      <div class="dash-stat-card">
        <div class="dash-stat-label">Rejected</div>
        <div class="dash-stat-val" style="color:var(--t3)">${s.REJECTED ?? 0}</div>
        <div class="dash-stat-actions">
          <button class="dash-stat-btn" onclick="navigate('REJECTED')">View rejected</button>
          <button class="dash-stat-btn" style="cursor:default;opacity:.5">${s.approval_rate ?? 0}% approval</button>
        </div>
      </div>
    </div>

    <div class="stat-row">
      <div class="stat-card blue">
        <div class="stat-label">Avg margin (queue)</div>
        <div class="stat-val">${s.avg_margin_pending ?? 0}<span style="font-size:15px;font-weight:500">%</span></div>
      </div>
      <div class="stat-card purple">
        <div class="stat-label">Avg AI score</div>
        <div class="stat-val">${s.avg_score_pending ?? 0}</div>
      </div>
      <div class="stat-card green">
        <div class="stat-label">Posted 7 days</div>
        <div class="stat-val">${s.posted_7d ?? 0}</div>
      </div>
      <div class="stat-card amber">
        <div class="stat-label">Approval rate</div>
        <div class="stat-val">${s.approval_rate ?? 0}<span style="font-size:15px;font-weight:500">%</span></div>
      </div>
      <div class="stat-card gray">
        <div class="stat-label">Total scans</div>
        <div class="stat-val">${s.total_jobs ?? 0}</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div class="card">
        <div class="card-title">Recent scans</div>
        ${!jobs.length
          ? `<div class="empty" style="padding:24px 0"><span class="empty-icon">○</span><h3>No scans yet</h3></div>`
          : jobs.map(j => `
            <div class="job-row">
              <div class="job-dot ${j.status}"></div>
              <div style="flex:1;min-width:0">
                <div style="font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escHtml((j.keywords || []).join(', ') || '—')}</div>
                <div style="font-size:11px;color:var(--t3);font-family:var(--ff-m)">${j.status} · ${j.after_ai ?? 0} passed</div>
              </div>
              ${j.status !== 'done' && j.status !== 'queued'
                ? `<span style="font-size:11px;color:var(--t3);font-family:var(--ff-m)">${j.progress ?? 0}%</span>` : ''}
            </div>`).join('')}
        <div style="margin-top:14px;display:flex;gap:8px">
          <button class="btn btn-sm" onclick="navigate('scan')">New scan</button>
          ${(s.ENRICHED > 0) ? `<button class="btn btn-sm btn-green" onclick="navigate('queue')">Review ${s.ENRICHED} products</button>` : ''}
          ${(s.REVIEWED > 0) ? `<button class="btn btn-sm btn-amber" onclick="navigate('REVIEWED')">Post ${s.REVIEWED} approved</button>` : ''}
        </div>
      </div>

      <div class="card">
        <div class="card-title">Last scan pipeline</div>
        <div class="pipe-bar-chart">
          ${pipeStages.map(({ label, val, color }) => {
            const pct = maxVal > 0 ? Math.round((val / maxVal) * 100) : 0;
            return `
              <div class="pipe-bar-row">
                <span class="pipe-bar-label">${label}</span>
                <div class="pipe-bar-track">
                  <div class="pipe-bar-fill" style="width:${pct}%;background:${color}"></div>
                </div>
                <span class="pipe-bar-count">${val}</span>
                <span class="pipe-bar-pct">${pct}%</span>
              </div>`;
          }).join('')}
        </div>
      </div>
    </div>`;
}

// ── Scan ───────────────────────────────────────────────────────────────────
async function renderScan() {
  setTitle('Scan');
  document.getElementById('topbar-actions').innerHTML = '';
  try {
    settingsData = await api('/settings');
    scanSource = String(settingsData.cssbuy_source || scanSource || '1688');
  } catch (e) {}
  renderScanContent();
  if (activeJob && !activeJobPoll) activeJobPoll = setInterval(pollActiveJob, 2000);
}

function renderScanContent() {
  const localOnly = !!settingsData.local_scraping_only;
  document.getElementById('content').innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
      <div>
        <div class="card" style="margin-bottom:14px">
          <div class="card-title">Search keywords</div>
          <div style="display:flex;flex-wrap:wrap;gap:7px;margin-bottom:12px">
            ${scanKeywords.map((kw, i) => `
              <div class="keyword-tag">${kw}
                <button onclick="removeKeyword(${i})">×</button>
              </div>`).join('')}
          </div>
          <div style="display:flex;gap:8px">
            <input type="text" id="kw-input" placeholder="Add keyword…" style="flex:1" onkeydown="if(event.key==='Enter')addKeyword()"/>
            <button class="btn btn-sm" onclick="addKeyword()">Add</button>
          </div>
        </div>
        <div class="card">
          <div class="card-title">Scan settings</div>
          <div class="form-group">
            <label>Source platform</label>
            <select id="scan-source" onchange="scanSource=this.value">
              <option value="1688"   ${scanSource==='1688'   ? 'selected':''}>1688 — real sales data, ranked by orders</option>
              <option value="taobao" ${scanSource==='taobao' ? 'selected':''}>Taobao — broader catalog, no sales filter</option>
              <option value="both"   ${scanSource==='both'   ? 'selected':''}>Both — 1688 + Taobao combined</option>
            </select>
          </div>
          <div class="form-group">
            <label>Max products per keyword</label>
            <input type="number" id="max-per-kw" value="100" min="10" max="500"/>
          </div>
          <button id="scan-btn" class="btn btn-primary" style="width:100%" onclick="startScan()" ${activeJob || localOnly ? 'disabled' : ''}>
            ${localOnly ? 'Local upload enabled' : activeJob ? 'Scanning…' : 'Start scan'}
          </button>
          ${localOnly ? `<div class="card-sm" style="margin-top:12px">
            <div style="font-size:11px;color:var(--t3);line-height:1.6">
              Website scraping is disabled. Run <code>python backend/local_scrape_upload.py</code> on your PC to scrape locally and upload results here.
            </div>
          </div>` : ''}
        </div>
      </div>

      <div class="card">
        <div class="card-title" style="display:flex;align-items:center;gap:8px">
          Pipeline status
          ${activeJob ? `<span class="badge badge-amber">Running</span>` : ''}
        </div>
        ${activeJob ? renderJobProgress(activeJob) : `
          <div class="empty" style="padding:32px 0">
            <span class="empty-icon">○</span>
            <h3>No active job</h3>
            <p>${localOnly ? 'Local uploads will appear here while processing' : 'Start a scan to see pipeline progress'}</p>
          </div>`}
        <div style="margin-top:18px;border-top:1px solid var(--b1);padding-top:14px">
          <div style="font-size:10px;color:var(--t3);font-family:var(--ff-m);text-transform:uppercase;letter-spacing:.7px;margin-bottom:10px">Pipeline steps</div>
          ${[
            ['1', localOnly ? 'Local scrape upload → raw store' : 'Scrape 1688 + Taobao → raw store'],
            ['2','Basic filter — spam, orders, rating'],
            ['3','Profit calc — margin threshold'],
            ['4','Deduplication — image hash'],
            ['5','Rule scoring → AI enrichment'],
            ['6','Save to review queue'],
          ].map(([n, label]) => {
            const prog = activeJob?.progress || 0;
            const thresholds = [0, 20, 40, 55, 60, 96, 100];
            const ni = parseInt(n);
            const isDone = prog >= thresholds[ni];
            const isActive = prog >= thresholds[ni - 1] && !isDone;
            return `
              <div class="pipeline-step">
                <div class="step-num ${isDone ? 'done' : isActive ? 'active' : ''}">${isDone ? '✓' : n}</div>
                <span style="font-size:12px;color:${isDone ? 'var(--green)' : isActive ? 'var(--accent)' : 'var(--t3)'}">${label}</span>
              </div>`;
          }).join('')}
        </div>
      </div>
    </div>`;
}

function renderJobProgress(job) {
  const prog = job?.progress || 0;
  return `
    <div style="margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px">
        <span style="font-size:12px;color:var(--t2)">${job.status}</span>
        <span style="font-size:12px;font-family:var(--ff-m);color:var(--accent)">${prog}%</span>
      </div>
      <div class="progress-bar"><div class="progress-fill" style="width:${prog}%"></div></div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      ${[['Scraped',job.scraped??0],['After filter',job.after_basic??0],['Profitable',job.after_profit??0],['Deduped',job.after_dedup??0],['AI passed',job.after_ai??0]].map(([l,v]) =>
        `<div class="mini-metric"><div class="mini-metric-label">${l}</div><div class="mini-metric-val">${v}</div></div>`
      ).join('')}
    </div>`;
}

async function pollActiveJob() {
  if (!activeJob) { clearInterval(activeJobPoll); activeJobPoll = null; return; }
  try {
    const job = await api(`/jobs/${activeJob.id}`);
    activeJob = job;
    const dot = document.getElementById('status-dot');
    const lbl = document.getElementById('status-label');
    if (job.status === 'done') {
      clearInterval(activeJobPoll); activeJobPoll = null; activeJob = null;
      dot.className = 'status-dot'; lbl.textContent = 'Idle';
      toast(`Scan done · ${job.after_ai} products added to queue`, 'success');
      await refreshStats();
      if (currentPage === 'scan') renderScanContent();
    } else {
      dot.className = 'status-dot on'; lbl.textContent = job.status;
      if (currentPage === 'scan') renderScanContent();
    }
  } catch(e) {}
}

function addKeyword() {
  const inp = document.getElementById('kw-input');
  if (!inp?.value.trim()) return;
  scanKeywords.push(inp.value.trim()); inp.value = '';
  renderScanContent();
}
function removeKeyword(i) { scanKeywords.splice(i, 1); renderScanContent(); }

async function startScan() {
  const scanBtn = document.getElementById('scan-btn');
  if (scanBtn) scanBtn.disabled = true;
  try {
    if (!scanKeywords.length) { toast('Add at least one keyword', 'error'); return; }
    const max = parseInt(document.getElementById('max-per-kw')?.value || 100);
    const job = await api('/scan', 'POST', { keywords: scanKeywords, max_per_keyword: max, source: scanSource });
    activeJob = { id: job.job_id, status: 'queued', progress: 0 };
    const dot = document.getElementById('status-dot');
    const lbl = document.getElementById('status-label');
    dot.className = 'status-dot on'; lbl.textContent = 'Scanning';
    if (activeJobPoll) clearInterval(activeJobPoll);
    activeJobPoll = setInterval(pollActiveJob, 2000);
    toast('Scan started', 'success');
    renderScanContent();
  } catch(e) {
    if (scanBtn) scanBtn.disabled = false;
  }
}

// ── Queue ──────────────────────────────────────────────────────────────────
async function renderQueue() {
  setTitle('Review', 'approve winners, reject the rest');
  document.getElementById('topbar-actions').innerHTML = `
    <select onchange="queueSort=this.value;loadQueue()" style="width:auto;font-size:12px;padding:6px 10px">
      <option value="score"   ${queueSort==='score'  ?'selected':''}>Score ↓</option>
      <option value="margin"  ${queueSort==='margin' ?'selected':''}>Margin ↓</option>
      <option value="orders"  ${queueSort==='orders' ?'selected':''}>Orders ↓</option>
      <option value="created" ${queueSort==='created'?'selected':''}>Newest</option>
    </select>
    <button class="btn btn-sm" onclick="loadQueue()">↻</button>`;
  await loadQueue();
}

async function loadQueue(append = false) {
  const offset = append ? queueProducts.length : 0;
  if (!append) queueProducts = [];
  const data = await api(`/products?stage=ENRICHED&limit=50&offset=${offset}&sort=${queueSort}`).catch(() => ({ products: [], total: 0 }));
  queueProducts = append ? queueProducts.concat(data.products) : data.products;
  queueTotal = data.total;
  renderQueueGrid();
}

function renderQueueGrid() {
  if (!queueProducts.length) {
    document.getElementById('content').innerHTML = `
      <div class="empty" style="margin-top:48px">
        <span class="empty-icon">○</span>
        <h3>Queue is empty</h3>
        <p>Run a scan to find new products</p>
        <button class="btn" style="margin-top:16px" onclick="navigate('scan')">Start scan</button>
      </div>`;
    return;
  }
  const canMore = queueProducts.length < queueTotal;
  document.getElementById('content').innerHTML = `
    <div class="queue-toolbar">
      <span style="font-size:12px;color:var(--t3)">${queueTotal} products waiting</span>
      <button class="btn btn-sm" onclick="selectAll()">Select all</button>
      <button class="btn btn-sm btn-green" onclick="selectAll();batchApprove()">Approve visible</button>
      <button class="btn btn-sm btn-danger" onclick="selectAll();batchReject()">Reject visible</button>
      <button class="btn btn-sm btn-danger" onclick="rejectAllPending()">Reject All (${queueTotal})</button>
      <button class="btn btn-sm" onclick="clearSel()">Clear</button>
    </div>
    <div class="product-grid" id="product-grid">
      ${queueProducts.map(p => productCard(p, 'queue')).join('')}
    </div>
    ${canMore ? `<div style="text-align:center;margin-top:20px">
      <button class="btn" onclick="loadQueue(true)">Load more (${queueTotal - queueProducts.length} remaining)</button>
    </div>` : ''}`;
  updateSelBar();
}

// ── Approved ───────────────────────────────────────────────────────────────
async function renderApproved() {
  setTitle('Approved');
  document.getElementById('topbar-actions').innerHTML = `<button class="btn btn-sm" onclick="loadApproved()">↻</button>`;
  await loadApproved();
}

async function loadApproved(append = false) {
  const offset = append ? approvedProducts.length : 0;
  if (!append) approvedProducts = [];
  const data = await api(`/products?stage=REVIEWED&limit=50&offset=${offset}&sort=score`).catch(() => ({ products: [], total: 0 }));
  approvedProducts = append ? approvedProducts.concat(data.products) : data.products;
  approvedTotal = data.total;
  renderApprovedGrid();
}

function renderApprovedGrid() {
  if (!approvedProducts.length) {
    document.getElementById('content').innerHTML = `
      <div class="empty" style="margin-top:48px">
        <span class="empty-icon">◆</span>
        <h3>Nothing approved yet</h3>
        <p>Approve products from the review queue</p>
        <button class="btn" style="margin-top:16px" onclick="navigate('queue')">Go to queue</button>
      </div>`;
    return;
  }
  const canMore = approvedProducts.length < approvedTotal;
  document.getElementById('content').innerHTML = `
    <div class="queue-toolbar">
      <span style="font-size:12px;color:var(--t3)">${approvedTotal} approved · select to batch post</span>
      <button class="btn btn-sm" onclick="selectAll()">Select all</button>
      <button class="btn btn-sm" onclick="clearSel()">Clear</button>
    </div>
    <div class="product-grid" id="product-grid">
      ${approvedProducts.map(p => productCard(p, 'REVIEWED')).join('')}
    </div>
    ${canMore ? `<div style="text-align:center;margin-top:20px">
      <button class="btn" onclick="loadApproved(true)">Load more (${approvedTotal - approvedProducts.length} remaining)</button>
    </div>` : ''}`;
  updateSelBar('post');
}

async function renderTextEdit() {
  setTitle('Text edit', 'approved products with Chinese text in the photo');
  document.getElementById('topbar-actions').innerHTML = `<button class="btn btn-sm" onclick="loadTextEdit()">↻</button>`;
  await loadTextEdit();
}

async function loadTextEdit(append = false) {
  const offset = append ? textEditProducts.length : 0;
  if (!append) textEditProducts = [];
  const data = await api(`/products?stage=TEXT_REMOVAL&limit=50&offset=${offset}&sort=score`).catch(() => ({ products: [], total: 0 }));
  textEditProducts = append ? textEditProducts.concat(data.products) : data.products;
  textEditTotal = data.total;
  renderTextEditGrid();
}

function renderTextEditGrid() {
  if (!textEditProducts.length) {
    document.getElementById('content').innerHTML = `
      <div class="empty" style="margin-top:48px">
        <span class="empty-icon">文</span>
        <h3>No products need text cleanup</h3>
        <p>Products with Chinese text appear here after you approve them</p>
      </div>`;
    return;
  }
  const canMore = textEditProducts.length < textEditTotal;
  document.getElementById('content').innerHTML = `
    <div class="queue-toolbar">
      <span style="font-size:12px;color:var(--t3)">${textEditTotal} need image text cleanup</span>
    </div>
    <div class="product-grid" id="product-grid">
      ${textEditProducts.map(p => productCard(p, 'TEXT_REMOVAL')).join('')}
    </div>
    ${canMore ? `<div style="text-align:center;margin-top:20px">
      <button class="btn" onclick="loadTextEdit(true)">Load more (${textEditTotal - textEditProducts.length} remaining)</button>
    </div>` : ''}`;
}

// ── Product card ───────────────────────────────────────────────────────────
function verdictBadge(verdict) {
  if (!verdict) return '';
  const cfg = {
    top_priority:      ['badge-purple', 'top priority'],
    strong_candidate:  ['badge-green',  'strong'],
    pending_review:    ['badge-gray',   'pending review'],
    auto_reject:       ['badge-red',    'auto reject'],
  };
  const [cls, label] = cfg[verdict] || ['badge-gray', verdict.replace(/_/g, ' ')];
  return `<span class="badge ${cls}" style="align-self:flex-start;font-size:9px">${label}</span>`;
}

function productCard(p, mode) {
  const sel = selectedProducts.has(p.id);
  const img = imageUrl(firstImage(p));
  const score = p.composite_score || p.score || 0;
  const sc = score >= 8 ? 'hi' : score >= 7 ? 'mi' : 'lo';

  let actions = '';
  if (mode === 'queue') {
    actions = `<button class="pca-approve" onclick="event.stopPropagation();quickApprove(${p.id})">Approve</button>
               <button class="pca-reject"  onclick="event.stopPropagation();showRejectModal(${p.id})">✕</button>`;
  } else if (mode === 'REVIEWED') {
    actions = `<button class="pca-post"   onclick="event.stopPropagation();quickPost(${p.id})">Post →</button>
               <button class="pca-reject" onclick="event.stopPropagation();showRejectModal(${p.id})">✕</button>`;
  }

  if (mode === 'TEXT_REMOVAL') {
    actions = `<button class="pca-clean" id="clean-btn-${p.id}" onclick="event.stopPropagation();cleanImage(${p.id},this)">🧹 Clean</button>
               <button class="pca-reject" onclick="event.stopPropagation();showRejectModal(${p.id})">Reject</button>`;
  }

  const name = escHtml(p.product_name || p.title_translated || p.title || 'Unknown');
  const provider = p.ai_provider ? escHtml(String(p.ai_provider).toUpperCase()) : '';
  const ordersLabel = p.source_platform === 'taobao' ? 'sales unknown' : `${(p.orders ?? 0).toLocaleString()} sold`;
  const cat  = [p.keyword ? `#${escHtml(p.keyword)}` : '', escHtml(p.category || '')].filter(Boolean).join(' · ');

  return `
    <div class="product-card${sel ? ' selected' : ''}" id="card-${p.id}" onclick="showDetail(${p.id})">
      <div class="pcard-img-wrap">
        ${img
          ? `<img class="pcard-img" src="${img}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex';this.nextElementSibling.innerHTML='IMAGE ERROR'">`
          : ''}
        <div class="pcard-placeholder" style="${img ? 'display:none' : ''}">◈</div>
        <div class="pcard-score ${sc}">${score.toFixed(1)}</div>
        ${provider ? `<div class="pcard-score ${sc}" style="left:auto;right:10px;font-size:9px">${provider}</div>` : ''}
        <div class="pcard-check" onclick="event.stopPropagation();toggleSel(${p.id})">
          <span class="pcard-check-mark">${IC.check}</span>
        </div>
      </div>
      <div class="pcard-body">
        <div class="pcard-name editable" ondblclick="event.stopPropagation();startEdit(${p.id}, 'product_name', this)">${name}</div>
        ${p.has_chinese_text ? `<span class="badge badge-amber" style="align-self:flex-start">Chinese text</span>` : ''}
        ${verdictBadge(p.verdict)}
        <div class="pcard-cat">${cat || '—'}</div>
        <div class="pcard-pricing">
          <span class="p-cost">₾${p.cost_eur ?? '?'}</span>
          <span class="p-arr">→</span>
          <span class="p-sell editable" ondblclick="event.stopPropagation();startEdit(${p.id}, 'sell_price_eur', this)">₾${p.sell_price_eur ?? '?'}</span>
          <span class="p-margin">${p.margin_pct ?? 0}%</span>
        </div>
        <div class="pcard-social">
          <span>★ ${p.rating ?? 0}</span>
          <span>${ordersLabel}</span>
        </div>
      </div>
      ${actions ? `<div class="pcard-actions">${actions}</div>` : ''}
    </div>`;
}

// ── Selection ──────────────────────────────────────────────────────────────
function toggleSel(id) {
  if (selectedProducts.has(id)) {
    selectedProducts.delete(id);
  } else {
    if (selectedProducts.size >= 10) { toast('Max 10 at once', 'error'); return; }
    selectedProducts.add(id);
  }
  const card = document.getElementById(`card-${id}`);
  if (card) {
    card.className = `product-card${selectedProducts.has(id) ? ' selected' : ''}`;
  }
  updateSelBar(currentPage === 'REVIEWED' ? 'post' : currentPage === 'textEdit' ? 'TEXT_REMOVAL' : 'approve');
}

function selectAll() {
  const list = currentPage === 'REVIEWED' ? approvedProducts : currentPage === 'textEdit' ? textEditProducts : queueProducts;
  list.slice(0, 10).forEach(p => selectedProducts.add(p.id));
  if (currentPage === 'REVIEWED') renderApprovedGrid();
  else if (currentPage === 'textEdit') renderTextEditGrid();
  else renderQueueGrid();
}

function clearSel() {
  selectedProducts.clear();
  if (currentPage === 'REVIEWED') renderApprovedGrid();
  else if (currentPage === 'textEdit') renderTextEditGrid();
  else renderQueueGrid();
}

function updateSelBar(mode = 'approve') {
  let bar = document.getElementById('selection-bar');
  if (!selectedProducts.size) { bar?.remove(); return; }
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'selection-bar';
    bar.className = 'selection-bar';
    document.body.appendChild(bar);
  }
  const n = selectedProducts.size;
  let actions = '';
  if (mode === 'post') {
    actions = `<button class="btn btn-primary" onclick="batchPost()">Post ${n} →</button>
      ${n >= 2 && n <= 6 ? `<button class="btn btn-collage" onclick="postCollage([...selectedProducts])">📸 Collage (${n})</button>` : ''}`;
  } else {
    actions = `<button class="btn btn-green" onclick="batchApprove()">Approve ${n}</button>
               <button class="btn btn-danger" onclick="batchReject()">Reject ${n}</button>`;
  }
  bar.innerHTML = `
    <span style="font-family:var(--ff-m);font-size:12px;color:var(--accent)">${n} selected</span>
    ${actions}
    <button class="btn" onclick="clearSel()">Cancel</button>`;
}

async function batchApprove() {
  _cacheInvalidate('/products', '/stats');
  const ids = [...selectedProducts];
  try {
    const res = await api('/approve', 'POST', { product_ids: ids });
    const textEdit = res.TEXT_REMOVAL || 0;
    const approved = res.REVIEWED || 0;
    toast(textEdit ? `${approved} approved · ${textEdit} moved to Text edit` : `${approved || ids.length} approved`, 'success');
    selectedProducts.clear();
    await refreshStats();
    await loadQueue();
  } catch(e) {}
}

async function batchMarkTextEdited() {
  const ids = [...selectedProducts];
  if (!ids.length) return;
  try {
    await Promise.all(ids.map(id => api(`/products/${id}/text-edited`, 'POST')));
    toast(`${ids.length} moved to Approved`, 'success');
    selectedProducts.clear();
    await refreshStats();
    await loadTextEdit();
  } catch(e) {}
}

async function batchReject() {
  const ids = [...selectedProducts];
  if (!ids.length) return;
  if (!confirm(`Reject ${ids.length} selected product${ids.length === 1 ? '' : 's'}?`)) return;
  try {
    await api('/reject', 'POST', { product_ids: ids });
    toast(`${ids.length} rejected`, 'success');
    selectedProducts.clear();
    queueProducts = queueProducts.filter(p => !ids.includes(p.id));
    queueTotal = Math.max(0, queueTotal - ids.length);
    await refreshStats();
    renderQueueGrid();
  } catch(e) {}
}

async function rejectAllPending() {
  if (!queueTotal) return;
  if (!confirm(`Reject ALL ${queueTotal} pending products? This cannot be undone.`)) return;
  try {
    const res = await api('/reject-all-pending', 'POST');
    const done = res.rejected || queueTotal;
    queueProducts = [];
    queueTotal = 0;
    selectedProducts.clear();
    _cacheInvalidate('/products', '/stats');
    await refreshStats();
    toast(`❌ Rejected ${done} products`, 'success');
    renderQueueGrid();
  } catch(e) {
    toast('Error: ' + e.message, 'error');
  }
}

async function batchPost() {
  const ids = [...selectedProducts];
  if (!ids.length) return;
  if (!confirm(`Queue ${ids.length} product${ids.length === 1 ? '' : 's'} for Instagram posting?`)) return;
  try {
    await api('/post', 'POST', { product_ids: ids });
    toast(`${ids.length} queued for Instagram posting`, 'success');
    selectedProducts.clear();
    await refreshStats();
    await loadApproved();
  } catch(e) {}
}

async function quickApprove(id) {
  _cacheInvalidate('/products', '/stats');
  try {
    const res = await api(`/products/${id}/approve`, 'POST');
    toast(res.stage === 'TEXT_REMOVAL' ? 'Moved to Text edit' : 'Approved', 'success');
    closeDetail();
    queueProducts = queueProducts.filter(p => p.id !== id);
    selectedProducts.delete(id);
    queueTotal = Math.max(0, queueTotal - 1);
    renderQueueGrid();
    refreshStats();
  } catch(e) {}
}

// ── Clipdrop image clean ──────────────────────────────────────────────────────
async function cleanImage(id, btn) {
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="clean-spinner"></span> Cleaning…'; }
  try {
    const r = await api(`/products/${id}/remove-text`, 'POST');
    if (r.ok) {
      if (r.public === false) toast('Image cleaned & approved — but it is only stored on this machine. Add Supabase Storage (Settings → Instagram) so the cleaned photo can be posted.', 'error', 7000);
      else toast('✅ Image cleaned & approved!', 'success');
      _cacheInvalidate('/products', '/stats');
      await refreshStats();
      const card = document.getElementById(`card-${id}`);
      if (card) { card.style.transition = 'opacity .5s'; card.style.opacity = '0'; setTimeout(() => card.remove(), 500); }
    } else {
      toast(r.detail || r.error || 'Clean failed — check Clipdrop key in Settings', 'error');
      if (btn) { btn.disabled = false; btn.innerHTML = '🧹 Clean'; }
    }
  } catch(e) {
    toast('Clean failed: ' + (e.message || 'Unknown'), 'error');
    if (btn) { btn.disabled = false; btn.innerHTML = '🧹 Clean'; }
  }
}

async function batchCleanImages(btn) {
  if (!selectedProducts.size) { toast('Select products first', 'error'); return; }
  const ids = [...selectedProducts];
  if (btn) { btn.disabled = true; btn.textContent = `Cleaning ${ids.length}…`; }
  let done = 0, failed = 0;
  for (const id of ids) {
    try {
      const r = await api(`/products/${id}/remove-text`, 'POST');
      if (r.ok) done++; else failed++;
    } catch { failed++; }
  }
  toast(done > 0 ? `✅ Cleaned ${done}/${ids.length} images` : `❌ Clean failed — check Clipdrop key`, done > 0 ? 'success' : 'error');
  selectedProducts.clear();
  _cacheInvalidate('/products', '/stats');
  await refreshStats();
  loadTextEdit();
}

// ── Collage posting ────────────────────────────────────────────────────────────
async function postCollage(ids) {
  if (!ids || ids.length < 2) { toast('Select 2–6 approved products for a collage', 'error'); return; }
  const use = [...ids].slice(0, 6);
  if (!confirm(`Create a collage from ${use.length} product photos and post to Instagram?`)) return;
  toast('📸 Generating collage…', 'info');
  try {
    const r = await api('/collage/post', 'POST', { product_ids: use });
    if (r.ok) {
      toast('🎉 Collage posted to Instagram!', 'success');
      _cacheInvalidate('/products', '/stats');
      await refreshStats();
      selectedProducts.clear();
      loadApproved();
    } else {
      toast(r.detail || r.error || 'Collage failed — check Instagram token in Settings', 'error');
    }
  } catch(e) {
    toast('Collage error: ' + (e.message || 'Unknown'), 'error');
  }
}

async function markTextEdited(id) {
  try {
    await api(`/products/${id}/text-edited`, 'POST');
    toast('Moved to Approved', 'success');
    closeDetail();
    textEditProducts = textEditProducts.filter(p => p.id !== id);
    selectedProducts.delete(id);
    textEditTotal = Math.max(0, textEditTotal - 1);
    renderTextEditGrid();
    refreshStats();
  } catch(e) {}
}

async function quickPost(id) {
  try {
    await api(`/products/${id}/post`, 'POST');
    toast('Queued for Instagram posting', 'success');
    closeDetail();
    approvedProducts = approvedProducts.filter(p => p.id !== id);
    selectedProducts.delete(id);
    approvedTotal = Math.max(0, approvedTotal - 1);
    renderApprovedGrid();
    refreshStats();
  } catch(e) {}
}

async function quickPublishWebsite(id) {
  try {
    await api(`/products/${id}/publish-website`, 'POST');
    toast('Published to website', 'success');
    closeDetail();
    approvedProducts = approvedProducts.filter(p => p.id !== id);
    selectedProducts.delete(id);
    approvedTotal = Math.max(0, approvedTotal - 1);
    renderApprovedGrid();
    refreshStats();
  } catch(e) { toast('Publish failed', 'error'); }
}

async function batchPublishWebsite() {
  const ids = [...selectedProducts];
  if (!ids.length) return;
  if (!confirm(`Publish ${ids.length} product${ids.length === 1 ? '' : 's'} to the website?`)) return;
  try {
    await Promise.all(ids.map(id => api(`/products/${id}/publish-website`, 'POST')));
    toast(`${ids.length} published to website`, 'success');
    approvedProducts = approvedProducts.filter(p => !ids.includes(p.id));
    approvedTotal = Math.max(0, approvedTotal - ids.length);
    selectedProducts.clear();
    renderApprovedGrid();
    refreshStats();
  } catch(e) { toast('Batch publish failed', 'error'); }
}

// ── Reject modal ───────────────────────────────────────────────────────────
function showRejectModal(id) {
  rejectTargetId = id;
  document.getElementById('reject-modal')?.remove();
  const m = document.createElement('div');
  m.className = 'modal-overlay'; m.id = 'reject-modal';
  m.innerHTML = `
    <div class="modal" onclick="event.stopPropagation()">
      <div class="modal-title">Reject product</div>
      <div class="modal-sub">Pick a reason to track patterns over time</div>
      <div class="reason-pills">
        ${['Bad niche fit','Poor images','Oversaturated','Too expensive','Wrong category','Low quality'].map(r =>
          `<button class="btn btn-sm" onclick="setReason(this,'${r}')">${r}</button>`).join('')}
      </div>
      <div class="form-group">
        <label>Custom reason (optional)</label>
        <input type="text" id="reject-reason-input" placeholder="Type your own reason…"/>
      </div>
      <div style="display:flex;gap:8px;margin-top:16px">
        <button class="btn btn-danger" style="flex:1" onclick="confirmReject()">Reject</button>
        <button class="btn" onclick="closeRejectModal()">Cancel</button>
      </div>
    </div>`;
  m.addEventListener('click', closeRejectModal);
  document.body.appendChild(m);
}

function setReason(btn, r) {
  document.getElementById('reject-reason-input').value = r;
  btn.closest('.reason-pills').querySelectorAll('.btn').forEach(b => { b.style.borderColor = ''; b.style.color = ''; });
  btn.style.borderColor = 'var(--red)'; btn.style.color = 'var(--red)';
}

function closeRejectModal() { document.getElementById('reject-modal')?.remove(); rejectTargetId = null; }

async function confirmReject() {
  if (!rejectTargetId) return;
  const id = rejectTargetId;
  const reason = document.getElementById('reject-reason-input')?.value?.trim() || '';
  closeRejectModal();
  try {
    await api(`/products/${id}/reject`, 'POST', { reason: reason || null });
    toast('Rejected', 'success');
    closeDetail();
    queueProducts = queueProducts.filter(p => p.id !== id);
    approvedProducts = approvedProducts.filter(p => p.id !== id);
    textEditProducts = textEditProducts.filter(p => p.id !== id);
    selectedProducts.delete(id);
    if (currentPage === 'queue') { queueTotal = Math.max(0, queueTotal - 1); renderQueueGrid(); }
    else if (currentPage === 'REVIEWED') { approvedTotal = Math.max(0, approvedTotal - 1); renderApprovedGrid(); }
    else if (currentPage === 'textEdit') { textEditTotal = Math.max(0, textEditTotal - 1); renderTextEditGrid(); }
    refreshStats();
  } catch(e) {}
}

// ── Detail panel ───────────────────────────────────────────────────────────
async function showDetail(id) {
  const p = await api(`/products/${id}`).catch(() => null);
  if (!p) return;
  document.getElementById('detail-overlay')?.remove();

  const stage = p.stage || 'SCRAPED';
  const img   = imageUrl((p.images || [])[0] || '');
  const tags  = (p.hashtags || []);

  const sBar = (label, val) => {
    const pct = Math.min(100, (val / 10) * 100);
    const c = val >= 8 ? 'var(--green)' : val >= 5 ? 'var(--amber)' : 'var(--red)';
    return `<div class="sbar-row">
      <span class="sbar-lbl">${label}</span>
      <div class="sbar-track"><div class="sbar-fill" style="width:${pct}%;background:${c}"></div></div>
      <span class="sbar-num">${(val || 0).toFixed(1)}</span>
    </div>`;
  };

  const stageBadge = { SCRAPED:'badge-gray', ENRICHED:'badge-amber', REVIEWED:'badge-green', TEXT_REMOVAL:'badge-amber', QUEUED:'badge-blue', LIVE:'badge-blue', REJECTED:'badge-red' }[stage] || 'badge-gray';
  const stageLabel = { SCRAPED:'Scoring…', ENRICHED:'Pending review', REVIEWED:'Approved', TEXT_REMOVAL:'Text edit', QUEUED:'Queued to post', LIVE:'Posted', REJECTED:'Rejected' }[stage] || stage;
  const sc = p.scores || {};
  const dims = [
    ['Cute appeal',      sc.cute_appeal      ?? p.cute_appeal   ?? 0, '30%'],
    ['Romantic trigger', sc.romantic_trigger ?? p.niche_fit     ?? 0, '25%'],
    ['Visual',           sc.visual_score     ?? p.visual_appeal ?? 0, '20%'],
    ['Trend fit',        sc.trend_fit        ?? p.trend_score   ?? 0, '15%'],
    ['Giftability',      sc.giftability      ?? p.giftability   ?? 0, '10%'],
  ];
  const providerLabel = p.ai_provider ? String(p.ai_provider).replace('gemini-batch','Gemini').replace('gemini','Gemini').replace('groq','Groq (text only)').replace('mock','no AI — rule score') : '';

  let actionHtml = '';
  if (stage === 'ENRICHED')
    actionHtml = `<button class="btn btn-green" style="flex:1" onclick="quickApprove(${p.id})">Approve</button>
                  <button class="btn btn-danger" onclick="showRejectModal(${p.id})">Reject</button>`;
  else if (stage === 'REVIEWED')
    actionHtml = `<button class="btn btn-primary" style="flex:1" onclick="quickPost(${p.id})">Post to Instagram →</button>
                  <button class="btn" onclick="quickPublishWebsite(${p.id})" title="Mark as live without posting to Instagram">Website only</button>
                  <button class="btn btn-danger" onclick="showRejectModal(${p.id})">Reject</button>`;
  else if (stage === 'TEXT_REMOVAL')
    actionHtml = `<button class="btn btn-green" style="flex:1" id="clean-btn-${p.id}" onclick="cleanImage(${p.id},this)">🧹 Clean image</button>
                  <button class="btn btn-danger" onclick="showRejectModal(${p.id})">Reject</button>`;
  else if (stage === 'REJECTED')
    actionHtml = `<button class="btn btn-amber" style="flex:1" onclick="reconsider(${p.id})">Move back to queue</button>`;

  const ov = document.createElement('div');
  ov.className = 'detail-overlay'; ov.id = 'detail-overlay';
  ov.addEventListener('click', e => { if (e.target === ov) closeDetail(); });

  ov.innerHTML = `
    <div class="detail-panel">
      <div class="detail-hdr">
        <div style="display:flex;align-items:center;gap:8px">
          <span class="badge ${stageBadge}">${stageLabel}</span>
          ${p.source ? `<span class="badge badge-gray">${p.source.replace('_mock','')}</span>` : ''}
        </div>
        <div class="detail-actions">
          ${actionHtml}
          <button class="btn btn-sm" onclick="closeDetail()">Close</button>
        </div>
      </div>
      <div class="detail-body">
        ${img ? `<img class="detail-img" src="${img}" onerror="this.style.display='none'">` : ''}

        <div style="font-family:var(--ff-d);font-size:19px;font-weight:800;line-height:1.2;margin-bottom:4px">${escHtml(p.product_name || '—')}</div>
        <div style="font-size:11px;color:var(--t3);font-family:var(--ff-m);margin-bottom:${p.keyword ? '3px' : '14px'};line-height:1.5">${escHtml(p.title_translated || p.title || '')}</div>
        ${p.keyword ? `<div style="font-size:11px;color:var(--t3);margin-bottom:14px">Keyword: <span style="color:var(--accent)">${escHtml(p.keyword)}</span></div>` : ''}

        ${p.has_chinese_text ? `
        <div class="detail-sec">
          <span class="detail-sec-lbl">Chinese text detected</span>
          <div class="card-sm" style="font-size:12px;color:var(--amber);line-height:1.6">${escHtml(p.chinese_text_note || 'Chinese text is visible in the product image.')}</div>
        </div>` : ''}

        <div class="detail-sec">
          <span class="detail-sec-lbl">Pricing</span>
          <div class="m3">
            <div class="mbox">
              <div class="mbox-lbl">Cost</div>
              <div class="mbox-val">₾${p.cost_eur ?? 0}</div>
              <div class="mbox-sub">¥${p.price_cny ?? 0} CNY</div>
            </div>
            <div class="mbox">
              <div class="mbox-lbl">Sell</div>
              <div class="mbox-val" style="color:var(--green)">₾${p.sell_price_eur ?? 0}</div>
            </div>
            <div class="mbox">
              <div class="mbox-lbl">Margin</div>
              <div class="mbox-val" style="color:var(--green)">${p.margin_pct ?? 0}%</div>
            </div>
          </div>
        </div>

        <div class="detail-sec">
          <span class="detail-sec-lbl">Source performance
            ${p.source_platform ? `<span class="badge badge-gray" style="margin-left:6px;font-size:10px">${escHtml(p.source_platform)}</span>` : ''}
          </span>
          <div class="m3">
            <div class="mbox">
              <div class="mbox-lbl">Sold</div>
              <div class="mbox-val" style="font-size:16px;${(p.orders??0)>0?'color:var(--green)':''}">${(p.orders ?? 0).toLocaleString()}</div>
              <div class="mbox-sub">${p.source_platform==='1688' ? 'monthly orders' : p.source_platform==='taobao' ? 'not available' : 'orders'}</div>
            </div>
            <div class="mbox">
              <div class="mbox-lbl">Rating</div>
              <div class="mbox-val" style="font-size:16px">★${p.rating ?? 0}</div>
              <div class="mbox-sub">${p.source_platform==='taobao' ? 'shopDsr' : 'avg score'}</div>
            </div>
            <div class="mbox">
              <div class="mbox-lbl">Category</div>
              <div class="mbox-val" style="font-size:12px">${escHtml(p.category || '—')}</div>
            </div>
          </div>
        </div>

        <div class="detail-sec">
          <span class="detail-sec-lbl" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">AI score — ${(p.composite_score ?? p.score ?? 0).toFixed(1)} / 10
            ${verdictBadge(p.verdict)}
            ${p.product_tier && p.product_tier !== 'auto_reject' && p.product_tier !== 'unscored' ? `<span class="badge badge-gray" style="font-size:9px">${escHtml(String(p.product_tier).replace(/_/g,' '))}</span>` : ''}
          </span>
          ${dims.map(([l, v]) => sBar(l, Number(v) || 0)).join('')}
          ${(p.viral_angle || p.emotional_hook) ? `
          <div class="card-sm" style="margin-top:8px;font-size:12px;line-height:1.6;color:var(--t2)">
            ${p.emotional_hook ? `<div><span style="color:var(--t3)">Hook:</span> ${escHtml(p.emotional_hook)}</div>` : ''}
            ${p.viral_angle ? `<div><span style="color:var(--t3)">Viral angle:</span> ${escHtml(p.viral_angle)}</div>` : ''}
          </div>` : ''}
          ${providerLabel ? `<div style="font-size:10px;color:var(--t4);font-family:var(--ff-m);margin-top:6px">scored by ${escHtml(providerLabel)}${p.confidence ? ` · confidence ${Math.round(Number(p.confidence) * 100)}%` : ''}</div>` : ''}
        </div>

        ${p.caption ? `
        <div class="detail-sec">
          <span class="detail-sec-lbl">Instagram caption</span>
          <div class="card-sm" style="font-size:12.5px;color:var(--t2);line-height:1.7">${escHtml(p.caption)}</div>
        </div>` : ''}

        <details class="detail-sec edit-box">
          <summary>Edit product</summary>
          <div class="form-group">
            <label>Store name</label>
            <input type="text" id="edit-name" value="${escHtml(p.product_name || '')}"/>
          </div>
          <div class="form-group">
            <label>Short description</label>
            <textarea id="edit-description" rows="3" style="width:100%;resize:vertical">${escHtml(p.description || '')}</textarea>
          </div>
          <div class="form-group">
            <label>Sell price</label>
            <input type="number" id="edit-price" value="${p.sell_price_eur ?? 0}" step="0.01" min="0"/>
          </div>
          <div class="form-group">
            <label>Caption</label>
            <textarea id="edit-caption" rows="5" style="width:100%;resize:vertical">${escHtml(p.caption || '')}</textarea>
          </div>
          <div class="form-group">
            <label>Hashtags</label>
            <input type="text" id="edit-tags" value="${escHtml(tags.join(', '))}"/>
          </div>
          <button class="btn btn-green" onclick="saveProductEdit(${p.id})">Save product changes</button>
        </details>

        ${tags.length ? `
        <div class="detail-sec">
          <span class="detail-sec-lbl">Hashtags</span>
          <div style="display:flex;flex-wrap:wrap;gap:5px">
            ${tags.map(h => `<span class="badge badge-purple">#${escHtml(h.replace('#',''))}</span>`).join('')}
          </div>
        </div>` : ''}

        ${p.rejection_reason ? `
        <div class="detail-sec">
          <span class="detail-sec-lbl">Rejection reason</span>
          <div class="card-sm" style="font-size:12px;color:var(--red)">${escHtml(p.rejection_reason)}</div>
        </div>` : ''}

        <div class="detail-sec">
          <span class="detail-sec-lbl">Review note</span>
          <textarea id="review-note-input" rows="3" style="width:100%;resize:vertical" placeholder="Add a note…">${escHtml(p.review_note || '')}</textarea>
          <button class="btn btn-sm" style="margin-top:7px" onclick="saveNote(${p.id})">Save note</button>
        </div>

        <div class="detail-sec">
          <span class="detail-sec-lbl">Timeline</span>
          <div style="font-size:11px;font-family:var(--ff-m);line-height:2.2;color:var(--t3)">
            ${p.created_at  ? `<div>Scraped: ${fmtDate(p.created_at)}</div>` : ''}
            ${p.approved_at ? `<div style="color:var(--green)">Approved: ${fmtDate(p.approved_at)}</div>` : ''}
            ${p.rejected_at ? `<div style="color:var(--red)">Rejected: ${fmtDate(p.rejected_at)}</div>` : ''}
            ${p.posted_at   ? `<div style="color:var(--blue)">Posted: ${fmtDate(p.posted_at)}${p.instagram_url ? ` · <a href="${safeUrl(p.instagram_url)}" target="_blank" rel="noopener noreferrer" style="color:var(--blue)">Instagram ↗</a>` : ''}</div>` : ''}
          </div>
        </div>

        ${p.url ? `<a href="${safeUrl(p.url)}" target="_blank" rel="noopener noreferrer" style="display:block;text-align:center;color:var(--t3);font-size:11px;margin-top:14px;text-decoration:none;font-family:var(--ff-m)">View on source ↗</a>` : ''}
      </div>
    </div>`;
  document.body.appendChild(ov);
}

function closeDetail() { document.getElementById('detail-overlay')?.remove(); }

async function saveNote(id) {
  const note = document.getElementById('review-note-input')?.value || '';
  try { await api(`/products/${id}/note`, 'PATCH', { note }); toast('Note saved', 'success'); } catch(e) {}
}

async function saveProductEdit(id) {
  const payload = {
    product_name: document.getElementById('edit-name')?.value || '',
    description: document.getElementById('edit-description')?.value || '',
    sell_price_eur: parseFloat(document.getElementById('edit-price')?.value || '0'),
    caption: document.getElementById('edit-caption')?.value || '',
    hashtags: (document.getElementById('edit-tags')?.value || '')
      .split(',')
      .map(s => s.trim().replace(/^#/, ''))
      .filter(Boolean),
  };
  try {
    const res = await api(`/products/${id}`, 'PATCH', payload);
    toast('Product updated', 'success');
    const updated = res.product;
    const lists = [queueProducts, approvedProducts, rejectedProducts];
    lists.forEach(list => {
      const idx = list.findIndex(p => p.id === id);
      if (idx >= 0) list[idx] = updated;
    });
    showDetail(id);
    if (currentPage === 'queue') renderQueueGrid();
    if (currentPage === 'REVIEWED') renderApprovedGrid();
    if (currentPage === 'REJECTED') renderRejectedTable();
  } catch(e) {
    toast(`Save failed: ${e.message || e}`, 'error');
  }
}

async function reconsider(id) {
  try {
    await api(`/products/${id}/reconsider`, 'POST');
    toast('Moved to review queue', 'success');
    closeDetail();
    rejectedProducts = rejectedProducts.filter(p => p.id !== id);
    renderRejectedTable();
    refreshStats();
  } catch(e) {}
}

function fmtDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  catch(e) { return iso; }
}

// ── Posted ─────────────────────────────────────────────────────────────────
async function renderPosted() {
  setTitle('Posted');
  document.getElementById('topbar-actions').innerHTML = '';
  const data = await api('/products?stage=LIVE&limit=100&sort=created').catch(() => ({ products: [], total: 0 }));

  if (!data.products.length) {
    document.getElementById('content').innerHTML = `
      <div class="empty" style="margin-top:48px">
        <span class="empty-icon">◉</span>
        <h3>Nothing posted yet</h3>
        <p>Approve products then post them from the Approved page</p>
      </div>`;
    return;
  }

  document.getElementById('content').innerHTML = `
    <div style="margin-bottom:14px;font-size:12px;color:var(--t3)">${data.total} posted</div>
    <div class="card" style="padding:0;overflow:hidden">
      <table class="table">
        <thead><tr>
          <th>Product</th><th>Score</th><th>Margin</th><th>Sell</th><th>Orders</th><th>Posted</th><th></th>
        </tr></thead>
        <tbody>
          ${data.products.map(p => `
            <tr style="cursor:pointer" onclick="showDetail(${p.id})">
              <td>
                <div style="display:flex;align-items:center;gap:10px">
                  ${(p.images || [])[0] ? `<img src="${imageUrl((p.images || [])[0])}" style="width:36px;height:36px;object-fit:cover;border-radius:6px;flex-shrink:0" onerror="this.style.display='none'">` : ''}
                  <div>
                    <div style="font-weight:500;font-size:12.5px">${escHtml(p.product_name || p.title_translated || '—')}</div>
                    <div style="font-size:10px;color:var(--t3);font-family:var(--ff-m)">${escHtml(p.keyword || p.category || '')}</div>
                  </div>
                </div>
              </td>
              <td><span class="badge badge-purple">${(p.composite_score ?? p.score ?? 0).toFixed(1)}</span></td>
              <td><span class="badge badge-green">${p.margin_pct ?? 0}%</span></td>
              <td style="font-family:var(--ff-m);color:var(--green);font-size:12px">₾${p.sell_price_eur ?? 0}</td>
              <td style="font-family:var(--ff-m);font-size:12px">${(p.orders ?? 0).toLocaleString()}</td>
              <td style="font-size:11px;color:var(--t3);font-family:var(--ff-m);white-space:nowrap">${fmtDate(p.posted_at || p.created_at)}</td>
              <td>${p.instagram_url ? `<a href="${safeUrl(p.instagram_url)}" target="_blank" rel="noopener noreferrer" class="btn btn-sm" onclick="event.stopPropagation()">IG ↗</a>` : '<span style="font-size:10px;color:var(--t4)">website</span>'}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

// ── Rejected ───────────────────────────────────────────────────────────────
async function renderRejected() {
  setTitle('Rejected');
  document.getElementById('topbar-actions').innerHTML = '';
  const data = await api('/products?stage=REJECTED&limit=100&sort=created').catch(() => ({ products: [], total: 0 }));
  rejectedProducts = data.products;
  rejectedTotal = data.total;
  renderRejectedTable();
}

function renderRejectedTable() {
  if (!rejectedProducts.length) {
    document.getElementById('content').innerHTML = `
      <div class="empty" style="margin-top:48px">
        <span class="empty-icon">✕</span>
        <h3>No rejected products</h3>
        <p>Rejected products appear here with their reasons</p>
      </div>`;
    return;
  }
  document.getElementById('content').innerHTML = `
    <div style="margin-bottom:14px;font-size:12px;color:var(--t3)">${rejectedTotal} rejected</div>
    <div class="card" style="padding:0;overflow:hidden">
      <table class="table">
        <thead><tr>
          <th>Product</th><th>Score</th><th>Reason</th><th>Rejected</th><th></th>
        </tr></thead>
        <tbody>
          ${rejectedProducts.map(p => `
            <tr>
              <td style="cursor:pointer" onclick="showDetail(${p.id})">
                <div style="font-weight:500;font-size:12.5px">${escHtml(p.product_name || p.title_translated || '—')}</div>
                <div style="font-size:10px;color:var(--t3);font-family:var(--ff-m)">${escHtml(p.keyword || '')}</div>
              </td>
              <td><span class="badge badge-gray">${(p.composite_score ?? p.score ?? 0).toFixed(1)}</span></td>
              <td style="font-size:12px;color:var(--t3);max-width:220px">${p.rejection_reason ? escHtml(p.rejection_reason) : '<span style="opacity:.35">—</span>'}</td>
              <td style="font-size:11px;color:var(--t3);font-family:var(--ff-m);white-space:nowrap">${fmtDate(p.rejected_at)}</td>
              <td><button class="btn btn-sm btn-amber" onclick="reconsider(${p.id})">Reconsider</button></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

// ── Settings ───────────────────────────────────────────────────────────────
async function renderSettings() {
  setTitle('Settings');
  document.getElementById('topbar-actions').innerHTML = `<button id="settings-save-btn" class="btn btn-primary" onclick="saveSettings()">Save settings</button>`;
  document.getElementById('content').innerHTML = '<div style="color:var(--t3);font-size:12px;padding:40px 0;text-align:center">Loading settings…</div>';
  try {
    settingsData = await api('/settings');
  } catch (e) {
    document.getElementById('content').innerHTML = '<div style="color:var(--red);font-size:12px;padding:40px 0;text-align:center">Could not load settings. Try again.</div>';
    return;
  }
  const s = settingsData;

  document.getElementById('content').innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:800px">

      <div class="card">
        <div class="card-title">Store &amp; AI curator</div>
        <div style="font-size:11px;color:var(--t3);margin-bottom:10px;line-height:1.6">These fields are rendered into the Gemini curator prompt that scores every scraped product.</div>
        <div class="form-row">
          <div><label>Store name</label><input type="text" id="s-store-name" value="${escHtml(s.store_name || '')}" placeholder="Tskvili"/></div>
          <div><label>Sell price range (₾)</label>
            <div style="display:flex;gap:6px;align-items:center">
              <input type="number" id="s-price-min" value="${s.sell_price_min ?? 40}" min="0" step="1" style="flex:1"/>
              <span style="color:var(--t3)">–</span>
              <input type="number" id="s-price-max" value="${s.sell_price_max ?? 119}" min="0" step="1" style="flex:1"/>
            </div>
          </div>
        </div>
        <div class="form-group">
          <label>Target audience</label>
          <input type="text" id="s-audience" value="${escHtml(s.target_audience || '')}" placeholder="Gen-Z couples in Georgia (ages 16–26)…"/>
        </div>
        <div class="form-group">
          <label>Niche / store focus</label>
          <textarea id="s-niche" rows="2" style="resize:vertical">${escHtml(s.niche || '')}</textarea>
        </div>
        <div class="form-group">
          <label>Example products that sell</label>
          <textarea id="s-examples" rows="2" style="resize:vertical">${escHtml(s.example_products || '')}</textarea>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Instagram</div>
        <div class="form-group">
          <label>Instagram username <span style="color:var(--t3);font-weight:400">(display only)</span></label>
          <input type="text" id="s-instagram" value="${s.instagram_username || ''}" placeholder="@yourstore"/>
        </div>
        <div class="form-group">
          <label>Instagram Business Account ID</label>
          <div style="display:flex;gap:8px;align-items:center">
            <input type="text" id="s-ig-user-id" value="${s.instagram_user_id || ''}" placeholder="17841400000000000" style="flex:1"/>
            <button class="btn btn-sm" onclick="detectIgAccount()" style="white-space:nowrap;flex-shrink:0">Auto-detect</button>
          </div>
          <div id="ig-detect-result" style="font-size:11px;margin-top:5px;color:var(--t3)">
            Paste your token first, then click Auto-detect to find the correct ID automatically.
          </div>
        </div>
        <div class="form-group">
          <label>Page Access Token</label>
          <input type="password" id="s-ig-token" value="" placeholder="${s.instagram_access_token_set ? '••••  saved — paste to replace' : 'EAABs…'}"/>
          <div style="font-size:11px;margin-top:5px;color:${s.instagram_access_token_set && s.instagram_user_id ? 'var(--green)' : 'var(--t3)'}">
            ${s.instagram_access_token_set && s.instagram_user_id
              ? '✓ Graph API configured — posts will publish directly to Instagram'
              : 'Not set — posts will be simulated (add token + account ID above)'}
          </div>
        </div>
        <div class="form-group">
          <label>Public app URL <span style="color:var(--t3);font-weight:400">(optional)</span></label>
          <input type="text" id="s-public-url" value="${escHtml(s.public_base_url || '')}" placeholder="https://dropos.example.com"/>
          <div style="font-size:11px;color:var(--t3);margin-top:5px">Only if this server is reachable from the internet (hosted or tunnelled). Used for the webhook URL and as an image proxy for Instagram.</div>
        </div>
        <div class="card-sm" style="margin-top:4px;border-color:${s.image_storage_set ? 'rgba(34,197,94,.3)' : 'rgba(245,158,11,.35)'}">
          <div style="font-size:11px;line-height:1.6;color:${s.image_storage_set ? 'var(--green)' : 'var(--amber)'}">
            ${s.image_storage_set
              ? '✓ Image storage (Supabase) configured — approved product photos are re-hosted on a public URL Instagram can fetch.'
              : 'Image storage not configured. Instagram can only post images it can download from a <b>public</b> URL — supplier CDN links usually work, but for reliability add <code>SUPABASE_URL</code> + <code>SUPABASE_SERVICE_ROLE_KEY</code> (free tier) to <code>.env</code> and restart.'}
          </div>
        </div>
        <div class="card-sm" style="margin-top:4px">
          <div style="font-size:11px;color:var(--t3);line-height:1.6">
            <b style="color:var(--t1)">Setup (one time):</b><br>
            1. developers.facebook.com → your app → Add product: <b>Instagram Graph API</b><br>
            2. Graph API Explorer → select your app → Generate Token with permissions:<br>
            &nbsp;&nbsp;&nbsp;<code style="color:var(--accent)">instagram_basic</code> &nbsp;<code style="color:var(--accent)">instagram_content_publish</code> &nbsp;<code style="color:var(--accent)">pages_read_engagement</code><br>
            3. Exchange for a long-lived token (60 days): Access Token Debugger → Extend<br>
            4. GET <code>/me/accounts</code> → find your Page → GET <code>/{page-id}?fields=instagram_business_account</code> → copy the ID<br>
            <br>
            Official API — no proxy needed, no ban risk. Image must be a public HTTPS URL (CDN links from 1688 work fine).
          </div>
        </div>
      </div>

      <div class="card" style="grid-column:1/-1">
        <div class="card-title">Comment &amp; DM auto-reply</div>
        <div class="card-sm" style="margin-bottom:12px;font-size:11px;color:var(--t3);line-height:1.6">
          Replies are sent through the Graph API when a comment / DM matches a rule below. Meta must be able to reach this server:
          the webhook URL has to be <b>public HTTPS</b> (a hosted deployment or a tunnel such as Cloudflare Tunnel / ngrok when running on your PC).
          Token permissions: <code>instagram_manage_comments</code>, <code>instagram_manage_messages</code>.
        </div>
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none">
            <input type="checkbox" id="s-autoreply-enabled" ${s.instagram_auto_reply_enabled ? 'checked' : ''}
              onchange="document.getElementById('autoreply-body').style.opacity=this.checked?'1':'0.45'"
              style="width:16px;height:16px;accent-color:var(--accent)"/>
            <span style="font-size:13px">Enable auto-reply to comments</span>
          </label>
          <span style="font-size:11px;color:var(--t3)">— replies are sent via Graph API, no delay, 24/7</span>
        </div>

        <div id="autoreply-body" style="opacity:${s.instagram_auto_reply_enabled ? '1' : '0.45'};transition:opacity .2s">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px">
            <div>
              <label style="font-size:11px;color:var(--t3);display:block;margin-bottom:4px">Webhook URL <span style="color:var(--t4)">(paste into Meta App Dashboard → Webhooks)</span></label>
              <div style="font-family:var(--ff-m);font-size:11px;background:var(--s3);padding:7px 10px;border-radius:var(--r);color:var(--accent);word-break:break-all" id="webhook-url-display">
                ${escHtml((s.public_base_url || window.location.origin).replace(/\/$/, ''))}/api/instagram/webhook
              </div>
              ${!/^https:/.test(s.public_base_url || window.location.origin) ? `<div style="font-size:10px;color:var(--amber);margin-top:4px">Not HTTPS / not public — set “Public app URL” above to your tunnel or host URL.</div>` : ''}
            </div>
            <div>
              <label style="font-size:11px;color:var(--t3);display:block;margin-bottom:4px">Verify token <span style="color:var(--t4)">(copy this into Meta webhook verify token field)</span></label>
              <input type="text" id="s-webhook-token" value="${escHtml(s.instagram_webhook_token || 'dropos_webhook_secret')}" style="font-family:var(--ff-m);font-size:12px"/>
              <label style="font-size:11px;color:var(--t3);display:block;margin:8px 0 4px">Meta app secret <span style="color:var(--t4)">(optional — verifies webhook signatures)</span></label>
              <input type="password" id="s-ig-app-secret" value="" placeholder="${s.instagram_app_secret_set ? '••••  saved — paste to replace' : 'App Dashboard → Settings → Basic → App secret'}" style="font-family:var(--ff-m);font-size:12px"/>
            </div>
          </div>

          <div style="font-size:12px;font-weight:600;color:var(--t2);margin-bottom:8px">Reply rules <span style="color:var(--t3);font-weight:400">— first matching rule wins. Leave keywords empty for a catch-all default reply.</span></div>
          <div id="reply-rules-list" style="display:flex;flex-direction:column;gap:8px;margin-bottom:10px">
            ${(s.instagram_reply_rules || []).map((r,i) => `
              <div class="reply-rule-row" style="display:grid;grid-template-columns:1fr 1.5fr auto;gap:8px;align-items:start">
                <div>
                  <div style="font-size:10px;color:var(--t3);margin-bottom:3px">Keywords (comma-separated)</div>
                  <input type="text" class="rule-keywords" value="${(r.keywords||[]).join(', ')}" placeholder="price, cost, how much"/>
                </div>
                <div>
                  <div style="font-size:10px;color:var(--t3);margin-bottom:3px">Auto-reply message</div>
                  <input type="text" class="rule-reply" value="${r.reply||''}" placeholder="DM us for pricing! 💌"/>
                </div>
                <button onclick="this.closest('.reply-rule-row').remove()" style="margin-top:17px;background:var(--red-d);color:var(--red);border:none;border-radius:var(--r);padding:6px 10px;cursor:pointer;font-size:12px">✕</button>
              </div>
            `).join('')}
          </div>
          <button class="btn btn-sm" onclick="addReplyRule()">+ Add rule</button>

          <div style="margin-top:20px;border-top:1px solid var(--b1);padding-top:16px">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
              <label style="display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none">
                <input type="checkbox" id="s-dm-enabled" ${s.instagram_dm_reply_enabled ? 'checked' : ''}
                  onchange="document.getElementById('dm-rules-body').style.opacity=this.checked?'1':'0.45'"
                  style="width:16px;height:16px;accent-color:var(--accent)"/>
                <span style="font-size:13px;font-weight:600">Enable DM auto-reply</span>
              </label>
              <span style="font-size:11px;color:var(--t3)">— replies sent to anyone who DMs your account</span>
            </div>
            <div id="dm-rules-body" style="opacity:${s.instagram_dm_reply_enabled ? '1' : '0.45'};transition:opacity .2s">
              <div style="font-size:11px;color:var(--amber);margin-bottom:8px">
                Requires <code>instagram_manage_messages</code> permission in your Meta app + subscribe to <b>messages</b> webhook field.
              </div>
              <div style="font-size:12px;font-weight:600;color:var(--t2);margin-bottom:8px">DM reply rules</div>
              <div id="dm-rules-list" style="display:flex;flex-direction:column;gap:8px;margin-bottom:10px">
                ${(s.instagram_dm_rules || []).map((r,i) => `
                  <div class="dm-rule-row" style="display:grid;grid-template-columns:1fr 1.5fr auto;gap:8px;align-items:start">
                    <div>
                      <div style="font-size:10px;color:var(--t3);margin-bottom:3px">Keywords (comma-separated)</div>
                      <input type="text" class="dm-rule-keywords" value="${(r.keywords||[]).join(', ')}" placeholder="price, link, buy"/>
                    </div>
                    <div>
                      <div style="font-size:10px;color:var(--t3);margin-bottom:3px">Auto-reply message</div>
                      <input type="text" class="dm-rule-reply" value="${r.reply||''}" placeholder="Hi! Check our link in bio 🛍️"/>
                    </div>
                    <button onclick="this.closest('.dm-rule-row').remove()" style="margin-top:17px;background:var(--red-d);color:var(--red);border:none;border-radius:var(--r);padding:6px 10px;cursor:pointer;font-size:12px">✕</button>
                  </div>
                `).join('')}
              </div>
              <button class="btn btn-sm" onclick="addDmRule()">+ Add rule</button>
            </div>
          </div>

          <div style="margin-top:16px;border-top:1px solid var(--b1);padding-top:14px">
            <div style="font-size:12px;font-weight:600;color:var(--t2);margin-bottom:6px">Reply log <span style="color:var(--t3);font-weight:400">(comments + DMs)</span></div>
            <div id="reply-log-list" style="font-size:11px;color:var(--t3)">Loading…</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Filter thresholds</div>
        <div class="form-row">
          <div><label>Min margin (%)</label><input type="number" id="s-margin" value="${s.min_margin ?? 60}" step="5" min="0" max="95"/>
            <div style="font-size:11px;color:var(--t3);margin-top:4px">Relaxed to 45% automatically when cost &gt; ₾30.</div></div>
          <div><label>Min rating <span style="color:var(--t3);font-weight:400">(Taobao only)</span></label><input type="number" id="s-rating" value="${s.min_rating ?? 4.5}" step="0.1" min="1" max="5"/>
            <div style="font-size:11px;color:var(--t3);margin-top:4px">1688 listings are ranked by orders instead.</div></div>
        </div>
        <div style="font-size:11px;color:var(--t3);line-height:1.6;margin-top:4px">
          Products scoring below <b>6.0</b> from the AI curator are rejected automatically; 6.0–7.0 land in Review as <i>pending review</i>.
        </div>
      </div>

      <div class="card">
        <div class="card-title">Pricing & markup</div>
        <div class="form-group">
          <label>CNY → GEL rate</label>
          <input type="number" id="s-exchange" value="${s.exchange_rate ?? 0.353}" step="0.001" min="0.01"/>
        </div>
        <div class="form-group">
          <label>Markup · landed cost &lt; ₾10 (×)</label>
          <input type="number" id="s-ml" value="${s.sell_markup_low ?? 3.5}" step="0.1" min="1"/>
        </div>
        <div class="form-group">
          <label>Markup · everything else (×)</label>
          <input type="number" id="s-mm" value="${s.sell_markup_mid ?? 2.8}" step="0.1" min="1"/>
        </div>
        <div class="form-group">
          <label>Markup · electronics / cameras (×)</label>
          <input type="number" id="s-mh" value="${s.sell_markup_high ?? 2.2}" step="0.1" min="1"/>
        </div>
        <div style="font-size:11px;color:var(--t3);line-height:1.6">Landed cost = (item price + ¥10 shipping for 1688 / ¥15 Taobao) × rate. Sell prices snap to ₾29.90 / ₾44.90 / ₾64.90 / x.90.</div>
      </div>

      <div class="card">
        <div class="card-title">AI &amp; API keys</div>

        <!-- Gemini -->
        <div class="api-key-row">
          <div class="api-key-header">
            <div>
              <span class="api-key-name">🤖 Gemini AI</span>
              <span class="api-key-badge ${s.gemini_key_set ? 'badge-active' : 'badge-missing'}">${s.gemini_key_set ? '✓ Active' : '⚠ Not set'}</span>
            </div>
            <button class="btn btn-sm btn-test" onclick="testApiKey('gemini')" id="test-gemini-btn">Test</button>
          </div>
          <div style="font-size:11px;color:var(--t3);margin-bottom:8px">Image analysis · AI assistant · product scoring · <a href="https://aistudio.google.com" target="_blank" style="color:var(--accent)">Free key →</a></div>
          <input type="password" id="s-gemini" value="" placeholder="${s.gemini_key_set ? '••••  saved — paste new key to replace' : 'AIzaSy…  (get free key at aistudio.google.com)'}"/>
          <div style="display:flex;gap:8px;align-items:center;margin-top:8px">
            <label style="font-size:11px;color:var(--t3);white-space:nowrap;margin:0">Model</label>
            <input type="text" id="s-gemini-model" value="${escHtml(s.gemini_model || 'gemini-2.5-flash-lite')}" placeholder="gemini-2.5-flash-lite" style="font-family:var(--ff-m);font-size:12px"/>
          </div>
          <div id="gemini-test-result" style="font-size:11px;margin-top:5px;display:none"></div>
        </div>

        <!-- Groq -->
        <div class="api-key-row">
          <div class="api-key-header">
            <div>
              <span class="api-key-name">⚡ Groq</span>
              <span class="api-key-badge ${s.groq_key_set ? 'badge-active' : 'badge-missing'}">${s.groq_key_set ? '✓ Active' : '⚠ Not set'}</span>
            </div>
            <button class="btn btn-sm btn-test" onclick="testApiKey('groq')" id="test-groq-btn">Test</button>
          </div>
          <div style="font-size:11px;color:var(--t3);margin-bottom:8px">Free text AI fallback · 14,400 req/day · <a href="https://console.groq.com" target="_blank" style="color:var(--accent)">Free key →</a></div>
          <input type="password" id="s-groq" value="" placeholder="${s.groq_key_set ? '••••  saved — paste new key to replace' : 'gsk_…  (get free key at console.groq.com)'}"/>
          <div id="groq-test-result" style="font-size:11px;margin-top:5px;display:none"></div>
        </div>

        <!-- Clipdrop -->
        <div class="api-key-row" style="border-bottom:none">
          <div class="api-key-header">
            <div>
              <span class="api-key-name">🖼 Clipdrop</span>
              <span class="api-key-badge ${s.clipdrop_key_set ? 'badge-active' : 'badge-missing'}">${s.clipdrop_key_set ? '✓ Active' : '⚠ Not set'}</span>
            </div>
          </div>
          <div style="font-size:11px;color:var(--t3);margin-bottom:8px">Remove Chinese watermarks from product images · 100 free/month · <a href="https://clipdrop.co/apis" target="_blank" style="color:var(--accent)">Get key →</a></div>
          <input type="password" id="s-clipdrop" value="" placeholder="${s.clipdrop_key_set ? '••••  saved — paste new key to replace' : 'sk_…  (get key at clipdrop.co/apis)'}"/>
        </div>

        <div class="card-sm" style="margin-top:8px;background:rgba(var(--green-rgb,34,197,94),0.08);border-color:rgba(var(--green-rgb,34,197,94),0.2)">
          <div style="font-size:11px;color:var(--t2);line-height:1.7">
            <b style="color:var(--t1)">Priority:</b> Gemini first (image analysis) → Groq fallback (free) → rule-based.<br>
            <b style="color:var(--t1)">Minimum:</b> Add Gemini key — it's 100% free at aistudio.google.com.<br>
            <b style="color:var(--t1)">Tip:</b> After saving a key, click <b>Test</b> to verify it works.
          </div>
        </div>

        <div style="margin-top:14px;padding-top:14px;border-top:1px solid var(--border)">
          <label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer;user-select:none">
            <input type="checkbox" id="s-context-injection" ${s.ai_context_injection ? 'checked' : ''}
              style="width:16px;height:16px;margin-top:2px;flex-shrink:0;accent-color:var(--accent)"/>
            <div>
              <div style="font-size:13px;color:var(--t1);font-weight:500">Decision-memory context injection</div>
              <div style="font-size:11px;color:var(--t3);margin-top:3px;line-height:1.6">
                When ON, appends a compact summary of past accepted/rejected decisions to the Gemini scoring prompt.
                Default: OFF. Requires at least 10 reviewed products to have any effect.
                Use <b>Analytics → Injection Stats</b> to compare results.
              </div>
            </div>
          </label>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Scheduled scan keywords</div>
        <div style="font-size:11px;color:var(--t3);margin-bottom:10px;line-height:1.6">Keywords the server scans on its interval (<code>SCRAPE_INTERVAL</code> env, default every hour) and the default list for the local scraper. One per line.</div>
        <div class="form-group">
          <textarea id="s-scan-kw" rows="5" style="font-family:var(--ff-m);font-size:12px;resize:vertical">${escHtml((s.scan_keywords || []).join('\n'))}</textarea>
        </div>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <button class="btn btn-sm" onclick="triggerScheduledScan()" ${s.local_scraping_only ? 'disabled title="Server-side scraping is off (local scraping only)"' : ''}>Run scan with these keywords now</button>
          <span id="sched-status" style="font-size:11px;color:var(--t3)">Loading scheduler…</span>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Instagram posting schedule</div>
        <label style="display:flex;align-items:center;gap:8px;margin-bottom:12px;font-size:12px;color:var(--t2);cursor:pointer">
          <input type="checkbox" id="s-post-enabled" ${s.post_schedule_enabled ? 'checked' : ''} style="width:16px;height:16px;accent-color:var(--accent)"/>
          Auto-post the top approved product at peak hours
        </label>
        <div class="form-row">
          <div><label>Post times (HH:MM, comma-separated)</label><input type="text" id="s-post-times" value="${escHtml((s.post_times || ['19:00','21:00']).join(', '))}" placeholder="19:00, 21:00"/></div>
          <div><label>Timezone</label><input type="text" id="s-post-tz" value="${escHtml(s.post_timezone || 'Asia/Tbilisi')}" placeholder="Asia/Tbilisi"/></div>
        </div>
        <div class="form-group">
          <label>Products per slot</label>
          <input type="number" id="s-posts-per-slot" value="${s.posts_per_slot ?? 1}" min="1" max="5" style="max-width:120px"/>
        </div>
        <div id="posting-status" style="font-size:11px;color:var(--t3);line-height:1.6">Loading…</div>
      </div>

      <div class="card">
        <div class="card-title">CSSBuy scraper</div>
        <label style="display:flex;align-items:center;gap:8px;margin-bottom:14px;font-size:12px;color:var(--t2)">
          <input type="checkbox" id="s-local-only" ${s.local_scraping_only ? 'checked' : ''}/>
          Store data here, scrape locally only
        </label>
        <div class="form-group">
          <label>Ingest API token</label>
          <input type="password" id="s-ingest-token" value="" placeholder="${s.ingest_api_token_set ? 'Configured - leave blank to keep current token' : 'Create a private upload token'}"/>
          <div style="font-size:11px;margin-top:5px;color:${s.ingest_api_token_set ? 'var(--green)' : 'var(--t3)'}">
            ${s.ingest_api_token_set ? 'Configured' : 'Required for local uploads'}
          </div>
        </div>
        <div style="font-size:11px;color:var(--t3);margin-bottom:10px;line-height:1.6">
          Logs into cssbuy.com with Playwright and intercepts search results.
          Session is saved after first login — captcha rarely appears again.
        </div>
        <div class="form-group">
          <label>CSSBuy username / email</label>
          <input type="text" id="s-cssbuy-user" value="${s.cssbuy_username || ''}" placeholder="your@email.com"/>
        </div>
        <div class="form-group">
          <label>CSSBuy password</label>
          <input type="password" id="s-cssbuy-pass" value="" placeholder="${s.cssbuy_password_set ? 'Configured - leave blank to keep current password' : ''}"/>
          <div style="font-size:11px;margin-top:5px;color:${s.cssbuy_password_set ? 'var(--green)' : 'var(--t3)'}">
            ${s.cssbuy_password_set ? 'Configured' : 'Not set'}
          </div>
        </div>
        <div class="form-group">
          <label>Source platform</label>
          <select id="s-cssbuy-source">
            <option value="1688"   ${String(s.cssbuy_source||'1688')==='1688'   ? 'selected':''}>1688 — real sales data, filtered &amp; ranked by orders</option>
            <option value="taobao" ${String(s.cssbuy_source||'')==='taobao' ? 'selected':''}>Taobao — broader catalog, no sales filter</option>
            <option value="both"   ${String(s.cssbuy_source||'')==='both'   ? 'selected':''}>Both — 1688 + Taobao combined</option>
          </select>
        </div>
        <div class="form-group">
          <label>2captcha API key <span style="color:var(--t3);font-weight:400">(optional — for auto captcha solve)</span></label>
          <input type="password" id="s-captcha-key" value="" placeholder="${s.captcha_2captcha_key_set ? '••••  saved — paste to replace' : '2captcha key…'}"/>
          <div style="font-size:11px;margin-top:5px;color:${s.captcha_2captcha_key_set ? 'var(--green)' : 'var(--t3)'}">
            ${s.captcha_2captcha_key_set ? '✓ Auto captcha enabled' : 'Not set — browser opens visibly on first login so you can solve captcha manually'}
          </div>
        </div>
        <div class="card-sm" style="margin-top:4px">
          <div style="font-size:11px;color:var(--t3);line-height:1.6">
            First run: save settings, then start a scan — browser will open for manual captcha if no 2captcha key.
            After first login the session is saved and captcha won't appear again.
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Google Sheets online backup</div>
        <div style="font-size:11px;color:var(--t3);margin-bottom:10px">Settings and product data are restored from this spreadsheet after deploys.</div>
        <div class="form-group">
          <label>Spreadsheet ID</label>
          <input type="text" id="s-sheets-id" value="${s.google_sheets_id || ''}" placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"/>
          <div style="font-size:11px;color:var(--t3);margin-top:4px">Found in the sheet URL after /d/</div>
        </div>
        <div class="form-group">
          <label>Service account credentials path (optional)</label>
          <input type="text" id="s-sheets-creds" value="${s.google_sheets_credentials || ''}" placeholder="/path/to/service-account.json"/>
          <div style="font-size:11px;color:var(--t3);margin-top:4px">Prefer server env var <code>GOOGLE_SERVICE_ACCOUNT_JSON</code> in production.</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-sm" onclick="backupToSheets()">Backup DB now</button>
          <button class="btn btn-sm btn-amber" onclick="restoreFromSheets()">Restore from Sheets</button>
          <button class="btn btn-sm" onclick="exportToSheets()">Export approved list</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">This installation</div>
        <div style="font-size:11px;color:var(--t3);line-height:1.9;font-family:var(--ff-m)">
          <div>Database: <span style="color:var(--t1)">${s.runtime?.embedded_db ? 'embedded PostgreSQL (data/pg)' : 'external PostgreSQL (DATABASE_URL)'}</span></div>
          <div>Data dir: <span style="color:var(--t1)">${escHtml(s.runtime?.data_dir || '—')}</span></div>
          <div>Mode: <span style="color:var(--t1)">${s.runtime?.production ? 'production' : 'development'}</span> · API docs ${s.runtime?.production ? 'hidden' : `<a href="/docs" target="_blank" style="color:var(--accent)">/docs</a>`}</div>
          <div>Image storage: <span style="color:${s.image_storage_set ? 'var(--green)' : 'var(--amber)'}">${s.image_storage_set ? 'Supabase' : 'none (supplier CDN URLs)'}</span></div>
        </div>
        <div style="font-size:11px;color:var(--t3);margin-top:8px;line-height:1.6">Back up by copying the data directory (and your <code>.env</code>). Keys pasted here are stored in the database.</div>
      </div>

      <div class="card" style="border:1px solid var(--red-d)">
        <div class="card-title" style="color:var(--red)">Danger zone</div>
        <div style="font-size:11px;color:var(--t3);margin-bottom:12px">Permanently delete all products, jobs, and history. This action cannot be undone.</div>
        <button class="btn btn-sm btn-danger" onclick="resetDatabase()">Reset database</button>
      </div>

    </div>`;
  setTimeout(loadSchedulerStatus, 150);
  setTimeout(loadReplyLog, 200);
}

async function loadSchedulerStatus() {
  try {
    const st = await api('/scheduler/status');
    const el = document.getElementById('sched-status');
    if (el) {
      if (st.running && st.jobs?.length) {
        const secs = st.jobs[0]?.interval || 3600;
        const every = secs >= 3600 ? `${Math.round(secs / 3600 * 10) / 10}h` : `${Math.round(secs / 60)}min`;
        el.textContent = `Server scan loop running — every ${every}`;
      } else {
        el.textContent = settingsData.local_scraping_only ? 'Server scraping off — upload from the local scraper' : 'Scan loop not running';
      }
    }
    const pel = document.getElementById('posting-status');
    if (pel) {
      const jobs = st.posting?.jobs || [];
      if (!st.posting?.running) pel.textContent = 'Posting scheduler not running';
      else if (!jobs.length) pel.textContent = 'No post times planned';
      else {
        const enabled = !!settingsData.post_schedule_enabled;
        pel.innerHTML = (enabled ? '<span style="color:var(--green)">Enabled</span>' : '<span style="color:var(--amber)">Planned but disabled</span>')
          + ' · next: ' + jobs.map(j => j.next_run ? escHtml(new Date(j.next_run).toLocaleString(undefined, { weekday:'short', hour:'2-digit', minute:'2-digit' })) : '—').join(', ');
      }
    }
  } catch(e) {
    const el = document.getElementById('sched-status');
    if (el) el.textContent = 'Backend offline';
  }
}

function addReplyRule() {
  const list = document.getElementById('reply-rules-list');
  const row = document.createElement('div');
  row.className = 'reply-rule-row';
  row.style.cssText = 'display:grid;grid-template-columns:1fr 1.5fr auto;gap:8px;align-items:start';
  row.innerHTML = `
    <div>
      <div style="font-size:10px;color:var(--t3);margin-bottom:3px">Keywords (comma-separated)</div>
      <input type="text" class="rule-keywords" placeholder="price, cost, how much"/>
    </div>
    <div>
      <div style="font-size:10px;color:var(--t3);margin-bottom:3px">Auto-reply message</div>
      <input type="text" class="rule-reply" placeholder="DM us for pricing! 💌"/>
    </div>
    <button onclick="this.closest('.reply-rule-row').remove()" style="margin-top:17px;background:var(--red-d);color:var(--red);border:none;border-radius:var(--r);padding:6px 10px;cursor:pointer;font-size:12px">✕</button>
  `;
  list.appendChild(row);
}

function _collectReplyRules() {
  return [...document.querySelectorAll('.reply-rule-row')].map(row => ({
    keywords: (row.querySelector('.rule-keywords')?.value || '')
      .split(',').map(k => k.trim()).filter(Boolean),
    reply: row.querySelector('.rule-reply')?.value?.trim() || '',
  })).filter(r => r.reply);
}

function addDmRule() {
  const list = document.getElementById('dm-rules-list');
  const row = document.createElement('div');
  row.className = 'dm-rule-row';
  row.style.cssText = 'display:grid;grid-template-columns:1fr 1.5fr auto;gap:8px;align-items:start';
  row.innerHTML = `
    <div>
      <div style="font-size:10px;color:var(--t3);margin-bottom:3px">Keywords (comma-separated)</div>
      <input type="text" class="dm-rule-keywords" placeholder="price, link, buy"/>
    </div>
    <div>
      <div style="font-size:10px;color:var(--t3);margin-bottom:3px">Auto-reply message</div>
      <input type="text" class="dm-rule-reply" placeholder="Hi! Check our link in bio 🛍️"/>
    </div>
    <button onclick="this.closest('.dm-rule-row').remove()" style="margin-top:17px;background:var(--red-d);color:var(--red);border:none;border-radius:var(--r);padding:6px 10px;cursor:pointer;font-size:12px">✕</button>
  `;
  list.appendChild(row);
}

function _collectDmRules() {
  return [...document.querySelectorAll('.dm-rule-row')].map(row => ({
    keywords: (row.querySelector('.dm-rule-keywords')?.value || '')
      .split(',').map(k => k.trim()).filter(Boolean),
    reply: row.querySelector('.dm-rule-reply')?.value?.trim() || '',
  })).filter(r => r.reply);
}

async function loadReplyLog() {
  const el = document.getElementById('reply-log-list');
  if (!el) return;
  try {
    const rows = await api('/instagram/reply-log', 'GET');
    if (!rows.length) { el.textContent = 'No replies sent yet.'; return; }
    el.innerHTML = rows.slice(0, 20).map(r =>
      `<div style="padding:4px 0;border-bottom:1px solid var(--b1)">
        <span style="color:var(--t2)">${r.replied_at?.slice(0,16).replace('T',' ')}</span>
        &nbsp;→&nbsp; ${r.matched_rule?.slice(0,60)}
      </div>`
    ).join('');
  } catch { el.textContent = 'Could not load log.'; }
}

async function resetDatabase() {
  if (!confirm('Are you absolutely sure? This will delete ALL products, scans, and history from the database. This cannot be undone.')) return;
  if (!confirm('Final confirmation: You are about to wipe your entire catalog. Continue?')) return;
  
  try {
    const res = await api('/admin/reset-database', 'POST');
    if (res.ok) {
      toast('Database reset successfully', 'success');
      refreshStats();
      navigate('dashboard');
    }
  } catch (e) {
    toast('Reset failed: ' + e.message, 'error');
  }
}

async function detectIgAccount() {
  const el = document.getElementById('ig-detect-result');
  el.style.color = 'var(--t3)';
  el.textContent = 'Detecting…';

  // Save token first so the backend can use it
  const token = document.getElementById('s-ig-token')?.value?.trim();
  if (!token) {
    el.style.color = 'var(--red)';
    el.textContent = 'Paste your Page Access Token first, then click Auto-detect.';
    return;
  }
  await api('/settings', 'PATCH', { instagram_access_token: token });

  try {
    const res = await api('/instagram/accounts', 'GET');
    const accounts = res.accounts || [];
    const found = accounts.filter(a => a.instagram_business_account_id);

    if (!found.length) {
      el.style.color = 'var(--red)';
      el.textContent = 'No Instagram Business Account found. Make sure your Instagram is set to Business or Creator and linked to a Facebook Page.';
      return;
    }

    // Auto-fill with the first match
    document.getElementById('s-ig-user-id').value = found[0].instagram_business_account_id;
    el.style.color = 'var(--green)';
    el.textContent = `✓ Found: ${found[0].page_name} → Instagram ID ${found[0].instagram_business_account_id}` +
      (found.length > 1 ? ` (${found.length - 1} more page(s) — change manually if needed)` : '');
  } catch(e) {
    el.style.color = 'var(--red)';
    el.textContent = `Error: ${e.message || e}`;
  }
}

async function triggerScheduledScan() {
  try {
    const res = await api('/scheduler/trigger', 'POST', {});
    toast(`Scan started (job #${res.job_id}) — follow it in Pipeline → Scan`, 'success');
    activeJob = { id: res.job_id, status: 'queued', progress: 0 };
    if (activeJobPoll) clearInterval(activeJobPoll);
    activeJobPoll = setInterval(pollActiveJob, 2000);
  } catch(e) {
    /* api() already toasted the server's message */
  }
}

async function exportToSheets() {
  try {
    const res = await api('/sheets/export', 'POST', {});
    toast(`Exported ${res.exported} products to Sheets${res.mock ? ' (mock)' : ''}`, 'success');
  } catch(e) {
    toast('Sheets export failed', 'error');
  }
}

async function backupToSheets() {
  try {
    const res = await api('/sheets/backup', 'POST', {});
    const savedProducts = res.products?.saved ?? 0;
    const savedSettings = res.settings?.saved ?? 0;
    toast(`Backed up ${savedProducts} products and ${savedSettings} settings`, 'success');
  } catch(e) {
    toast('Sheets backup failed', 'error');
  }
}

async function restoreFromSheets() {
  if (!confirm('Restore settings and products from Google Sheets? Current matching products will be updated.')) return;
  try {
    const res = await api('/sheets/restore', 'POST', {});
    toast(`Restored ${res.products || 0} products and ${res.settings || 0} settings`, 'success');
    await refreshStats();
    renderSettings();
  } catch(e) {
    toast('Sheets restore failed', 'error');
  }
}

async function testApiKey(provider) {
  const btnId = `test-${provider}-btn`;
  const resultId = `${provider}-test-result`;
  const btn = document.getElementById(btnId);
  const resultEl = document.getElementById(resultId);
  if (!btn || !resultEl) return;

  // Check if user typed a new key in the field
  const inputId = provider === 'gemini' ? 's-gemini' : 's-groq';
  const typedKey = document.getElementById(inputId)?.value?.trim() || '';

  btn.disabled = true;
  btn.textContent = 'Testing…';
  resultEl.style.display = 'block';
  resultEl.style.color = 'var(--t3)';
  resultEl.textContent = 'Connecting…';

  try {
    const body = { provider };
    if (typedKey) body.key = typedKey;
    const res = await api('/ai/test', 'POST', body);
    if (res.ok) {
      resultEl.style.color = 'var(--green)';
      resultEl.textContent = `✓ ${res.model || provider} working — ${res.latency_ms || '?'}ms`;
    } else {
      resultEl.style.color = 'var(--red)';
      resultEl.textContent = `✗ ${res.error || 'Connection failed'}`;
    }
  } catch(e) {
    resultEl.style.color = 'var(--red)';
    resultEl.textContent = `✗ ${e.message || 'Request failed'}`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test';
  }
}

async function saveSettings() {
  const saveBtn = document.getElementById('settings-save-btn');
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
  }
  const g = id => document.getElementById(id);
  const kwRaw = g('s-scan-kw')?.value || '';
  const scanKws = kwRaw.split('\n').map(s => s.trim()).filter(Boolean);
  const includeIfNonEmpty = (obj, key, value) => {
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (!trimmed) return;
      obj[key] = trimmed;
      return;
    }
    if (value !== null && value !== undefined) obj[key] = value;
  };
  const postTimes = (g('s-post-times')?.value || '')
    .split(',').map(t => t.trim()).filter(t => /^\d{1,2}:\d{2}$/.test(t));
  const data = {
    store_name:        g('s-store-name')?.value || '',
    niche:             g('s-niche')?.value,
    target_audience:   g('s-audience')?.value || '',
    example_products:  g('s-examples')?.value || '',
    sell_price_min:    parseFloat(g('s-price-min')?.value || 40),
    sell_price_max:    parseFloat(g('s-price-max')?.value || 119),
    post_schedule_enabled: g('s-post-enabled')?.checked ?? false,
    post_times:        postTimes.length ? postTimes : ['19:00', '21:00'],
    post_timezone:     g('s-post-tz')?.value?.trim() || 'Asia/Tbilisi',
    posts_per_slot:    Math.max(1, parseInt(g('s-posts-per-slot')?.value || 1)),
    instagram_username:          g('s-instagram')?.value,
    instagram_user_id:           g('s-ig-user-id')?.value           || '',
    instagram_auto_reply_enabled: g('s-autoreply-enabled')?.checked ?? false,
    instagram_reply_rules:        _collectReplyRules(),
    instagram_dm_reply_enabled:   g('s-dm-enabled')?.checked ?? false,
    instagram_dm_rules:           _collectDmRules(),
    min_margin:    parseFloat(g('s-margin')?.value    || 60),
    min_rating:    parseFloat(g('s-rating')?.value    || 4.5),
    exchange_rate: parseFloat(g('s-exchange')?.value  || 0.353),
    sell_markup_low:  parseFloat(g('s-ml')?.value || 3.5),
    sell_markup_mid:  parseFloat(g('s-mm')?.value || 2.8),
    sell_markup_high: parseFloat(g('s-mh')?.value || 2.2),
    scan_keywords:  scanKws,
    google_sheets_id:          g('s-sheets-id')?.value    || '',
    public_base_url:           g('s-public-url')?.value    || '',
    cssbuy_username:      g('s-cssbuy-user')?.value    || '',
    cssbuy_source:        g('s-cssbuy-source')?.value  || '1688',
    local_scraping_only:        g('s-local-only')?.checked ?? false,
    ai_context_injection:       g('s-context-injection')?.checked ?? false,
  };
  includeIfNonEmpty(data, 'instagram_access_token', g('s-ig-token')?.value);
  includeIfNonEmpty(data, 'instagram_webhook_token', g('s-webhook-token')?.value);
  includeIfNonEmpty(data, 'instagram_app_secret', g('s-ig-app-secret')?.value);
  includeIfNonEmpty(data, 'gemini_model', g('s-gemini-model')?.value);
  includeIfNonEmpty(data, 'gemini_key', g('s-gemini')?.value);
  includeIfNonEmpty(data, 'groq_key', g('s-groq')?.value);
  includeIfNonEmpty(data, 'clipdrop_key', g('s-clipdrop')?.value);
  includeIfNonEmpty(data, 'anthropic_key', g('s-anthropic')?.value);
  includeIfNonEmpty(data, 'google_sheets_credentials', g('s-sheets-creds')?.value);
  includeIfNonEmpty(data, 'cssbuy_password', g('s-cssbuy-pass')?.value);
  includeIfNonEmpty(data, 'captcha_2captcha_key', g('s-captcha-key')?.value);
  includeIfNonEmpty(data, 'ingest_api_token', g('s-ingest-token')?.value);
  try {
    await api('/settings', 'PATCH', data);
    toast('Settings saved ✓', 'success');
    loadSchedulerStatus();
    // Reload settings page to show updated key status indicators
    setTimeout(() => renderSettings(), 400);
  } catch (e) {
    toast(`Settings save failed: ${e.message || e}`, 'error');
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save settings';
    }
  }
}

// ── Pipeline ───────────────────────────────────────────────────────────────
let pipelineJobs = [];
let pipelineJobId = null;
let pipelineActiveStage = null;
let pipelineData = null;

const STAGE_ORDER = ['raw_fetch','basic_reject','profit_reject','dedup_reject','score_reject','ai_reject','ai_pass'];
const STAGE_LABELS = {
  raw_fetch:      'Fetched',
  basic_reject:  'Spam / No image',
  profit_reject: 'Low margin',
  dedup_reject:  'Duplicate',
  score_reject:  'Low raw score',
  ai_reject:     'AI rejected',
  ai_pass:       'AI passed',
};
const STAGE_TYPE = {
  raw_fetch:'neutral',
  basic_reject:'reject', profit_reject:'reject', dedup_reject:'reject',
  score_reject:'reject', ai_reject:'reject', ai_pass:'pass',
};

async function renderPipeline() {
  setTitle('Scan log', 'where each scraped product dropped out');
  const el = document.getElementById('content');

  // Load jobs list
  if (!pipelineJobs.length) {
    pipelineJobs = await api('/jobs?limit=30').catch(() => []);
  }
  if (!pipelineJobs.length) {
    el.innerHTML = `<div class="empty" style="margin-top:48px"><span class="empty-icon">○</span><h3>No scans yet</h3><p>Run a scan or upload from the local scraper first</p><button class="btn" style="margin-top:16px" onclick="navigate('scan')">New scan</button></div>`;
    return;
  }

  if (!pipelineJobId) pipelineJobId = pipelineJobs[0].id;

  // Load pipeline data for selected job
  const raw = await api(`/jobs/${pipelineJobId}/pipeline`).catch(() => null);
  pipelineData = raw?.stages || {};
  const job = raw?.job || {};
  const summary = raw?.summary || {};

  // Compute AI summary
  const aiPass = pipelineData['ai_pass'] || [];
  const aiReject = pipelineData['ai_reject'] || [];
  const aiTotal = aiPass.length + aiReject.length;
  const avgScore = aiPass.length ? (aiPass.reduce((s,p) => s + (p.ai_score||0), 0) / aiPass.length).toFixed(1) : '—';
  const avgNiche = aiPass.length ? (aiPass.reduce((s,p) => s + (p.ai_niche_fit||0), 0) / aiPass.length).toFixed(1) : '—';
  const avgVisual = aiPass.length ? (aiPass.reduce((s,p) => s + (p.ai_visual||0), 0) / aiPass.length).toFixed(1) : '—';
  const passRate = aiTotal ? Math.round(aiPass.length / aiTotal * 100) : 0;

  // Top rejection reason
  const reasons = [...(pipelineData['ai_reject']||[])].map(p=>p.filter_reason).filter(Boolean);
  const reasonCounts = {};
  reasons.forEach(r => { reasonCounts[r] = (reasonCounts[r]||0)+1; });
  const topReason = Object.entries(reasonCounts).sort((a,b)=>b[1]-a[1])[0]?.[0] || '—';

  if (!pipelineActiveStage) pipelineActiveStage = STAGE_ORDER.find(s => pipelineData[s]?.length) || 'ai_pass';

  const stageItems = pipelineData[pipelineActiveStage] || [];

  const jobOptions = pipelineJobs.map(j => `<option value="${j.id}" ${j.id===pipelineJobId?'selected':''}>Job #${j.id} — ${escHtml((j.keywords||[]).join(', ').substring(0,40))} (${escHtml(j.status||'')})</option>`).join('');

  el.innerHTML = `
    <div style="max-width:1100px">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
        <select style="background:var(--s2);color:var(--t1);border:1px solid var(--b2);border-radius:var(--r);padding:7px 12px;font-size:12px;flex:1;max-width:420px" onchange="pipelineJobId=+this.value;pipelineActiveStage=null;pipelineData=null;renderPage()">
          ${jobOptions}
        </select>
        <button class="btn btn-sm" onclick="clearScanHistory()">Clear history</button>
        <span style="font-size:11px;color:var(--t3)">${job.created_at ? new Date(job.created_at).toLocaleString() : ''}</span>
      </div>

      <div style="font-size:11px;color:var(--t3);text-transform:uppercase;letter-spacing:.7px;font-family:var(--ff-m);margin-bottom:10px">Pipeline Summary</div>
      <div class="pl-summary" style="margin-bottom:24px">
        <div class="pl-sum-card"><div class="pl-sum-label">Scraped</div><div class="pl-sum-val">${job.scraped??0}</div><div class="pl-sum-sub">raw products</div></div>
        <div class="pl-sum-card"><div class="pl-sum-label">After filter</div><div class="pl-sum-val">${job.after_basic??0}</div><div class="pl-sum-sub">passed quality checks</div></div>
        <div class="pl-sum-card"><div class="pl-sum-label">Profitable</div><div class="pl-sum-val">${job.after_profit??0}</div><div class="pl-sum-sub">passed margin checks</div></div>
        <div class="pl-sum-card"><div class="pl-sum-label">Deduped</div><div class="pl-sum-val">${job.after_dedup??0}</div><div class="pl-sum-sub">unique products</div></div>
        <div class="pl-sum-card"><div class="pl-sum-label">AI Pass rate</div><div class="pl-sum-val" style="color:var(--green)">${passRate}%</div><div class="pl-sum-sub">${aiPass.length} of ${aiTotal} reviewed</div></div>
        <div class="pl-sum-card"><div class="pl-sum-label">Avg AI score</div><div class="pl-sum-val">${avgScore}</div><div class="pl-sum-sub">passed products</div></div>
        <div class="pl-sum-card"><div class="pl-sum-label">Avg niche fit</div><div class="pl-sum-val">${avgNiche}</div><div class="pl-sum-sub">niche relevance</div></div>
        <div class="pl-sum-card"><div class="pl-sum-label">Avg visual</div><div class="pl-sum-val">${avgVisual}</div><div class="pl-sum-sub">photo quality</div></div>
        <div class="pl-sum-card"><div class="pl-sum-label">Top AI rejection</div><div class="pl-sum-val" style="font-size:13px;line-height:1.3">${topReason.substring(0,30)}</div><div class="pl-sum-sub">most common reason</div></div>
      </div>

      <div style="border:1px solid var(--b1);background:var(--s1);border-radius:var(--r);padding:16px;margin-bottom:24px">
        <div style="font-size:11px;color:var(--t3);text-transform:uppercase;letter-spacing:.7px;font-family:var(--ff-m);margin-bottom:8px">AI scan analysis</div>
        <div style="font-size:15px;color:var(--t1);font-weight:600;margin-bottom:10px">${summary.headline || `${aiPass.length} products accepted for review.`}</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px">
          <div>
            <div style="font-size:12px;color:var(--t3);margin-bottom:6px">Rejected mostly because</div>
            ${(summary.top_reasons||[]).length
              ? (summary.top_reasons||[]).map(r => `<div style="font-size:12px;color:var(--t2);margin-bottom:4px">${escHtml(r.reason)} <span style="color:var(--t4)">(${r.count})</span></div>`).join('')
              : `<div style="font-size:12px;color:var(--t4)">No rejection pattern yet</div>`}
          </div>
          <div>
            <div style="font-size:12px;color:var(--t3);margin-bottom:6px">Accepted examples</div>
            ${(summary.accepted_examples||[]).length
              ? (summary.accepted_examples||[]).map(p => `<div style="font-size:12px;color:var(--t2);margin-bottom:4px">${escHtml((p.title||'').substring(0,42))} <span style="color:var(--green)">${Number(p.composite_score||p.score||0).toFixed(1)}</span></div>`).join('')
              : `<div style="font-size:12px;color:var(--t4)">No accepted products yet</div>`}
          </div>
          <div>
            <div style="font-size:12px;color:var(--t3);margin-bottom:6px">Notes</div>
            ${(summary.recommendations||[]).length
              ? (summary.recommendations||[]).map(t => `<div style="font-size:12px;color:var(--t2);margin-bottom:4px">${escHtml(t)}</div>`).join('')
              : `<div style="font-size:12px;color:var(--t4)">Filters look balanced</div>`}
          </div>
        </div>
      </div>

      <div style="font-size:11px;color:var(--t3);text-transform:uppercase;letter-spacing:.7px;font-family:var(--ff-m);margin-bottom:10px">Filter stages</div>
      <div class="pl-flow">
        ${STAGE_ORDER.map((s,i) => `
          <div class="pl-stage ${STAGE_TYPE[s]} ${pipelineActiveStage===s?'active':''}" onclick="pipelineActiveStage='${s}';renderPage()">
            <div class="pl-stage-label">${STAGE_LABELS[s]}</div>
            <div class="pl-stage-count">${(pipelineData[s]||[]).length}</div>
          </div>
          ${i < STAGE_ORDER.length-1 ? '<div class="pl-arrow">›</div>' : ''}
        `).join('')}
      </div>

      <div style="font-size:11px;color:var(--t3);text-transform:uppercase;letter-spacing:.7px;font-family:var(--ff-m);margin-bottom:12px">
        ${STAGE_LABELS[pipelineActiveStage]} — ${stageItems.length} products
      </div>

      ${!stageItems.length
        ? `<div class="pl-empty">No products at this stage</div>`
        : `<div class="pl-grid">
            ${stageItems.map(p => `
              <div class="pl-card">
                ${p.image_url
                  ? `<img src="${imageUrl(p.image_url)}" loading="lazy" onerror="this.style.display='none'">`
                  : `<div style="width:100%;aspect-ratio:1;background:var(--s3);display:flex;align-items:center;justify-content:center;color:var(--t4);font-size:20px">?</div>`
                }
                <div class="pl-card-body">
                  <div class="pl-card-title">${escHtml(p.title||'—')}</div>
                  ${p.filter_reason ? `<div class="pl-card-reason">${escHtml(p.filter_reason)}</div>` : ''}
                  <div class="pl-card-score">
                    raw ${Number(p.raw_score||0).toFixed(0)}
                    ${p.ai_score ? ` · AI ${Number(p.ai_score||0).toFixed(1)}` : ''}
                    ${p.ai_provider ? ' · '+String(p.ai_provider).toUpperCase() : ''}
                  </div>
                  <div class="pl-card-meta">¥${p.price_cny?.toFixed(0)||0}${p.orders ? ' · '+p.orders+' sold' : ''}${p.rating ? ' · '+Number(p.rating).toFixed(1)+'★' : ''}</div>
                  ${p.ai_score ? `<div class="pl-card-meta">romantic ${Number(p.ai_niche_fit||p.niche_fit||0).toFixed(1)} · visual ${Number(p.ai_visual||p.visual_appeal||0).toFixed(1)} · trend ${Number(p.trend_score||0).toFixed(1)}</div>` : ''}
                  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
                    ${(p.url||p.link) ? `<a class="btn btn-sm" href="${safeUrl(p.url||p.link)}" target="_blank" rel="noopener">Item</a>` : ''}
                    ${(p.image_url||p.photo_link) ? `<a class="btn btn-sm" href="${safeUrl(p.image_url||p.photo_link)}" target="_blank" rel="noopener">Photo</a>` : ''}
                  </div>
                </div>
              </div>`).join('')}
          </div>`}
    </div>`;
}

// ── Router ─────────────────────────────────────────────────────────────────
async function clearScanHistory() {
  if (!confirm('Clear all scan job history? Product queue items will stay.')) return;
  try { await api('/jobs', 'DELETE'); toast('Scan history cleared', 'success'); } catch(e) { return; }
  resetPipelineState();
  activeJob = null;
  if (activeJobPoll) { clearInterval(activeJobPoll); activeJobPoll = null; }
  toast('Scan history cleared', 'success');
  await refreshStats();
  renderPipeline();
}

// ── Analytics sub-tabs ────────────────────────────────────────────────────────

let analyticsTab = 'overview';

function switchAnalyticsTab(tab) { analyticsTab = tab; renderAnalytics(); }

async function renderMarginsTab() {
  // Real numbers from approved + posted products
  const [a, l] = await Promise.all([
    api('/products?stage=REVIEWED&limit=200&sort=margin').catch(() => ({ products: [] })),
    api('/products?stage=LIVE&limit=200&sort=margin').catch(() => ({ products: [] })),
  ]);
  const products = [...(a.products || []), ...(l.products || [])]
    .filter(p => (p.sell_price_eur || 0) > 0)
    .sort((x, y) => (y.margin_pct || 0) - (x.margin_pct || 0));
  if (!products.length) {
    return `<div class="empty" style="margin-top:40px"><span class="empty-icon">₾</span><h3>No approved products yet</h3><p>Margins appear here once products are approved</p></div>`;
  }
  const avg = products.reduce((s, p) => s + (p.margin_pct || 0), 0) / products.length;
  const avgProfit = products.reduce((s, p) => s + ((p.sell_price_eur || 0) - (p.cost_eur || 0)), 0) / products.length;
  const rows = products.map(p => {
    const profit = ((p.sell_price_eur || 0) - (p.cost_eur || 0)).toFixed(2);
    const m = p.margin_pct || 0;
    const col = m >= 60 ? 'var(--green)' : m >= 45 ? 'var(--amber)' : 'var(--red)';
    return `<tr class="cat-row" style="cursor:pointer" onclick="showDetail(${p.id})">
      <td><span style="font-weight:500;color:var(--t1)">${escHtml(p.product_name || p.title_translated || '—')}</span></td>
      <td><span class="badge ${p.stage === 'LIVE' ? 'badge-blue' : 'badge-green'}">${p.stage === 'LIVE' ? 'Posted' : 'Approved'}</span></td>
      <td><span style="font-family:var(--ff-m);font-size:12px">¥${Number(p.price_cny || 0).toFixed(1)}</span></td>
      <td><span style="font-family:var(--ff-m);font-size:12px">₾${Number(p.cost_eur || 0).toFixed(2)}</span></td>
      <td><span style="font-family:var(--ff-m);font-size:12px;font-weight:600;color:var(--t1)">₾${Number(p.sell_price_eur || 0).toFixed(2)}</span></td>
      <td><span style="font-family:var(--ff-m);font-size:12px;color:var(--green)">₾${profit}</span></td>
      <td><span style="font-family:var(--ff-m);font-size:12px;font-weight:700;color:${col}">${m}%</span></td>
    </tr>`;
  }).join('');
  return `
    <div style="display:flex;align-items:center;gap:18px;margin-bottom:16px;flex-wrap:wrap;font-size:12px;color:var(--t3)">
      <span><b style="color:var(--t1)">${products.length}</b> products</span>
      <span>avg margin <b style="color:var(--green)">${avg.toFixed(1)}%</b></span>
      <span>avg profit <b style="color:var(--green)">₾${avgProfit.toFixed(2)}</b> / unit</span>
    </div>
    <div class="catalog-table-wrap">
      <table class="catalog-table">
        <thead><tr><th>Product</th><th>Stage</th><th>Supplier ¥</th><th>Landed ₾</th><th>Sell ₾</th><th>Profit</th><th>Margin</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

async function renderInsightsTab() {
  const recs = await api('/ai/recommendations').catch(() => ({ recommendations: [] }));
  const list = recs.recommendations || [];
  const riskCls = { low: 'badge-green', medium: 'badge-amber', high: 'badge-red' };
  const cards = list.map(r => {
    const f = r.payload || {};
    const change = f.proposed_change ? Object.entries(f.proposed_change).map(([k, v]) => `${escHtml(k)}: ${escHtml(typeof v === 'object' ? JSON.stringify(v) : String(v))}`).join(' · ') : '';
    return `<div class="card" style="margin-bottom:10px">
      <div style="display:flex;align-items:flex-start;gap:10px;justify-content:space-between">
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:600;color:var(--t1);margin-bottom:4px">${escHtml(r.headline || '')}</div>
          <div style="font-size:12px;color:var(--t2);line-height:1.6">${escHtml(f.detail || '')}</div>
          ${change ? `<div style="font-size:11px;color:var(--t3);font-family:var(--ff-m);margin-top:6px">Suggested: ${change}</div>` : ''}
          <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
            <span class="badge badge-gray">${escHtml(String(r.analysis_type || '').replace(/_/g,' '))}</span>
            <span class="badge ${riskCls[f.risk] || 'badge-gray'}">${escHtml(f.risk || 'low')} risk</span>
            <span class="badge badge-purple">${Math.round((f.confidence || 0) * 100)}% confidence</span>
          </div>
        </div>
        <button class="btn btn-sm" onclick="dismissRecommendation(${r.id})">Dismiss</button>
      </div>
    </div>`;
  }).join('');
  return `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px;flex-wrap:wrap">
      <div style="font-size:12px;color:var(--t3);line-height:1.6;max-width:620px">Deterministic analysis of your approve/reject history — score calibration, margin threshold drift, wasted categories and keywords. No AI calls; needs at least 15 reviewed products.</div>
      <button class="btn btn-sm btn-primary" id="analyze-btn" onclick="runAnalysis(this)">Analyze decisions</button>
    </div>
    <div id="insights-status" style="font-size:11px;color:var(--t3);margin-bottom:12px"></div>
    ${cards || `<div class="empty" style="margin-top:24px"><span class="empty-icon">◎</span><h3>No findings yet</h3><p>Review some products, then click “Analyze decisions”</p></div>`}`;
}

async function runAnalysis(btn) {
  if (btn) { btn.disabled = true; btn.textContent = 'Analyzing…'; }
  try {
    const res = await api('/ai/analyze', 'POST', {});
    const st = res.status || {};
    if (!st.ready) toast(st.reason || 'Not enough decisions yet', 'error', 5000);
    else toast(`${res.count} finding${res.count === 1 ? '' : 's'} from ${st.total} decisions`, 'success');
    renderAnalytics();
  } catch(e) {
    if (btn) { btn.disabled = false; btn.textContent = 'Analyze decisions'; }
  }
}

async function dismissRecommendation(id) {
  try { await api(`/ai/recommendations/${id}/dismiss`, 'POST'); renderAnalytics(); } catch(e) {}
}

const PAGE_RENDERERS = {
  dashboard: renderDashboard,
  scan:      renderScan,
  scans:     renderPipeline,
  queue:     renderQueue,
  textEdit:  renderTextEdit,
  REVIEWED:  renderApproved,
  LIVE:      renderPosted,
  REJECTED:  renderRejected,
  settings:  renderSettings,
  analytics: renderAnalytics,
  chat:      renderChat,
  catalog:   renderCatalog,
  login:     renderLogin,
};

async function renderLogin() {
  document.body.classList.add('is-login');
  const el = document.getElementById('content');
  // First run on a fresh install: no admin exists yet → show the setup form
  let needsSetup = false;
  try {
    const st = await fetch(API + '/auth/status').then(r => r.ok ? r.json() : null);
    needsSetup = !!(st && st.needs_setup);
  } catch(e) {}
  if (needsSetup) {
    el.innerHTML = `
      <div class="login-container">
        <div class="login-box">
          <div class="login-logo">D</div>
          <h2>Welcome to DropOS</h2>
          <p style="font-size:12px;color:var(--t3);margin:-6px 0 16px;line-height:1.6">Create the admin account for this installation. You'll use it to sign in from now on.</p>
          <form id="setup-form" onsubmit="handleSetup(event)">
            <div class="input-group">
              <label>Email</label>
              <input type="email" id="setup-email" required autocomplete="username" />
            </div>
            <div class="input-group">
              <label>Password <span style="color:var(--t4);font-weight:400">(min 8 characters)</span></label>
              <input type="password" id="setup-password" required minlength="8" autocomplete="new-password" />
            </div>
            <div id="login-error" style="display:none;color:var(--red,#e55);font-size:12px;margin-bottom:8px;text-align:center"></div>
            <button type="submit" class="btn login-btn" id="login-btn">Create account</button>
          </form>
        </div>
      </div>`;
    return;
  }
  el.innerHTML = `
    <div class="login-container">
      <div class="login-box">
        <div class="login-logo">D</div>
        <h2>DropOS Backoffice</h2>
        <form id="login-form" onsubmit="handleLogin(event)">
          <div class="input-group">
            <label>Email</label>
            <input type="email" id="login-email" required />
          </div>
          <div class="input-group">
            <label>Password</label>
            <input type="password" id="login-password" required />
          </div>
          <div id="login-error" style="display:none;color:var(--red,#e55);font-size:12px;margin-bottom:8px;text-align:center"></div>
          <button type="submit" class="btn login-btn" id="login-btn">Sign In</button>
        </form>
      </div>
    </div>
  `;
}

function _loginError(msg) {
  // Always re-query elements — DOM may have been replaced by bootApp
  const b = document.getElementById('login-btn');
  const e = document.getElementById('login-error');
  if (b) { b.textContent = 'Sign In'; b.disabled = false; }
  if (e) { e.textContent = msg; e.style.display = 'block'; }
}

async function handleLogin(ev) {
  ev.preventDefault();
  try {
    const btn = document.getElementById('login-btn');
    const errEl = document.getElementById('login-error');
    if (errEl) errEl.style.display = 'none';
    if (btn) { btn.textContent = 'Signing in...'; btn.disabled = true; }
    const email = (document.getElementById('login-email') || {}).value?.trim() || '';
    const password = (document.getElementById('login-password') || {}).value || '';
    if (!email || !password) { _loginError('Please enter your email and password.'); return; }
    const data = await api('/auth/login', 'POST', { email, password });
    if (!data || !data.token) {
      _loginError('Server error: no token returned.');
      return;
    }
    setToken(data.token);
    const ok = await bootApp();
    if (!ok) _loginError('Authenticated but session failed to load. Please try again.');
  } catch(err) {
    const msg = err.message === 'Unauthorized'
      ? 'Invalid email or password.'
      : (err.message || 'Login failed. Please try again.');
    _loginError(msg);
  }
}

async function handleSetup(ev) {
  ev.preventDefault();
  const btn = document.getElementById('login-btn');
  const errEl = document.getElementById('login-error');
  if (errEl) errEl.style.display = 'none';
  if (btn) { btn.textContent = 'Creating…'; btn.disabled = true; }
  const email = (document.getElementById('setup-email')?.value || '').trim();
  const password = document.getElementById('setup-password')?.value || '';
  try {
    const r = await fetch(API + '/auth/setup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
    const text = await r.text();
    if (!r.ok) { _loginError(apiErrorMessage(text, r.status)); if (btn) btn.textContent = 'Create account'; return; }
    const data = JSON.parse(text);
    setToken(data.token);
    toast('Admin account created — welcome!', 'success');
    const ok = await bootApp();
    if (!ok) _loginError('Account created but the session failed to load. Please sign in.');
  } catch(err) {
    _loginError(err.message || 'Setup failed. Please try again.');
    if (btn) btn.textContent = 'Create account';
  }
}

function _fadeIn() {
  const c = document.getElementById('content');
  if (!c) return;
  c.style.opacity = '0';
  c.style.transition = 'opacity 0.15s ease';
  requestAnimationFrame(() => { c.style.opacity = '1'; });
}



// ── Catalog ───────────────────────────────────────────────────────────────

let _catalogEditId = null;

async function renderCatalog() {
  setTitle('Catalog', 'edit products & sync to Google Sheets');
  document.getElementById('topbar-actions').innerHTML = `
    <button class="btn btn-sm" onclick="loadCatalog()">↻ Refresh</button>`;
  catalogPage = 0;
  catalogProducts = [];
  await loadCatalog();
}

async function loadCatalog(append = false) {
  const offset = append ? catalogProducts.length : 0;
  const q = catalogSearch ? `&q=${encodeURIComponent(catalogSearch)}` : '';
  // "all" = approved + posted; the server does the text search
  let products = [], total = 0;
  if (catalogStage === 'all') {
    const [a, p] = await Promise.all([
      api(`/products?stage=REVIEWED&limit=50&offset=${offset}&sort=created${q}`).catch(() => ({ products: [], total: 0 })),
      api(`/products?stage=LIVE&limit=50&offset=${offset}&sort=created${q}`).catch(() => ({ products: [], total: 0 })),
    ]);
    products = [...a.products, ...p.products];
    total = a.total + p.total;
  } else {
    const data = await api(`/products?stage=${catalogStage}&limit=50&offset=${offset}&sort=created${q}`).catch(() => ({ products: [], total: 0 }));
    products = data.products;
    total = data.total;
  }
  catalogProducts = append ? catalogProducts.concat(products) : products;
  catalogTotal = total;
  renderCatalogTable();
}

function renderCatalogTable() {
  const el = document.getElementById('content');
  const canMore = catalogProducts.length < catalogTotal;

  el.innerHTML = `
    <div class="catalog-toolbar">
      <div class="catalog-tabs">
        <button class="cat-tab${catalogStage==='REVIEWED'?' active':''}" onclick="setCatalogStage('REVIEWED')">✅ Approved</button>
        <button class="cat-tab${catalogStage==='LIVE'?' active':''}" onclick="setCatalogStage('LIVE')">📤 Posted</button>
        <button class="cat-tab${catalogStage==='all'?' active':''}" onclick="setCatalogStage('all')">All</button>
      </div>
      <div class="catalog-search">
        <input type="text" id="catalog-search-input" placeholder="Search by name, category…"
          value="${catalogSearch}"
          oninput="debCatalogSearch(this.value)"
          style="width:220px;padding:6px 10px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:12px">
      </div>
      <span style="font-size:12px;color:var(--t3);margin-left:auto">${catalogProducts.length} products${!catalogSearch && catalogTotal > catalogProducts.length ? ' of ' + catalogTotal : ''}</span>
    </div>
    ${catalogProducts.length === 0 ? `
      <div class="empty" style="margin-top:48px">
        <span class="empty-icon">🗂️</span>
        <h3>No products found</h3>
        <p>${catalogSearch ? 'Try a different search' : 'Approve products from the review queue first'}</p>
      </div>` : `
    <div class="catalog-table-wrap">
      <table class="catalog-table">
        <thead>
          <tr>
            <th style="width:60px">Photo</th>
            <th>Name</th>
            <th style="width:90px">Price (₾)</th>
            <th style="width:80px">Stage</th>
            <th style="width:60px">Score</th>
            <th>Caption</th>
            <th style="width:80px">Actions</th>
          </tr>
        </thead>
        <tbody id="catalog-tbody">
          ${catalogProducts.map(p => catalogRow(p)).join('')}
        </tbody>
      </table>
    </div>
    ${canMore ? `<div style="text-align:center;margin-top:20px">
      <button class="btn" onclick="loadCatalog(true)">Load more (${catalogTotal - catalogProducts.length} remaining)</button>
    </div>` : ''}
    `}
  `;
}

function catalogRow(p, editMode = false) {
  const img = (p.images || [])[0];
  const name = p.product_name || p.title_translated || '—';
  const price = p.sell_price_eur ?? 0;
  const caption = p.caption || '';
  const stageBadge = p.stage === 'LIVE'
    ? '<span class="badge" style="background:#3b82f6;color:#fff">Posted</span>'
    : '<span class="badge badge-green">Approved</span>';
  const score = (p.composite_score ?? p.score ?? 0).toFixed(1);

  if (editMode) {
    return `<tr id="cat-row-${p.id}" class="cat-row editing">
      <td>
        ${img ? `<img src="${imageUrl(img)}" class="cat-thumb" onerror="this.style.display='none'">` : '<div class="cat-thumb-ph">?</div>'}
      </td>
      <td>
        <input id="cat-name-${p.id}" class="cat-input" type="text" value="${escHtml(name)}" placeholder="Product name">
      </td>
      <td>
        <input id="cat-price-${p.id}" class="cat-input cat-price-input" type="number" step="0.01" min="0" value="${price}" placeholder="0.00">
      </td>
      <td>${stageBadge}</td>
      <td><span class="badge badge-purple">${score}</span></td>
      <td>
        <textarea id="cat-caption-${p.id}" class="cat-input cat-caption-input" placeholder="Caption for Instagram">${escHtml(caption)}</textarea>
      </td>
      <td>
        <button class="btn btn-sm" style="background:var(--green);color:#fff;margin-bottom:4px" onclick="saveCatalogRow(${p.id})">💾 Save</button>
        <button class="btn btn-sm" onclick="cancelCatalogEdit(${p.id})">✕</button>
      </td>
    </tr>`;
  }

  return `<tr id="cat-row-${p.id}" class="cat-row">
    <td>
      ${img ? `<img src="${imageUrl(img)}" class="cat-thumb" onerror="this.style.display='none'">` : '<div class="cat-thumb-ph">?</div>'}
    </td>
    <td>
      <div class="cat-name">${escHtml(name)}</div>
      <div style="font-size:10px;color:var(--t3)">${escHtml(p.category || p.keyword || '')}</div>
    </td>
    <td>
      <span class="cat-price-display">₾${price}</span>
    </td>
    <td>${stageBadge}</td>
    <td><span class="badge badge-purple">${score}</span></td>
    <td>
      <div class="cat-caption-preview">${escHtml(caption.slice(0, 80))}${caption.length > 80 ? '…' : ''}</div>
    </td>
    <td>
      <button class="btn btn-sm" onclick="editCatalogRow(${p.id})">✏️ Edit</button>
    </td>
  </tr>`;
}


function editCatalogRow(id) {
  if (_catalogEditId && _catalogEditId !== id) cancelCatalogEdit(_catalogEditId);
  _catalogEditId = id;
  const p = catalogProducts.find(x => x.id === id);
  if (!p) return;
  const row = document.getElementById(`cat-row-${id}`);
  if (row) row.outerHTML = catalogRow(p, true);
}

function cancelCatalogEdit(id) {
  const p = catalogProducts.find(x => x.id === id);
  if (!p) return;
  const row = document.getElementById(`cat-row-${id}`);
  if (row) row.outerHTML = catalogRow(p, false);
  _catalogEditId = null;
}

async function saveCatalogRow(id) {
  const name = document.getElementById(`cat-name-${id}`)?.value?.trim();
  const price = parseFloat(document.getElementById(`cat-price-${id}`)?.value || '0');
  const caption = document.getElementById(`cat-caption-${id}`)?.value?.trim();

  const btn = document.querySelector(`#cat-row-${id} .btn`);
  if (btn) { btn.textContent = '⏳'; btn.disabled = true; }

  try {
    const result = await api(`/products/${id}`, 'PATCH', {
      product_name: name,
      sell_price_eur: isNaN(price) ? undefined : price,
      caption: caption,
    });

    // Update local state
    const idx = catalogProducts.findIndex(x => x.id === id);
    if (idx >= 0) {
      catalogProducts[idx] = { ...catalogProducts[idx], ...result.product };
      const row = document.getElementById(`cat-row-${id}`);
      if (row) row.outerHTML = catalogRow(catalogProducts[idx], false);
    }
    _catalogEditId = null;
    toast('✅ Saved & synced to Sheets', 'success');
  } catch(e) {
    toast('❌ ' + (e.message || 'Save failed'), 'error');
    const btn2 = document.querySelector(`#cat-row-${id} .btn`);
    if (btn2) { btn2.textContent = '💾 Save'; btn2.disabled = false; }
  }
}

function setCatalogStage(stage) {
  catalogStage = stage;
  catalogPage = 0;
  catalogProducts = [];
  loadCatalog();
}

let _catalogSearchTimer = null;
function debCatalogSearch(val) {
  catalogSearch = val;
  clearTimeout(_catalogSearchTimer);
  _catalogSearchTimer = setTimeout(() => {
    catalogPage = 0;
    catalogProducts = [];
    loadCatalog();
  }, 350);
}



function _pipelineSubNav(active) {
  const stages = [
    { id: 'queue',    label: 'Review',    count: stats.ENRICHED      },
    { id: 'textEdit', label: 'Text Edit', count: stats.TEXT_REMOVAL },
    { id: 'REVIEWED', label: 'Approved',  count: stats.REVIEWED  },
    { id: 'LIVE',     label: 'Posted',    count: stats.LIVE      },
    { id: 'catalog',  label: 'Catalog',   count: null            },
    { id: 'REJECTED', label: 'Rejected',  count: stats.REJECTED  },
    { id: 'scan',     label: '+ Scan',    count: null, side: true },
    { id: 'scans',    label: 'Scan log',  count: null, side: true },
  ];
  const tab = s => {
    const badge = s.count != null && s.count > 0
      ? `<span style="margin-left:5px;font-family:var(--ff-m);font-size:10px;opacity:.7">${s.count}</span>` : '';
    return `<button class="cat-tab ${s.id === active ? 'active' : ''}" onclick="navigate('${s.id}')">${s.label}${badge}</button>`;
  };
  const main = stages.filter(s => !s.side).map(tab).join('');
  const side = stages.filter(s => s.side).map(tab).join('');
  return `<div class="catalog-tabs" style="margin-bottom:20px;display:flex;flex-wrap:wrap;gap:4px"><div style="display:flex;flex-wrap:wrap;gap:4px">${main}</div><div style="margin-left:auto;display:flex;gap:4px">${side}</div></div>`;
}

async function renderPage() {
  if (currentPage !== 'login') _fadeIn();
  const fn = PAGE_RENDERERS[currentPage];
  if (fn) await fn().catch(e => {
    const c = document.getElementById('content');
    if (c) c.innerHTML =
      `<div style="color:var(--red);padding:20px;font-family:var(--ff-m);font-size:12px">Error: ${escHtml(e.message)}</div>`;
  });
  if (PIPELINE_STAGE_PAGES.has(currentPage)) {
    const el = document.getElementById('content');
    if (el) {
      const nav = document.createElement('div');
      nav.innerHTML = _pipelineSubNav(currentPage);
      el.insertBefore(nav.firstElementChild, el.firstChild);
    }
  }
}


// ── Analytics ────────────────────────────────────────────────────────────────

async function renderAnalytics() {
  const tabLabels = { overview: 'Overview', margins: 'Margins', insights: 'Insights' };
  setTitle('Analytics', tabLabels[analyticsTab] || 'Overview');
  document.getElementById('topbar-actions').innerHTML = '';
  const el = document.getElementById('content');

  const tabBar = `<div class="catalog-tabs" style="margin-bottom:20px">
    <button class="cat-tab ${analyticsTab==='overview'?'active':''}" onclick="switchAnalyticsTab('overview')">Overview</button>
    <button class="cat-tab ${analyticsTab==='margins'?'active':''}" onclick="switchAnalyticsTab('margins')">Margins</button>
    <button class="cat-tab ${analyticsTab==='insights'?'active':''}" onclick="switchAnalyticsTab('insights')">Insights</button>
  </div>`;

  if (analyticsTab === 'margins') { el.innerHTML = tabBar + '<div style="color:var(--t3);font-size:12px;padding:30px 0;text-align:center">Loading…</div>'; el.innerHTML = tabBar + await renderMarginsTab(); return; }
  if (analyticsTab === 'insights') { el.innerHTML = tabBar + '<div style="color:var(--t3);font-size:12px;padding:30px 0;text-align:center">Loading…</div>'; el.innerHTML = tabBar + await renderInsightsTab(); return; }

  el.innerHTML = '<div style="color:var(--t3);font-size:12px;padding:40px 0;text-align:center">Loading analytics…</div>';

  const [data] = await Promise.all([
    api('/analytics').catch(() => ({}))
  ]);

  const stats = data.stats || {};
  const timeline = data.timeline || [];
  const categories = data.categories || [];
  const rejections = data.top_rejections || [];
  const keywords = data.keywords || [];
  const scoreDist = data.score_distribution || [];
  const providers = data.ai_providers || [];

  const total = (stats.ENRICHED||0)+(stats.TEXT_REMOVAL||0)+(stats.REVIEWED||0)+(stats.LIVE||0)+(stats.REJECTED||0);
  const approvalRate = total ? Math.round(((stats.REVIEWED||0)+(stats.LIVE||0))/total*100) : 0;

  // Timeline sparkline (simple)
  const tlMax = Math.max(...timeline.map(d => d.total), 1);
  const tlBars = timeline.slice(-14).map(d => {
    const h = Math.max(4, Math.round((d.total / tlMax) * 48));
    const approved = d.approved ?? d.REVIEWED ?? 0;
    const hA = Math.max(0, Math.round((approved / tlMax) * 48));
    return `<div class="an-bar-wrap" title="${escHtml(d.day)}: ${d.total} added, ${approved} approved">
      <div class="an-bar-total" style="height:${h}px"></div>
      <div class="an-bar-approved" style="height:${hA}px"></div>
    </div>`;
  }).join('');

  // Score distribution
  const sdMax = Math.max(...scoreDist.map(d => d.cnt), 1);
  const sdBars = scoreDist.map(d => {
    const w = Math.max(4, Math.round((d.cnt / sdMax) * 100));
    return `<div class="an-hbar-row">
      <span class="an-hbar-label">${d.bucket}</span>
      <div class="an-hbar-track"><div class="an-hbar-fill" style="width:${w}%"></div></div>
      <span class="an-hbar-val">${d.cnt}</span>
    </div>`;
  }).join('');

  // Rejection reasons
  const rejMax = Math.max(...rejections.map(r => r.cnt), 1);
  const rejRows = rejections.map(r => {
    const w = Math.max(4, Math.round((r.cnt / rejMax) * 100));
    return `<div class="an-hbar-row">
      <span class="an-hbar-label" title="${escHtml(r.reason)}">${escHtml(r.reason.length>28?r.reason.slice(0,28)+'…':r.reason)}</span>
      <div class="an-hbar-track"><div class="an-hbar-fill" style="width:${w}%;background:var(--red)"></div></div>
      <span class="an-hbar-val">${r.cnt}</span>
    </div>`;
  }).join('');

  // Category rows
  const catMax = Math.max(...categories.map(c => c.cnt), 1);
  const catRows = categories.map(c => {
    const w = Math.max(4, Math.round((c.cnt / catMax) * 100));
    return `<div class="an-hbar-row">
      <span class="an-hbar-label">${escHtml(c.category||'Unknown')}</span>
      <div class="an-hbar-track"><div class="an-hbar-fill" style="width:${w}%;background:var(--blue)"></div></div>
      <span class="an-hbar-val">${c.cnt}</span>
    </div>`;
  }).join('');

  // Keywords table
  const kwRows = keywords.map(k => {
    const approved = k.approved ?? k.REVIEWED ?? 0;
    return `
    <tr>
      <td>${escHtml(k.keyword||'—')}</td>
      <td style="color:var(--t2)">${k.total}</td>
      <td style="color:var(--green)">${approved}</td>
      <td style="color:var(--amber)">${k.avg_score??'—'}</td>
      <td style="color:var(--t3)">${k.total?Math.round((approved/k.total)*100):0}%</td>
    </tr>`;
  }).join('');

  // AI Provider badges
  const provBadges = providers.map(p => `
    <div class="an-badge">
      <span style="color:var(--t1)">${escHtml(p.provider)}</span>
      <span style="color:var(--t3)">${p.cnt}</span>
    </div>`).join('');

  el.innerHTML = tabBar + `
    <div class="an-page">

      <div class="dash-stat-grid" style="margin-bottom:16px">
        <div class="dash-stat-card">
          <div class="dash-stat-label">Total products</div>
          <div class="dash-stat-val">${total}</div>
          <div class="dash-stat-actions">
            <span style="color:var(--t3);font-size:11px">${approvalRate}% approval rate</span>
          </div>
        </div>
        <div class="dash-stat-card">
          <div class="dash-stat-label">Pending → Approved → Posted</div>
          <div class="dash-stat-val" style="font-size:20px;color:var(--t1)">
            <span style="color:var(--blue)">${stats.ENRICHED||0}</span>
            <span style="color:var(--t3);font-size:14px">→</span>
            <span style="color:var(--green)">${stats.REVIEWED||0}</span>
            <span style="color:var(--t3);font-size:14px">→</span>
            <span style="color:var(--amber)">${stats.LIVE||0}</span>
          </div>
          <div class="dash-stat-actions">
            <span style="color:var(--t3);font-size:11px">${stats.REJECTED||0} rejected total</span>
          </div>
        </div>
        <div class="dash-stat-card">
          <div class="dash-stat-label">AI Providers</div>
          <div class="an-badge-row">${provBadges||'<span style="color:var(--t3);font-size:11px">No data yet</span>'}</div>
        </div>
      </div>

      ${timeline.length ? `
      <div class="an-section">
        <div class="an-section-title">📈 Last 14 days (grey=total, green=approved)</div>
        <div class="an-sparkline">${tlBars}</div>
      </div>` : ''}

      <div class="an-two-col">

        <div class="an-section">
          <div class="an-section-title">🎯 Score distribution</div>
          ${sdBars || '<div class="an-empty">No scored products yet</div>'}
        </div>

        <div class="an-section">
          <div class="an-section-title">❌ Top rejection reasons</div>
          ${rejRows || '<div class="an-empty">No rejection data yet</div>'}
        </div>

        <div class="an-section">
          <div class="an-section-title">📦 Category breakdown</div>
          ${catRows || '<div class="an-empty">No category data yet</div>'}
        </div>

        <div class="an-section">
          <div class="an-section-title">🔑 Keyword performance</div>
          ${keywords.length ? `
          <div class="an-table-wrap">
            <table class="an-table">
              <thead><tr><th>Keyword</th><th>Total</th><th>Approved</th><th>Avg score</th><th>Rate</th></tr></thead>
              <tbody>${kwRows}</tbody>
            </table>
          </div>` : '<div class="an-empty">No keyword data yet</div>'}
        </div>

      </div>
    </div>`;
}


// ── AI Chat Assistant ─────────────────────────────────────────────────────────

let chatHistory = [];
let chatPending = false;

const QUICK_ACTIONS = [
  { label: 'Pipeline status', msg: 'Give me a brief operational summary: pipeline counts, approval rate, top rejection reasons, and any active recommendations.' },
  { label: 'Review pending', msg: 'Review all my pending products. For each, recommend approve or reject with a short reason.' },
  { label: 'Show approved', msg: 'Show me all currently approved products ready to post.' },
  { label: 'Rejected gems', msg: 'From the rejected products, which 5-10 are the strongest candidates to reconsider? Focus on high score and strong couple angle.' },
  { label: 'Improve titles', msg: 'Look at my pending products and suggest better, more romantic and emotionally resonant English titles.' },
  { label: 'Keyword performance', msg: 'Which keywords are bringing in the most approved products? Which should I drop or add?' },
  { label: 'Generate captions', msg: 'Generate 3 Instagram captions (romantic, heartfelt, couple-focused) for one of my recently approved products.' },
];

function chatAppend(role, text, meta = {}) {
  chatHistory.push({ role, text, meta, ts: Date.now() });
  renderChatMessages();
}

function renderChatMessages() {
  const el = document.getElementById('chat-messages');
  if (!el) return;
  el.innerHTML = chatHistory.map((m, idx) => {
    if (m.role === 'user') {
      return `<div class="chat-msg user"><div class="chat-bubble">${escHtml(m.text)}</div></div>`;
    }
    // Assistant message
    let actions = '';
    const meta = m.meta || {};

    if (meta.action === 'reconsider' && (meta.product_ids||[]).length) {
      actions += `<button class="chat-action-btn" onclick="chatReconsider(${JSON.stringify(meta.product_ids)})">♻️ Reconsider ${meta.product_ids.length} products</button>`;
    }
    if (meta.action === 'show_products' && (meta.product_ids||[]).length) {
      actions += `<button class="chat-action-btn" onclick="navigate('REJECTED')">👀 View rejected products</button>`;
    }
    if (meta.action === 'approve_products' && (meta.product_ids||[]).length) {
      actions += `<button class="chat-action-btn approve-btn" onclick="chatApproveProducts(${JSON.stringify(meta.product_ids)})">✅ Approve ${meta.product_ids.length} products</button>`;
    }
    if (meta.action === 'edit_products' && (meta.edits||[]).length) {
      actions += `<button class="chat-action-btn" onclick="chatApplyEdits(${idx})">💾 Apply ${meta.edits.length} edits</button>`;
    }

    // Inline product cards for list_products
    let productCards = '';
    if ((meta.action === 'list_products' || meta.action === 'show_products' || meta.action === 'review_pending') && (meta.products||[]).length) {
      const prods = meta.products || [];
      productCards = `<div class="chat-product-grid">${prods.map(p => renderChatProductCard(p)).join('')}</div>`;
      // Bulk action buttons for review_pending
      if (meta.action === 'review_pending' && prods.length > 0) {
        const toApprove = prods.filter(p => p.recommendation === 'approve').map(p => p.id).filter(Boolean);
        const toReject  = prods.filter(p => p.recommendation === 'reject').map(p => p.id).filter(Boolean);
        const bulkBtns = [
          toApprove.length ? `<button class="btn-sm chat-bulk-approve" onclick="chatBulkApprove([${toApprove.join(',')}], this)">✅ Approve ${toApprove.length} products</button>` : '',
          toReject.length  ? `<button class="btn-sm chat-bulk-reject"  onclick="chatBulkReject([${toReject.join(',')}], this)">❌ Reject ${toReject.length} products</button>`   : '',
        ].filter(Boolean).join('');
        if (bulkBtns) productCards += `<div class="chat-bulk-row">${bulkBtns}</div>`;
      }
    }

    // Edit preview cards for edit_products
    let editCards = '';
    if (meta.action === 'edit_products' && (meta.edits||[]).length) {
      editCards = `<div class="chat-edit-list">${(meta.edits||[]).map(e => `
        <div class="chat-edit-item">
          <span class="chat-edit-id">#${e.id}</span>
          ${e.title ? `<span class="chat-edit-field">📝 ${escHtml(e.title)}</span>` : ''}
          ${e.price != null ? `<span class="chat-edit-field">💶 €${e.price}</span>` : ''}
          ${e.caption ? `<span class="chat-edit-field caption-preview">💬 ${escHtml(e.caption.substring(0,60))}…</span>` : ''}
        </div>`).join('')}</div>`;
    }

    const suggestion = meta.suggestion ? `<div class="chat-suggestion">${escHtml(meta.suggestion)}</div>` : '';
    return `<div class="chat-msg assistant">
      <div class="chat-avatar">AI</div>
      <div class="chat-bubble">${formatChatText(m.text)}${editCards}${productCards}${suggestion}${actions}</div>
    </div>`;
  }).join('');
  el.scrollTop = el.scrollHeight;
}

function renderChatProductCard(p) {
  const img = p.image_url || p.images?.[0] || '';
  const title = p.title_translated || p.product_name || p.title || 'Product';
  const price = (p.sell_price_eur || p.price) ? `₾${Number(p.sell_price_eur || p.price).toFixed(2)}` : '';
  const score = (p.composite_score || p.score) ? `${(p.composite_score || p.score).toFixed ? Number(p.composite_score || p.score).toFixed(1) : p.composite_score || p.score}` : '';
  const niche = p.niche_fit ? `nf:${p.niche_fit}` : '';
  const stage = p.stage || '';
  const rec = p.recommendation || '';
  const reason = p.reason || '';
  const stageColor = {REVIEWED:'#22c55e',ENRICHED:'#f59e0b',REJECTED:'#ef4444',LIVE:'#3b82f6'}[stage]||'#888';
  const recBadge = rec === 'approve'
    ? `<span class="chat-rec approve">✅ Approve</span>`
    : rec === 'reject'
    ? `<span class="chat-rec reject">❌ Reject</span>`
    : '';
  const imgEl = img
    ? `<img src="${API.replace('/api','')}/api/image?url=${encodeURIComponent(img)}" onerror="this.style.display='none'" loading="lazy">`
    : `<div class="chat-card-no-img">📦</div>`;
  const actionBtns = p.id && (stage === 'ENRICHED' || stage === 'SCRAPED') ? `
    <div class="chat-card-actions">
      <button class="chat-card-approve-btn" onclick="event.stopPropagation();chatQuickApprove(${p.id}, this)">✅ Approve</button>
      <button class="chat-card-reject-btn" onclick="event.stopPropagation();chatQuickReject(${p.id}, this)">❌ Reject</button>
    </div>` : '';
  const clickable = p.id ? `onclick="showDetail(${p.id})" style="cursor:pointer"` : '';
  return `<div class="chat-product-card${rec ? ' rec-'+rec : ''}" ${clickable}>
    <div class="chat-card-img">${imgEl}</div>
    <div class="chat-card-info">
      ${recBadge}
      <div class="chat-card-title">${escHtml(title)}</div>
      ${reason ? `<div class="chat-card-reason">${escHtml(reason)}</div>` : ''}
      <div class="chat-card-meta">
        ${price ? `<span class="chat-card-price">${price}</span>` : ''}
        ${score ? `<span class="chat-card-score">⭐${score}</span>` : ''}
        ${niche ? `<span class="chat-card-score" style="color:#a78bfa">${niche}</span>` : ''}
        <span class="chat-card-stage" style="color:${stageColor}">${stage}</span>
      </div>
      ${actionBtns}
    </div>
  </div>`;
}

function formatChatText(s) {
  // Escape HTML but allow line breaks as <br> and bold **text**
  const escaped = String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  return escaped
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\n/g,'<br>');
}

async function chatBulkApprove(ids, btn) {
  if (!ids?.length) return;
  if (!confirm(`Approve ${ids.length} products?`)) return;
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Approving…'; }
  try {
    const res = await api('/approve', 'POST', { product_ids: ids });
    const done = (res.REVIEWED || 0) + (res.TEXT_REMOVAL || 0);
    _cacheInvalidate('/products', '/stats');
    await refreshStats();
    toast(`✅ Approved ${done} products!`, 'success');
    if (btn) { btn.textContent = `✅ Approved ${done}`; }
    document.querySelectorAll('.chat-product-card.rec-approve').forEach(c => c.classList.add('chat-card-done-approve'));
  } catch(e) {
    toast('Error: ' + e.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = `✅ Approve ${ids.length} products`; }
  }
}

async function chatBulkReject(ids, btn) {
  if (!ids?.length) return;
  if (!confirm(`Reject ${ids.length} products?`)) return;
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Rejecting…'; }
  try {
    const res = await api('/reject', 'POST', { product_ids: ids });
    const done = res.rejected || ids.length;
    _cacheInvalidate('/products', '/stats');
    await refreshStats();
    toast(`❌ Rejected ${done} products`, 'success');
    if (btn) { btn.textContent = `❌ Rejected ${done}`; }
    document.querySelectorAll('.chat-product-card.rec-reject').forEach(c => c.classList.add('chat-card-done-reject'));
  } catch(e) {
    toast('Error: ' + e.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = `❌ Reject ${ids.length} products`; }
  }
}

async function chatSend(msg) {
  if (!msg || !msg.trim() || chatPending) return;
  const input = document.getElementById('chat-input');
  if (input) input.value = '';
  chatAppend('user', msg);
  chatPending = true;
  document.getElementById('chat-send-btn')?.setAttribute('disabled','1');
  // Show typing indicator
  const typingId = 'typing-' + Date.now();
  const messagesEl = document.getElementById('chat-messages');
  if (messagesEl) {
    messagesEl.insertAdjacentHTML('beforeend', `<div class="chat-msg assistant" id="${typingId}"><div class="chat-avatar">AI</div><div class="chat-bubble chat-typing-bubble"><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span></div></div>`);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
  try {
    const result = await api('/ai/chat', 'POST', { message: msg });
    document.getElementById(typingId)?.remove();
    chatAppend('assistant', result.reply || 'No response.', {
      action: result.action,
      product_ids: result.product_ids || [],
      products: result.products || [],
      edits: result.edits || [],
      suggestion: result.suggestion,
    });
  } catch(e) {
    document.getElementById(typingId)?.remove();
    chatAppend('assistant', '⚠️ Error: ' + (e.message || 'Unknown error'));
  } finally {
    chatPending = false;
    document.getElementById('chat-send-btn')?.removeAttribute('disabled');
    document.getElementById('chat-input')?.focus();
  }
}

async function chatQuickApprove(id, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  try {
    await api(`/products/${id}/approve`, 'POST');
    _cacheInvalidate('/products', '/stats');
    await refreshStats();
    toast('✅ Approved!', 'success');
    if (btn) {
      const card = btn.closest('.chat-product-card');
      if (card) card.classList.add('chat-card-done-approve');
      btn.textContent = '✅ Done';
      const rejectBtn = btn.closest('.chat-card-actions')?.querySelector('.chat-card-reject-btn');
      if (rejectBtn) rejectBtn.style.display = 'none';
    }
  } catch(e) {
    toast('Approve failed: ' + e.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = '✅ Approve'; }
  }
}

async function chatQuickReject(id, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  try {
    await api(`/products/${id}/reject`, 'POST');
    _cacheInvalidate('/products', '/stats');
    await refreshStats();
    toast('❌ Rejected', 'success');
    if (btn) {
      const card = btn.closest('.chat-product-card');
      if (card) card.classList.add('chat-card-done-reject');
      btn.textContent = '❌ Done';
      const approveBtn = btn.closest('.chat-card-actions')?.querySelector('.chat-card-approve-btn');
      if (approveBtn) approveBtn.style.display = 'none';
    }
  } catch(e) {
    toast('Reject failed: ' + e.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = '❌ Reject'; }
  }
}

async function chatApproveProducts(ids) {
  if (!ids?.length) return;
  if (!confirm(`Approve ${ids.length} products?`)) return;
  try {
    const res = await api('/approve', 'POST', { product_ids: ids.slice(0, 50) });
    const count = (res.REVIEWED || 0) + (res.TEXT_REMOVAL || 0);
    _cacheInvalidate('/products', '/stats');
    await refreshStats();
    toast(`✅ ${count} products approved!`, 'success');
    chatAppend('assistant', `Done! Approved ${count} products. Check the Approved tab to see them.`);
  } catch(e) {
    toast('Approve failed: ' + e.message, 'error');
  }
}

async function chatApplyEdits(msgIdx) {
  const m = chatHistory[msgIdx];
  if (!m?.meta?.edits?.length) return;
  if (!confirm(`Apply ${m.meta.edits.length} AI-suggested edits to product titles/prices?`)) return;
  try {
    let count = 0;
    for (const edit of m.meta.edits.slice(0, 20)) {
      const fields = {};
      if (edit.title) fields.title_translated = edit.title;
      if (edit.price != null) fields.sell_price_eur = edit.price;
      if (edit.caption) fields.caption = edit.caption;
      if (Object.keys(fields).length) {
        await api(`/products/${edit.id}`, 'PATCH', fields).catch(() => {});
        count++;
      }
    }
    _cacheInvalidate('/products', '/stats');
    toast(`💾 ${count} products edited!`, 'success');
    chatAppend('assistant', `Done! Updated ${count} products. Refresh the Review queue to see the changes.`);
  } catch(e) {
    toast('Edit failed: ' + e.message, 'error');
  }
}

async function chatReconsider(ids) {
  if (!ids?.length) return;
  if (!confirm(`Move ${ids.length} products back to Pending for review?`)) return;
  try {
    for (const id of ids.slice(0,20)) {
      await api(`/products/${id}/reconsider`, 'POST').catch(()=>{});
    }
    await refreshStats();
    toast(`♻️ ${ids.length} products moved to Pending`, 'success');
    chatAppend('assistant', `Done! Moved ${ids.length} products back to Pending. Go to the Review queue to check them.`);
  } catch(e) {
    toast('Reconsider failed: ' + e.message, 'error');
  }
}

function _chatAiStatusBanner(settingsData) {
  const hasGemini = settingsData?.gemini_key_set;
  const hasGroq   = settingsData?.groq_key_set;
  if (hasGemini || hasGroq) {
    const which = hasGemini ? 'Gemini' : 'Groq';
    return `<span class="chat-ai-badge ready">● ${which} connected</span>`;
  }
  return `<span class="chat-ai-badge warn">⚠ No AI key — <button onclick="navigate('settings')" style="background:none;border:none;color:inherit;cursor:pointer;font-size:inherit;padding:0;text-decoration:underline">add in Settings</button></span>`;
}

function _chatContextStrip(s) {
  if (!s) return '';
  const pending  = (s.ENRICHED || 0) + (s.TEXT_REMOVAL || 0);
  const approved = s.REVIEWED || 0;
  const live     = s.LIVE || 0;
  const rejected = s.REJECTED || 0;
  return `<div class="chat-ctx-strip">
    <span class="ctx-pill ctx-pending">${pending} pending</span>
    <span class="ctx-pill ctx-approved">${approved} approved</span>
    <span class="ctx-pill ctx-live">${live} live</span>
    <span class="ctx-pill ctx-rejected">${rejected} rejected</span>
  </div>`;
}

async function renderChat() {
  setTitle('Operations', 'Cute Couple Gifts — AI assistant');
  document.getElementById('topbar-actions').innerHTML = `
    <button class="btn-sm" onclick="chatHistory=[];renderChatMessages()">Clear</button>`;

  document.getElementById('content').innerHTML = `
    <div class="chat-page">
      <div class="chat-header-bar">
        ${_chatContextStrip(stats)}
        ${_chatAiStatusBanner(settingsData)}
      </div>
      <div class="chat-quick-row">
        ${QUICK_ACTIONS.map(a => `<button class="chat-quick-btn" data-msg="${a.msg.replace(/"/g,'&quot;')}" onclick="chatSend(this.dataset.msg)">${a.label}</button>`).join('')}
      </div>
      <div class="chat-messages" id="chat-messages"></div>
      <div class="chat-input-row">
        <textarea class="chat-input" id="chat-input" placeholder="Ask anything — review queue, keyword performance, rejected gems, caption ideas…" rows="2"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();chatSend(this.value)}"></textarea>
        <button class="chat-send-btn" id="chat-send-btn" onclick="chatSend(document.getElementById('chat-input').value)">↑</button>
      </div>
    </div>`;

  renderChatMessages();

  if (chatHistory.length === 0) {
    chatAppend('assistant', 'Welcome to Cute Couple Gifts operations. I have full access to your pipeline — pending products, approvals, rejections, scan history, keyword analytics, and AI recommendations.\n\nAsk me to review the queue, surface rejected gems, suggest title improvements, or summarise performance. What do you need?');
  }
}


// ── Mobile hamburger toggle ───────────────────────────────────────────────────
function toggleMobileNav() {
  document.getElementById('sidebar').classList.toggle('mobile-open');
}

// Close mobile nav when page is selected
const _origNavigate = navigate;
// Already defined above, patch via override
const _navClickClose = (page) => {
  document.getElementById('sidebar')?.classList.remove('mobile-open');
};

// ── Boot ───────────────────────────────────────────────────────────────────
function chooseStartPage() {
  return 'dashboard';
}

// ── Boot ──────────────────────────────────────────────────────────────────
async function bootApp() {
  const token = getToken();
  if (!token) {
    currentPage = 'login';
    await renderPage();
    return false;
  }
  try {
    stats = await api('/stats');
  } catch(e) {
    clearToken();
    currentPage = 'login';
    await renderPage();
    return false;
  }
  _isLoggedOut = false;
  document.body.classList.remove('is-login');
  currentPage = chooseStartPage();
  buildNav();
  await renderPage();
  api('/settings').then(s => { scanSource = String(s.cssbuy_source || '1688'); }).catch(() => {});
  setInterval(() => { if (currentPage !== 'login') refreshStats(); }, 20000);
  return true;
}

bootApp();




// v8 build 1777996588

// ── Keyboard Navigation & Inline Editing ──────────────────────────────────
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
  if (!hotkeysEnabled || document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') return;
  
  const cards = document.querySelectorAll('.product-card');
  if (!cards.length) return;

  if (e.key === 'j' || e.key === 'ArrowDown') {
    activeRowIndex = Math.min(activeRowIndex + 1, cards.length - 1);
    applyActiveRow();
    e.preventDefault();
  } else if (e.key === 'k' || e.key === 'ArrowUp') {
    activeRowIndex = Math.max(activeRowIndex - 1, 0);
    applyActiveRow();
    e.preventDefault();
  } else if (e.key === 'a' || e.key === 'A' || e.key === 'r' || e.key === 'R') {
    // a = approve, r = reject — only meaningful on the Review / Text edit / Approved grids
    if (!['queue', 'textEdit', 'REVIEWED'].includes(currentPage)) return;
    const target = cards[activeRowIndex];
    const pidMatch = target && target.id.match(/card-(\d+)/);
    if (!pidMatch) return;
    const pid = parseInt(pidMatch[1]);
    const approve = e.key === 'a' || e.key === 'A';
    if (approve && currentPage === 'REVIEWED') { quickPost(pid); return; }
    const stage = approve ? 'REVIEWED' : 'REJECTED';
    api('/products/bulk-status', 'POST', { product_ids: [pid], stage }).then(res => {
      if (res.skipped?.length) { toast('Nothing changed', 'error'); return; }
      toast(approve ? 'Approved' : 'Rejected', 'success');
      [queueProducts, textEditProducts, approvedProducts].forEach(list => {
        const i = list.findIndex(p => p.id === pid); if (i >= 0) list.splice(i, 1);
      });
      selectedProducts.delete(pid);
      target.remove();
      activeRowIndex = Math.min(activeRowIndex, Math.max(0, document.querySelectorAll('.product-card').length - 1));
      applyActiveRow();
      refreshStats();
    }).catch(err => console.error(err));
  } else if (e.key === 'Enter') {
    const target = cards[activeRowIndex];
    const pidMatch = target && target.id.match(/card-(\d+)/);
    if (pidMatch) showDetail(parseInt(pidMatch[1]));
  } else if (e.key === 'Escape') {
    closeDetail(); closeRejectModal();
  }
});

function startEdit(id, field, el) {
  if (el.querySelector('input')) return;
  hotkeysEnabled = false;
  const originalText = el.innerText.replace('₾', '');
  const input = document.createElement('input');
  input.type = 'text';
  input.value = originalText;
  input.style.width = '100%';
  
  input.onkeydown = async (e) => {
    if (e.key === 'Enter') {
      const val = input.value;
      const body = {};
      body[field] = field === 'sell_price_eur' ? parseFloat(val) : val;
      try {
        await api('/products/' + id, 'PATCH', body);
        toast('Saved', 'success');
        el.innerHTML = field === 'sell_price_eur' ? '₾' + val : val;
        hotkeysEnabled = true;
      } catch (err) {
        toast('Failed to save', 'error');
        el.innerHTML = field === 'sell_price_eur' ? '₾' + originalText : originalText;
        hotkeysEnabled = true;
      }
    } else if (e.key === 'Escape') {
      el.innerHTML = field === 'sell_price_eur' ? '₾' + originalText : originalText;
      hotkeysEnabled = true;
    }
  };
  
  input.onblur = () => {
    el.innerHTML = field === 'sell_price_eur' ? '₾' + originalText : originalText;
    hotkeysEnabled = true;
  };
  
  el.innerHTML = '';
  el.appendChild(input);
  input.focus();
}
