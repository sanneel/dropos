/* ═══ DropOS — Settings: setup checklist · connections · curation · automation · advanced ═══ */

async function renderSettings(tab) {
  const subs = { setup: 'what is connected, what is missing', connections: 'keys, logins and tokens', curation: 'how the AI judges products and how prices are set', automation: 'what Autopilot does and when', advanced: 'backup, installation, danger zone' };
  setTitle('Settings', subs[tab] || '');
  setActions(`<button id="settings-save-btn" class="btn btn-primary" onclick="saveSettings()">Save changes</button>`);
  const el = document.getElementById('content');
  el.innerHTML = tabBar('settings') + loadingState('Loading settings…');
  try { settingsData = await api('/settings'); } catch(e) { el.innerHTML = tabBar('settings') + emptyState('!', 'Could not load settings'); return; }
  try { autopilotData = await api('/autopilot'); } catch(e) {}
  const s = settingsData;
  // All panels are rendered (so Save can read every field); only the active one is shown.
  el.innerHTML = tabBar('settings') + `
    <div class="settings-panels">
      <section class="spanel ${tab==='setup'?'show':''}" id="sp-setup">${setupPanel(s)}</section>
      <section class="spanel ${tab==='connections'?'show':''}" id="sp-connections">${connectionsPanel(s)}</section>
      <section class="spanel ${tab==='curation'?'show':''}" id="sp-curation">${curationPanel(s)}</section>
      <section class="spanel ${tab==='automation'?'show':''}" id="sp-automation">${automationPanel(s)}</section>
      <section class="spanel ${tab==='advanced'?'show':''}" id="sp-advanced">${advancedPanel(s)}</section>
    </div>`;
  setTimeout(loadSchedulerStatus, 100);
  setTimeout(loadReplyLog, 150);
}

// ── helpers ──────────────────────────────────────────────────────────────────
const fieldRow = (label, input, help = '') => `<div class="form-group"><label>${label}</label>${input}${help ? `<div class="help">${help}</div>` : ''}</div>`;
const secretInput = (id, isSet, placeholder) => `<input type="password" id="${id}" value="" autocomplete="new-password" placeholder="${isSet ? '••••••••  saved — paste a new value to replace' : escHtml(placeholder)}"/>`;
const statusChip = (ok, okText = 'Connected', badText = 'Not set') => `<span class="chip ${ok ? 'v-strong' : 'v-text'}">${ok ? okText : badText}</span>`;

// ── Setup checklist ──────────────────────────────────────────────────────────
function setupPanel(s) {
  const ap = autopilotData || { stages: [], enabled: false };
  const items = [
    { ok: !!s.gemini_key_set, title: 'AI scoring (Gemini)', desc: s.gemini_key_set ? `Products are scored by ${escHtml(s.gemini_model || 'gemini-2.5-flash-lite')}.` : 'Without it nothing is judged — every product lands in Review unscored. Free key at aistudio.google.com.', tab: 'connections' },
    { ok: !!(s.cssbuy_username && s.cssbuy_password_set), title: 'Product source (CSSBuy)', desc: s.cssbuy_username ? `Logged in as ${escHtml(s.cssbuy_username)} · source: ${escHtml(s.cssbuy_source || '1688')}.` : 'Your CSSBuy login lets DropOS scrape 1688 / Taobao.', tab: 'connections' },
    { ok: !!(s.instagram_access_token_set && s.instagram_user_id), title: 'Instagram', desc: (s.instagram_access_token_set && s.instagram_user_id) ? `Posting to account ${escHtml(s.instagram_user_id)}.` : 'Page access token + business account ID. Until then posts are simulated.', tab: 'connections' },
    { ok: !!s.image_storage_set, soft: true, title: 'Image storage (Supabase)', desc: s.image_storage_set ? 'Photos are re-hosted on a public URL Instagram can always fetch.' : 'Optional but recommended: supplier CDN links usually work, Supabase Storage (free) always works. Set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in .env.', tab: 'connections' },
    { ok: !!s.clipdrop_key_set, soft: true, title: 'Photo cleaning (Clipdrop)', desc: s.clipdrop_key_set ? 'Chinese text / watermarks are removed automatically.' : 'Optional: cleans Chinese text from photos so they can be posted. 100 free images / month.', tab: 'connections' },
    (() => { const sc = (ap.stages || []).find(x => x.key === 'scan') || { blockers: [] };
       const kwOk = !sc.blockers.some(b => /brands page/i.test(b));
       return { ok: kwOk, title: 'Brands & keywords', desc: kwOk ? (sc.detail || 'Keyword pools are ready.') : sc.blockers.find(b => /brands page/i.test(b)), action: `<button class="btn btn-sm ${kwOk ? '' : 'btn-primary'}" onclick="navigate('brands')">${kwOk ? 'Open Brands' : 'Set up'}</button>` }; })(),
    { ok: !!ap.enabled, title: 'Autopilot', desc: ap.enabled ? `On — ${ap.stages.filter(x => x.active).length} of 6 stages running.` : 'Off — turn it on once the items above are green.', tab: null, action: `<button class="btn btn-sm ${ap.enabled ? '' : 'btn-primary'}" onclick="navigate('home')">${ap.enabled ? 'Open Home' : 'Turn on'}</button>` },
  ];
  const done = items.filter(i => i.ok).length;
  return `
    <div class="setup-hd">
      <div><h3>Setup checklist</h3><p class="muted">${done} of ${items.length} done. Items marked optional improve reliability but are not required.</p></div>
      <div class="setup-bar"><i style="width:${Math.round(done / items.length * 100)}%"></i></div>
    </div>
    <ul class="setup-list">
      ${items.map(i => `
        <li class="${i.ok ? 'ok' : i.soft ? 'soft' : 'todo'}">
          <span class="setup-ic">${i.ok ? IC.check : (i.soft ? '○' : '!')}</span>
          <div class="setup-txt"><b>${escHtml(i.title)}${!i.ok && i.soft ? ' <span class="muted">(optional)</span>' : ''}</b><div class="muted">${i.desc}</div></div>
          <div class="setup-act">${i.action || (i.tab ? `<button class="btn btn-sm ${i.ok ? '' : 'btn-primary'}" onclick="navigate('settings','${i.tab}')">${i.ok ? 'Change' : 'Set up'}</button>` : '')}</div>
        </li>`).join('')}
    </ul>`;
}

// ── Connections ──────────────────────────────────────────────────────────────
function connectionsPanel(s) {
  return `
    <div class="settings-grid">
      <div class="card">
        <div class="card-hd"><h3>AI</h3><span class="muted">scoring · captions · assistant</span></div>
        <div class="kv"><span>Gemini</span>${statusChip(s.gemini_key_set, 'Active')}<button class="btn btn-sm" onclick="testApiKey('gemini')" id="test-gemini-btn">Test</button></div>
        ${fieldRow('Gemini API key', secretInput('s-gemini', s.gemini_key_set, 'AIzaSy…  (free at aistudio.google.com)'))}
        ${fieldRow('Gemini model', `<input type="text" id="s-gemini-model" value="${escHtml(s.gemini_model || 'gemini-2.5-flash-lite')}" class="mono"/>`, 'Change only if Google retires the model.')}
        <div id="gemini-test-result" class="help" style="display:none"></div>
        <div class="kv" style="margin-top:14px"><span>Groq <span class="muted">(text-only fallback)</span></span>${statusChip(s.groq_key_set, 'Active')}<button class="btn btn-sm" onclick="testApiKey('groq')" id="test-groq-btn">Test</button></div>
        ${fieldRow('Groq API key', secretInput('s-groq', s.groq_key_set, 'gsk_…  (free at console.groq.com)'))}
        <div id="groq-test-result" class="help" style="display:none"></div>
        <div class="kv" style="margin-top:14px"><span>Clipdrop <span class="muted">(photo cleaning)</span></span>${statusChip(s.clipdrop_key_set, 'Active')}</div>
        ${fieldRow('Clipdrop API key', secretInput('s-clipdrop', s.clipdrop_key_set, 'sk_…  (clipdrop.co/apis — 100 free / month)'))}
      </div>

      <div class="card">
        <div class="card-hd"><h3>Product source — CSSBuy</h3>${statusChip(s.cssbuy_username && s.cssbuy_password_set, 'Logged in', 'Not set')}</div>
        ${fieldRow('CSSBuy e-mail', `<input type="text" id="s-cssbuy-user" value="${escHtml(s.cssbuy_username || '')}" placeholder="you@email.com"/>`)}
        ${fieldRow('CSSBuy password', secretInput('s-cssbuy-pass', s.cssbuy_password_set, ''))}
        ${fieldRow('Source platform', `<select id="s-cssbuy-source">
            <option value="1688"   ${String(s.cssbuy_source||'1688')==='1688'   ? 'selected':''}>1688 — real sales data, ranked by orders</option>
            <option value="taobao" ${String(s.cssbuy_source||'')==='taobao' ? 'selected':''}>Taobao — broader catalog, no sales filter</option>
            <option value="both"   ${String(s.cssbuy_source||'')==='both'   ? 'selected':''}>Both</option>
          </select>`)}
        ${fieldRow('2captcha key <span class="muted">(optional)</span>', secretInput('s-captcha-key', s.captcha_2captcha_key_set, 'for automatic captcha solving'), s.captcha_2captcha_key_set ? 'Captchas are solved automatically.' : 'Without it a browser window opens on first login so you can solve the captcha yourself; the session is saved afterwards.')}
        <details class="adv"><summary>Hosted setup — scrape from another PC</summary>
          <label class="check"><input type="checkbox" id="s-local-only" ${s.local_scraping_only ? 'checked' : ''}/> Store data here, scrape locally only</label>
          ${fieldRow('Ingest API token', secretInput('s-ingest-token', s.ingest_api_token_set, 'a private random token'), 'Used by <code>local_scrape_upload.py</code> to upload results to this instance.')}
        </details>
      </div>

      <div class="card">
        <div class="card-hd"><h3>Instagram</h3>${statusChip(s.instagram_access_token_set && s.instagram_user_id, 'Connected', 'Simulated')}</div>
        ${fieldRow('Page access token', secretInput('s-ig-token', s.instagram_access_token_set, 'EAABs…'))}
        ${fieldRow('Business account ID', `<div class="row"><input type="text" id="s-ig-user-id" value="${escHtml(s.instagram_user_id || '')}" placeholder="17841400000000000" style="flex:1"/><button class="btn btn-sm" onclick="detectIgAccount()">Auto-detect</button></div><div id="ig-detect-result" class="help">Paste the token, save, then Auto-detect fills the ID.</div>`)}
        ${fieldRow('Instagram username <span class="muted">(display only)</span>', `<input type="text" id="s-instagram" value="${escHtml(s.instagram_username || '')}" placeholder="@yourstore"/>`)}
        ${fieldRow('Public app URL <span class="muted">(optional)</span>', `<input type="text" id="s-public-url" value="${escHtml(s.public_base_url || '')}" placeholder="https://dropos.example.com"/>`, 'Only if this server is reachable from the internet (hosting or tunnel). Needed for the webhook (auto-reply / inbox) and used as an image proxy.')}
        ${fieldRow('Meta app secret <span class="muted">(optional)</span>', secretInput('s-ig-app-secret', s.instagram_app_secret_set, 'App Dashboard → Settings → Basic'), 'Verifies webhook signatures.')}
        <div class="hint ${s.image_storage_set ? 'ok' : 'warn'}" style="margin-top:6px">${s.image_storage_set
          ? 'Image storage (Supabase) configured — photos are re-hosted on a public URL Instagram can always fetch.'
          : 'Image storage not configured: Instagram downloads photos straight from the supplier CDN, which usually works. For reliability add <code>SUPABASE_URL</code> + <code>SUPABASE_SERVICE_ROLE_KEY</code> to <code>.env</code> and restart.'}</div>
        <details class="adv"><summary>How to get the token (one time)</summary>
          <ol class="steps">
            <li>developers.facebook.com → your app → add product <b>Instagram Graph API</b></li>
            <li>Graph API Explorer → generate a token with <code>instagram_basic</code>, <code>instagram_content_publish</code>, <code>pages_read_engagement</code> (+ <code>instagram_manage_comments</code>, <code>instagram_manage_messages</code> for auto-reply)</li>
            <li>Extend it to a long-lived token (Access Token Debugger → Extend)</li>
            <li>Paste it above, Save, click Auto-detect</li>
          </ol>
        </details>
      </div>
    </div>`;
}

// ── Curation ─────────────────────────────────────────────────────────────────
function curationPanel(s) {
  return `
    <div class="settings-grid">
      <div class="card">
        <div class="card-hd"><h3>Store persona</h3><span class="muted">rendered into the AI curator prompt</span></div>
        <div class="form-row">
          ${fieldRow('Store name', `<input type="text" id="s-store-name" value="${escHtml(s.store_name || '')}" placeholder="Tskvili"/>`)}
          ${fieldRow('Sell price range (₾)', `<div class="row"><input type="number" id="s-price-min" value="${s.sell_price_min ?? 40}" min="0" step="1"/><span class="muted">–</span><input type="number" id="s-price-max" value="${s.sell_price_max ?? 119}" min="0" step="1"/></div>`)}
        </div>
        ${fieldRow('Target audience', `<input type="text" id="s-audience" value="${escHtml(s.target_audience || '')}" placeholder="Gen-Z couples in Georgia (ages 16–26)…"/>`)}
        ${fieldRow('Niche / store focus', `<textarea id="s-niche" rows="2">${escHtml(s.niche || '')}</textarea>`)}
        ${fieldRow('Example products that sell', `<textarea id="s-examples" rows="2">${escHtml(s.example_products || '')}</textarea>`)}
        <label class="check" style="margin-top:6px"><input type="checkbox" id="s-context-injection" ${s.ai_context_injection ? 'checked' : ''}/> Feed a summary of my past approve/reject decisions into the prompt <span class="muted">(needs ≥ 10 reviewed products)</span></label>
      </div>

      <div class="card">
        <div class="card-hd"><h3>Filters</h3><span class="muted">before the AI sees anything</span></div>
        <div class="form-row">
          ${fieldRow('Min margin (%)', `<input type="number" id="s-margin" value="${s.min_margin ?? 60}" step="5" min="0" max="95"/>`, 'Relaxed to 45% automatically when cost &gt; ₾30.')}
          ${fieldRow('Min rating <span class="muted">(Taobao)</span>', `<input type="number" id="s-rating" value="${s.min_rating ?? 4.5}" step="0.1" min="1" max="5"/>`, '1688 listings are ranked by orders instead.')}
        </div>
        <div class="help">Products the AI scores below <b>6.0</b> are rejected automatically; 6.0–7.0 land in Review as <i>needs a look</i>; above the auto-approve threshold (Automation tab) they skip review.</div>
      </div>

      <div class="card">
        <div class="card-hd"><h3>Pricing</h3><span class="muted">supplier ¥ → sell ₾</span></div>
        ${fieldRow('CNY → GEL rate', `<input type="number" id="s-exchange" value="${s.exchange_rate ?? 0.353}" step="0.001" min="0.01"/>`)}
        <div class="form-row">
          ${fieldRow('Markup · landed cost &lt; ₾10', `<input type="number" id="s-ml" value="${s.sell_markup_low ?? 3.5}" step="0.1" min="1"/>`)}
          ${fieldRow('Markup · everything else', `<input type="number" id="s-mm" value="${s.sell_markup_mid ?? 2.8}" step="0.1" min="1"/>`)}
          ${fieldRow('Markup · electronics', `<input type="number" id="s-mh" value="${s.sell_markup_high ?? 2.2}" step="0.1" min="1"/>`)}
        </div>
        <div class="help">Landed cost = (item price + ¥10 shipping for 1688 / ¥15 Taobao) × rate. Sell prices snap to ₾29.90 / ₾44.90 / ₾64.90 / x.90.</div>
      </div>
    </div>`;
}

// ── Automation ───────────────────────────────────────────────────────────────
function automationPanel(s) {
  const verdicts = s.auto_approve_verdicts || ['top_priority', 'strong_candidate'];
  const ruleRow = (cls, kwCls, rpCls, r = {}) => `
    <div class="${cls} rule-row">
      <input type="text" class="${kwCls}" value="${escHtml((r.keywords||[]).join(', '))}" placeholder="keywords, comma separated (empty = always)"/>
      <input type="text" class="${rpCls}" value="${escHtml(r.reply||'')}" placeholder="reply message"/>
      <button class="btn btn-sm btn-danger-ghost" onclick="this.closest('.rule-row').remove()" title="Remove">${IC.x}</button>
    </div>`;
  return `
    <div class="settings-grid">
      <div class="card">
        <div class="card-hd"><h3>Find products</h3><span class="muted">scheduled scans</span></div>
        <label class="check"><input type="checkbox" id="s-auto-scan" ${s.auto_scan_enabled !== false ? 'checked' : ''}/> Scan automatically</label>
        ${fieldRow('Every (hours, per brand)', `<input type="number" id="s-scan-hours" value="${s.scan_interval_hours ?? 12}" min="0.5" step="0.5" style="max-width:120px"/>`)}
        <div class="hint info" style="margin:10px 0">Keywords now live per <b>brand</b> — each market keeps its own pool, the AI tops it up, and
          Autopilot scans the best performers first. <a href="#" onclick="navigate('brands');return false">Open Brands →</a></div>
        <div class="row"><button class="btn btn-sm" onclick="triggerScheduledScan()" ${s.local_scraping_only ? 'disabled' : ''}>Scan now</button><span id="sched-status" class="muted">…</span></div>
      </div>

      <div class="card">
        <div class="card-hd"><h3>Approve &amp; clean</h3><span class="muted">what skips the review queue</span></div>
        <label class="check"><input type="checkbox" id="s-auto-approve" ${s.auto_approve_enabled !== false ? 'checked' : ''}/> Auto-approve AI winners</label>
        ${fieldRow('Minimum score', `<input type="number" id="s-auto-min" value="${s.auto_approve_min_score ?? 7}" min="6" max="10" step="0.1" style="max-width:120px"/>`, '7.0 = strong candidates and up · 8.0 = top picks only.')}
        ${fieldRow('Verdicts that qualify', `<label class="check"><input type="checkbox" id="s-v-top" ${verdicts.includes('top_priority') ? 'checked' : ''}/> Top pick</label><label class="check"><input type="checkbox" id="s-v-strong" ${verdicts.includes('strong_candidate') ? 'checked' : ''}/> Strong candidate</label>`)}
        <label class="check"><input type="checkbox" id="s-auto-clean" ${s.auto_clean_images !== false ? 'checked' : ''}/> Clean Chinese text from photos automatically <span class="muted">(needs Clipdrop key)</span></label>
        ${fieldRow('Auto-reject pending items after (days)', `<input type="number" id="s-auto-reject-days" value="${s.auto_reject_pending_days ?? 0}" min="0" step="1" style="max-width:120px"/>`, '0 = keep them in Review forever.')}
      </div>

      <div class="card">
        <div class="card-hd"><h3>Post to Instagram</h3><span class="muted">peak hours</span></div>
        <label class="check"><input type="checkbox" id="s-post-enabled" ${s.post_schedule_enabled ? 'checked' : ''}/> Post the best approved product at each slot</label>
        <div class="form-row">
          ${fieldRow('Post times', `<input type="text" id="s-post-times" value="${escHtml((s.post_times || ['19:00','21:00']).join(', '))}" placeholder="19:00, 21:00"/>`)}
          ${fieldRow('Timezone', `<input type="text" id="s-post-tz" value="${escHtml(s.post_timezone || 'Asia/Tbilisi')}"/>`)}
        </div>
        <div class="form-row">
          ${fieldRow('Products per slot', `<input type="number" id="s-posts-per-slot" value="${s.posts_per_slot ?? 1}" min="1" max="5"/>`)}
          ${fieldRow('Max posts per day', `<input type="number" id="s-max-posts" value="${s.max_posts_per_day ?? 2}" min="1" max="20"/>`)}
        </div>
        <div id="posting-status" class="help">…</div>
      </div>

      <div class="card wide">
        <div class="card-hd"><h3>Answer comments &amp; DMs</h3><span class="muted">first matching rule wins · empty keywords = always</span></div>
        <div class="hint info">Needs a public HTTPS URL (Settings → Connections → Public app URL) and the webhook registered in your Meta app. Webhook URL: <code>${escHtml((s.public_base_url || window.location.origin).replace(/\/$/, ''))}/api/instagram/webhook</code> · verify token below.</div>
        <div class="two">
          <div>
            <label class="check"><input type="checkbox" id="s-autoreply-enabled" ${s.instagram_auto_reply_enabled ? 'checked' : ''}/> Reply to comments</label>
            <div id="reply-rules-list" class="rules">${(s.instagram_reply_rules || []).map(r => ruleRow('reply-rule-row', 'rule-keywords', 'rule-reply', r)).join('')}</div>
            <button class="btn btn-sm" onclick="addReplyRule()">+ comment rule</button>
          </div>
          <div>
            <label class="check"><input type="checkbox" id="s-dm-enabled" ${s.instagram_dm_reply_enabled ? 'checked' : ''}/> Reply to DMs</label>
            <div id="dm-rules-list" class="rules">${(s.instagram_dm_rules || []).map(r => ruleRow('dm-rule-row', 'dm-rule-keywords', 'dm-rule-reply', r)).join('')}</div>
            <button class="btn btn-sm" onclick="addDmRule()">+ DM rule</button>
          </div>
        </div>
        <div class="form-row" style="margin-top:14px">
          ${fieldRow('Webhook verify token', `<input type="text" id="s-webhook-token" value="${escHtml(s.instagram_webhook_token || 'dropos_webhook_secret')}" class="mono"/>`)}
          ${fieldRow('Order-intent words <span class="muted">(flag as possible order in Inbox)</span>', `<input type="text" id="s-lead-keywords" value="${escHtml((s.lead_keywords || []).join(', '))}"/>`)}
        </div>
        <details class="adv"><summary>Reply log</summary><div id="reply-log-list" class="help">Loading…</div></details>
      </div>
    </div>`;
}

// ── Advanced ─────────────────────────────────────────────────────────────────
function advancedPanel(s) {
  return `
    <div class="settings-grid">
      <div class="card">
        <div class="card-hd"><h3>Google Sheets backup</h3><span class="muted">optional</span></div>
        ${fieldRow('Spreadsheet ID', `<input type="text" id="s-sheets-id" value="${escHtml(s.google_sheets_id || '')}" placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"/>`, 'From the sheet URL after /d/')}
        ${fieldRow('Service-account JSON path <span class="muted">(optional)</span>', `<input type="text" id="s-sheets-creds" value="${escHtml(s.google_sheets_credentials || '')}" placeholder="/path/to/service-account.json"/>`, 'Or set <code>GOOGLE_SERVICE_ACCOUNT_JSON</code> in .env.')}
        <div class="row"><button class="btn btn-sm" onclick="backupToSheets()">Backup now</button><button class="btn btn-sm" onclick="restoreFromSheets()">Restore</button><button class="btn btn-sm" onclick="exportToSheets()">Export approved</button></div>
      </div>
      <div class="card">
        <div class="card-hd"><h3>This installation</h3></div>
        <div class="kv-list">
          <div><span>Database</span><b>${s.runtime?.embedded_db ? 'embedded PostgreSQL (data/pg)' : 'external PostgreSQL'}</b></div>
          <div><span>Data directory</span><b class="mono">${escHtml(s.runtime?.data_dir || '—')}</b></div>
          <div><span>Mode</span><b>${s.runtime?.production ? 'production' : 'development'} ${s.runtime?.production ? '' : `· <a href="/docs" target="_blank">API docs</a>`}</b></div>
          <div><span>Image storage</span><b>${s.image_storage_set ? 'Supabase' : 'none (supplier CDN)'}</b></div>
          <div><span>Version</span><b>${APP_VERSION}</b></div>
        </div>
        <div class="help">Back up by copying the data directory (and <code>.env</code>). Keys pasted here are stored in the database.</div>
        <div class="row" style="margin-top:10px"><button class="btn btn-sm" onclick="logout()">Sign out</button></div>
      </div>
      <div class="card danger">
        <div class="card-hd"><h3>Danger zone</h3></div>
        <p class="help">Permanently delete all products, scans and history. Settings are kept.</p>
        <button class="btn btn-sm btn-danger" onclick="resetDatabase()">Reset database</button>
      </div>
    </div>`;
}

// ── Save ─────────────────────────────────────────────────────────────────────
async function saveSettings() {
  const saveBtn = document.getElementById('settings-save-btn');
  if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }
  const g = id => document.getElementById(id);
  const has = id => !!g(id);
  const num = (id, d) => { const v = parseFloat(g(id)?.value); return isNaN(v) ? d : v; };
  const data = {};
  // text / numeric (only when the input exists)
  const txt = { 's-store-name': 'store_name', 's-audience': 'target_audience', 's-niche': 'niche', 's-examples': 'example_products',
    's-instagram': 'instagram_username', 's-ig-user-id': 'instagram_user_id', 's-public-url': 'public_base_url',
    's-cssbuy-user': 'cssbuy_username', 's-cssbuy-source': 'cssbuy_source', 's-sheets-id': 'google_sheets_id',
    's-post-tz': 'post_timezone', 's-webhook-token': 'instagram_webhook_token', 's-gemini-model': 'gemini_model' };
  for (const [id, key] of Object.entries(txt)) if (has(id)) data[key] = (g(id).value || '').trim();
  const nums = { 's-price-min': ['sell_price_min', 40], 's-price-max': ['sell_price_max', 119], 's-margin': ['min_margin', 60], 's-rating': ['min_rating', 4.5],
    's-exchange': ['exchange_rate', 0.353], 's-ml': ['sell_markup_low', 3.5], 's-mm': ['sell_markup_mid', 2.8], 's-mh': ['sell_markup_high', 2.2],
    's-scan-hours': ['scan_interval_hours', 12], 's-auto-min': ['auto_approve_min_score', 7], 's-auto-reject-days': ['auto_reject_pending_days', 0],
    's-posts-per-slot': ['posts_per_slot', 1], 's-max-posts': ['max_posts_per_day', 2] };
  for (const [id, [key, d]] of Object.entries(nums)) if (has(id)) data[key] = num(id, d);
  const bools = { 's-local-only': 'local_scraping_only', 's-context-injection': 'ai_context_injection', 's-auto-scan': 'auto_scan_enabled',
    's-auto-approve': 'auto_approve_enabled', 's-auto-clean': 'auto_clean_images', 's-post-enabled': 'post_schedule_enabled',
    's-autoreply-enabled': 'instagram_auto_reply_enabled', 's-dm-enabled': 'instagram_dm_reply_enabled' };
  for (const [id, key] of Object.entries(bools)) if (has(id)) data[key] = !!g(id).checked;
  if (has('s-scan-kw')) data.scan_keywords = g('s-scan-kw').value.split('\n').map(s => s.trim()).filter(Boolean);
  if (has('s-post-times')) { const t = g('s-post-times').value.split(',').map(x => x.trim()).filter(x => /^\d{1,2}:\d{2}$/.test(x)); data.post_times = t.length ? t : ['19:00', '21:00']; }
  if (has('s-lead-keywords')) data.lead_keywords = g('s-lead-keywords').value.split(',').map(x => x.trim()).filter(Boolean);
  if (has('s-v-top') || has('s-v-strong')) { const v = []; if (g('s-v-top')?.checked) v.push('top_priority'); if (g('s-v-strong')?.checked) v.push('strong_candidate'); data.auto_approve_verdicts = v.length ? v : ['top_priority']; }
  if (has('reply-rules-list')) data.instagram_reply_rules = _collectReplyRules();
  if (has('dm-rules-list')) data.instagram_dm_rules = _collectDmRules();
  // secrets: only when typed
  const secrets = { 's-gemini': 'gemini_key', 's-groq': 'groq_key', 's-clipdrop': 'clipdrop_key', 's-ig-token': 'instagram_access_token',
    's-ig-app-secret': 'instagram_app_secret', 's-cssbuy-pass': 'cssbuy_password', 's-captcha-key': 'captcha_2captcha_key',
    's-ingest-token': 'ingest_api_token', 's-sheets-creds': 'google_sheets_credentials' };
  for (const [id, key] of Object.entries(secrets)) { const v = g(id)?.value?.trim(); if (v) data[key] = v; }
  try {
    await api('/settings', 'PATCH', data);
    toast('Settings saved', 'success');
    setTimeout(() => renderSettings(currentTab), 300);
  } catch(e) {
  } finally { if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save changes'; } }
}

// ── Helpers (rules, status, tests, sheets, danger) ───────────────────────────
function _ruleRowHtml(cls, kwCls, rpCls) {
  return `<input type="text" class="${kwCls}" placeholder="keywords, comma separated (empty = always)"/><input type="text" class="${rpCls}" placeholder="reply message"/><button class="btn btn-sm btn-danger-ghost" onclick="this.closest('.rule-row').remove()" title="Remove">${IC.x}</button>`;
}
function addReplyRule() { const list = document.getElementById('reply-rules-list'); const row = document.createElement('div'); row.className = 'reply-rule-row rule-row'; row.innerHTML = _ruleRowHtml('reply-rule-row', 'rule-keywords', 'rule-reply'); list.appendChild(row); row.querySelector('input')?.focus(); }
function _collectReplyRules() { return [...document.querySelectorAll('.reply-rule-row')].map(row => ({ keywords: (row.querySelector('.rule-keywords')?.value || '').split(',').map(k => k.trim()).filter(Boolean), reply: row.querySelector('.rule-reply')?.value?.trim() || '' })).filter(r => r.reply); }
function addDmRule() { const list = document.getElementById('dm-rules-list'); const row = document.createElement('div'); row.className = 'dm-rule-row rule-row'; row.innerHTML = _ruleRowHtml('dm-rule-row', 'dm-rule-keywords', 'dm-rule-reply'); list.appendChild(row); row.querySelector('input')?.focus(); }
function _collectDmRules() { return [...document.querySelectorAll('.dm-rule-row')].map(row => ({ keywords: (row.querySelector('.dm-rule-keywords')?.value || '').split(',').map(k => k.trim()).filter(Boolean), reply: row.querySelector('.dm-rule-reply')?.value?.trim() || '' })).filter(r => r.reply); }

async function loadSchedulerStatus() {
  try {
    const st = await api('/scheduler/status');
    const el = document.getElementById('sched-status');
    if (el) {
      const j = st.jobs?.[0];
      el.textContent = !st.running ? (settingsData.local_scraping_only ? 'Server scraping off — upload from the local scraper' : 'Scan loop not running')
        : j?.scanning ? 'Scanning now…' : `Autopilot scan loop running${j?.last_run ? ' · last: ' + j.last_run : ''}${j?.last_error ? ' · last error: ' + j.last_error : ''}`;
    }
    const pel = document.getElementById('posting-status');
    if (pel) {
      const jobs = st.posting?.jobs || [];
      if (!st.posting?.running) pel.textContent = 'Posting scheduler not running';
      else if (!jobs.length) pel.textContent = 'No post times planned';
      else pel.innerHTML = (settingsData.post_schedule_enabled && autopilotData?.enabled ? '<span class="ok-txt">Active</span>' : '<span class="warn-txt">Planned but ' + (autopilotData?.enabled ? 'posting is off' : 'Autopilot is off') + '</span>')
          + ' · next: ' + jobs.map(j => j.next_run ? escHtml(new Date(j.next_run).toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' })) : '—').join(', ');
    }
  } catch(e) { const el = document.getElementById('sched-status'); if (el) el.textContent = 'Backend offline'; }
}
async function loadReplyLog() {
  const el = document.getElementById('reply-log-list'); if (!el) return;
  try {
    const rows = await api('/instagram/reply-log', 'GET');
    if (!rows.length) { el.textContent = 'No replies sent yet.'; return; }
    el.innerHTML = rows.slice(0, 20).map(r => `<div class="log-row"><span class="mono muted">${escHtml(r.replied_at?.slice(0,16).replace('T',' ') || '')}</span> ${escHtml(r.reply_type || '')} → ${escHtml(r.matched_rule?.slice(0,60) || '')}</div>`).join('');
  } catch { el.textContent = 'Could not load log.'; }
}
async function resetDatabase() {
  if (!confirm('Delete ALL products, scans and history? This cannot be undone.')) return;
  if (!confirm('Final confirmation: wipe the entire catalog?')) return;
  try { const res = await api('/admin/reset-database', 'POST'); if (res.ok) { toast('Database reset', 'success'); refreshStats(); navigate('home'); } } catch(e) {}
}
async function detectIgAccount() {
  const el = document.getElementById('ig-detect-result'); el.className = 'help'; el.textContent = 'Detecting…';
  const token = document.getElementById('s-ig-token')?.value?.trim();
  if (token) await api('/settings', 'PATCH', { instagram_access_token: token }).catch(() => {});
  else if (!settingsData.instagram_access_token_set) { el.className = 'help err-txt'; el.textContent = 'Paste your Page access token first.'; return; }
  try {
    const res = await api('/instagram/accounts', 'GET');
    const found = (res.accounts || []).filter(a => a.instagram_business_account_id);
    if (!found.length) { el.className = 'help err-txt'; el.textContent = 'No Instagram Business account found. Make sure the account is Business/Creator and linked to a Facebook Page.'; return; }
    document.getElementById('s-ig-user-id').value = found[0].instagram_business_account_id;
    el.className = 'help ok-txt'; el.textContent = `Found: ${found[0].page_name} → ${found[0].instagram_business_account_id}` + (found.length > 1 ? ` (${found.length - 1} more — change manually if needed)` : '') + '. Click Save.';
  } catch(e) { el.className = 'help err-txt'; el.textContent = `Error: ${e.message || e}`; }
}
async function triggerScheduledScan() {
  try {
    const res = await api('/scheduler/trigger', 'POST', {});
    toast(`Scan started (job #${res.job_id})`, 'success');
    activeJob = { id: res.job_id, status: 'queued', progress: 0 };
    if (activeJobPoll) clearInterval(activeJobPoll);
    activeJobPoll = setInterval(pollActiveJob, 2000);
    navigate('scans', 'new');
  } catch(e) {}
}
async function exportToSheets() { try { const res = await api('/sheets/export', 'POST', {}); toast(`Exported ${res.exported} products${res.mock ? ' (mock — Sheets not configured)' : ''}`, 'success'); } catch(e) {} }
async function backupToSheets() { try { const res = await api('/sheets/backup', 'POST', {}); toast(res.ok ? `Backed up ${res.products?.saved ?? 0} products` : 'Backup skipped — Sheets not configured', res.ok ? 'success' : 'info'); } catch(e) {} }
async function restoreFromSheets() {
  if (!confirm('Restore settings and products from Google Sheets? Matching products will be updated.')) return;
  try { const res = await api('/sheets/restore', 'POST', {}); toast(`Restored ${res.products || 0} products and ${res.settings || 0} settings`, 'success'); await refreshStats(); renderSettings(currentTab); } catch(e) {}
}
async function testApiKey(provider) {
  const btn = document.getElementById(`test-${provider}-btn`); const resultEl = document.getElementById(`${provider}-test-result`);
  if (!btn || !resultEl) return;
  const typedKey = document.getElementById(provider === 'gemini' ? 's-gemini' : 's-groq')?.value?.trim() || '';
  btn.disabled = true; btn.textContent = 'Testing…'; resultEl.style.display = 'block'; resultEl.className = 'help'; resultEl.textContent = 'Connecting…';
  try {
    const body = { provider }; if (typedKey) body.key = typedKey;
    const res = await api('/ai/test', 'POST', body);
    if (res.ok) { resultEl.className = 'help ok-txt'; resultEl.textContent = `✓ ${res.model || provider} working — ${res.latency_ms || '?'} ms`; }
    else { resultEl.className = 'help err-txt'; resultEl.textContent = `✗ ${res.error || 'Connection failed'}`; }
  } catch(e) { resultEl.className = 'help err-txt'; resultEl.textContent = `✗ ${e.message || 'Request failed'}`; }
  finally { btn.disabled = false; btn.textContent = 'Test'; }
}

registerPage('settings', renderSettings);
