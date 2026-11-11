/* Card Scanner — scans Pokémon / One Piece cards and lists TCGplayer prices, set and PSA 9/10 pop. */
(() => {
  'use strict';
  const M = window.Matcher;
  const $ = (s) => document.querySelector(s);
  const GAME_LABEL = { pokemon: 'Pokémon', 'pokemon-jp': 'Pokémon (JP)', onepiece: 'One Piece' };
  const DEFAULT_MODEL = 'claude-sonnet-5-5';

  // ---------- storage ----------
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* full or blocked */ } },
  };
  const settings = Object.assign({ key: '', model: DEFAULT_MODEL, ghToken: '', ghRepo: guessRepo() }, store.get('cs.settings', {}));
  if (!settings.ghRepo) settings.ghRepo = guessRepo();
  let list = store.get('cs.list', []);   // [{uid, game, pid, printing, added, detected, candidates, psaPending}]
  const saveList = () => store.set('cs.list', list);

  function guessRepo() {
    const h = location.hostname;
    if (!h.endsWith('.github.io')) return '';
    const owner = h.split('.')[0];
    const first = location.pathname.split('/').filter(Boolean)[0];
    return first ? `${owner}/${first}` : `${owner}/${h}`;
  }

  // ---------- data ----------
  const games = {};        // game -> decoded data
  const loading = {};
  let meta = null;
  let psa = {};

  async function fetchJSON(path) {
    const r = await fetch(path, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }
  async function loadMeta() {
    try {
      meta = await fetchJSON('data/meta.json');
      const built = new Date(meta.built);
      $('#data-status').textContent = `Prices updated ${built.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ${built.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`;
    } catch (e) {
      $('#data-status').textContent = 'Price data not found yet. Run the GitHub workflow (see setup guide).';
    }
  }
  async function loadPsa() {
    try { psa = (await fetchJSON('data/psa.json')).cards || {}; } catch { psa = {}; }
    // Clear "pending" once real numbers have arrived.
    let changed = false;
    for (const it of list) {
      if (it.psaPending && psa[it.pid] && (psa[it.pid].g10 != null || psa[it.pid].error)) { it.psaPending = false; changed = true; }
    }
    if (changed) saveList();
  }
  function loadGame(game) {
    if (games[game]) return Promise.resolve(games[game]);
    if (!loading[game]) {
      const file = meta && meta.games && meta.games[game] ? meta.games[game].file : `${game}.json`;
      loading[game] = fetchJSON(`data/${file}`).then((j) => (games[game] = M.decodeGame(j)))
        .catch((e) => { delete loading[game]; throw e; });
    }
    return loading[game];
  }

  // ---------- helpers ----------
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const money = (v) => (v == null ? '—' : '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const num = (v) => (v == null ? '—' : Number(v).toLocaleString());
  const img = (pid) => `https://tcgplayer-cdn.tcgplayer.com/product/${pid}_200w.jpg`;
  const tcgUrl = (pid) => `https://www.tcgplayer.com/product/${pid}?Condition=Near+Mint`;
  const uid = () => Math.random().toString(36).slice(2, 10);
  const released = (d) => {
    if (!d) return '';
    const dt = new Date(d + 'T12:00:00');
    return isNaN(dt) ? d : dt.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
  };
  function cardOf(it) { const g = games[it.game]; return g ? g.byId.get(it.pid) : null; }
  function marketOf(it, card) {
    card = card || cardOf(it);
    if (!card) return null;
    const p = card.prices[it.printing] || card.prices[Object.keys(card.prices)[0]];
    return p ? p[0] : null;
  }
  function showError(msg) { const el = $('#error'); el.textContent = msg; el.hidden = !msg; }
  function busy(text) { $('#busy').hidden = !text; if (text) $('#busy-text').textContent = text; }

  // ---------- rendering ----------
  function render() {
    const el = $('#list');
    $('#empty').hidden = list.length > 0;
    let total = 0;
    el.innerHTML = list.map((it) => {
      const c = cardOf(it);
      if (!c) {
        return `<article class="item" data-uid="${it.uid}"><div class="thumb"></div><div class="meta"><h3>${esc(it.detected?.name || 'Card')}</h3><div class="sub">Loading ${esc(GAME_LABEL[it.game] || '')} prices…</div></div></article>`;
      }
      const m = marketOf(it, c);
      if (m) total += m;
      const printings = Object.keys(c.prices);
      const chips = printings.length > 1
        ? `<div class="chips">${printings.map((p) => `<button class="chip ${p === it.printing ? 'on' : ''}" data-act="printing" data-p="${esc(p)}">${esc(p)} ${money(c.prices[p][0])}</button>`).join('')}</div>`
        : '';
      return `
      <article class="item ${it.check ? 'check' : ''}" data-uid="${it.uid}">
        <img class="thumb" src="${img(c.id)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
        <div class="meta">
          <h3>${esc(c.name)}</h3>
          <div class="sub">${esc(c.set.name)}${c.set.date ? ` · released ${esc(released(c.set.date))}` : ''}</div>
          <div class="sub">${c.num ? '#' + esc(c.num) + ' · ' : ''}${esc(c.rarity)} · ${esc(GAME_LABEL[it.game])}</div>
          ${it.check ? '<div class="flag">⚠︎ Not 100% sure this is the right version. Tap “Change” to check.</div>' : ''}
          <div class="price"><span class="amt">${money(m)}</span><span class="lbl">market${it.printing && printings.length > 1 ? ' · ' + esc(it.printing) : ''}</span></div>
          ${chips}
          ${psaHtml(it)}
          <div class="actions">
            <a class="btn secondary" href="${tcgUrl(c.id)}" target="_blank" rel="noopener">TCGplayer ↗</a>
            <button class="btn secondary" data-act="change">Change</button>
            <button class="btn ghost" data-act="remove">Remove</button>
          </div>
        </div>
      </article>`;
    }).join('');
    $('#sum-count').textContent = list.length;
    $('#sum-value').textContent = money(total);
  }

  function psaHtml(it) {
    const p = psa[it.pid];
    if (p && p.g10 != null) {
      return `<div class="psa"><span class="tag">PSA</span><span>9: <b>${num(p.g9)}</b></span><span>10: <b>${num(p.g10)}</b></span><button class="linkish" data-act="psa">edit</button></div>`;
    }
    if (it.psaPending) return `<div class="psa"><span class="tag">PSA</span><span class="muted">Linked. Counts appear in a few minutes.</span></div>`;
    if (p && p.error) return `<div class="psa"><span class="tag">PSA</span><span class="muted">Lookup failed (${esc(p.error)}).</span><button class="linkish" data-act="psa">Fix link</button></div>`;
    if (p) return `<div class="psa"><span class="tag">PSA</span><span class="muted">Linked. Counts arrive with the next update.</span></div>`;
    return `<div class="psa"><span class="tag">PSA</span><button class="linkish" data-act="psa">Link PSA 9/10 pop</button></div>`;
  }

  $('#list').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const it = list.find((x) => x.uid === btn.closest('.item').dataset.uid);
    if (!it) return;
    const act = btn.dataset.act;
    if (act === 'remove') { list = list.filter((x) => x !== it); saveList(); render(); }
    if (act === 'printing') { it.printing = btn.dataset.p; saveList(); render(); }
    if (act === 'change') openPicker(it);
    if (act === 'psa') openPsa(it);
  });

  // ---------- scanning ----------
  async function resizeImage(file, max = 1400) {
    const url = URL.createObjectURL(file);
    try {
      const im = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error('Could not open that photo.')); i.src = url; });
      const scale = Math.min(1, max / Math.max(im.naturalWidth, im.naturalHeight));
      const cv = document.createElement('canvas');
      cv.width = Math.round(im.naturalWidth * scale);
      cv.height = Math.round(im.naturalHeight * scale);
      cv.getContext('2d').drawImage(im, 0, 0, cv.width, cv.height);
      return cv.toDataURL('image/jpeg', 0.85).split(',')[1];
    } finally { URL.revokeObjectURL(url); }
  }

  const PROMPT = `You are identifying trading cards so their prices can be looked up on TCGplayer.
Identify every Pokémon TCG or One Piece Card Game card that is fully or mostly visible in the photo. Read the printed text carefully, especially the collector number (bottom corner) and the set code.
Reply with ONLY a JSON object, no other text, in this shape:
{"cards":[{
 "game": "pokemon" | "onepiece" | "other",
 "language": "en" | "ja" | "other",
 "name": "card name as printed; for Japanese cards give the English name",
 "number": "collector number exactly as printed, e.g. 025/165, 4/102, SWSH050, SVP 044, TG05/TG30, OP05-119, ST01-012, P-001",
 "set_name": "set name if you can tell, else empty",
 "set_code": "set code printed on the card if visible (e.g. SVI, PAL, MEW, sv2a, OP05), else empty",
 "finish": "holo" | "reverse holo" | "non-holo" | "unknown",
 "variant": "short notes such as: alternate art, parallel, manga, full art, special illustration rare, gold, 1st edition, shadowless, promo stamp, or empty",
 "confidence": 0.0
}]}
If no card is visible, reply {"cards":[]}.`;

  async function identify(b64) {
    if (!settings.key) throw new Error('Add your Claude AI API key in Settings first.');
    const r = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': settings.key,
        'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'true',
      },
      body: JSON.stringify({
        model: settings.model || DEFAULT_MODEL,
        max_tokens: 1500,
        messages: [{ role: 'user', content: [
          { type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: b64 } },
          { type: 'text', text: PROMPT },
        ] }],
      }),
    });
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try { msg = (await r.json()).error.message || msg; } catch { /* keep */ }
      if (r.status === 401) msg = 'Your Claude AI API key was rejected. Check it in Settings.';
      throw new Error('Card reading failed: ' + msg);
    }
    const j = await r.json();
    const text = (j.content || []).filter((c) => c.type === 'text').map((c) => c.text).join('');
    const a = text.indexOf('{'), b = text.lastIndexOf('}');
    if (a < 0 || b < 0) throw new Error('Could not read the card. Try a closer, sharper photo.');
    return (JSON.parse(text.slice(a, b + 1)).cards || []);
  }

  function datasetFor(d) {
    if (d.game === 'onepiece') return 'onepiece';
    if (d.game === 'pokemon') return d.language === 'ja' ? 'pokemon-jp' : 'pokemon';
    return null;
  }

  async function addDetected(d) {
    let game = datasetFor(d);
    if (!game) return null;
    let data = await loadGame(game);
    let results = M.match(d, data);
    // Japanese/English guess can be wrong: try the other Pokémon list if the match is weak.
    if (game.startsWith('pokemon') && (!results.length || results[0].score < 60)) {
      const other = game === 'pokemon' ? 'pokemon-jp' : 'pokemon';
      try {
        const od = await loadGame(other);
        const or = M.match(d, od);
        if (or.length && (!results.length || or[0].score > results[0].score)) { game = other; data = od; results = or; }
      } catch { /* other list missing */ }
    }
    const item = {
      uid: uid(), game, added: Date.now(), detected: d,
      pid: results.length ? results[0].card.id : null,
      candidates: results.map((r) => r.card.id),
      check: !M.isConfident(results),
    };
    if (!item.pid) return { item, unmatched: true };
    item.printing = M.pickPrinting(results[0].card.prices, d.finish, d.variant);
    return { item };
  }

  async function handleFiles(files) {
    showError('');
    if (!files || !files.length) return;
    if (!settings.key) { showError('Add your Claude AI API key in Settings to scan cards.'); openSettings(); return; }
    const misses = [];
    let added = 0;
    for (let i = 0; i < files.length; i++) {
      try {
        busy(files.length > 1 ? `Reading photo ${i + 1} of ${files.length}…` : 'Reading card…');
        const b64 = await resizeImage(files[i]);
        const found = await identify(b64);
        if (!found.length) { misses.push('No card found in the photo.'); continue; }
        busy('Matching to TCGplayer…');
        for (const d of found) {
          const res = await addDetected(d);
          if (!res) { misses.push(`${d.name || 'A card'} isn't Pokémon or One Piece.`); continue; }
          if (res.unmatched) { misses.push(`Couldn't match “${d.name} ${d.number || ''}”. Use Search to add it.`); continue; }
          list.unshift(res.item); added++;
        }
        saveList(); render();
      } catch (e) {
        misses.push(e.message || String(e));
      }
    }
    busy('');
    if (misses.length) showError(misses.join(' '));
    if (added) window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  $('#in-camera').addEventListener('change', (e) => { handleFiles([...e.target.files]); e.target.value = ''; });
  $('#in-library').addEventListener('change', (e) => { handleFiles([...e.target.files]); e.target.value = ''; });

  // ---------- pick / change / search ----------
  let pickTarget = null; // item being changed, or null when adding by search
  const dlgPick = $('#dlg-pick');

  function pickRow(c, current) {
    const p = Object.values(c.prices)[0];
    return `<button class="pick ${current ? 'current' : ''}" data-pid="${c.id}">
      <img src="${img(c.id)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
      <span><span class="p-name">${esc(c.name)}</span><br><span class="p-sub">${esc(c.set.name)} · #${esc(c.num)} · ${esc(c.rarity)}</span></span>
      <span class="p-price">${money(p ? p[0] : null)}</span></button>`;
  }

  async function showPickResults() {
    const game = $('#pick-game').value;
    const box = $('#pick-results');
    let data;
    try { data = await loadGame(game); } catch { box.innerHTML = '<p class="muted">Price data for this game isn’t available yet.</p>'; return; }
    const q = $('#pick-query').value.trim();
    let cards;
    if (q) cards = M.search(q, data).map((r) => r.card);
    else if (pickTarget && pickTarget.game === game) cards = pickTarget.candidates.map((id) => data.byId.get(id)).filter(Boolean);
    else cards = [];
    box.innerHTML = cards.length
      ? cards.map((c) => pickRow(c, pickTarget && c.id === pickTarget.pid)).join('')
      : `<p class="muted small">${q ? 'No matches. Try fewer words, or just the number.' : 'Type a card name, number or set.'}</p>`;
  }

  function openPicker(item) {
    pickTarget = item || null;
    $('#pick-title').textContent = item ? 'Choose the right card' : 'Add a card by search';
    const d = item && item.detected;
    $('#pick-detected').textContent = d ? `Read from photo: ${d.name || '?'} ${d.number ? '#' + d.number : ''}${d.variant ? ' · ' + d.variant : ''}` : '';
    $('#pick-game').value = item ? item.game : ($('#pick-game').value || 'pokemon');
    $('#pick-query').value = '';
    showPickResults();
    dlgPick.showModal();
    if (!item) setTimeout(() => $('#pick-query').focus(), 50);
  }

  let qTimer;
  $('#pick-query').addEventListener('input', () => { clearTimeout(qTimer); qTimer = setTimeout(showPickResults, 200); });
  $('#pick-game').addEventListener('change', showPickResults);
  $('#pick-results').addEventListener('click', (e) => {
    const b = e.target.closest('.pick');
    if (!b) return;
    const game = $('#pick-game').value;
    const c = games[game].byId.get(Number(b.dataset.pid));
    if (pickTarget) {
      pickTarget.game = game;
      pickTarget.pid = c.id;
      pickTarget.check = false;
      pickTarget.psaPending = false;
      pickTarget.printing = M.pickPrinting(c.prices, pickTarget.detected?.finish, pickTarget.detected?.variant);
    } else {
      list.unshift({ uid: uid(), game, pid: c.id, added: Date.now(), detected: null, candidates: [c.id], check: false,
        printing: M.pickPrinting(c.prices, '', '') });
    }
    saveList(); render(); dlgPick.close();
  });
  $('#btn-search').addEventListener('click', () => openPicker(null));

  // ---------- PSA linking ----------
  const dlgPsa = $('#dlg-psa');
  let psaTarget = null;

  function b64encode(str) { return btoa(unescape(encodeURIComponent(str))); }
  function b64decode(b64) { return decodeURIComponent(escape(atob(b64.replace(/\s/g, '')))); }

  async function updateLinks(mutate) {
    if (!settings.ghToken || !settings.ghRepo) throw new Error('Add your GitHub token and repository in Settings first.');
    const url = `https://api.github.com/repos/${settings.ghRepo}/contents/psa-links.json`;
    const headers = { Authorization: `Bearer ${settings.ghToken}`, Accept: 'application/vnd.github+json' };
    let sha, data = {};
    const r = await fetch(url, { headers, cache: 'no-store' });
    if (r.ok) { const j = await r.json(); sha = j.sha; data = JSON.parse(b64decode(j.content) || '{}'); }
    else if (r.status !== 404) throw new Error(`GitHub said ${r.status}. Check the token and repository name.`);
    mutate(data);
    const put = await fetch(url, {
      method: 'PUT', headers,
      body: JSON.stringify({ message: 'Update PSA links', content: b64encode(JSON.stringify(data, null, 2) + '\n'), sha }),
    });
    if (!put.ok) {
      let m = `GitHub said ${put.status}.`;
      try { m += ' ' + (await put.json()).message; } catch { /* keep */ }
      throw new Error(m);
    }
  }

  function openPsa(item) {
    psaTarget = item;
    const c = cardOf(item);
    $('#psa-card').textContent = c ? `${c.name} · ${c.set.name} · #${c.num}` : '';
    const linked = psa[item.pid];
    $('#psa-cert').value = linked ? linked.cert : '';
    $('#psa-unlink').hidden = !linked;
    $('#psa-msg').textContent = linked && linked.certDesc ? `Linked to PSA: ${linked.certDesc}` : '';
    const q = c ? `PSA ${M.baseName(c.name)} ${c.num.split('/')[0]} ${c.set.name}` : 'PSA';
    $('#psa-find').href = `https://www.ebay.com/sch/i.html?_nkw=${encodeURIComponent(q)}`;
    dlgPsa.showModal();
  }

  async function savePsa(cert) {
    const it = psaTarget;
    $('#psa-msg').textContent = 'Saving…';
    try {
      await updateLinks((links) => { if (cert) links[String(it.pid)] = cert; else delete links[String(it.pid)]; });
      for (const x of list) if (x.pid === it.pid) x.psaPending = !!cert;
      if (!cert) delete psa[it.pid];
      saveList(); render(); dlgPsa.close();
    } catch (e) {
      $('#psa-msg').textContent = e.message;
    }
  }
  $('#psa-save').addEventListener('click', () => {
    const cert = $('#psa-cert').value.replace(/\D/g, '');
    if (cert.length < 6) { $('#psa-msg').textContent = 'That doesn’t look like a PSA cert number.'; return; }
    savePsa(cert);
  });
  $('#psa-unlink').addEventListener('click', () => savePsa(''));

  // ---------- settings ----------
  const dlgSet = $('#dlg-settings');
  function openSettings() {
    $('#set-key').value = settings.key;
    $('#set-model').value = settings.model || DEFAULT_MODEL;
    $('#set-gh').value = settings.ghToken;
    $('#set-repo').value = settings.ghRepo;
    const g = meta && meta.games ? Object.entries(meta.games).map(([k, v]) => `${GAME_LABEL[k] || k}: ${v.cards.toLocaleString()} cards`).join(' · ') : 'No price data loaded.';
    $('#set-data').textContent = g;
    dlgSet.showModal();
  }
  $('#btn-settings').addEventListener('click', openSettings);
  $('#set-save').addEventListener('click', () => {
    settings.key = $('#set-key').value.trim();
    settings.model = $('#set-model').value;
    settings.ghToken = $('#set-gh').value.trim();
    settings.ghRepo = $('#set-repo').value.trim().replace(/^https?:\/\/github\.com\//, '').replace(/\/$/, '');
    store.set('cs.settings', settings);
    dlgSet.close();
    showError('');
  });
  $('#btn-clear').addEventListener('click', () => {
    if (!list.length || !confirm(`Remove all ${list.length} cards from the list?`)) return;
    list = []; saveList(); render(); dlgSet.close();
  });
  $('#btn-export').addEventListener('click', async () => {
    const rows = [['Name', 'Game', 'Set', 'Released', 'Number', 'Rarity', 'Printing', 'Market Price', 'PSA 9', 'PSA 10', 'TCGplayer']];
    for (const it of list) {
      const c = cardOf(it); if (!c) continue;
      const p = psa[it.pid] || {};
      rows.push([c.name, GAME_LABEL[it.game], c.set.name, c.set.date, c.num, c.rarity, it.printing || '', marketOf(it, c) ?? '', p.g9 ?? '', p.g10 ?? '', `https://www.tcgplayer.com/product/${c.id}`]);
    }
    const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n');
    const name = `cards-${new Date().toISOString().slice(0, 10)}.csv`;
    const file = new File([csv], name, { type: 'text/csv' });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: 'Card list' }); return; } catch { /* cancelled */ }
    }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(file); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });

  // ---------- start ----------
  async function start() {
    render();
    await Promise.all([loadMeta(), loadPsa()]);
    const needed = [...new Set(list.map((i) => i.game))];
    await Promise.allSettled(needed.map(loadGame));
    render();
    if (!settings.key) showError('Welcome! Open Settings (gear icon) and add your Claude AI API key to start scanning.');
    // Warm up the rest in the background so the first scan is quick.
    setTimeout(() => ['pokemon', 'onepiece', 'pokemon-jp'].forEach((g) => loadGame(g).catch(() => {})), 1500);
  }
  // Pick up fresh PSA numbers when the app comes back to the foreground.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && list.some((i) => i.psaPending)) loadPsa().then(render);
  });

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
  start();
})();
