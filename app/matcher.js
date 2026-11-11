/* Card matching: turns what the AI read off a card into the right TCGplayer product.
   Works in the browser (window.Matcher) and in Node (require) for testing. */
(function (root) {
  'use strict';

  // "025/165" -> left "25", total "165"; "TG05/TG30" -> "TG5"/"TG30"; "OP05-119" -> "OP5-119"
  function normNum(s) {
    if (!s) return '';
    s = String(s).toUpperCase().replace(/\s+/g, '').replace(/^#/, '').replace(/^NO\.?/, '');
    return s.replace(/(^|[^0-9])0+(?=\d)/g, '$1');
  }
  function splitNum(s) {
    const n = normNum(s);
    const i = n.indexOf('/');
    return i < 0 ? { left: n, total: '' } : { left: n.slice(0, i), total: n.slice(i + 1) };
  }
  function digitsOf(s) { return String(s || '').replace(/[^0-9]/g, ''); }

  function normText(s) {
    return String(s || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '')
      .replace(/[’'`]/g, '').replace(/[^a-z0-9぀-ヿ一-龯]+/g, ' ').trim();
  }
  // "Charizard ex - 223/197" -> "Charizard ex"; "Monkey.D.Luffy (Parallel)" -> "Monkey.D.Luffy"
  function baseName(name) {
    return String(name || '')
      .replace(/\s+-\s+[A-Za-z]*\d[\w/-]*\s*$/, '')
      .replace(/\([^)]*\)|\[[^\]]*\]/g, ' ')
      .replace(/\s+/g, ' ').trim();
  }
  function variantText(name) {
    const m = String(name || '').match(/\(([^)]*)\)|\[([^\]]*)\]/g);
    return m ? m.join(' ').toLowerCase() : '';
  }

  function bigrams(s) {
    const t = ' ' + s + ' ';
    const out = new Map();
    for (let i = 0; i < t.length - 1; i++) {
      const b = t.slice(i, i + 2);
      out.set(b, (out.get(b) || 0) + 1);
    }
    return out;
  }
  function bigramSim(a, b) {
    if (!a || !b) return 0;
    if (a === b) return 1;
    let inter = 0, na = 0, nb = 0;
    for (const v of a.values()) na += v;
    for (const v of b.values()) nb += v;
    for (const [k, v] of a) { const w = b.get(k); if (w) inter += Math.min(v, w); }
    return (2 * inter) / (na + nb);
  }
  const textSim = (x, y) => bigramSim(bigrams(normText(x)), bigrams(normText(y)));

  const VARIANT_RE = /parallel|alternate|alt art|manga|special|\bsp\b|full art|treasure|serial|super parallel|red super/;

  /* Turn the compact file from build_prices.py into objects. */
  function decodeGame(json) {
    const sets = json.sets.map(([id, name, abbr, date]) => ({ id, name, abbr, date }));
    const cards = json.cards.map(([id, name, num, rarity, si, prices]) => {
      const c = { id, name, num, rarity, set: sets[si], prices: prices || {} };
      c._num = splitNum(num);
      c._name = normText(baseName(name));
      c._bg = bigrams(c._name);
      c._variant = variantText(name);
      return c;
    });
    const byId = new Map(cards.map(c => [c.id, c]));
    return { game: json.game, built: json.built, sets, cards, byId };
  }

  function wantsVariant(d) {
    return VARIANT_RE.test(String(d.variant || '').toLowerCase());
  }

  function scoreCard(c, d, dn, dBg, setBg) {
    let s = 0;
    if (dn.left) {
      if (c._num.left === dn.left) {
        s += 50;
        if (dn.total && c._num.total) s += c._num.total === dn.total ? 12 : -8;
      } else if (c._num.left && digitsOf(c._num.left) && digitsOf(c._num.left) === digitsOf(dn.left)) {
        s += 12; // same digits, different prefix (e.g. "TG5" vs "5")
      }
    }
    s += 35 * bigramSim(dBg, c._bg);
    if (d.set_code && c.set.abbr && normText(d.set_code) === normText(c.set.abbr)) s += 15;
    if (setBg) s += 15 * bigramSim(setBg, bigrams(normText(c.set.name)));
    const has = VARIANT_RE.test(c._variant);
    const want = wantsVariant(d);
    if (want && has) s += 8;
    if (!want && has) s -= 4;
    return s;
  }

  /* Best matches for one detected card. Returns [{card, score}] best first. */
  function match(detected, data, limit) {
    limit = limit || 8;
    const d = detected || {};
    const dn = splitNum(d.number);
    const dBg = bigrams(normText(baseName(d.name)));
    const setBg = d.set_name ? bigrams(normText(d.set_name)) : null;
    const scored = [];
    for (const c of data.cards) {
      // Quick skip: no number match and the name is not even close.
      if (dn.left && c._num.left !== dn.left && digitsOf(c._num.left) !== digitsOf(dn.left)) {
        if (bigramSim(dBg, c._bg) < 0.6) continue;
      }
      const score = scoreCard(c, d, dn, dBg, setBg);
      if (score > 20) scored.push({ card: c, score });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, limit);
  }

  /* Is the top match clearly the right one? */
  function isConfident(results) {
    if (!results.length) return false;
    const [a, b] = results;
    if (a.score < 75) return false;
    return !b || a.score - b.score >= 6;
  }

  /* Choose which printing's price to show (Normal, Holofoil, Reverse Holofoil, 1st Edition…). */
  function pickPrinting(prices, finish, variant) {
    const keys = Object.keys(prices || {});
    if (!keys.length) return null;
    if (keys.length === 1) return keys[0];
    const f = String(finish || '').toLowerCase();
    const v = String(variant || '').toLowerCase();
    const first = /1st|first/.test(v);
    const score = (k) => {
      const kl = k.toLowerCase();
      let s = 0;
      if (/reverse/.test(f)) s += /reverse/.test(kl) ? 10 : 0;
      else if (/holo/.test(f)) s += /holo/.test(kl) && !/reverse/.test(kl) ? 10 : 0;
      else if (/non/.test(f)) s += /normal|unlimited$/.test(kl) || !/holo/.test(kl) ? 10 : 0;
      s += first ? (/1st/.test(kl) ? 5 : 0) : (/1st/.test(kl) ? -5 : 0);
      if (kl === 'normal') s += 1;
      if (kl === 'holofoil') s += 0.5;
      return s;
    };
    return keys.slice().sort((a, b) => score(b) - score(a))[0];
  }

  /* Plain text search for the "pick a different card" screen. */
  function search(query, data, limit) {
    limit = limit || 30;
    const q = normText(query);
    if (!q) return [];
    const words = q.split(' ');
    const qn = splitNum(query).left;
    const qBg = bigrams(q);
    const out = [];
    for (const c of data.cards) {
      const hay = c._name + ' ' + normText(c.num) + ' ' + normText(c.set.name) + ' ' + normText(c.set.abbr) + ' ' + c._variant;
      if (!words.every(w => hay.includes(w) || normNum(w) === c._num.left)) continue;
      let s = bigramSim(qBg, c._bg);
      if (qn && c._num.left === qn) s += 1;
      out.push({ card: c, score: s });
    }
    out.sort((a, b) => b.score - a.score);
    return out.slice(0, limit);
  }

  const api = { normNum, splitNum, normText, baseName, decodeGame, match, isConfident, pickPrinting, search, textSim };
  root.Matcher = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof self !== 'undefined' ? self : globalThis);
