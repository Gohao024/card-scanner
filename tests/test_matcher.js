// Run: node tests/test_matcher.js
const assert = require('assert');
const M = require('../app/matcher.js');

const pokemon = M.decodeGame({
  game: 'pokemon',
  sets: [
    [604, 'Base Set', 'BS', '1999-01-09'],
    [23237, 'SV: Scarlet & Violet 151', 'MEW', '2023-09-22'],
    [3170, 'SWSH12: Silver Tempest', 'SWSH12', '2022-11-11'],
    [17688, 'SWSH12: Silver Tempest Trainer Gallery', 'SWSH12TG', '2022-11-11'],
    [22873, 'SV: Paldea Evolved', 'PAL', '2023-06-09'],
  ],
  cards: [
    [42382, 'Charizard', '4/102', 'Holo Rare', 0, { Holofoil: [400.5, 350], '1st Edition Holofoil': [9000, 8000] }],
    [42346, 'Blastoise', '2/102', 'Holo Rare', 0, { Holofoil: [150, 120] }],
    [517045, 'Charizard ex - 199/165', '199/165', 'Special Illustration Rare', 1, { Holofoil: [210.12, 190] }],
    [502544, 'Charizard ex - 006/165', '006/165', 'Double Rare', 1, { Holofoil: [5.5, 4] }],
    [502900, 'Pikachu - 025/165', '025/165', 'Common', 1, { Normal: [0.4, 0.1], 'Reverse Holofoil': [1.2, 0.8] }],
    [451396, 'Lugia VSTAR', '139/195', 'Ultra Rare', 2, { Holofoil: [3.1, 2.5] }],
    [451544, 'Lugia V (Alternate Full Art)', '186/195', 'Ultra Rare', 2, { Holofoil: [280, 250] }],
    [451400, 'Pikachu', 'TG05/TG30', 'Trainer Gallery Rare Holo', 3, { Holofoil: [6, 5] }],
    [496000, 'Pikachu - 025/193', '025/193', 'Common', 4, { Normal: [0.2, 0.05], 'Reverse Holofoil': [0.6, 0.3] }],
  ],
});

const onepiece = M.decodeGame({
  game: 'onepiece',
  sets: [[23213, 'Awakening of the New Era', 'OP05', '2023-12-08']],
  cards: [
    [516001, 'Monkey.D.Luffy', 'OP05-119', 'Secret Rare', 0, { Normal: [60, 55] }],
    [516002, 'Monkey.D.Luffy (Parallel)', 'OP05-119', 'Secret Rare', 0, { Normal: [180, 170] }],
    [516003, 'Monkey.D.Luffy (Manga)', 'OP05-119', 'Secret Rare', 0, { Normal: [2500, 2300] }],
    [516010, 'Kaido', 'OP05-118', 'Super Rare', 0, { Foil: [1.2, 1] }],
  ],
});

let n = 0;
function t(name, fn) { fn(); n++; console.log('ok -', name); }

t('number normalization', () => {
  assert.strictEqual(M.normNum('025/165'), '25/165');
  assert.strictEqual(M.normNum('TG05/TG30'), 'TG5/TG30');
  assert.strictEqual(M.normNum('OP05-119'), 'OP5-119');
  assert.strictEqual(M.normNum('100/102'), '100/102');
  assert.strictEqual(M.baseName('Charizard ex - 199/165'), 'Charizard ex');
  assert.strictEqual(M.baseName('Monkey.D.Luffy (Parallel)'), 'Monkey.D.Luffy');
});

t('same number in two sets is told apart by the total', () => {
  const r = M.match({ name: 'Pikachu', number: '025/165' }, pokemon);
  assert.strictEqual(r[0].card.id, 502900);
  assert.ok(M.isConfident(r));
  const r2 = M.match({ name: 'Pikachu', number: '025/193' }, pokemon);
  assert.strictEqual(r2[0].card.id, 496000);
});

t('SIR vs regular Charizard ex by number', () => {
  const r = M.match({ name: 'Charizard ex', number: '199/165', set_name: '151' }, pokemon);
  assert.strictEqual(r[0].card.id, 517045);
});

t('vintage card with leading-zero-free number', () => {
  const r = M.match({ name: 'Charizard', number: '4/102', set_name: 'Base Set', finish: 'holo' }, pokemon);
  assert.strictEqual(r[0].card.id, 42382);
  assert.strictEqual(M.pickPrinting(r[0].card.prices, 'holo', ''), 'Holofoil');
  assert.strictEqual(M.pickPrinting(r[0].card.prices, 'holo', '1st edition'), '1st Edition Holofoil');
});

t('trainer gallery number', () => {
  const r = M.match({ name: 'Pikachu', number: 'TG05/TG30' }, pokemon);
  assert.strictEqual(r[0].card.id, 451400);
});

t('slight misread of name still matches by number', () => {
  const r = M.match({ name: 'Lugla VSTAR', number: '139/195' }, pokemon);
  assert.strictEqual(r[0].card.id, 451396);
});

t('no number: falls back to name', () => {
  const r = M.match({ name: 'Blastoise', number: '' }, pokemon);
  assert.strictEqual(r[0].card.id, 42346);
});

t('One Piece base vs parallel vs manga', () => {
  const base = M.match({ name: 'Monkey.D.Luffy', number: 'OP05-119', variant: '' }, onepiece);
  assert.strictEqual(base[0].card.id, 516001);
  const alt = M.match({ name: 'Monkey.D.Luffy', number: 'OP05-119', variant: 'alternate art parallel' }, onepiece);
  assert.notStrictEqual(alt[0].card.id, 516001);
  assert.ok(!M.isConfident(alt), 'parallel vs manga should ask the user to confirm');
  const manga = M.match({ name: 'Monkey D. Luffy', number: 'OP05-119', variant: 'manga' }, onepiece);
  assert.ok([516002, 516003].includes(manga[0].card.id));
});

t('reverse holo printing pick', () => {
  const c = pokemon.byId.get(502900);
  assert.strictEqual(M.pickPrinting(c.prices, 'reverse holo', ''), 'Reverse Holofoil');
  assert.strictEqual(M.pickPrinting(c.prices, 'non-holo', ''), 'Normal');
  assert.strictEqual(M.pickPrinting(c.prices, 'unknown', ''), 'Normal');
});

t('text search', () => {
  const r = M.search('lugia alternate', pokemon);
  assert.strictEqual(r[0].card.id, 451544);
  const r2 = M.search('pikachu 25', pokemon);
  assert.strictEqual(r2.length, 2);
});

console.log(`\n${n} tests passed`);
