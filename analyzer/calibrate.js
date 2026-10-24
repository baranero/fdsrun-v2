// Compare analyzer estimates with real run times from the old portal export.
const fs = require('fs');
const path = require('path');
const A = require('./fds-analyzer.js');

const dir = process.argv[2];
const csv = fs.readFileSync(path.join(dir, 'symulacje-admin-2026-10-24.csv'), 'utf8').replace(/^﻿/, '');
const rows = csv.trim().split(/\r?\n/).slice(1).map(l => l.split(';').map(c => c.replace(/^"|"$/g, '')));
const parseDate = s => { const [d, t] = s.split(', '); const [D, M, Y] = d.split('.').map(Number); const [h, m, sec] = t.split(':').map(Number); return new Date(Y, M - 1, D, h, m, sec); };
const plNum = s => Number(String(s).replace(',', '.'));
const runs = rows.map(r => ({
  file: r[3], server: r[5], cells: Number(r[6]), estH: Number(r[7]), price: plNum(r[8]), costEur: plNum(r[9]),
  wallH: (parseDate(r[12]) - parseDate(r[11])) / 3600e3,
}));

// effective server rates
const rates = {};
runs.filter(r => r.wallH > 1).forEach(r => { (rates[r.server] = rates[r.server] || []).push(r.costEur / r.wallH); });
console.log('EUR/h per server:', Object.fromEntries(Object.entries(rates).map(([k, v]) => [k, +(v.reduce((a, b) => a + b) / v.length).toFixed(3)])));

const out = [];
fs.readdirSync(dir).filter(f => f.endsWith('.fds')).forEach(f => {
  const { model, issues } = A.analyze(fs.readFileSync(path.join(dir, f), 'utf8'));
  const run = runs.find(r => r.file === f);
  const s = A.estimate(model, { ...A.DEFAULTS, kSecPerCellStep: 1 }).steps;
  const work = model.maxLoad * s;                    // cell-steps on the busiest process
  const k = run ? run.wallH * 3600 / work : null;   // seconds per cell-step
  out.push({ f, model, issues, run, work, k });
});

const ks = out.filter(o => o.k).map(o => o.k).sort((a, b) => a - b);
console.log('\nk per run [µs/cell-step]:', ks.map(k => (k * 1e6).toFixed(2)).join(', '));

out.forEach(o => {
  const m = o.model;
  const e = A.estimate(m).hours;
  console.log(`\n== ${o.f}`);
  console.log(`cells ${m.totalCells} (csv ${o.run && o.run.cells}), meshes ${m.meshes.length}, procs ${m.nProc}, maxLoad ${m.maxLoad}, balance ${(m.balance * 100).toFixed(0)}%, dxMin ${m.dxMin.toFixed(3)}, T ${m.simTime}`);
  console.log(`velocity u=${m.velocity.u} (plume ${m.velocity.plume}, forced ${m.velocity.forced}, fire ${m.velocity.largestFire} kW), steps ${A.estimate(m).steps}`);
  console.log(`real ${o.run ? o.run.wallH.toFixed(2) : '-'} h on ${o.run && o.run.server} | old estimate ${o.run && o.run.estH.toFixed(2)} h | new estimate ${e.toFixed(2)} h | price ${o.run && o.run.price} zł, cost ${o.run && o.run.costEur} €`);
  console.log(`slices ~${(m.sliceBytes / 1e9).toFixed(2)} GB`);
  o.issues.forEach(i => console.log(`  [${i.level}] ${i.msg}`));
  const adv = A.advise(m);
  adv.best.forEach(b => console.log(`  opt: ${b.procs} proc on ${b.server}: ${A.fmtHours(b.hours)}, ${b.costEur.toFixed(2)} €, ${b.pricePln.toFixed(0)} zł`));
  adv.tips.forEach(t => console.log('  tip: ' + t));
});
