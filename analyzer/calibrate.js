// Compare analyzer estimates with real FDS runs.
// Uses .out files (exact step count, wall time per step, server) where available,
// and the old portal's CSV export for server names and prices.
// usage: node calibrate.js <dir with .fds + csv> <dir with .out> [--json]
const fs = require('fs');
const path = require('path');
const A = require('./fds-analyzer.js');
const { parseOut } = require('./parse-out.js');

const [dir, outDir] = process.argv.slice(2);
const asJson = process.argv.includes('--json');

const csv = fs.readFileSync(path.join(dir, 'symulacje-admin-2026-10-24.csv'), 'utf8').replace(/^﻿/, '');
const rows = csv.trim().split(/\r?\n/).slice(1).map(l => l.split(';').map(c => c.replace(/^"|"$/g, '')));
const plNum = s => Number(String(s).replace(',', '.'));
const runs = new Map(rows.map(r => [r[3], { server: r[5], oldEstH: Number(r[7]), price: plNum(r[8]), costEur: plNum(r[9]) }]));

const results = [];
fs.readdirSync(dir).filter(f => f.endsWith('.fds')).sort().forEach(f => {
  const text = fs.readFileSync(path.join(dir, f), 'utf8');
  const outPath = outDir && path.join(outDir, f.replace(/\.fds$/, '.out'));
  if (!outPath || !fs.existsSync(outPath)) return;
  const o = parseOut(fs.readFileSync(outPath, 'utf8'));
  const complete0 = /completed successfully/.test(o.status);
  // for runs stopped early, estimate only up to the simulated time actually reached
  const { model } = A.analyze(complete0 ? text : text.replace(/T_END\s*=\s*[\d.E+-]+/i, `T_END=${o.tReached}`));
  const fullModel = A.analyze(text).model;
  const run = runs.get(f) || {};
  const server = A.DEFAULTS.servers.find(s => s.name === run.server) || A.DEFAULTS.servers[1];
  const complete = /completed successfully/.test(o.status);
  // compare on the simulated time actually reached
  const estSteps = A.estimate(model, A.DEFAULTS, model.maxLoad, server).steps;
  const estHours = A.estimate(model, A.DEFAULTS, model.maxLoad, server).hours;
  results.push({
    file: f.replace(/\.fds$/, ''), server: server.name, complete, tReached: o.tReached, tEnd: fullModel.simTime,
    steps: o.nSteps, estSteps: Math.round(estSteps),
    kReal: o.wallPerStep / model.maxLoad, kModel: server.k,
    realH: o.wallStepping / 3600, estH: estHours, oldEstH: run.oldEstH,
    full: { realH: complete ? o.wallStepping / 3600 : null, estH: A.estimate(fullModel, A.DEFAULTS, fullModel.maxLoad, server).hours },
    piter: o.pIterMean,
  });
});

if (asJson) { console.log(JSON.stringify(results)); process.exit(0); }
const pct = (a, b) => `${a > b ? '+' : ''}${Math.round((a / b - 1) * 100)}%`.padStart(5);
console.log('file'.padEnd(48), 'srv  ', 'done', 'steps(real/est)'.padStart(22), 'k µs(real/model)'.padStart(18), 'hours(real/est/old)'.padStart(24));
results.forEach(r => console.log(
  r.file.slice(0, 47).padEnd(48), r.server, r.complete ? ' yes' : ` ${Math.round(r.tReached)}s`,
  `${r.steps}/${r.estSteps} ${pct(r.estSteps, r.steps)}`.padStart(22),
  `${(r.kReal * 1e6).toFixed(2)}/${(r.kModel * 1e6).toFixed(1)}`.padStart(18),
  `${r.realH.toFixed(1)}/${r.estH.toFixed(1)} ${pct(r.estH, r.realH)} / ${r.oldEstH ? r.oldEstH.toFixed(1) : '-'}`.padStart(24)));
const ks = (srv) => results.filter(r => r.server === srv).map(r => r.kReal * 1e6).sort((a, b) => a - b);
['cpx42', 'cpx62'].forEach(s => console.log(`k ${s} [µs]:`, ks(s).map(v => v.toFixed(2)).join(', ')));
