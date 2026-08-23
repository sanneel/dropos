/* ═══ DropOS — Home: Autopilot control room ═══ */

const STAGE_ICON = { scan: 'st_scan', score: 'st_score', approve: 'st_approve', clean: 'st_clean', post: 'st_post', reply: 'st_reply' };
const STAGE_SETTING = { scan: 'auto_scan_enabled', approve: 'auto_approve_enabled', clean: 'auto_clean_images', post: 'post_schedule_enabled' };
const STAGE_HELP = {
  scan:    'Scrapes CSSBuy (1688 / Taobao) with your saved keywords on a schedule.',
  score:   'Every scraped product is scored by Gemini vision against your store persona. Always on.',
  approve: 'Winners above the threshold skip the review queue and go straight to the post queue.',
  clean:   'Photos with Chinese text / watermarks are cleaned with Clipdrop before posting.',
  post:    'The best approved product is posted to Instagram at your peak hours.',
  reply:   'Comments and DMs that match your rules get an instant answer; order intent lands in Inbox.',
};
const NEED_ICON = { review: 'review', clean: 'st_clean', lead: 'inbox', error: 'warn', config: 'settings' };
const ACT_KIND_CLS = {
  auto_approved: 'ok', approved: 'ok', posted: 'ok', image_cleaned: 'ok', reply_sent: 'ok', scan_done: 'ok',
  needs_review: 'info', scan_started: 'info', reconsidered: 'info', config: 'info',
  auto_rejected: 'muted', rejected: 'muted',
  lead_received: 'hot', post_failed: 'err', scan_failed: 'err', image_clean_failed: 'err',
};
let _actFilter = 'all';

async function renderHome() {
  setTitle('Home', 'Autopilot control room');
  setActions(`<button class="btn btn-sm" onclick="renderHome()">Refresh</button>`);
  const el = document.getElementById('content');
  el.innerHTML = loadingState();
  const [ap, act] = await Promise.all([
    api('/autopilot').catch(() => null),
    api('/activity?limit=40').catch(() => ({ items: [] })),
  ]);
  if (!ap) { el.innerHTML = emptyState('!', 'Could not load Autopilot status'); return; }
  autopilotData = ap; renderSidebar();

  const on = ap.enabled;
  const active = ap.stages.filter(s => s.active).length;
  const ready  = ap.stages.filter(s => s.ready).length;
  const t = ap.today || {};
  const summary = on
    ? `${active} of 6 stages running` + (ready < 6 ? ` · ${6 - ready} need setup` : '')
    : `Paused — nothing runs without you${ready ? ` · ${ready} stages ready` : ''}`;

  el.innerHTML = `
    <section class="ap-hero ${on ? 'on' : 'off'}">
      <div class="ap-hero-main">
        <div class="ap-hero-title">
          <span class="ap-big-dot"></span>
          <h2>Autopilot ${on ? 'is on' : 'is off'}</h2>
        </div>
        <p>${escHtml(summary)}. ${on ? 'You only step in for what Autopilot can’t decide.' : 'Turn it on and the whole flow — find → score → approve → clean → post → reply — runs by itself.'}</p>
      </div>
      <button class="ap-master ${on ? 'on' : 'off'}" onclick="toggleAutopilot(${!on})">
        <span class="ap-master-knob"></span>
        <span class="ap-master-lbl">${on ? 'ON' : 'OFF'}</span>
      </button>
    </section>

    <section class="stage-flow">
      ${ap.stages.map((s, i) => stageCard(s, i, on)).join('<div class="stage-arrow">›</div>')}
    </section>

    <section class="home-grid">
      <div class="card needs-card">
        <div class="card-hd"><h3>Needs you</h3><span class="muted">${ap.needs_you.length ? '' : 'nothing right now'}</span></div>
        ${ap.needs_you.length ? `<ul class="needs-list">${ap.needs_you.map(n => `
          <li onclick="navigate('${escHtml(n.page)}')">
            <span class="needs-ic ${n.kind}">${IC[NEED_ICON[n.kind]] || IC.warn}</span>
            <span class="needs-txt">${n.count ? `<b>${n.count}</b> ` : ''}${escHtml(n.label)}</span>
            <span class="needs-go">›</span>
          </li>`).join('')}</ul>`
          : `<div class="needs-empty">${IC.check} All clear. ${on ? 'Autopilot is handling it.' : 'Turn Autopilot on to start the flow.'}</div>`}
      </div>

      <div class="card today-card">
        <div class="card-hd"><h3>Today</h3><span class="muted">${new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' })}</span></div>
        <div class="today-grid">
          ${todayStat('Scanned', t.scanned, 'scans')}
          ${todayStat('Scored', t.scored, 'products')}
          ${todayStat('Auto-approved', t.auto_approved, '', 'ok')}
          ${todayStat('For review', t.needs_review, '', 'info')}
          ${todayStat('Posted', t.posted, '', 'ok')}
          ${todayStat('Replies', t.replies, '')}
          ${todayStat('Leads', t.leads, '', t.leads ? 'hot' : '')}
          ${todayStat('Errors', t.errors, '', t.errors ? 'err' : '')}
        </div>
        <div class="today-pipeline">
          <span><b>${ap.stats.SCRAPED || 0}</b> waiting for AI</span>
          <span><b>${ap.stats.ENRICHED || 0}</b> in review</span>
          <span><b>${ap.stats.REVIEWED || 0}</b> ready to post</span>
          <span><b>${ap.stats.LIVE || 0}</b> live</span>
        </div>
      </div>

      <div class="card activity-card">
        <div class="card-hd">
          <h3>Activity</h3>
          <div class="seg">
            <button class="${_actFilter === 'all' ? 'active' : ''}" onclick="_actFilter='all';renderHome()">All</button>
            <button class="${_actFilter === 'errors' ? 'active' : ''}" onclick="_actFilter='errors';renderHome()">Errors</button>
            <button class="${_actFilter === 'me' ? 'active' : ''}" onclick="_actFilter='me';renderHome()">My actions</button>
          </div>
        </div>
        ${activityList(act.items || [])}
      </div>
    </section>`;
}

function todayStat(label, val, sub, cls = '') {
  return `<div class="today-stat ${cls}"><div class="ts-val">${val ?? 0}</div><div class="ts-lbl">${escHtml(label)}</div></div>`;
}

function stageCard(s, i, master) {
  const state = !s.ready ? 'setup' : (master && s.on) ? 'active' : 'paused';
  const stateLbl = { setup: 'Needs setup', active: 'Running', paused: s.on ? 'Paused (Autopilot off)' : 'Off' }[state];
  const settingKey = STAGE_SETTING[s.key];
  const canToggle = !!settingKey || s.key === 'reply';
  const extra = [];
  if (s.key === 'scan' && s.next_run && s.on && master && s.ready) extra.push(`next ${untilTime(s.next_run)}`);
  if (s.key === 'scan' && s.running) extra.push('scanning now');
  if (s.key === 'post' && s.next_run && s.on && master && s.ready) extra.push(`next ${untilTime(s.next_run)}`);
  if (s.key === 'post' && s.queue != null) extra.push(`${s.queue} in queue`);
  if (s.key === 'score' && s.queue) extra.push(`${s.queue} waiting`);
  if (s.key === 'approve' && s.needs_you) extra.push(`${s.needs_you} for you`);
  if (s.key === 'clean' && s.needs_you) extra.push(`${s.needs_you} for you`);
  if (s.key === 'reply' && s.leads) extra.push(`${s.leads} leads`);
  return `
    <div class="stage ${state}" title="${escHtml(STAGE_HELP[s.key] || '')}">
      <div class="stage-top">
        <span class="stage-ic">${IC[STAGE_ICON[s.key]] || ''}</span>
        ${canToggle ? toggleHtml(`st-${s.key}`, s.on, `toggleStage('${s.key}', this.checked)`, true) : `<span class="chip v-strong" style="font-size:9px">always</span>`}
      </div>
      <div class="stage-label">${escHtml(s.label)}</div>
      <div class="stage-state"><span class="dot"></span>${escHtml(stateLbl)}</div>
      <div class="stage-detail">${escHtml(s.detail || '')}</div>
      <div class="stage-foot">
        <span class="stage-today" title="today">${s.today ?? 0} today</span>
        ${extra.length ? `<span class="stage-extra">${escHtml(extra.join(' · '))}</span>` : ''}
      </div>
      ${!s.ready ? `<button class="stage-fix" onclick="event.stopPropagation();navigate('settings','connections')">${escHtml(s.blockers[0] || 'Configure')}</button>` : ''}
    </div>`;
}

function activityList(items) {
  let list = items;
  if (_actFilter === 'errors') list = items.filter(i => i.level === 'error' || i.level === 'warn');
  if (_actFilter === 'me') list = items.filter(i => ['approved', 'rejected', 'reconsidered', 'config'].includes(i.kind));
  if (!list.length) return `<div class="act-empty">${_actFilter === 'errors' ? 'No errors — nice.' : 'Nothing yet. Activity shows up here as Autopilot works.'}</div>`;
  return `<ul class="act-list">${list.map(i => `
    <li class="act ${ACT_KIND_CLS[i.kind] || ''}" ${i.product_id ? `onclick="showDetail(${i.product_id})" style="cursor:pointer"` : ''}>
      <span class="act-dot"></span>
      <span class="act-msg">${escHtml(i.message)}</span>
      <span class="act-time" title="${escHtml(i.ts)}">${relTime(i.ts)}</span>
    </li>`).join('')}</ul>`;
}

async function toggleAutopilot(enabled) {
  try {
    await api('/autopilot/toggle', 'POST', { enabled });
    toast(enabled ? 'Autopilot ON — the flow now runs by itself' : 'Autopilot paused', enabled ? 'success' : 'info');
    _cacheInvalidate('/');
    await renderHome();
  } catch(e) {}
}

async function toggleStage(key, on) {
  const setting = STAGE_SETTING[key];
  const body = {};
  if (setting) body[setting] = !!on;
  if (key === 'reply') { body.instagram_auto_reply_enabled = !!on; body.instagram_dm_reply_enabled = !!on; }
  try {
    await api('/settings', 'PATCH', body);
    settingsData = { ...settingsData, ...body };
    toast(`${on ? 'Enabled' : 'Disabled'} “${(autopilotData?.stages || []).find(s => s.key === key)?.label || key}”`, 'success', 1800);
    await renderHome();
  } catch(e) { renderHome(); }
}

registerPage('home', renderHome);
