/* ═══ DropOS — Scans: start a scan, see where every product dropped out ═══ */

async function renderScans(tab) {
  setTitle('Scans', tab === 'history' ? 'where each scraped product dropped out' : 'find new products on 1688 / Taobao');
  setActions(tab === 'history' ? `<button class="btn btn-sm" onclick="clearScanHistory()">Clear history</button>` : '');
  const el = document.getElementById('content');
  el.innerHTML = tabBar('scans') + `<div id="scans-body">${loadingState()}</div>`;
  if (tab === 'history') { pipelineJobs = []; return renderPipeline(); }
  return renderScanNew();
}

// ── Scan ───────────────────────────────────────────────────────────────────
async function renderScanNew() {
  try {
    settingsData = await api('/settings');
    scanSource = String(settingsData.cssbuy_source || scanSource || '1688');
    if (!scanKeywords.length) scanKeywords = [...(settingsData.scan_keywords || [])];
  } catch (e) {}
  // pick up a scan that is already running (e.g. started by Autopilot)
  try { const jobs = await api('/jobs?limit=1'); const j = jobs[0]; if (j && !['done','error','interrupted'].includes(j.status)) activeJob = j; } catch(e) {}
  renderScanContent();
  if (activeJob && !activeJobPoll) activeJobPoll = setInterval(pollActiveJob, 2000);
}

function renderScanContent() {
  const localOnly = !!settingsData.local_scraping_only;
  const host = document.getElementById('scans-body'); if (!host) return;
  const noCreds = !settingsData.cssbuy_username || !settingsData.cssbuy_password_set;
  host.innerHTML = `
    ${noCreds && !localOnly ? `<div class="hint warn">CSSBuy login is not set — scans will find nothing. <a href="#" onclick="navigate('settings','connections');return false">Add it in Settings → Connections</a>.</div>` : ''}
    ${autopilotData?.enabled && settingsData.auto_scan_enabled !== false ? `<div class="hint ok">Autopilot scans these saved keywords every ${settingsData.scan_interval_hours || 12}h. You can still start one now.</div>` : ''}
    `+`
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
      <div>
        <div class="card" style="margin-bottom:14px">
          <div class="card-title">Search keywords</div>
          <div style="display:flex;flex-wrap:wrap;gap:7px;margin-bottom:12px">
            ${scanKeywords.map((kw, i) => `
              <div class="keyword-tag">${escHtml(kw)}
                <button onclick="removeKeyword(${i})" title="Remove">×</button>
              </div>`).join('')}
            ${!scanKeywords.length ? '<span class="muted">No keywords yet — add a few below</span>' : ''}
          </div>
          <div style="margin-top:8px"><button class="btn btn-sm" onclick="saveScanKeywords()">Save as Autopilot keywords</button></div>
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
      toast(`Scan done · ${job.after_ai} products sent to AI scoring`, 'success');
      await refreshStats();
      if (curView() === 'scan') renderScanContent();
    } else {
      dot.className = 'status-dot on'; lbl.textContent = job.status;
      if (curView() === 'scan') renderScanContent();
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


async function saveScanKeywords() {
  try { await api('/settings', 'PATCH', { scan_keywords: scanKeywords }); settingsData.scan_keywords = [...scanKeywords]; toast('Saved — Autopilot will scan these keywords', 'success'); } catch(e) {}
}


// ── Pipeline ───────────────────────────────────────────────────────────────

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
  const el = document.getElementById('scans-body'); if (!el) return;

  // Load jobs list
  if (!pipelineJobs.length) {
    pipelineJobs = await api('/jobs?limit=30').catch(() => []);
  }
  if (!pipelineJobs.length) {
    el.innerHTML = emptyState('○', 'No scans yet', 'Run a scan or let Autopilot do it — every scan shows up here with a breakdown of what was filtered out and why.', `<div class="empty-actions"><button class="btn" onclick="navigate('scans','new')">New scan</button></div>`);
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

  const jobOptions = pipelineJobs.map(j => `<option value="${j.id}" ${j.id===pipelineJobId?'selected':''}>#${j.id} · ${escHtml((j.keywords||[]).join(', ').substring(0,40))} · ${escHtml(j.status||'')} · ${fmtDate(j.created_at)}</option>`).join('');

  el.innerHTML = `
    <div style="max-width:1100px">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
        <select class="sel-sm" style="flex:1;max-width:520px" onchange="pipelineJobId=+this.value;pipelineActiveStage=null;pipelineData=null;renderPipeline()">
          ${jobOptions}
        </select>
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
  pipelineJobs = []; pipelineJobId = null; pipelineActiveStage = null; pipelineData = null;
  activeJob = null;
  if (activeJobPoll) { clearInterval(activeJobPoll); activeJobPoll = null; }
  renderPipeline();
  toast('Scan history cleared', 'success');
  await refreshStats();
  renderPipeline();
}


registerPage('scans', renderScans);
