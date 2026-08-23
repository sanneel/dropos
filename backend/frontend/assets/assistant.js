/* ═══ DropOS — AI assistant (chat over the pipeline) ═══ */

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

async function renderAssistant() {
  setTitle('Assistant', 'ask about the pipeline, review in bulk, find rejected gems');
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



registerPage('assistant', renderAssistant);
