/* ═══ DropOS — Review: what a human still has to decide ═══ */

let queueVerdictFilter = 'all';
let rejectedFilter = 'all';

async function renderReview(tab) {
  const labels = { queue: 'Needs your decision', textEdit: 'Photos with Chinese text', rejected: 'Rejected products' };
  setTitle('Review', labels[tab] || '');
  setActions(tab === 'queue'
    ? `<select class="sel-sm" onchange="queueSort=this.value;loadQueue()">
         <option value="score"   ${queueSort==='score'  ?'selected':''}>Best score first</option>
         <option value="created" ${queueSort==='created'?'selected':''}>Newest first</option>
         <option value="margin"  ${queueSort==='margin' ?'selected':''}>Highest margin</option>
         <option value="orders"  ${queueSort==='orders' ?'selected':''}>Most sold</option>
       </select>
       <button class="btn btn-sm" onclick="loadQueue()" title="Refresh">↻</button>`
    : `<button class="btn btn-sm" onclick="renderReview('${tab}')" title="Refresh">↻</button>`);
  const el = document.getElementById('content');
  el.innerHTML = tabBar('review') + `<div id="review-body">${loadingState()}</div>`;
  if (tab === 'textEdit') return loadTextEdit();
  if (tab === 'rejected') return renderRejected();
  return loadQueue();
}

// ── Needs decision (ENRICHED) ───────────────────────────────────────────────
async function loadQueue(append = false) {
  const offset = append ? queueProducts.length : 0;
  if (!append) queueProducts = [];
  const data = await api(`/products?stage=ENRICHED&limit=60&offset=${offset}&sort=${queueSort}`).catch(() => ({ products: [], total: 0 }));
  queueProducts = append ? queueProducts.concat(data.products) : data.products;
  queueTotal = data.total;
  renderQueueGrid();
}

function _visibleQueue() {
  if (queueVerdictFilter === 'all') return queueProducts;
  if (queueVerdictFilter === 'unscored') return queueProducts.filter(p => !p.ai_provider || p.ai_provider === 'mock');
  return queueProducts.filter(p => p.verdict === queueVerdictFilter);
}

function renderQueueGrid() {
  const body = document.getElementById('review-body'); if (!body) return;
  const ap = autopilotData;
  const autoOn = !!(ap?.enabled && settingsData.auto_approve_enabled !== false);
  if (!queueProducts.length) {
    body.innerHTML = emptyState('✓', 'Nothing to decide', autoOn
      ? 'Autopilot approves the clear winners by itself; only borderline products show up here.'
      : 'Scored products appear here. Turn on Autopilot to auto-approve the clear winners.',
      `<div class="empty-actions"><button class="btn" onclick="navigate('scans','new')">Run a scan</button><button class="btn btn-ghost" onclick="navigate('home')">Autopilot</button></div>`);
    return;
  }
  const counts = { top_priority: 0, strong_candidate: 0, pending_review: 0, unscored: 0 };
  queueProducts.forEach(p => { if (!p.ai_provider || p.ai_provider === 'mock') counts.unscored++; else if (counts[p.verdict] != null) counts[p.verdict]++; });
  const visible = _visibleQueue();
  const canMore = queueProducts.length < queueTotal;
  const chip = (id, label, n) => n || id === 'all' ? `<button class="fchip ${queueVerdictFilter === id ? 'active' : ''}" onclick="queueVerdictFilter='${id}';renderQueueGrid()">${label}${n ? ` <b>${n}</b>` : ''}</button>` : '';
  body.innerHTML = `
    <div class="toolbar">
      <div class="toolbar-l">
        <span class="toolbar-count"><b>${queueTotal}</b> waiting</span>
        ${chip('all', 'All', 0)}${chip('top_priority', 'Top picks', counts.top_priority)}${chip('strong_candidate', 'Strong', counts.strong_candidate)}${chip('pending_review', 'Needs a look', counts.pending_review)}${chip('unscored', 'Unscored', counts.unscored)}
      </div>
      <div class="toolbar-r">
        <button class="btn btn-sm" onclick="selectAll()">Select visible</button>
        <button class="btn btn-sm btn-green" onclick="selectAll();batchApprove()">Approve visible</button>
        <button class="btn btn-sm btn-danger-ghost" onclick="selectAll();batchReject()">Reject visible</button>
        <button class="btn btn-sm btn-danger-ghost" onclick="rejectAllPending()" title="Reject every pending product">Reject all (${queueTotal})</button>
      </div>
    </div>
    ${autoOn ? '' : `<div class="hint">Tip: with <b>Autopilot</b> on, products scoring ≥ ${Number(settingsData.auto_approve_min_score || 7).toFixed(1)} are approved automatically and only borderline ones land here. <a href="#" onclick="navigate('home');return false">Turn it on →</a></div>`}
    <div class="product-grid" id="product-grid">${visible.map(p => productCard(p, 'queue')).join('')}</div>
    ${visible.length === 0 ? `<div class="empty small">No products match this filter</div>` : ''}
    ${canMore ? `<div class="more"><button class="btn" onclick="loadQueue(true)">Load more (${queueTotal - queueProducts.length} remaining)</button></div>` : ''}
    <div class="hotkey-hint">j / k move · <b>a</b> approve · <b>r</b> reject · Enter details · ? help</div>`;
  updateSelBar();
}

// ── Text edit (TEXT_REMOVAL) ─────────────────────────────────────────────────
async function loadTextEdit(append = false) {
  const offset = append ? textEditProducts.length : 0;
  if (!append) textEditProducts = [];
  const data = await api(`/products?stage=TEXT_REMOVAL&limit=60&offset=${offset}&sort=score`).catch(() => ({ products: [], total: 0 }));
  textEditProducts = append ? textEditProducts.concat(data.products) : data.products;
  textEditTotal = data.total;
  renderTextEditGrid();
}
function renderTextEditGrid() {
  const body = document.getElementById('review-body'); if (!body) return;
  const hasClip = !!settingsData.clipdrop_key_set;
  if (!textEditProducts.length) {
    body.innerHTML = emptyState('文', 'No photos need cleaning', hasClip
      ? 'Approved products whose photo has Chinese text land here. With Autopilot on, Clipdrop cleans them automatically.'
      : 'Approved products whose photo has Chinese text land here. Add a Clipdrop key in Settings → Connections to clean them in one click.');
    return;
  }
  const canMore = textEditProducts.length < textEditTotal;
  body.innerHTML = `
    <div class="toolbar">
      <div class="toolbar-l"><span class="toolbar-count"><b>${textEditTotal}</b> photos with Chinese text</span>
        ${hasClip ? '' : `<span class="chip v-text">Clipdrop key missing — <a href="#" onclick="navigate('settings','connections');return false">add it</a></span>`}</div>
      <div class="toolbar-r">
        ${hasClip ? `<button class="btn btn-sm btn-green" onclick="batchCleanImages(this)">Clean all visible</button>` : ''}
        <button class="btn btn-sm" onclick="selectAll()">Select visible</button>
        <button class="btn btn-sm" onclick="selectAll();batchMarkTextEdited()">Mark visible as fine</button>
      </div>
    </div>
    <div class="product-grid" id="product-grid">${textEditProducts.map(p => productCard(p, 'TEXT_REMOVAL')).join('')}</div>
    ${canMore ? `<div class="more"><button class="btn" onclick="loadTextEdit(true)">Load more (${textEditTotal - textEditProducts.length} remaining)</button></div>` : ''}`;
  updateSelBar('TEXT_REMOVAL');
}

// ── Rejected ────────────────────────────────────────────────────────────────
async function renderRejected() {
  const data = await api('/products?stage=REJECTED&limit=200&sort=created').catch(() => ({ products: [], total: 0 }));
  rejectedProducts = data.products; rejectedTotal = data.total;
  renderRejectedTable();
}
function _rejectSource(p) {
  const r = p.rejection_reason || '';
  if (r.startsWith('Curator:')) return 'ai';
  if (r.startsWith('Bouncer:') || r.startsWith('Detective:') || r.startsWith('hard_reject') || r.startsWith('Autopilot:')) return 'filter';
  return 'me';
}
function renderRejectedTable() {
  const body = document.getElementById('review-body'); if (!body) return;
  if (!rejectedProducts.length) { body.innerHTML = emptyState('✕', 'No rejected products', 'Rejected products appear here with their reasons so you can reconsider.'); return; }
  const counts = { ai: 0, filter: 0, me: 0 };
  rejectedProducts.forEach(p => counts[_rejectSource(p)]++);
  const list = rejectedFilter === 'all' ? rejectedProducts : rejectedProducts.filter(p => _rejectSource(p) === rejectedFilter);
  const chip = (id, label, n) => `<button class="fchip ${rejectedFilter === id ? 'active' : ''}" onclick="rejectedFilter='${id}';renderRejectedTable()">${label}${n ? ` <b>${n}</b>` : ''}</button>`;
  body.innerHTML = `
    <div class="toolbar">
      <div class="toolbar-l"><span class="toolbar-count"><b>${rejectedTotal}</b> rejected</span>
        ${chip('all', 'All', 0)}${chip('ai', 'By AI', counts.ai)}${chip('filter', 'By filters', counts.filter)}${chip('me', 'By you', counts.me)}</div>
    </div>
    <div class="card table-card">
      <table class="table">
        <thead><tr><th></th><th>Product</th><th>Score</th><th>Reason</th><th>When</th><th></th></tr></thead>
        <tbody>
          ${list.map(p => `
            <tr>
              <td class="td-thumb" onclick="showDetail(${p.id})">${firstImage(p) ? `<img src="${imageUrl(firstImage(p))}" loading="lazy" onerror="this.style.display='none'">` : ''}</td>
              <td class="td-name" onclick="showDetail(${p.id})">
                <div class="tname">${escHtml(p.product_name || p.title_translated || '—')}</div>
                <div class="tsub">${escHtml(p.keyword || p.category || '')}</div>
              </td>
              <td><span class="score-pill sm ${scoreClass(p.composite_score ?? p.score ?? 0)}">${(p.composite_score ?? p.score ?? 0).toFixed(1)}</span></td>
              <td class="td-reason">${p.rejection_reason ? escHtml(p.rejection_reason) : '<span class="muted">—</span>'}</td>
              <td class="td-time">${fmtDate(p.rejected_at || p.created_at)}</td>
              <td><button class="btn btn-sm" onclick="reconsider(${p.id})">Reconsider</button></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

registerPage('review', renderReview);
