const API = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  ? 'http://localhost:8000/api'
  : window.location.origin + '/api';

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

// ── Nav ────────────────────────────────────────────────────────────────────
const NAV_PAGES = [
  { id:'dashboard', label:'Today',        icon:'dashboard', section:'Overview' },
  { id:'scan',      label:'Find',         icon:'scan'                          },
  { id:'pipeline',  label:'Pipeline',     icon:'scan',      section:undefined  },
  { id:'queue',     label:'Review',       icon:'queue',     section:'Pipeline', stageKey:'pending'  },
  { id:'textEdit',  label:'Text edit',    icon:'settings',  stageKey:'text_edit' },
  { id:'approved',  label:'Approved',     icon:'approved',  stageKey:'approved' },
  { id:'posted',    label:'Posted',       icon:'posted'     },
  { id:'rejected',  label:'Rejected',     icon:'rejected'   },
  { id:'settings',  label:'Settings',     icon:'settings',  section:'Config'    },
  { id:'analytics', label:'Analytics',   icon:'analytics', section:'Tools'    },
  { id:'chat',      label:'AI Assistant',icon:'chat'                           },
];

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
  let html = '';
  let lastSection = null;
  for (const p of NAV_PAGES) {
    if (p.section && p.section !== lastSection) {
      html += `<span class="nav-group-label">${p.section}</span>`;
      lastSection = p.section;
    }
    const cnt = p.stageKey ? stats[p.stageKey] : null;
    const badgeClass = p.stageKey === 'approved' ? 'nav-badge g' : 'nav-badge';
    html += `
      <button class="nav-item${p.id === currentPage ? ' active' : ''}" onclick="navigate('${p.id}')" title="${p.label}">
        ${IC[p.icon]}
        <span class="lbl">${p.label}</span>
        ${cnt != null && cnt > 0 ? `<span class="${badgeClass}">${cnt}</span>` : ''}
      </button>`;
  }
  document.getElementById('nav').innerHTML = html;
}

function navigate(page) {
  currentPage = page;
  resetSelectionState();
  resetCatalogState();
  resetPipelineState();
  buildNav();
  renderPage();
}

function imageUrl(src) {
  return src ? `/api/image?url=${encodeURIComponent(src)}` : '';
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
async function api(path, method = 'GET', body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== null) opts.body = JSON.stringify(body);
  try {
    const r = await fetch(API + path, opts);
    if (!r.ok) {
      const text = await r.text().catch(() => r.statusText);
      throw new Error(apiErrorMessage(text, r.status));
    }
    return r.json();
  } catch(e) { toast(e.message || 'API error', 'error'); throw e; }
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
        <div class="dash-stat-val" style="color:var(--blue)">${s.pending ?? 0}</div>
        <div class="dash-stat-actions">
          <button class="dash-stat-btn" onclick="navigate('queue')">Review now</button>
          <button class="dash-stat-btn" onclick="navigate('scan')">Find products</button>
        </div>
      </div>
      <div class="dash-stat-card">
        <div class="dash-stat-label">Approved</div>
        <div class="dash-stat-val" style="color:var(--green)">${s.approved ?? 0}</div>
        <div class="dash-stat-actions">
          <button class="dash-stat-btn" onclick="navigate('approved')">Post next</button>
          <button class="dash-stat-btn" onclick="navigate('posted')">Posted: ${s.posted ?? 0}</button>
        </div>
      </div>
      <div class="dash-stat-card">
        <div class="dash-stat-label">Rejected</div>
        <div class="dash-stat-val" style="color:var(--t3)">${s.rejected ?? 0}</div>
        <div class="dash-stat-actions">
          <button class="dash-stat-btn" onclick="navigate('rejected')">View rejected</button>
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
                <div style="font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${(j.keywords || []).join(', ') || '—'}</div>
                <div style="font-size:11px;color:var(--t3);font-family:var(--ff-m)">${j.status} · ${j.after_ai ?? 0} passed</div>
              </div>
              ${j.status !== 'done' && j.status !== 'queued'
                ? `<span style="font-size:11px;color:var(--t3);font-family:var(--ff-m)">${j.progress ?? 0}%</span>` : ''}
            </div>`).join('')}
        <div style="margin-top:14px;display:flex;gap:8px">
          <button class="btn btn-sm" onclick="navigate('scan')">New scan</button>
          ${(s.pending > 0) ? `<button class="btn btn-sm btn-green" onclick="navigate('queue')">Review ${s.pending} products</button>` : ''}
          ${(s.approved > 0) ? `<button class="btn btn-sm btn-amber" onclick="navigate('approved')">Post ${s.approved} approved</button>` : ''}
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
  const data = await api(`/products?stage=pending&limit=50&offset=${offset}&sort=${queueSort}`).catch(() => ({ products: [], total: 0 }));
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
  const data = await api(`/products?stage=approved&limit=50&offset=${offset}&sort=score`).catch(() => ({ products: [], total: 0 }));
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
      ${approvedProducts.map(p => productCard(p, 'approved')).join('')}
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
  const data = await api(`/products?stage=text_edit&limit=50&offset=${offset}&sort=score`).catch(() => ({ products: [], total: 0 }));
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
      ${textEditProducts.map(p => productCard(p, 'text_edit')).join('')}
    </div>
    ${canMore ? `<div style="text-align:center;margin-top:20px">
      <button class="btn" onclick="loadTextEdit(true)">Load more (${textEditTotal - textEditProducts.length} remaining)</button>
    </div>` : ''}`;
}

// ── Product card ───────────────────────────────────────────────────────────
function productCard(p, mode) {
  const sel = selectedProducts.has(p.id);
  const img = imageUrl((p.images || [])[0] || '');
  const score = p.score || 0;
  const sc = score >= 8 ? 'hi' : score >= 7 ? 'mi' : 'lo';

  let actions = '';
  if (mode === 'queue') {
    actions = `<button class="pca-approve" onclick="event.stopPropagation();quickApprove(${p.id})">Approve</button>
               <button class="pca-reject"  onclick="event.stopPropagation();showRejectModal(${p.id})">✕</button>`;
  } else if (mode === 'approved') {
    actions = `<button class="pca-post"   onclick="event.stopPropagation();quickPost(${p.id})">Post →</button>
               <button class="pca-reject" onclick="event.stopPropagation();showRejectModal(${p.id})">✕</button>`;
  }

  if (mode === 'text_edit') {
    actions = `<button class="pca-post" onclick="event.stopPropagation();markTextEdited(${p.id})">Cleaned</button>
               <button class="pca-reject" onclick="event.stopPropagation();showRejectModal(${p.id})">Reject</button>`;
  }

  const name = p.product_name || p.title_translated || p.title || 'Unknown';
  const provider = p.ai_provider ? String(p.ai_provider).toUpperCase() : '';
  const ordersLabel = p.source_platform === 'taobao' ? 'sales unknown' : `${(p.orders ?? 0).toLocaleString()} sold`;
  const cat  = [p.keyword ? `#${p.keyword}` : '', p.category].filter(Boolean).join(' · ');

  return `
    <div class="product-card${sel ? ' selected' : ''}" id="card-${p.id}" onclick="showDetail(${p.id})">
      <div class="pcard-img-wrap">
        ${img
          ? `<img class="pcard-img" src="${img}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
          : ''}
        <div class="pcard-placeholder" style="${img ? 'display:none' : ''}">◈</div>
        <div class="pcard-score ${sc}">${score.toFixed(1)}</div>
        ${provider ? `<div class="pcard-score ${sc}" style="left:auto;right:10px;font-size:9px">${provider}</div>` : ''}
        <div class="pcard-check" onclick="event.stopPropagation();toggleSel(${p.id})">
          <span class="pcard-check-mark">${IC.check}</span>
        </div>
      </div>
      <div class="pcard-body">
        <div class="pcard-name">${name}</div>
        ${p.has_chinese_text ? `<span class="badge badge-amber" style="align-self:flex-start">Chinese text</span>` : ''}
        <div class="pcard-cat">${cat || '—'}</div>
        <div class="pcard-pricing">
          <span class="p-cost">₾${p.cost_eur ?? '?'}</span>
          <span class="p-arr">→</span>
          <span class="p-sell">₾${p.sell_price_eur ?? '?'}</span>
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
  } else if (mode === 'text_edit') {
    actions = `<button class="btn btn-green" onclick="batchMarkTextEdited()">Mark cleaned ${n}</button>`;
  } else {
    if (selectedProducts.size >= 10) { toast('Max 10 at once', 'error'); return; }
    selectedProducts.add(id);
  }
  const card = document.getElementById(`card-${id}`);
  if (card) {
    card.className = `product-card${selectedProducts.has(id) ? ' selected' : ''}`;
  }
  updateSelBar(currentPage === 'approved' ? 'post' : currentPage === 'textEdit' ? 'text_edit' : 'approve');
}

function selectAll() {
  const list = currentPage === 'approved' ? approvedProducts : currentPage === 'textEdit' ? textEditProducts : queueProducts;
  list.slice(0, 10).forEach(p => selectedProducts.add(p.id));
  if (currentPage === 'approved') renderApprovedGrid();
  else if (currentPage === 'textEdit') renderTextEditGrid();
  else renderQueueGrid();
}

function clearSel() {
  selectedProducts.clear();
  if (currentPage === 'approved') renderApprovedGrid();
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
    actions = `<button class="btn btn-primary" onclick="batchPost()">Post ${n} →</button>`;
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
  const ids = [...selectedProducts];
  try {
    const res = await api('/approve', 'POST', { product_ids: ids });
    const textEdit = res.text_edit || 0;
    const approved = res.approved || 0;
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
  try {
    const res = await api(`/products/${id}/approve`, 'POST');
    toast(res.stage === 'text_edit' ? 'Moved to Text edit' : 'Approved', 'success');
    closeDetail();
    queueProducts = queueProducts.filter(p => p.id !== id);
    selectedProducts.delete(id);
    queueTotal = Math.max(0, queueTotal - 1);
    renderQueueGrid();
    refreshStats();
  } catch(e) {}
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
    else if (currentPage === 'approved') { approvedTotal = Math.max(0, approvedTotal - 1); renderApprovedGrid(); }
    else if (currentPage === 'textEdit') { textEditTotal = Math.max(0, textEditTotal - 1); renderTextEditGrid(); }
    refreshStats();
  } catch(e) {}
}

// ── Detail panel ───────────────────────────────────────────────────────────
async function showDetail(id) {
  const p = await api(`/products/${id}`).catch(() => null);
  if (!p) return;
  document.getElementById('detail-overlay')?.remove();

  const stage = p.stage || 'pending';
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

  const stageBadge = { pending:'badge-amber', approved:'badge-green', text_edit:'badge-amber', posted:'badge-blue', rejected:'badge-red' }[stage] || 'badge-gray';
  const stageLabel = { pending:'Pending', approved:'Approved', text_edit:'Text edit', posted:'Posted', rejected:'Rejected' }[stage] || stage;

  let actionHtml = '';
  if (stage === 'pending')
    actionHtml = `<button class="btn btn-green" style="flex:1" onclick="quickApprove(${p.id})">Approve</button>
                  <button class="btn btn-danger" onclick="showRejectModal(${p.id})">Reject</button>`;
  else if (stage === 'approved')
    actionHtml = `<button class="btn btn-primary" style="flex:1" onclick="quickPost(${p.id})">Post to Instagram →</button>
                  <button class="btn btn-danger" onclick="showRejectModal(${p.id})">Reject</button>`;
  else if (stage === 'text_edit')
    actionHtml = `<button class="btn btn-green" style="flex:1" onclick="markTextEdited(${p.id})">Mark cleaned</button>
                  <button class="btn btn-danger" onclick="showRejectModal(${p.id})">Reject</button>`;
  else if (stage === 'rejected')
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

        <div style="font-family:var(--ff-d);font-size:19px;font-weight:800;line-height:1.2;margin-bottom:4px">${p.product_name || '—'}</div>
        <div style="font-size:11px;color:var(--t3);font-family:var(--ff-m);margin-bottom:${p.keyword ? '3px' : '14px'};line-height:1.5">${p.title_translated || p.title || ''}</div>
        ${p.keyword ? `<div style="font-size:11px;color:var(--t3);margin-bottom:14px">Keyword: <span style="color:var(--accent)">${p.keyword}</span></div>` : ''}

        ${p.has_chinese_text ? `
        <div class="detail-sec">
          <span class="detail-sec-lbl">Chinese text detected</span>
          <div class="card-sm" style="font-size:12px;color:var(--amber);line-height:1.6">${p.chinese_text_note || 'Chinese text is visible in the product image.'}</div>
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
            ${p.source_platform ? `<span class="badge badge-gray" style="margin-left:6px;font-size:10px">${p.source_platform}</span>` : ''}
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
              <div class="mbox-val" style="font-size:12px">${p.category || '—'}</div>
            </div>
          </div>
        </div>

        <div class="detail-sec">
          <span class="detail-sec-lbl">AI score — ${(p.score ?? 0).toFixed(1)} / 10</span>
          ${sBar('Niche fit',  p.niche_fit         ?? 0)}
          ${sBar('Visual',     p.visual_appeal     ?? 0)}
          ${sBar('Trend',      p.trend_score       ?? 0)}
          ${sBar('Opp.',       p.competition_score ?? 0)}
        </div>

        ${p.caption ? `
        <div class="detail-sec">
          <span class="detail-sec-lbl">Instagram caption</span>
          <div class="card-sm" style="font-size:12.5px;color:var(--t2);line-height:1.7">${p.caption}</div>
        </div>` : ''}

        <details class="detail-sec edit-box">
          <summary>Edit product</summary>
          <div class="form-group">
            <label>Store name</label>
            <input type="text" id="edit-name" value="${(p.product_name || '').replace(/"/g,'&quot;')}"/>
          </div>
          <div class="form-group">
            <label>Short description</label>
            <textarea id="edit-description" rows="3" style="width:100%;resize:vertical">${p.description || ''}</textarea>
          </div>
          <div class="form-group">
            <label>Sell price</label>
            <input type="number" id="edit-price" value="${p.sell_price_eur ?? 0}" step="0.01" min="0"/>
          </div>
          <div class="form-group">
            <label>Caption</label>
            <textarea id="edit-caption" rows="5" style="width:100%;resize:vertical">${p.caption || ''}</textarea>
          </div>
          <div class="form-group">
            <label>Hashtags</label>
            <input type="text" id="edit-tags" value="${tags.join(', ')}"/>
          </div>
          <button class="btn btn-green" onclick="saveProductEdit(${p.id})">Save product changes</button>
        </details>

        ${tags.length ? `
        <div class="detail-sec">
          <span class="detail-sec-lbl">Hashtags</span>
          <div style="display:flex;flex-wrap:wrap;gap:5px">
            ${tags.map(h => `<span class="badge badge-purple">#${h.replace('#','')}</span>`).join('')}
          </div>
        </div>` : ''}

        ${p.rejection_reason ? `
        <div class="detail-sec">
          <span class="detail-sec-lbl">Rejection reason</span>
          <div class="card-sm" style="font-size:12px;color:var(--red)">${p.rejection_reason}</div>
        </div>` : ''}

        <div class="detail-sec">
          <span class="detail-sec-lbl">Review note</span>
          <textarea id="review-note-input" rows="3" style="width:100%;resize:vertical" placeholder="Add a note…">${p.review_note || ''}</textarea>
          <button class="btn btn-sm" style="margin-top:7px" onclick="saveNote(${p.id})">Save note</button>
        </div>

        <div class="detail-sec">
          <span class="detail-sec-lbl">Timeline</span>
          <div style="font-size:11px;font-family:var(--ff-m);line-height:2.2;color:var(--t3)">
            ${p.created_at  ? `<div>Scraped: ${fmtDate(p.created_at)}</div>` : ''}
            ${p.approved_at ? `<div style="color:var(--green)">Approved: ${fmtDate(p.approved_at)}</div>` : ''}
            ${p.rejected_at ? `<div style="color:var(--red)">Rejected: ${fmtDate(p.rejected_at)}</div>` : ''}
            ${p.posted_at   ? `<div style="color:var(--blue)">Posted: ${fmtDate(p.posted_at)}</div>` : ''}
          </div>
        </div>

        ${p.url ? `<a href="${p.url}" target="_blank" style="display:block;text-align:center;color:var(--t3);font-size:11px;margin-top:14px;text-decoration:none;font-family:var(--ff-m)">View on source ↗</a>` : ''}
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
    if (currentPage === 'approved') renderApprovedGrid();
    if (currentPage === 'rejected') renderRejectedTable();
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
  const data = await api('/products?stage=posted&limit=100&sort=created').catch(() => ({ products: [], total: 0 }));

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
          <th>Product</th><th>Score</th><th>Margin</th><th>Sell</th><th>Orders</th><th>Posted</th>
        </tr></thead>
        <tbody>
          ${data.products.map(p => `
            <tr style="cursor:pointer" onclick="showDetail(${p.id})">
              <td>
                <div style="display:flex;align-items:center;gap:10px">
                  ${(p.images || [])[0] ? `<img src="${imageUrl((p.images || [])[0])}" style="width:36px;height:36px;object-fit:cover;border-radius:6px;flex-shrink:0" onerror="this.style.display='none'">` : ''}
                  <div>
                    <div style="font-weight:500;font-size:12.5px">${p.product_name || p.title_translated || '—'}</div>
                    <div style="font-size:10px;color:var(--t3);font-family:var(--ff-m)">${p.keyword || p.category || ''}</div>
                  </div>
                </div>
              </td>
              <td><span class="badge badge-purple">${(p.score ?? 0).toFixed(1)}</span></td>
              <td><span class="badge badge-green">${p.margin_pct ?? 0}%</span></td>
              <td style="font-family:var(--ff-m);color:var(--green);font-size:12px">₾${p.sell_price_eur ?? 0}</td>
              <td style="font-family:var(--ff-m);font-size:12px">${(p.orders ?? 0).toLocaleString()}</td>
              <td style="font-size:11px;color:var(--t3);font-family:var(--ff-m);white-space:nowrap">${fmtDate(p.posted_at || p.created_at)}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

// ── Rejected ───────────────────────────────────────────────────────────────
async function renderRejected() {
  setTitle('Rejected');
  document.getElementById('topbar-actions').innerHTML = '';
  const data = await api('/products?stage=rejected&limit=100&sort=created').catch(() => ({ products: [], total: 0 }));
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
                <div style="font-weight:500;font-size:12.5px">${p.product_name || p.title_translated || '—'}</div>
                <div style="font-size:10px;color:var(--t3);font-family:var(--ff-m)">${p.keyword || ''}</div>
              </td>
              <td><span class="badge badge-gray">${(p.score ?? 0).toFixed(1)}</span></td>
              <td style="font-size:12px;color:var(--t3);max-width:180px">${p.rejection_reason || '<span style="opacity:.35">—</span>'}</td>
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
        <div class="card-title">Store & niche</div>
        <div class="form-group">
          <label>Niche description</label>
          <textarea id="s-niche" rows="3" style="resize:vertical">${s.niche || ''}</textarea>
          <div style="font-size:11px;color:var(--t3);margin-top:5px">Used in AI prompts — be specific about your store's aesthetic.</div>
        </div>
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
          <input type="password" id="s-ig-token" value="${s.instagram_access_token || ''}" placeholder="EAABs…"/>
          <div style="font-size:11px;margin-top:5px;color:${s.instagram_access_token && s.instagram_user_id ? 'var(--green)' : 'var(--t3)'}">
            ${s.instagram_access_token && s.instagram_user_id
              ? '✓ Graph API configured — posts will publish directly to Instagram'
              : 'Not set — posts will be simulated'}
          </div>
        </div>
        <div class="form-group">
          <label>Public app URL</label>
          <input type="text" id="s-public-url" value="${s.public_base_url || ''}" placeholder="https://your-app.up.railway.app"/>
          <div style="font-size:11px;color:var(--t3);margin-top:5px">Used as an image proxy for Instagram if supplier image URLs block Meta.</div>
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
        <div class="card-title">Comment auto-reply</div>
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
                ${window.location.origin.replace(':5173','').replace('http://localhost','http://YOUR-SERVER-IP')}/api/instagram/webhook
              </div>
            </div>
            <div>
              <label style="font-size:11px;color:var(--t3);display:block;margin-bottom:4px">Verify token <span style="color:var(--t4)">(copy this into Meta webhook verify token field)</span></label>
              <input type="text" id="s-webhook-token" value="${s.instagram_webhook_token || 'dropos_webhook_secret'}" style="font-family:var(--ff-m);font-size:12px"/>
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
          <div><label>Min margin (%)</label><input type="number" id="s-margin" value="${s.min_margin ?? 60}" step="5" min="0" max="95"/></div>
          <div><label>Min AI score</label><input type="number" id="s-score" value="${s.min_score ?? 7}" step="0.5" min="1" max="10"/></div>
        </div>
        <div class="form-row">
          <div><label>Min orders</label><input type="number" id="s-orders" value="${s.min_orders ?? 100}" step="50" min="0"/></div>
          <div><label>Min rating</label><input type="number" id="s-rating" value="${s.min_rating ?? 4.5}" step="0.1" min="1" max="5"/></div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Pricing & markup</div>
        <div class="form-group">
          <label>CNY → GEL rate</label>
          <input type="number" id="s-exchange" value="${s.exchange_rate ?? 0.353}" step="0.001" min="0.01"/>
        </div>
        <div class="form-group">
          <label>Markup · cost &lt; ₾5 (×)</label>
          <input type="number" id="s-ml" value="${s.sell_markup_low ?? 3.5}" step="0.1" min="1"/>
        </div>
        <div class="form-group">
          <label>Markup · cost ₾5–₾15 (×)</label>
          <input type="number" id="s-mm" value="${s.sell_markup_mid ?? 2.8}" step="0.1" min="1"/>
        </div>
        <div class="form-group">
          <label>Markup · cost &gt; ₾15 (×)</label>
          <input type="number" id="s-mh" value="${s.sell_markup_high ?? 2.2}" step="0.1" min="1"/>
        </div>
      </div>

      <div class="card">
        <div class="card-title">API keys</div>
        <div class="form-group">
          <label>Apify token</label>
          <input type="password" id="s-apify" value="${s.apify_token || ''}" placeholder="apify_api_…"/>
          <div style="font-size:11px;margin-top:5px;color:${s.apify_token ? 'var(--green)' : 'var(--t3)'}">
            ${s.apify_token ? '✓ Configured' : 'Not set — mock data will be used'}
          </div>
        </div>
        <div class="form-group">
          <label>Gemini key <span style="color:var(--green);font-weight:400">— recommended (cheapest + image analysis)</span></label>
          <input type="password" id="s-gemini" value="${s.gemini_key || ''}" placeholder="AIza…"/>
          <div style="font-size:11px;margin-top:5px;color:${s.gemini_key ? 'var(--green)' : 'var(--t3)'}">
            ${s.gemini_key ? '✓ Gemini 2.5 Flash-Lite active — image analysis enabled' : 'Not set — get free key at aistudio.google.com'}
          </div>
        </div>
        <div class="form-group">
          <label>Groq key <span style="color:var(--t3);font-weight:400">(free fallback — 14,400 req/day, text-only)</span></label>
          <input type="password" id="s-groq" value="${s.groq_key || ''}" placeholder="gsk_…"/>
          <div style="font-size:11px;margin-top:5px;color:${s.groq_key ? 'var(--green)' : 'var(--t3)'}">
            ${s.groq_key ? '✓ Groq Llama 3.3 70B active' : 'Not set — get free key at console.groq.com'}
          </div>
        </div>
        <div class="form-group">
          <label>Anthropic key <span style="color:var(--t3);font-weight:400">(fallback, text-only)</span></label>
          <input type="password" id="s-anthropic" value="${s.anthropic_key || ''}" placeholder="sk-ant-…"/>
          <div style="font-size:11px;margin-top:5px;color:${s.anthropic_key ? 'var(--green)' : 'var(--t3)'}">
            ${s.anthropic_key ? '✓ Claude Haiku fallback active' : 'Not set'}
          </div>
        </div>
        <div class="card-sm" style="margin-top:4px">
          <div style="font-size:11px;color:var(--t3);line-height:1.6">
            Priority: <b style="color:var(--t1)">Groq</b> → Gemini → Anthropic → mock rule-based.<br>
            Groq is used first to avoid Gemini quota delays.<br>
            Gemini is only used if Groq is unavailable and will fall back immediately on quota errors.
          </div>
        </div>
      </div>

      <div class="card" style="grid-column:1/-1">
        <div class="card-title">Scheduled scan keywords</div>
        <div style="font-size:11px;color:var(--t3);margin-bottom:10px">Keywords used by the automatic 09:00 and 21:00 UTC scans. One per line.</div>
        <div class="form-group">
          <textarea id="s-scan-kw" rows="4" style="font-family:var(--ff-m);font-size:12px;resize:vertical">${(s.scan_keywords || []).join('\n')}</textarea>
        </div>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <button class="btn btn-sm" onclick="triggerScheduledScan()">Run scheduled scan now</button>
          <span id="sched-status" style="font-size:11px;color:var(--t3)">Loading scheduler…</span>
        </div>
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
          <input type="password" id="s-captcha-key" value="${s.captcha_2captcha_key || ''}" placeholder="2captcha key…"/>
          <div style="font-size:11px;margin-top:5px;color:var(--t3)">
            ${s.captcha_2captcha_key ? '✓ Auto captcha enabled' : 'Not set — browser opens visibly on first login so you can solve captcha manually'}
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

    </div>`;
  setTimeout(loadSchedulerStatus, 150);
  setTimeout(loadReplyLog, 200);
}

async function loadSchedulerStatus() {
  try {
    const st = await api('/scheduler/status');
    const el = document.getElementById('sched-status');
    if (!el) return;
    if (st.running && st.jobs?.length) {
      const next = st.jobs.map(j => `${j.id}: every ${j.interval || 3600}s`).join(' · ');
      el.textContent = `Running: ${next}`;
    } else {
      el.textContent = 'Scheduler not running';
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
    toast(`Scheduled scan started (job #${res.job_id})`, 'success');
  } catch(e) {
    toast('Failed to trigger scan', 'error');
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
  const data = {
    niche:             g('s-niche')?.value,
    instagram_username:          g('s-instagram')?.value,
    instagram_user_id:           g('s-ig-user-id')?.value           || '',
    instagram_auto_reply_enabled: g('s-autoreply-enabled')?.checked ?? false,
    instagram_reply_rules:        _collectReplyRules(),
    instagram_dm_reply_enabled:   g('s-dm-enabled')?.checked ?? false,
    instagram_dm_rules:           _collectDmRules(),
    min_margin:    parseFloat(g('s-margin')?.value    || 60),
    min_score:     parseFloat(g('s-score')?.value     || 7),
    min_orders:    parseInt  (g('s-orders')?.value    || 100),
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
    local_scraping_only:  g('s-local-only')?.checked ?? false,
  };
  includeIfNonEmpty(data, 'instagram_access_token', g('s-ig-token')?.value);
  includeIfNonEmpty(data, 'instagram_webhook_token', g('s-webhook-token')?.value);
  includeIfNonEmpty(data, 'apify_token', g('s-apify')?.value);
  includeIfNonEmpty(data, 'gemini_key', g('s-gemini')?.value);
  includeIfNonEmpty(data, 'groq_key', g('s-groq')?.value);
  includeIfNonEmpty(data, 'anthropic_key', g('s-anthropic')?.value);
  includeIfNonEmpty(data, 'google_sheets_credentials', g('s-sheets-creds')?.value);
  includeIfNonEmpty(data, 'cssbuy_password', g('s-cssbuy-pass')?.value);
  includeIfNonEmpty(data, 'captcha_2captcha_key', g('s-captcha-key')?.value);
  includeIfNonEmpty(data, 'ingest_api_token', g('s-ingest-token')?.value);
  try {
    await api('/settings', 'PATCH', data);
    toast('Settings saved', 'success');
    loadSchedulerStatus();
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
  setTitle('Pipeline', 'scan-by-scan breakdown');
  const el = document.getElementById('content');

  // Load jobs list
  if (!pipelineJobs.length) {
    pipelineJobs = await api('/jobs?limit=30').catch(() => []);
  }
  if (!pipelineJobs.length) {
    el.innerHTML = `<div class="pl-empty">No scans yet — run a scan first.</div>`;
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

  const jobOptions = pipelineJobs.map(j => `<option value="${j.id}" ${j.id===pipelineJobId?'selected':''}>Job #${j.id} — ${(j.keywords||[]).join(', ').substring(0,40)} (${j.status})</option>`).join('');

  el.innerHTML = `
    <div style="max-width:1100px">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
        <select style="background:var(--s2);color:var(--t1);border:1px solid var(--b2);border-radius:var(--r);padding:7px 12px;font-size:12px;flex:1;max-width:420px" onchange="pipelineJobId=+this.value;pipelineActiveStage=null;pipelineData=null;renderPipeline()">
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
              ? (summary.top_reasons||[]).map(r => `<div style="font-size:12px;color:var(--t2);margin-bottom:4px">${r.reason} <span style="color:var(--t4)">(${r.count})</span></div>`).join('')
              : `<div style="font-size:12px;color:var(--t4)">No rejection pattern yet</div>`}
          </div>
          <div>
            <div style="font-size:12px;color:var(--t3);margin-bottom:6px">Accepted examples</div>
            ${(summary.accepted_examples||[]).length
              ? (summary.accepted_examples||[]).map(p => `<div style="font-size:12px;color:var(--t2);margin-bottom:4px">${(p.title||'').substring(0,42)} <span style="color:var(--green)">${Number(p.score||0).toFixed(1)}</span></div>`).join('')
              : `<div style="font-size:12px;color:var(--t4)">No accepted products yet</div>`}
          </div>
          <div>
            <div style="font-size:12px;color:var(--t3);margin-bottom:6px">Filter improvements</div>
            ${(summary.recommendations||[]).map(t => `<div style="font-size:12px;color:var(--t2);margin-bottom:4px">${t}</div>`).join('')}
          </div>
        </div>
      </div>

      <div style="font-size:11px;color:var(--t3);text-transform:uppercase;letter-spacing:.7px;font-family:var(--ff-m);margin-bottom:10px">Filter stages</div>
      <div class="pl-flow">
        ${STAGE_ORDER.map((s,i) => `
          <div class="pl-stage ${STAGE_TYPE[s]} ${pipelineActiveStage===s?'active':''}" onclick="pipelineActiveStage='${s}';renderPipeline()">
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
                  <div class="pl-card-title">${p.title||'—'}</div>
                  ${p.filter_reason ? `<div class="pl-card-reason">${p.filter_reason}</div>` : ''}
                  <div class="pl-card-score">
                    raw ${Number(p.raw_score||0).toFixed(0)}
                    ${p.ai_score ? ` · AI ${Number(p.ai_score||0).toFixed(1)}` : ''}
                    ${p.ai_provider ? ' · '+String(p.ai_provider).toUpperCase() : ''}
                  </div>
                  <div class="pl-card-meta">¥${p.price_cny?.toFixed(0)||0}${p.orders ? ' · '+p.orders+' sold' : ''}${p.rating ? ' · '+Number(p.rating).toFixed(1)+'★' : ''}</div>
                  <div class="pl-card-meta">niche ${Number(p.ai_niche_fit||p.niche_fit||0).toFixed(1)} · visual ${Number(p.ai_visual||p.visual_appeal||0).toFixed(1)} · trend ${Number(p.trend_score||0).toFixed(1)} · comp ${Number(p.competition_score||0).toFixed(1)}</div>
                  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
                    ${(p.url||p.link) ? `<a class="btn btn-sm" href="${p.url||p.link}" target="_blank" rel="noopener">Item</a>` : ''}
                    ${(p.image_url||p.photo_link) ? `<a class="btn btn-sm" href="${p.image_url||p.photo_link}" target="_blank" rel="noopener">Photo</a>` : ''}
                  </div>
                </div>
              </div>`).join('')}
          </div>`}
    </div>`;
}

// ── Router ─────────────────────────────────────────────────────────────────
async function clearScanHistory() {
  if (!confirm('Clear all scan job history? Product queue items will stay.')) return;
  await api('/jobs', 'DELETE');
  resetPipelineState();
  activeJob = null;
  if (activeJobPoll) { clearInterval(activeJobPoll); activeJobPoll = null; }
  toast('Scan history cleared', 'success');
  await refreshStats();
  renderPipeline();
}

const PAGE_RENDERERS = {
  dashboard: renderDashboard,
  scan:      renderScan,
  pipeline:  renderPipeline,
  queue:     renderQueue,
  textEdit:  renderTextEdit,
  approved:  renderApproved,
  posted:    renderPosted,
  rejected:  renderRejected,
  settings:  renderSettings,
  analytics: renderAnalytics,
  chat:      renderChat,
};

async function renderPage() {
  const fn = PAGE_RENDERERS[currentPage];
  if (fn) await fn().catch(e => {
    document.getElementById('content').innerHTML =
      `<div style="color:var(--red);padding:20px;font-family:var(--ff-m);font-size:12px">Error: ${e.message}</div>`;
  });
}


// ── Analytics ────────────────────────────────────────────────────────────────

async function renderAnalytics() {
  setTitle('Analytics');
  document.getElementById('topbar-actions').innerHTML = '';
  const el = document.getElementById('content');
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

  const total = (stats.pending||0)+(stats.approved||0)+(stats.posted||0)+(stats.rejected||0);
  const approvalRate = total ? Math.round(((stats.approved||0)+(stats.posted||0))/total*100) : 0;

  // Timeline sparkline (simple)
  const tlMax = Math.max(...timeline.map(d => d.total), 1);
  const tlBars = timeline.slice(-14).map(d => {
    const h = Math.max(4, Math.round((d.total / tlMax) * 48));
    const hA = Math.max(0, Math.round((d.approved / tlMax) * 48));
    return `<div class="an-bar-wrap" title="${d.day}: ${d.total} added, ${d.approved} approved">
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
      <span class="an-hbar-label" title="${r.reason}">${r.reason.length>28?r.reason.slice(0,28)+'…':r.reason}</span>
      <div class="an-hbar-track"><div class="an-hbar-fill" style="width:${w}%;background:var(--red)"></div></div>
      <span class="an-hbar-val">${r.cnt}</span>
    </div>`;
  }).join('');

  // Category rows
  const catMax = Math.max(...categories.map(c => c.cnt), 1);
  const catRows = categories.map(c => {
    const w = Math.max(4, Math.round((c.cnt / catMax) * 100));
    return `<div class="an-hbar-row">
      <span class="an-hbar-label">${c.category||'Unknown'}</span>
      <div class="an-hbar-track"><div class="an-hbar-fill" style="width:${w}%;background:var(--blue)"></div></div>
      <span class="an-hbar-val">${c.cnt}</span>
    </div>`;
  }).join('');

  // Keywords table
  const kwRows = keywords.map(k => `
    <tr>
      <td>${k.keyword||'—'}</td>
      <td style="color:var(--t2)">${k.total}</td>
      <td style="color:var(--green)">${k.approved}</td>
      <td style="color:var(--amber)">${k.avg_score??'—'}</td>
      <td style="color:var(--t3)">${k.total?Math.round((k.approved/k.total)*100):0}%</td>
    </tr>`).join('');

  // AI Provider badges
  const provBadges = providers.map(p => `
    <div class="an-badge">
      <span style="color:var(--t1)">${p.provider}</span>
      <span style="color:var(--t3)">${p.cnt}</span>
    </div>`).join('');

  el.innerHTML = `
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
            <span style="color:var(--blue)">${stats.pending||0}</span>
            <span style="color:var(--t3);font-size:14px">→</span>
            <span style="color:var(--green)">${stats.approved||0}</span>
            <span style="color:var(--t3);font-size:14px">→</span>
            <span style="color:var(--amber)">${stats.posted||0}</span>
          </div>
          <div class="dash-stat-actions">
            <span style="color:var(--t3);font-size:11px">${stats.rejected||0} rejected total</span>
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
  { label: '🔍 Find rejected gems', msg: 'Review all rejected products and find any that were wrongly rejected or have borderline scores worth reconsidering.' },
  { label: "📊 Today's summary", msg: 'Give me a brief summary of the current pipeline status and any recommendations.' },
  { label: '🔑 Keyword advice', msg: 'Based on keyword performance, what keywords should I add, remove or prioritise?' },
  { label: '✨ Best candidates', msg: 'From the rejected products, which 5-10 are the best candidates to reconsider? List them with IDs.' },
];

function chatAppend(role, text, meta = {}) {
  chatHistory.push({ role, text, meta, ts: Date.now() });
  renderChatMessages();
}

function renderChatMessages() {
  const el = document.getElementById('chat-messages');
  if (!el) return;
  el.innerHTML = chatHistory.map(m => {
    if (m.role === 'user') {
      return `<div class="chat-msg user"><div class="chat-bubble">${escHtml(m.text)}</div></div>`;
    }
    // Assistant message
    let actions = '';
    if (m.meta?.action === 'reconsider' && (m.meta?.product_ids||[]).length) {
      actions = `<button class="chat-action-btn" onclick="chatReconsider(${JSON.stringify(m.meta.product_ids)})">
        ♻️ Reconsider ${m.meta.product_ids.length} products
      </button>`;
    }
    if (m.meta?.action === 'show_products' && (m.meta?.product_ids||[]).length) {
      actions = `<button class="chat-action-btn" onclick="navigate('rejected')">
        👀 View rejected products
      </button>`;
    }
    const suggestion = m.meta?.suggestion ? `<div class="chat-suggestion">${escHtml(m.meta.suggestion)}</div>` : '';
    return `<div class="chat-msg assistant">
      <div class="chat-avatar">AI</div>
      <div class="chat-bubble">${escHtml(m.text)}${suggestion}${actions}</div>
    </div>`;
  }).join('');
  el.scrollTop = el.scrollHeight;
}

function escHtml(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
}

async function chatSend(msg) {
  if (!msg || !msg.trim() || chatPending) return;
  const input = document.getElementById('chat-input');
  if (input) input.value = '';
  chatAppend('user', msg);
  chatPending = true;
  document.getElementById('chat-send-btn')?.setAttribute('disabled','1');
  try {
    const result = await api('/ai/chat', 'POST', { message: msg });
    chatAppend('assistant', result.reply || 'No response.', {
      action: result.action,
      product_ids: result.product_ids,
      suggestion: result.suggestion,
    });
  } catch(e) {
    chatAppend('assistant', '⚠️ Error: ' + (e.message || 'Unknown error'));
  } finally {
    chatPending = false;
    document.getElementById('chat-send-btn')?.removeAttribute('disabled');
    document.getElementById('chat-input')?.focus();
  }
}

async function chatReconsider(ids) {
  if (!ids?.length) return;
  if (!confirm(`Move ${ids.length} products back to Pending for review?`)) return;
  try {
    await api('/ai/chat', 'POST', { message: 'confirm reconsider', reconsider: true });
    // Actually call reconsider for each
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

async function renderChat() {
  setTitle('AI Assistant', 'Chat with your store AI');
  document.getElementById('topbar-actions').innerHTML = `
    <button class="btn-sm" onclick="chatHistory=[];renderChatMessages()">Clear chat</button>`;

  document.getElementById('content').innerHTML = `
    <div class="chat-page">
      <div class="chat-quick-row">
        ${QUICK_ACTIONS.map(a => `<button class="chat-quick-btn" onclick="chatSend(${JSON.stringify(a.msg)})">${a.label}</button>`).join('')}
      </div>
      <div class="chat-messages" id="chat-messages"></div>
      <div class="chat-input-row">
        <textarea class="chat-input" id="chat-input" placeholder="Ask anything about your store, or say 'find me rejected gems'…" rows="2"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();chatSend(this.value)}"></textarea>
        <button class="chat-send-btn" id="chat-send-btn" onclick="chatSend(document.getElementById('chat-input').value)">Send</button>
      </div>
    </div>`;

  renderChatMessages();

  // Welcome message on first open
  if (chatHistory.length === 0) {
    chatAppend('assistant', 'Hey! 👋 I\'m your store AI. I can review rejected products and find hidden gems, summarise your pipeline, or give keyword advice. What do you need?');
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
  if ((stats.pending || 0) > 0) return 'queue';
  if ((stats.text_edit || 0) > 0) return 'textEdit';
  if ((stats.approved || 0) > 0) return 'approved';
  return 'dashboard';
}

refreshStats().then(() => {
  currentPage = chooseStartPage();
  buildNav();
  renderPage();
});
setInterval(refreshStats, 20000);
api('/settings').then(s => { scanSource = String(s.cssbuy_source || '1688'); }).catch(() => {});



// v8 build 1777996588
