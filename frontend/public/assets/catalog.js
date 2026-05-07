/* ───────────────────────────────────────────────────────
   Lovu — catalog.js
   SPA logic: gallery, category switcher, profile view
   Backend: GET /api/products?stage=REVIEWED|LIVE
──────────────────────────────────────────────────────── */

'use strict';

// ── Config ────────────────────────────────────────────
const API_BASE = (() => {
  const h = window.location.hostname;
  return (h === 'localhost' || h === '127.0.0.1')
    ? 'http://localhost:8000/api'
    : window.location.origin + '/api';
})();

const IG_USERNAME = 'lovugifts'; // ← replace with your handle
const PAGE_LIMIT  = 24;

// Category → stage/keyword filter map
// We fetch REVIEWED + LIVE and filter client-side by category keyword
const CAT_KEYWORDS = {
  all:        null,
  jewelry:    ['jewelry', 'bracelet', 'necklace', 'ring', 'earring', 'pendant'],
  tech:       ['tech', 'gadget', 'electronic', 'wireless', 'bluetooth', 'phone', 'watch'],
  essentials: ['candle', 'perfume', 'mug', 'care', 'skincare', 'bag', 'wallet', 'home'],
};

// ── State ─────────────────────────────────────────────
let state = {
  allProducts: [],      // full fetched list
  filtered:    [],      // after category filter
  category:    'all',
  offset:      0,
  total:       0,
  loading:     false,
  currentProduct: null, // product shown in profile view
};

// ── DOM Refs ──────────────────────────────────────────
const $gallery  = document.getElementById('view-gallery');
const $profile  = document.getElementById('view-profile');
const $grid     = document.getElementById('bento-grid');
const $empty    = document.getElementById('empty-state');
const $loadMore = document.getElementById('load-more-wrap');
const $loadBtn  = document.getElementById('load-more-btn');
const $pill     = document.getElementById('liquid-pill');
const $catBtns  = document.querySelectorAll('.cat-btn');

// ── Boot ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initCategoryNav();
  fetchProducts(false);
  $loadBtn.addEventListener('click', () => fetchProducts(true));

  // Browser back button support
  window.addEventListener('popstate', (e) => {
    if (e.state?.view === 'profile' && e.state.id) {
      const p = state.allProducts.find(x => x.id === e.state.id);
      if (p) { showProfile(p, false); return; }
    }
    showGallery(false);
  });
});

// ── Fetch ─────────────────────────────────────────────
async function fetchProducts(append = false) {
  if (state.loading) return;
  state.loading = true;

  if (!append) {
    state.offset = 0;
    state.allProducts = [];
    showSkeletons();
  }

  try {
    const offset = state.offset;
    // Fetch both approved + live simultaneously
    const [resA, resL] = await Promise.all([
      apiFetch(`/products?stage=REVIEWED&limit=${PAGE_LIMIT}&offset=${offset}&sort=score`),
      apiFetch(`/products?stage=LIVE&limit=${PAGE_LIMIT}&offset=${offset}&sort=score`),
    ]);

    const fresh = [...(resA.products || []), ...(resL.products || [])];
    // deduplicate by id
    const seen = new Set(state.allProducts.map(p => p.id));
    const unique = fresh.filter(p => !seen.has(p.id));

    state.allProducts = append ? [...state.allProducts, ...unique] : unique;
    state.total = (resA.total || 0) + (resL.total || 0);
    state.offset = offset + PAGE_LIMIT;

    applyFilter();
  } catch (err) {
    console.error('Catalog fetch error:', err);
    showEmpty();
  } finally {
    state.loading = false;
  }
}

async function apiFetch(path) {
  const res = await fetch(API_BASE + path);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Category Nav ──────────────────────────────────────
function initCategoryNav() {
  $catBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const cat = btn.dataset.cat;
      if (cat === state.category) return;
      state.category = cat;

      $catBtns.forEach(b => b.classList.toggle('active', b.dataset.cat === cat));
      animatePill(btn);
      applyFilter();
    });
  });

  // Initial pill position — wait for layout
  requestAnimationFrame(() => animatePill(document.querySelector('.cat-btn.active')));
}

function animatePill(activeBtn) {
  if (!activeBtn || !$pill) return;
  const track = document.getElementById('category-track');
  const trackRect = track.getBoundingClientRect();
  const btnRect   = activeBtn.getBoundingClientRect();
  $pill.style.left  = (btnRect.left - trackRect.left) + 'px';
  $pill.style.width = btnRect.width + 'px';
}

// ── Filter ────────────────────────────────────────────
function applyFilter() {
  const keywords = CAT_KEYWORDS[state.category];
  if (!keywords) {
    state.filtered = [...state.allProducts];
  } else {
    state.filtered = state.allProducts.filter(p => {
      const haystack = [
        p.category || '',
        p.keyword  || '',
        p.product_name || '',
        p.title_translated || '',
      ].join(' ').toLowerCase();
      return keywords.some(k => haystack.includes(k));
    });
  }
  renderGrid();
}

// ── Render Grid ───────────────────────────────────────
function renderGrid() {
  if (state.filtered.length === 0) { showEmpty(); return; }

  $empty.style.display    = 'none';
  $grid.style.display     = 'grid';

  // Sort: score desc, then newest
  const sorted = [...state.filtered].sort((a, b) =>
    ((b.score ?? b.ai_score ?? 0) - (a.score ?? a.ai_score ?? 0))
  );

  $grid.innerHTML = sorted.map(p => cardHTML(p)).join('');

  // Lazy-load images
  $grid.querySelectorAll('.card-img-wrap img[data-src]').forEach(lazyLoad);

  // Attach click → profile
  $grid.querySelectorAll('.product-card[data-id]').forEach(el => {
    el.addEventListener('click', () => {
      const id = parseInt(el.dataset.id, 10);
      const product = state.allProducts.find(p => p.id === id);
      if (product) showProfile(product, true);
    });
  });

  // Load-more visibility
  const hasMore = state.allProducts.length < state.total && state.category === 'all';
  $loadMore.style.display = hasMore ? 'block' : 'none';
}

function cardHTML(p) {
  const name  = p.product_name || p.title_translated || 'Gift';
  const score = p.score ?? p.ai_score ?? 0;
  const isTall = score > 90;
  const price = p.sell_price_eur != null ? `₾${Number(p.sell_price_eur).toFixed(0)}` : '';
  const imgs  = Array.isArray(p.images) ? p.images : [];
  const imgSrc = imgs[0] ? imageUrl(imgs[0]) : null;
  const isPremium = score > 85;

  return `
  <article class="product-card${isTall ? ' tall' : ''}" data-id="${p.id}" role="button" tabindex="0" aria-label="View ${esc(name)}">
    <div class="card-img-wrap">
      ${imgSrc
        ? `<img data-src="${esc(imgSrc)}" alt="${esc(name)}" loading="lazy"/>`
        : `<div class="card-img-placeholder">🎁</div>`}
    </div>
    ${isPremium ? `<span class="card-badge-premium">Featured</span>` : ''}
    <div class="card-info">
      <div class="card-name">${esc(name)}</div>
      ${price ? `<div class="card-price">${esc(price)}</div>` : ''}
    </div>
  </article>`;
}

// ── Profile View ──────────────────────────────────────
function showProfile(product, pushHistory = true) {
  state.currentProduct = product;

  // Melt gallery
  $gallery.classList.add('melting');

  setTimeout(() => {
    $gallery.classList.remove('active');
    $gallery.classList.remove('melting');
    $profile.classList.add('active');
    $profile.classList.add('fading-in');

    renderProfile(product);
    window.scrollTo({ top: 0, behavior: 'instant' });

    if (pushHistory) {
      history.pushState({ view: 'profile', id: product.id }, '', `#product-${product.id}`);
    }

    setTimeout(() => $profile.classList.remove('fading-in'), 500);
  }, 420);
}

function showGallery(pushHistory = true) {
  $profile.classList.add('melting');

  setTimeout(() => {
    $profile.classList.remove('active');
    $profile.classList.remove('melting');
    $gallery.classList.add('active');
    $gallery.classList.add('fading-in');

    window.scrollTo({ top: 0, behavior: 'instant' });

    if (pushHistory) {
      history.pushState({ view: 'gallery' }, '', window.location.pathname);
    }

    setTimeout(() => $gallery.classList.remove('fading-in'), 500);
  }, 420);
}

function renderProfile(p) {
  const name    = p.product_name || p.title_translated || 'Gift';
  const story   = p.caption || p.description || 'A beautifully curated gift, chosen with intention for the moments that matter most.';
  const price   = p.sell_price_eur != null ? `₾${Number(p.sell_price_eur).toFixed(0)}` : '';
  const imgs    = Array.isArray(p.images) ? p.images : [];
  const imgSrc  = imgs[0] ? imageUrl(imgs[0]) : null;
  const igLink  = `https://ig.me/m/${IG_USERNAME}?text=Inquiry:%20${encodeURIComponent(name)}`;

  document.getElementById('profile-inner').innerHTML = `
    <div class="profile-back-bar">
      <button class="back-btn" id="back-btn" aria-label="Back to gallery">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"/>
        </svg>
        Gallery
      </button>
    </div>

    <div class="profile-hero">
      <div class="profile-img-wrap">
        ${imgSrc
          ? `<img data-src="${esc(imgSrc)}" alt="${esc(name)}"/>`
          : `<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:4rem;opacity:0.3">🎁</div>`}
      </div>
    </div>

    <div class="profile-details">
      <p class="profile-label">Curated Gift</p>
      <h1 class="profile-name">${esc(name)}</h1>
      ${price ? `<p class="profile-price">${esc(price)}</p>` : ''}
      <div class="profile-divider"></div>
      <p class="profile-story">${esc(story)}</p>
      <a class="cta-btn" href="${igLink}" target="_blank" rel="noopener" aria-label="Inquire about ${esc(name)} via Instagram">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="2" width="20" height="20" rx="5" ry="5"/>
          <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/>
          <line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/>
        </svg>
        Gift this Moment
      </a>
      <p class="cta-sub">Opens Instagram · No account needed</p>
    </div>
  `;

  // Back button
  document.getElementById('back-btn').addEventListener('click', () => showGallery(true));

  // Lazy-load profile image
  const img = document.querySelector('#profile-inner .profile-img-wrap img[data-src]');
  if (img) lazyLoad(img);
}

// ── Helpers ───────────────────────────────────────────
function showSkeletons() {
  $empty.style.display = 'none';
  $loadMore.style.display = 'none';
  $grid.style.display = 'grid';
  $grid.innerHTML = Array.from({ length: 6 }, (_, i) =>
    `<div class="product-card skeleton${i % 3 === 1 ? ' tall' : ''}"></div>`
  ).join('');
}

function showEmpty() {
  $grid.innerHTML = '';
  $grid.style.display = 'none';
  $loadMore.style.display = 'none';
  $empty.style.display = 'block';
}

function imageUrl(src) {
  if (!src) return null;
  if (src.startsWith('http')) {
    // proxy via backend to avoid CORS / mixed-content issues
    return `${API_BASE}/image?url=${encodeURIComponent(src)}`;
  }
  return src;
}

function lazyLoad(img) {
  const src = img.dataset.src;
  if (!src) return;
  img.src = src;
  img.onload  = () => img.classList.add('loaded');
  img.onerror = () => { img.style.display = 'none'; };
}

function esc(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
