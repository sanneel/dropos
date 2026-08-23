/* ═══ DropOS — Brands: markets, each with its own persona and learning keyword pool ═══ */

let _brands = [];
let _brandDetailId = null;

async function renderBrands() {
  setTitle('Brands', 'each market has its own AI persona and keyword pool');
  setActions(`<button class="btn btn-primary btn-sm" onclick="newBrandForm()">+ New brand</button>
              <button class="btn btn-sm" onclick="renderBrands()" title="Refresh">↻</button>`);
  const el = document.getElementById('content');
  el.innerHTML = loadingState();
  const data = await api('/brands').catch(() => ({ brands: [] }));
  _brands = data.brands || [];
  if (_brandDetailId && !_brands.some(b => b.id === _brandDetailId)) _brandDetailId = null;
  if (_brandDetailId) return renderBrandDetail(_brandDetailId);

  el.innerHTML = `
    <div class="hint info">Autopilot rotates through active brands: it scans each brand's best keywords (plus a third of untested ones),
    scores products with <b>that brand's persona</b>, and the AI keyword generator copies the patterns of whatever performed best.
    Keywords below the performance floor are skipped automatically.</div>
    <div class="brand-grid">
      ${_brands.map(brandCardHtml).join('')}
      <button class="brand-card add" onclick="newBrandForm()"><span>+</span>New brand<small>a new market with its own keywords &amp; persona</small></button>
    </div>
    <div id="brand-form-slot"></div>`;
}

function brandCardHtml(b) {
  const pr = b.products || {};
  return `
    <div class="brand-card ${b.active ? '' : 'inactive'}" onclick="_brandDetailId=${b.id};renderBrands()">
      <div class="brand-hd">
        <span class="brand-name">${escHtml(b.name)}</span>
        ${toggleHtml(`brand-active-${b.id}`, !!b.active, `event.stopPropagation();toggleBrandActive(${b.id}, this.checked)`, true)}
      </div>
      <div class="brand-niche">${escHtml(b.niche || 'no niche description yet')}</div>
      <div class="brand-stats">
        <span><b>${b.keywords_active || 0}</b> keywords</span>
        <span><b>${b.keywords_untested || 0}</b> untested</span>
        <span><b>${b.keywords_ai || 0}</b> from AI</span>
      </div>
      <div class="brand-stats">
        <span><b>${pr.in_review || 0}</b> in review</span>
        <span><b>${pr.approved || 0}</b> queued</span>
        <span><b>${pr.live || 0}</b> live</span>
      </div>
      ${b.best_keyword ? `<div class="brand-best" title="Best performing keyword">★ ${escHtml(b.best_keyword)}</div>` : `<div class="brand-best muted">no tested keywords yet</div>`}
    </div>`;
}

async function toggleBrandActive(id, active) {
  try { await api(`/brands/${id}`, 'PATCH', { active }); toast(active ? 'Brand activated' : 'Brand paused', 'success', 1600); renderBrands(); } catch(e) { renderBrands(); }
}

function newBrandForm() {
  const slot = document.getElementById('brand-form-slot');
  if (!slot) return;
  slot.innerHTML = `
    <div class="card" style="margin-top:16px;max-width:680px">
      <div class="card-hd"><h3>New brand</h3></div>
      <div class="form-row">
        <div class="form-group"><label>Name</label><input type="text" id="nb-name" placeholder="e.g. Cozy Home, Pet Lovers…"/></div>
        <div class="form-group"><label>Sell price range (₾)</label>
          <div class="row"><input type="number" id="nb-min" value="40" min="0"/><span class="muted">–</span><input type="number" id="nb-max" value="119" min="0"/></div></div>
      </div>
      <div class="form-group"><label>Niche</label><input type="text" id="nb-niche" placeholder="what this market sells, in one line"/></div>
      <div class="form-group"><label>Target audience</label><input type="text" id="nb-audience" placeholder="who buys, ages, platform, mindset"/></div>
      <div class="form-group"><label>Example products that fit</label><textarea id="nb-examples" rows="2" placeholder="comma-separated examples the AI can anchor on"></textarea></div>
      <div class="form-group"><label>Starting keywords <span class="muted">(one per line — or leave empty and let the AI generate them)</span></label>
        <textarea id="nb-keywords" rows="4" class="mono"></textarea></div>
      <div class="row"><button class="btn btn-primary" onclick="createBrand()">Create brand</button>
      <button class="btn" onclick="document.getElementById('brand-form-slot').innerHTML=''">Cancel</button></div>
    </div>`;
  document.getElementById('nb-name')?.focus();
  slot.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function createBrand() {
  const g = id => document.getElementById(id);
  const name = (g('nb-name')?.value || '').trim();
  if (!name) { toast('Give the brand a name', 'error'); return; }
  try {
    const res = await api('/brands', 'POST', {
      name, niche: g('nb-niche')?.value || '', target_audience: g('nb-audience')?.value || '',
      example_products: g('nb-examples')?.value || '',
      sell_price_min: parseFloat(g('nb-min')?.value || 40), sell_price_max: parseFloat(g('nb-max')?.value || 119),
    });
    const kws = (g('nb-keywords')?.value || '').split('\n').map(s => s.trim()).filter(Boolean);
    if (kws.length) await api(`/brands/${res.id}/keywords`, 'POST', { keywords: kws });
    toast(`Brand “${name}” created${kws.length ? ` with ${kws.length} keywords` : ''}`, 'success');
    _brandDetailId = res.id;
    renderBrands();
  } catch(e) {}
}

// ── Brand detail ─────────────────────────────────────────────────────────────
async function renderBrandDetail(id) {
  const el = document.getElementById('content');
  const b = _brands.find(x => x.id === id);
  if (!b) { _brandDetailId = null; return renderBrands(); }
  setActions(`<button class="btn btn-sm" onclick="_brandDetailId=null;renderBrands()">← All brands</button>
              <button class="btn btn-sm btn-primary" onclick="saveBrand(${id})">Save changes</button>`);
  el.innerHTML = loadingState();
  const kw = await api(`/brands/${id}/keywords`).catch(() => ({ keywords: [], next_scan: [] }));
  const pr = b.products || {};
  el.innerHTML = `
    <div class="brand-detail">
      <div class="card">
        <div class="card-hd"><h3>${escHtml(b.name)}</h3>
          <label class="check" style="margin:0">${toggleHtml(`bd-active`, !!b.active, '', true)} <span class="muted">active</span></label></div>
        <div class="form-row">
          <div class="form-group"><label>Name</label><input type="text" id="bd-name" value="${escHtml(b.name)}"/></div>
          <div class="form-group"><label>Sell price range (₾)</label>
            <div class="row"><input type="number" id="bd-min" value="${b.sell_price_min ?? 40}"/><span class="muted">–</span><input type="number" id="bd-max" value="${b.sell_price_max ?? 119}"/></div></div>
        </div>
        <div class="form-group"><label>Niche</label><input type="text" id="bd-niche" value="${escHtml(b.niche || '')}"/></div>
        <div class="form-group"><label>Target audience</label><input type="text" id="bd-audience" value="${escHtml(b.target_audience || '')}"/></div>
        <div class="form-group"><label>Example products</label><textarea id="bd-examples" rows="2">${escHtml(b.example_products || '')}</textarea></div>
        <div class="form-row">
          <div class="form-group"><label>Keywords per scan</label><input type="number" id="bd-kps" value="${b.keywords_per_scan ?? 6}" min="1" max="15"/></div>
          <div class="form-group"><label>&nbsp;</label><label class="check">${toggleHtml('bd-autokw', b.auto_keywords_enabled !== 0 && b.auto_keywords_enabled !== false, '', true)} <span>AI tops up keywords automatically</span></label></div>
        </div>
        <div class="row" style="margin-top:6px">
          <button class="btn btn-sm btn-green" onclick="scanBrandNow(${id})">Scan now</button>
          <span class="muted">products: ${pr.total || 0} total · ${pr.in_review || 0} in review · ${pr.live || 0} live</span>
        </div>
      </div>

      <div class="card wide">
        <div class="card-hd"><h3>Keywords</h3>
          <div class="row">
            <button class="btn btn-sm btn-primary" onclick="generateKeywords(${id}, this)">✨ Generate with AI</button>
            <button class="btn btn-sm" onclick="toggleAddKeywords()">+ Add manually</button>
          </div>
        </div>
        <div id="add-kw-slot" style="display:none;margin-bottom:12px">
          <div class="row"><input type="text" id="add-kw-input" placeholder="one or more keywords, comma separated" style="flex:1" onkeydown="if(event.key==='Enter')addKeywordsManual(${id})"/>
          <button class="btn btn-sm" onclick="addKeywordsManual(${id})">Add</button></div>
        </div>
        ${kw.next_scan?.length ? `<div class="hint ok" style="margin-bottom:12px">Next scan will use: ${kw.next_scan.map(k => `<b>${escHtml(k)}</b>`).join(' · ')}</div>` : ''}
        ${keywordTableHtml(kw.keywords || [], kw.min_sample || 5)}
      </div>
    </div>`;
}

function keywordTableHtml(rows, minSample) {
  if (!rows.length) return emptyState('#', 'No keywords yet', 'Add a few manually or let the AI generate them from the brand persona.');
  rows = [...rows].sort((a, b) => (b.perf_score ?? -1) - (a.perf_score ?? -1) || b.id - a.id);
  return `
    <div class="card table-card" style="border:none">
      <table class="table">
        <thead><tr><th>Keyword</th><th>Source</th><th>Status</th><th>Scans</th><th>Found</th><th>Approved</th><th>Posted</th><th>Perf</th><th></th></tr></thead>
        <tbody>
          ${rows.map(k => {
            const perf = k.perf_score;
            const pct = perf == null ? 0 : Math.round(perf * 100);
            const perfCell = k.loser ? `<span class="chip v-reject" title="Proven loser — skipped by Autopilot">skip</span>`
              : perf == null ? `<span class="muted" title="Needs ${minSample}+ scored products">untested</span>`
              : `<div class="perf" title="approval 55% + posting 25% + avg AI score 20%"><i style="width:${pct}%"></i><span>${pct}</span></div>`;
            return `<tr class="${k.status !== 'active' ? 'kw-off' : ''}">
              <td class="td-name"><div class="tname">${escHtml(k.keyword)}</div></td>
              <td>${k.source === 'ai' ? '<span class="chip v-top">AI</span>' : '<span class="chip v-pending">manual</span>'}</td>
              <td><span class="chip ${k.status === 'active' ? 'v-strong' : k.status === 'paused' ? 'v-text' : 'v-reject'}">${k.status}</span></td>
              <td class="mono">${k.scans || 0}</td>
              <td class="mono">${k.scraped || 0}</td>
              <td class="mono">${k.approved || 0}${k.scored ? ` <span class="muted">/ ${k.scored}</span>` : ''}</td>
              <td class="mono">${k.posted || 0}</td>
              <td>${perfCell}</td>
              <td class="td-actions">
                ${k.status === 'active'
                  ? `<button class="btn btn-sm" onclick="setKw(${k.id},'paused')">Pause</button> <button class="btn btn-sm btn-danger-ghost" onclick="setKw(${k.id},'retired')">Retire</button>`
                  : `<button class="btn btn-sm btn-green" onclick="setKw(${k.id},'active')">Activate</button> <button class="btn btn-sm btn-danger-ghost" onclick="delKw(${k.id})" title="Delete forever">${IC.x}</button>`}
              </td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>`;
}

function toggleAddKeywords() {
  const s = document.getElementById('add-kw-slot');
  if (s) { s.style.display = s.style.display === 'none' ? 'block' : 'none'; document.getElementById('add-kw-input')?.focus(); }
}
async function addKeywordsManual(id) {
  const inp = document.getElementById('add-kw-input');
  const kws = (inp?.value || '').split(',').map(s => s.trim()).filter(Boolean);
  if (!kws.length) return;
  try { const r = await api(`/brands/${id}/keywords`, 'POST', { keywords: kws }); toast(`Added ${r.added} keyword${r.added === 1 ? '' : 's'}`, 'success'); renderBrands(); } catch(e) {}
}
async function generateKeywords(id, btn) {
  if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
  try {
    const r = await api(`/brands/${id}/keywords/generate`, 'POST', { count: 10 });
    toast(`AI added ${r.added} keywords: ${r.keywords.slice(0, 4).join(', ')}${r.keywords.length > 4 ? '…' : ''}`, 'success', 5000);
    renderBrands();
  } catch(e) { if (btn) { btn.disabled = false; btn.textContent = '✨ Generate with AI'; } }
}
async function setKw(id, status) { try { await api(`/keywords/${id}?status=${status}`, 'PATCH'); renderBrands(); } catch(e) {} }
async function delKw(id) { try { await api(`/keywords/${id}`, 'DELETE'); renderBrands(); } catch(e) {} }

async function saveBrand(id) {
  const g = i => document.getElementById(i);
  try {
    await api(`/brands/${id}`, 'PATCH', {
      name: (g('bd-name')?.value || '').trim() || undefined,
      active: !!g('bd-active')?.checked,
      niche: g('bd-niche')?.value ?? '', target_audience: g('bd-audience')?.value ?? '',
      example_products: g('bd-examples')?.value ?? '',
      sell_price_min: parseFloat(g('bd-min')?.value || 40), sell_price_max: parseFloat(g('bd-max')?.value || 119),
      keywords_per_scan: parseInt(g('bd-kps')?.value || 6),
      auto_keywords_enabled: !!g('bd-autokw')?.checked,
    });
    toast('Brand saved', 'success');
    renderBrands();
  } catch(e) {}
}

async function scanBrandNow(id) {
  try {
    const res = await api(`/scheduler/trigger?brand_id=${id}`, 'POST', {});
    toast(`Scan started with: ${res.keywords.join(', ')}`, 'success', 5000);
    activeJob = { id: res.job_id, status: 'queued', progress: 0 };
    if (activeJobPoll) clearInterval(activeJobPoll);
    activeJobPoll = setInterval(pollActiveJob, 2000);
    navigate('scans', 'new');
  } catch(e) {}
}

registerPage('brands', renderBrands);
