/* ═══ DropOS — product card, selection, batch actions, detail drawer (shared by Review & Posts) ═══ */

// ── Product card ───────────────────────────────────────────────────────────
const VERDICT_CFG = {
  top_priority:     ['v-top',    'top pick'],
  strong_candidate: ['v-strong', 'strong'],
  pending_review:   ['v-pending','needs a look'],
  auto_reject:      ['v-reject', 'auto reject'],
};
function verdictBadge(verdict) {
  if (!verdict) return '';
  const [cls, label] = VERDICT_CFG[verdict] || ['v-pending', String(verdict).replace(/_/g, ' ')];
  return `<span class="chip ${cls}">${escHtml(label)}</span>`;
}
function scoreClass(score) { return score >= 8 ? 'hi' : score >= 7 ? 'mi' : score >= 6 ? 'lo' : 'bad'; }
function dimsBar(p) {
  const sc = p.scores || {};
  const dims = [
    ['Cute appeal',      sc.cute_appeal      ?? p.cute_appeal   ?? 0],
    ['Romantic trigger', sc.romantic_trigger ?? p.niche_fit     ?? 0],
    ['Visual',           sc.visual_score     ?? p.visual_appeal ?? 0],
    ['Trend fit',        sc.trend_fit        ?? p.trend_score   ?? 0],
    ['Giftability',      sc.giftability      ?? p.giftability   ?? 0],
  ];
  if (!p.ai_provider || p.ai_provider === 'mock') return '';
  if (!dims.some(([, v]) => Number(v) > 0)) return '';
  return `<div class="dims" title="${dims.map(([l, v]) => `${l} ${Number(v).toFixed(1)}`).join(' · ')}">
    ${dims.map(([l, v]) => `<span class="dim"><i style="height:${Math.max(8, Math.min(100, Number(v) * 10))}%"></i></span>`).join('')}
  </div>`;
}

function productCard(p, mode) {
  const sel = selectedProducts.has(p.id);
  const img = imageUrl(firstImage(p));
  const score = Number(p.composite_score || p.score || 0);
  const sc = scoreClass(score);
  const scored = p.ai_provider && p.ai_provider !== 'mock';

  let actions = '';
  if (mode === 'queue') {
    actions = `<button class="pca pca-approve" onclick="event.stopPropagation();quickApprove(${p.id})">Approve</button>
               <button class="pca pca-reject" title="Reject" onclick="event.stopPropagation();showRejectModal(${p.id})">${IC.x}</button>`;
  } else if (mode === 'REVIEWED') {
    actions = `<button class="pca pca-post" onclick="event.stopPropagation();quickPost(${p.id})">Post now</button>
               <button class="pca pca-ghost" title="Mark live without Instagram" onclick="event.stopPropagation();quickPublishWebsite(${p.id})">Skip IG</button>
               <button class="pca pca-reject" title="Reject" onclick="event.stopPropagation();showRejectModal(${p.id})">${IC.x}</button>`;
  } else if (mode === 'TEXT_REMOVAL') {
    actions = `<button class="pca pca-approve" id="clean-btn-${p.id}" onclick="event.stopPropagation();cleanImage(${p.id},this)">Clean photo</button>
               <button class="pca pca-ghost" title="Photo is fine — approve as is" onclick="event.stopPropagation();markTextEdited(${p.id})">Looks fine</button>
               <button class="pca pca-reject" title="Reject" onclick="event.stopPropagation();showRejectModal(${p.id})">${IC.x}</button>`;
  }

  const name = escHtml(p.product_name || p.title_translated || p.title || 'Unknown');
  const sub  = p.product_name && p.title_translated && p.product_name !== p.title_translated ? escHtml(p.title_translated) : '';
  const ordersLabel = (p.source || '').includes('taobao') ? 'sales n/a' : `${(p.orders ?? 0).toLocaleString()} sold`;
  const meta = [p.category ? escHtml(p.category) : '', p.keyword ? `#${escHtml(p.keyword)}` : ''].filter(Boolean).join(' · ');

  return `
    <div class="product-card${sel ? ' selected' : ''}" id="card-${p.id}" onclick="showDetail(${p.id})">
      <div class="pcard-img-wrap">
        ${img ? `<img class="pcard-img" src="${img}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">` : ''}
        <div class="pcard-placeholder" style="${img ? 'display:none' : ''}">no photo</div>
        <div class="pcard-top">
          <span class="score-pill ${sc}" title="AI composite score">${scored ? score.toFixed(1) : '–'}</span>
          ${p.has_chinese_text ? `<span class="chip v-text" title="${escHtml(p.chinese_text_note || 'Chinese text in photo')}">文 text</span>` : ''}
        </div>
        <button class="pcard-check ${sel ? 'on' : ''}" onclick="event.stopPropagation();toggleSel(${p.id})" title="Select">${IC.check}</button>
      </div>
      <div class="pcard-body">
        <div class="pcard-row">
          ${verdictBadge(p.verdict)}
          ${dimsBar(p)}
        </div>
        <div class="pcard-name editable" title="Double-click to rename" ondblclick="event.stopPropagation();startEdit(${p.id}, 'product_name', this)">${name}</div>
        ${sub ? `<div class="pcard-sub">${sub}</div>` : ''}
        <div class="pcard-meta">${meta || '—'}</div>
        <div class="pcard-pricing">
          <span class="p-sell editable" title="Double-click to change price" ondblclick="event.stopPropagation();startEdit(${p.id}, 'sell_price_eur', this)">₾${p.sell_price_eur ?? '?'}</span>
          <span class="p-cost">cost ₾${p.cost_eur ?? '?'}</span>
          <span class="p-margin ${(p.margin_pct ?? 0) >= 60 ? 'good' : ''}">${p.margin_pct ?? 0}%</span>
          <span class="p-social">★ ${p.rating ?? 0} · ${ordersLabel}</span>
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
  updateSelBar(curView() === 'REVIEWED' ? 'post' : curView() === 'textEdit' ? 'TEXT_REMOVAL' : 'approve');
}

function selectAll() {
  const list = curView() === 'REVIEWED' ? approvedProducts : curView() === 'textEdit' ? textEditProducts : queueProducts;
  list.slice(0, 10).forEach(p => selectedProducts.add(p.id));
  if (curView() === 'REVIEWED') renderApprovedGrid();
  else if (curView() === 'textEdit') renderTextEditGrid();
  else renderQueueGrid();
}

function clearSel() {
  selectedProducts.clear();
  if (curView() === 'REVIEWED') renderApprovedGrid();
  else if (curView() === 'textEdit') renderTextEditGrid();
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
    if (curView() === 'queue') { queueTotal = Math.max(0, queueTotal - 1); renderQueueGrid(); }
    else if (curView() === 'REVIEWED') { approvedTotal = Math.max(0, approvedTotal - 1); renderApprovedGrid(); }
    else if (curView() === 'textEdit') { textEditTotal = Math.max(0, textEditTotal - 1); renderTextEditGrid(); }
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
  const srcLabel = (p.source || '').replace('cssbuy_', '').replace('_mock', '');
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
          ${srcLabel ? `<span class="badge badge-gray">${escHtml(srcLabel)}</span>` : ''}
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

        <div class="detail-sec">
          <span class="detail-sec-lbl" style="display:flex;align-items:center;justify-content:space-between;gap:8px">Instagram caption
            <button class="btn btn-sm" id="rewrite-btn-${p.id}" onclick="rewriteCaption(${p.id}, this)" title="Write a fresh caption with the content model">✍ Rewrite</button>
          </span>
          <div class="card-sm" id="caption-box-${p.id}" style="font-size:12.5px;color:var(--t2);line-height:1.7;white-space:pre-wrap">${p.caption ? escHtml(p.caption) : '<span class="muted">no caption yet — Rewrite writes one</span>'}</div>
        </div>

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

async function rewriteCaption(id, btn) {
  if (btn) { btn.disabled = true; btn.textContent = 'Writing…'; }
  try {
    const r = await api(`/products/${id}/rewrite-caption`, 'POST');
    const box = document.getElementById(`caption-box-${id}`);
    if (box) box.textContent = r.caption;
    [queueProducts, approvedProducts, textEditProducts, catalogProducts].forEach(list => {
      const p = list.find(x => x.id === id); if (p) { p.caption = r.caption; if (r.hashtags?.length) p.hashtags = r.hashtags; }
    });
    toast(`New caption by ${r.provider}`, 'success');
  } catch(e) {
  } finally { if (btn) { btn.disabled = false; btn.textContent = '✍ Rewrite'; } }
}

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
    if (curView() === 'queue') renderQueueGrid();
    if (curView() === 'REVIEWED') renderApprovedGrid();
    if (curView() === 'REJECTED') renderRejectedTable();
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



// ── Inline editing (double-click on name / price) ──────────────────────────
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

