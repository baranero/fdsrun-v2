// Build the single-file analyzer page with sample files and calibration data embedded.
const fs = require('fs');
const path = require('path');
const A = require('./fds-analyzer.js');
const dir = process.argv[2], outFile = process.argv[3];

const csv = fs.readFileSync(path.join(dir, 'symulacje-admin-2026-10-24.csv'), 'utf8').replace(/^﻿/, '');
const rows = csv.trim().split(/\r?\n/).slice(1).map(l => l.split(';').map(c => c.replace(/^"|"$/g, '')));
const parseDate = s => { const [d, t] = s.split(', '); const [D, M, Y] = d.split('.').map(Number); const [h, m, sec] = t.split(':').map(Number); return new Date(Y, M - 1, D, h, m, sec); };

const samples = {}, calib = [];
fs.readdirSync(dir).filter(f => f.endsWith('.fds')).sort().forEach(f => {
  const text = fs.readFileSync(path.join(dir, f), 'utf8');
  samples[f] = text;
  const r = rows.find(x => x[3] === f);
  if (!r) return;
  const m = A.analyze(text).model;
  calib.push({ file: f.replace(/\.fds$/, ''), server: r[5], real: (parseDate(r[12]) - parseDate(r[11])) / 3600e3, old: Number(r[7]), est: A.estimate(m).hours });
});

const safe = o => JSON.stringify(o).replace(/<\//g, '<\\/');
let html = fs.readFileSync(path.join(__dirname, 'page.template.html'), 'utf8');
html = html.replace('/*__ANALYZER__*/', () => fs.readFileSync(path.join(__dirname, 'fds-analyzer.js'), 'utf8').replace(/<\//g, '<\\/'))
  .replace('/*__SAMPLES__*/', () => safe(samples))
  .replace('/*__CALIB__*/', () => safe(calib));
fs.writeFileSync(outFile, html);
console.log('wrote', outFile, (html.length / 1024).toFixed(0), 'KB', calib.length, 'calibration rows');
