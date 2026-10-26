#!/usr/bin/env node
// Analyze one .fds file and print JSON (used by the Django portal through a subprocess).
// usage: node cli.js <file.fds> [--multiplier 6] [--eur-pln 4.25]
const fs = require('fs');
const A = require('./fds-analyzer.js');

const args = process.argv.slice(2);
const file = args.find(a => !a.startsWith('--'));
if (!file) { console.error('usage: cli.js <file.fds>'); process.exit(2); }
const opt = (name, def) => { const i = args.indexOf(name); return i >= 0 ? Number(args[i + 1]) : def; };
// --k cpx42=3.4e-6 (repeatable): measured wall-seconds per cell-step for a server type
const kOverrides = {};
args.forEach((a, i) => { if (a === '--k' && args[i + 1] && args[i + 1].includes('=')) { const [srv, v] = args[i + 1].split('='); if (Number(v) > 0) kOverrides[srv] = Number(v); } });

let text;
try { text = fs.readFileSync(file, 'utf8'); } catch (e) { console.log(JSON.stringify({ ok: false, error: `cannot read file: ${e.message}` })); process.exit(0); }

// --assign N --out path: write a copy of the file prepared for N MPI processes, print a summary
if (args.includes('--assign')) {
  const k = opt('--assign', 1);
  const outPath = args[args.indexOf('--out') + 1];
  const result = A.assignProcesses(text, k);
  fs.writeFileSync(outPath, result);
  const m = A.analyze(result).model;
  console.log(JSON.stringify({ ok: true, procs: m.nProc, maxLoad: m.maxLoad, balance: m.balance }));
  process.exit(0);
}

try {
  const { model, issues } = A.analyze(text);
  const servers = A.DEFAULTS.servers.map(s => ({ ...s, k: kOverrides[s.name] || s.k }));
  const cfg = { ...A.DEFAULTS, servers, multiplier: opt('--multiplier', A.DEFAULTS.multiplier), eurPln: opt('--eur-pln', A.DEFAULTS.eurPln) };
  const estimate = A.estimate(model, cfg);
  const advice = A.advise(model, cfg);
  // strip functions / heavy fields
  const meshes = model.meshes.map(m => ({ id: m.id, ijk: m.ijk, xb: m.xb, dx: m.dx, dy: m.dy, dz: m.dz, cells: m.cells, mpi: m.mpi }));
  console.log(JSON.stringify({
    ok: true,
    model: { ...model, meshes, velocity: { ...model.velocity, integral: undefined } },
    issues,
    estimate,
    advice: { options: advice.options, best: advice.best, current: advice.current, fastest: advice.fastest, cheapest: advice.cheapest, tips: advice.tips },
  }));
} catch (e) {
  console.log(JSON.stringify({ ok: false, error: `analyzer failed: ${e.message}` }));
}
