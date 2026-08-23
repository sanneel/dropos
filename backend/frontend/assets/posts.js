/* ═══ DropOS — Posts: the approved queue, what went live, and the full catalog ═══ */

async function renderPosts(tab) {
  const labels = { queue: 'Approved — ready for Instagram', posted: 'Live on Instagram', all: 'Every approved & posted product' };
  setTitle('Posts', labels[tab] || '');
  setActions(`<button class="btn btn-sm" onclick="renderPosts('${tab}')" title="Refresh">↻</button>`);
  const el = document.getElementById('content');
  el.innerHTML = tabBar('posts') + `<div id="posts-body">${loadingState()}</div>`;
  await loadBrandsCache();
  if (tab === 'posted') return renderPosted();
  if (tab === 'all') return renderCatalog();
  return loadApproved();
}

// ── Queue (REVIEWED) ────────────────────────────────────────────────────────
async function loadApproved(append = false) {
  const offset = append ? approvedProducts.length : 0;
  if (!append) approvedProducts = [];
  const bq = brandFilter ? `&brand_id=${brandFilter}` : '';
  const data = await api(`/products?stage=REVIEWED&limit=60&offset=${offset}&sort=score${bq}`).catch(() => ({ products: [], total: 0 }));
  approvedProducts = append ? approvedProducts.concat(data.products) : data.products;
  approvedTotal = data.total;
  renderApprovedGrid();
}

function _postingSummary() {
  const st = (autopilotData?.stages || []).find(s => s.key === 'post');
  const ig = !!settingsData.instagram_connected;
  if (!ig) return { cls: 'warn', text: `Instagram is not connected — posts are simulated. Direct login needs no Meta account: <a href="#" onclick="navigate('settings','connections');return false">connect it</a>.` };
  if (!autopilotData?.enabled || !settingsData.post_schedule_enabled) return { cls: 'info', text: `Auto-posting is off — post manually below or <a href="#" onclick="navigate('home');return false">turn on Autopilot</a>.` };
  const next = st?.next_run ? `next post ${untilTime(st.next_run)} (${new Date(st.next_run).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })})` : 'no slot planned';
  return { cls: 'ok', text: `Autopilot posts the top product at ${escHtml((settingsData.post_times || ['19:00', '21:00']).join(', '))} · ${next} · ${st?.today || 0} posted today (max ${settingsData.max_posts_per_day || 2}/day).` };
}

function renderApprovedGrid() {
  const body = document.getElementById('posts-body'); if (!body) return;
  const sum = _postingSummary();
  if (!approvedProducts.length) {
    body.innerHTML = `<div class="hint ${sum.cls}">${sum.text}</div>` + emptyState('◆', 'Nothing approved yet', 'Approved products wait here in score order; the best one goes out at each posting slot.',
      `<div class="empty-actions"><button class="btn" onclick="navigate('review')">Go to Review</button></div>`);
    return;
  }
  const canMore = approvedProducts.length < approvedTotal;
  body.innerHTML = `
    <div class="hint ${sum.cls}">${sum.text}</div>
    <div class="toolbar">
      <div class="toolbar-l"><span class="toolbar-count"><b>${approvedTotal}</b> in queue · best score posts first</span>${brandFilterChips('loadApproved()')}</div>
      <div class="toolbar-r">
        <button class="btn btn-sm" onclick="selectAll()">Select visible</button>
        <button class="btn btn-sm" onclick="batchPublishWebsite()" title="Mark selected as live without posting">Skip IG for selected</button>
      </div>
    </div>
    <div class="product-grid" id="product-grid">${approvedProducts.map((p, i) => productCard(p, 'REVIEWED').replace('<div class="pcard-top">', `<div class="pcard-top">${i < 2 ? `<span class="chip v-next">${i === 0 ? 'next up' : 'after that'}</span>` : ''}`)).join('')}</div>
    ${canMore ? `<div class="more"><button class="btn" onclick="loadApproved(true)">Load more (${approvedTotal - approvedProducts.length} remaining)</button></div>` : ''}
    <div class="hotkey-hint">Select 2–6 products to post them as one <b>collage</b> · <b>a</b> posts the highlighted card now</div>`;
  updateSelBar('post');
}

// ── Posted (LIVE) ────────────────────────────────────────────────────────────
async function renderPosted() {
  const body = document.getElementById('posts-body'); if (!body) return;
  const data = await api('/products?stage=LIVE&limit=200&sort=created').catch(() => ({ products: [], total: 0 }));
  if (!data.products.length) { body.innerHTML = emptyState('◉', 'Nothing posted yet', 'Posts show up here with their Instagram link once they go live.'); return; }
  body.innerHTML = `
    <div class="toolbar"><div class="toolbar-l"><span class="toolbar-count"><b>${data.total}</b> posted</span></div></div>
    <div class="card table-card">
      <table class="table">
        <thead><tr><th></th><th>Product</th><th>Score</th><th>Price</th><th>Margin</th><th>Posted</th><th></th></tr></thead>
        <tbody>
          ${data.products.map(p => `
            <tr>
              <td class="td-thumb" onclick="showDetail(${p.id})">${firstImage(p) ? `<img src="${imageUrl(firstImage(p))}" loading="lazy" onerror="this.style.display='none'">` : ''}</td>
              <td class="td-name" onclick="showDetail(${p.id})"><div class="tname">${escHtml(p.product_name || p.title_translated || '—')}</div><div class="tsub">${escHtml(p.keyword || p.category || '')}</div></td>
              <td><span class="score-pill sm ${scoreClass(p.composite_score ?? p.score ?? 0)}">${(p.composite_score ?? p.score ?? 0).toFixed(1)}</span></td>
              <td class="mono">₾${p.sell_price_eur ?? 0}</td>
              <td class="mono ${(p.margin_pct ?? 0) >= 60 ? 'good' : ''}">${p.margin_pct ?? 0}%</td>
              <td class="td-time">${fmtDate(p.posted_at || p.created_at)}</td>
              <td>${p.instagram_url && !p.instagram_url.includes('mock') ? `<a class="btn btn-sm" href="${safeUrl(p.instagram_url)}" target="_blank" rel="noopener noreferrer">Open ${IC.ext}</a>` : `<span class="muted" title="Posted without Instagram or simulated">${p.instagram_url ? 'simulated' : 'no IG'}</span>`}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

// ── All products (catalog with search + inline edit) ─────────────────────────
let _catalogEditId = null;

async function renderCatalog() {
  catalogPage = 0; catalogProducts = [];
  await loadCatalog();
}

async function loadCatalog(append = false) {
  const offset = append ? catalogProducts.length : 0;
  const q = catalogSearch ? `&q=${encodeURIComponent(catalogSearch)}` : '';
  let products = [], total = 0;
  if (catalogStage === 'all') {
    const [a, p] = await Promise.all([
      api(`/products?stage=REVIEWED&limit=50&offset=${offset}&sort=created${q}`).catch(() => ({ products: [], total: 0 })),
      api(`/products?stage=LIVE&limit=50&offset=${offset}&sort=created${q}`).catch(() => ({ products: [], total: 0 })),
    ]);
    products = [...a.products, ...p.products]; total = a.total + p.total;
  } else {
    const data = await api(`/products?stage=${catalogStage}&limit=50&offset=${offset}&sort=created${q}`).catch(() => ({ products: [], total: 0 }));
    products = data.products; total = data.total;
  }
  catalogProducts = append ? catalogProducts.concat(products) : products;
  catalogTotal = total;
  renderCatalogTable();
}

function renderCatalogTable() {
  const body = document.getElementById('posts-body'); if (!body) return;
  const canMore = catalogProducts.length < catalogTotal;
  body.innerHTML = `
    <div class="toolbar">
      <div class="toolbar-l">
        <button class="fchip ${catalogStage==='all'?'active':''}" onclick="setCatalogStage('all')">All</button>
        <button class="fchip ${catalogStage==='REVIEWED'?'active':''}" onclick="setCatalogStage('REVIEWED')">Approved</button>
        <button class="fchip ${catalogStage==='LIVE'?'active':''}" onclick="setCatalogStage('LIVE')">Posted</button>
        <input type="search" class="search" id="catalog-search-input" placeholder="Search name, category, caption…" value="${escHtml(catalogSearch)}" oninput="debCatalogSearch(this.value)"/>
      </div>
      <div class="toolbar-r"><span class="toolbar-count">${catalogProducts.length}${catalogTotal > catalogProducts.length ? ' of ' + catalogTotal : ''} products</span></div>
    </div>
    ${catalogProducts.length === 0 ? emptyState('🗂', 'No products found', catalogSearch ? 'Try a different search' : 'Approve products from Review first') : `
    <div class="card table-card">
      <table class="table">
        <thead><tr><th></th><th>Name</th><th>Price</th><th>Stage</th><th>Score</th><th>Caption</th><th></th></tr></thead>
        <tbody id="catalog-tbody">${catalogProducts.map(p => catalogRow(p)).join('')}</tbody>
      </table>
    </div>
    ${canMore ? `<div class="more"><button class="btn" onclick="loadCatalog(true)">Load more (${catalogTotal - catalogProducts.length} remaining)</button></div>` : ''}`}`;
  const inp = document.getElementById('catalog-search-input');
  if (inp && catalogSearch) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
}

function catalogRow(p, editMode = false) {
  const img = firstImage(p);
  const name = p.product_name || p.title_translated || '—';
  const price = p.sell_price_eur ?? 0;
  const caption = p.caption || '';
  const stageBadge = p.stage === 'LIVE' ? '<span class="chip v-live">Posted</span>' : '<span class="chip v-strong">Approved</span>';
  const score = (p.composite_score ?? p.score ?? 0).toFixed(1);
  if (editMode) {
    return `<tr id="cat-row-${p.id}" class="editing">
      <td class="td-thumb">${img ? `<img src="${imageUrl(img)}" onerror="this.style.display='none'">` : ''}</td>
      <td><input id="cat-name-${p.id}" class="cat-input" type="text" value="${escHtml(name)}" placeholder="Product name"></td>
      <td><input id="cat-price-${p.id}" class="cat-input" type="number" step="0.01" min="0" value="${price}" style="width:90px"></td>
      <td>${stageBadge}</td>
      <td><span class="score-pill sm ${scoreClass(+score)}">${score}</span></td>
      <td><textarea id="cat-caption-${p.id}" class="cat-input" rows="3" placeholder="Instagram caption">${escHtml(caption)}</textarea></td>
      <td class="td-actions"><button class="btn btn-sm btn-green" onclick="saveCatalogRow(${p.id})">Save</button> <button class="btn btn-sm" onclick="cancelCatalogEdit(${p.id})">Cancel</button></td>
    </tr>`;
  }
  return `<tr id="cat-row-${p.id}">
    <td class="td-thumb" onclick="showDetail(${p.id})">${img ? `<img src="${imageUrl(img)}" loading="lazy" onerror="this.style.display='none'">` : ''}</td>
    <td class="td-name" onclick="showDetail(${p.id})"><div class="tname">${escHtml(name)}</div><div class="tsub">${escHtml(p.category || p.keyword || '')}</div></td>
    <td class="mono">₾${price}</td>
    <td>${stageBadge}</td>
    <td><span class="score-pill sm ${scoreClass(+score)}">${score}</span></td>
    <td class="td-caption">${escHtml(caption.slice(0, 90))}${caption.length > 90 ? '…' : ''}</td>
    <td class="td-actions"><button class="btn btn-sm" onclick="editCatalogRow(${p.id})">Edit</button></td>
  </tr>`;
}
function editCatalogRow(id) {
  if (_catalogEditId && _catalogEditId !== id) cancelCatalogEdit(_catalogEditId);
  _catalogEditId = id;
  const p = catalogProducts.find(x => x.id === id); if (!p) return;
  const row = document.getElementById(`cat-row-${id}`); if (row) row.outerHTML = catalogRow(p, true);
}
function cancelCatalogEdit(id) {
  const p = catalogProducts.find(x => x.id === id); if (!p) return;
  const row = document.getElementById(`cat-row-${id}`); if (row) row.outerHTML = catalogRow(p, false);
  _catalogEditId = null;
}
async function saveCatalogRow(id) {
  const name = document.getElementById(`cat-name-${id}`)?.value?.trim();
  const price = parseFloat(document.getElementById(`cat-price-${id}`)?.value || '0');
  const caption = document.getElementById(`cat-caption-${id}`)?.value?.trim();
  try {
    const result = await api(`/products/${id}`, 'PATCH', { product_name: name, sell_price_eur: isNaN(price) ? undefined : price, caption });
    const idx = catalogProducts.findIndex(x => x.id === id);
    if (idx >= 0) { catalogProducts[idx] = { ...catalogProducts[idx], ...result.product }; const row = document.getElementById(`cat-row-${id}`); if (row) row.outerHTML = catalogRow(catalogProducts[idx], false); }
    _catalogEditId = null;
    toast('Saved', 'success');
  } catch(e) {}
}
function setCatalogStage(stage) { catalogStage = stage; catalogPage = 0; catalogProducts = []; loadCatalog(); }
let _catalogSearchTimer = null;
function debCatalogSearch(val) { catalogSearch = val; clearTimeout(_catalogSearchTimer); _catalogSearchTimer = setTimeout(() => { catalogPage = 0; catalogProducts = []; loadCatalog(); }, 350); }

registerPage('posts', renderPosts);
