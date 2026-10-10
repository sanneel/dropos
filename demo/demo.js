/* DropOS static demo: answers every /api call from fixtures.json (recorded by
   demo/tools/record.py), so the real UI runs with no server. Writes are accepted
   and ignored. Loaded before core.js by demo/build.sh. */
(function () {
  const realFetch = window.fetch.bind(window);
  const fixturesReady = realFetch('/fixtures.json').then(r => r.json()).catch(() => ({}));
  localStorage.setItem('dropos_admin_token', 'demo');

  const CHAT_REPLY = 'This is the presentation demo, so I can\'t run a live analysis here. ' +
    'In the real app I read your review queue, compare it with what you approved before and suggest which products to post next.';

  function json(data, status = 200) {
    return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
  }

  function lookup(fx, path, params) {
    const full = path + (params.toString() ? '?' + params.toString() : '');
    if (full in fx) return fx[full];
    if (path in fx) return fx[path];
    // Same endpoint with other paging/sorting → closest recorded variant
    const stage = params.get('stage');
    const variants = Object.keys(fx).filter(k => k.split('?')[0] === path);
    if (path === '/api/products' && !stage) {
      const seen = new Set(), products = [];
      variants.forEach(k => (fx[k].products || []).forEach(p => { if (!seen.has(p.id)) { seen.add(p.id); products.push(p); } }));
      return { products, total: products.length };
    }
    const match = variants.find(k => !stage || k.includes('stage=' + stage + '&') || k.endsWith('stage=' + stage));
    if (match) return fx[match];
    if (path === '/api/products') return { products: [], total: 0 };
    return /s$|log$|history$/.test(path) ? [] : {};
  }

  window.fetch = async function (input, opts = {}) {
    const url = new URL(typeof input === 'string' ? input : input.url, location.origin);
    if (url.origin !== location.origin || !url.pathname.startsWith('/api/')) return realFetch(input, opts);
    const method = (opts.method || 'GET').toUpperCase();
    const fx = await fixturesReady;
    await new Promise(r => setTimeout(r, 120));   // feel like a network call
    if (method === 'GET') return json(lookup(fx, url.pathname, url.searchParams));
    if (url.pathname === '/api/ai/chat') return json({ reply: CHAT_REPLY });
    return json({ ok: true, demo: true });
  };
})();
