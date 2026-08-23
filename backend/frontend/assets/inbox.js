/* ═══ DropOS — Inbox: comments & DMs captured by the webhook; order leads first ═══ */

let inboxFilter = 'open';   // open | leads | all
let _inboxItems = [];

async function renderInbox() {
  setTitle('Inbox', 'comments & DMs — possible orders first');
  setActions(`<button class="btn btn-sm" onclick="renderInbox()" title="Refresh">↻</button>`);
  const el = document.getElementById('content');
  el.innerHTML = loadingState();
  const data = await api(`/inbox?all=${inboxFilter === 'all'}&limit=200`).catch(() => ({ items: [], counts: {} }));
  _inboxItems = data.items || [];
  const counts = data.counts || {};
  const ig = !!settingsData.instagram_connected;
  const priv = settingsData.instagram_mode === 'private';
  const publicUrl = /^https:/.test(settingsData.public_base_url || '');
  let list = _inboxItems;
  if (inboxFilter === 'leads') list = list.filter(i => i.is_lead);

  const chip = (id, label, n) => `<button class="fchip ${inboxFilter === id ? 'active' : ''}" onclick="inboxFilter='${id}';renderInbox()">${label}${n ? ` <b>${n}</b>` : ''}</button>`;
  el.innerHTML = `
    ${priv ? `<div class="hint ok">Direct login is reading your comments &amp; DMs every ${settingsData.ig_poll_minutes || 5} minutes — no Meta account needed. <a href="#" onclick="igPrivatePoll(this);return false">Check now</a>.</div>`
    : (!ig || !publicUrl) ? `<div class="hint ${!ig ? 'warn' : 'info'}">
      ${!ig ? 'Instagram is not connected, so nothing can arrive here yet. Easiest fix: <b>direct login</b> (username + password, no Meta account) in Settings → Connections. ' : ''}
      ${ig && !publicUrl ? 'The official API webhook needs a <b>public HTTPS</b> URL — or switch to direct login, which polls instead. ' : ''}
      <a href="#" onclick="navigate('settings','connections');return false">Settings → Connections</a>
      · <a href="#" onclick="simulateInbox();return false">send a test message</a> to see how it works.
    </div>` : ''}
    <div class="toolbar">
      <div class="toolbar-l">${chip('open', 'Open', counts.open)}${chip('leads', 'Possible orders', counts.leads)}${chip('all', 'All', counts.total)}</div>
      <div class="toolbar-r"><span class="muted">Lead words: ${escHtml((settingsData.lead_keywords || []).slice(0, 6).join(', '))}… <a href="#" onclick="navigate('settings','automation');return false">edit</a></span></div>
    </div>
    ${list.length ? `<div class="inbox-list">${list.map(inboxRow).join('')}</div>`
      : emptyState('✉', inboxFilter === 'leads' ? 'No possible orders right now' : inboxFilter === 'open' ? 'Inbox is clear' : 'No messages yet',
          'Comments and DMs that reach the webhook show up here. Messages with order intent are flagged so you can fulfil them — everything else is answered by your auto-reply rules.')}`;
}

function inboxRow(m) {
  const when = fmtDate(m.received_at);
  return `
    <div class="msg ${m.is_lead ? 'lead' : ''} ${m.handled ? 'handled' : ''}" id="msg-${m.id}">
      <div class="msg-side">
        <span class="msg-kind">${m.kind === 'comment' ? 'Comment' : 'DM'}</span>
        ${m.is_lead ? `<span class="chip v-hot">possible order</span>` : ''}
      </div>
      <div class="msg-main">
        <div class="msg-hd"><b>${escHtml(m.sender_name || m.sender_id || 'someone')}</b><span class="msg-time">${when}</span></div>
        <div class="msg-text">${escHtml(m.text || '')}</div>
        ${m.auto_reply ? `<div class="msg-auto">↳ auto-replied: “${escHtml(m.auto_reply)}”</div>` : ''}
        <div class="msg-reply">
          <input type="text" id="reply-${m.id}" placeholder="${m.kind === 'comment' ? 'Reply to this comment…' : 'Reply by DM…'}" onkeydown="if(event.key==='Enter')sendInboxReply(${m.id})"/>
          <button class="btn btn-sm btn-primary" onclick="sendInboxReply(${m.id})">Send</button>
          <button class="btn btn-sm" onclick="setInboxHandled(${m.id}, ${m.handled ? 'false' : 'true'})">${m.handled ? 'Reopen' : 'Done'}</button>
        </div>
      </div>
    </div>`;
}

async function sendInboxReply(id) {
  const inp = document.getElementById(`reply-${id}`); const text = (inp?.value || '').trim();
  if (!text) { toast('Type a reply first', 'error'); return; }
  try { await api(`/inbox/${id}/reply`, 'POST', { text }); toast('Reply sent', 'success'); renderInbox(); refreshStats(); } catch(e) {}
}
async function setInboxHandled(id, handled) {
  try { await api(`/inbox/${id}/handled?handled=${handled}`, 'POST'); renderInbox(); refreshStats(); } catch(e) {}
}
async function simulateInbox() {
  const text = prompt('Test message text (try including “price” or “order”):', 'Hi! How much is this? I want to order 🙈');
  if (!text) return;
  try { await api('/inbox/simulate', 'POST', { text, kind: 'dm', sender: 'test_user' }); toast('Test message delivered through the webhook path', 'success'); renderInbox(); refreshStats(); } catch(e) {}
}

registerPage('inbox', renderInbox);
