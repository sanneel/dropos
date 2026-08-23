/* ═══ DropOS — Analytics ═══ */

// ── Analytics sub-tabs ────────────────────────────────────────────────────────


function switchAnalyticsTab(tab) { navigate('analytics', tab); }

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
    renderAnalytics(analyticsTab);
  } catch(e) {
    if (btn) { btn.disabled = false; btn.textContent = 'Analyze decisions'; }
  }
}

async function dismissRecommendation(id) {
  try { await api(`/ai/recommendations/${id}/dismiss`, 'POST'); renderAnalytics(analyticsTab); } catch(e) {}
}


// ── Analytics ────────────────────────────────────────────────────────────────

async function renderAnalytics(tab) {
  analyticsTab = tab || currentTab || 'overview';
  const subs = { overview: 'pipeline health at a glance', margins: 'real margins of approved & posted products', insights: 'what your decisions say about your filters' };
  setTitle('Analytics', subs[analyticsTab] || '');
  setActions('');
  const el = document.getElementById('content');
  const tabs = tabBar('analytics');
  el.innerHTML = tabs + loadingState();
  const body = () => { el.innerHTML = tabs + '<div id="an-body"></div>'; return document.getElementById('an-body'); };

  if (analyticsTab === 'margins') { body().innerHTML = await renderMarginsTab(); return; }
  if (analyticsTab === 'insights') { body().innerHTML = await renderInsightsTab(); return; }

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

  body().innerHTML = `
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



registerPage('analytics', renderAnalytics);
