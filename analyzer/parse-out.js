// Extract run statistics from FDS .out files: steps, time step size, wall time per step, pressure iterations.
const fs = require('fs');
const path = require('path');

function parseOut(text) {
  const r = {};
  const m = (re) => { const x = text.match(re); return x ? x[1] : null; };
  r.version = m(/Revision\s*:\s*(\S+)/);
  r.mpi = Number(m(/Number of MPI Processes:\s*(\d+)/));
  r.omp = Number(m(/Number of OpenMP Threads:\s*(\d+)/)) || null;
  r.cells = Number(m(/Total Number of Grid Cells\s+(\d+)/)) || [...text.matchAll(/\n\s+Number of Grid Cells\s+(\d+)/g)].reduce((s, x) => s + Number(x[1]), 0) / 2;
  r.tEnd = Number(m(/Simulation End Time \(s\)\s+([\d.]+)/));
  r.status = m(/STOP:\s*(.+)/) || 'brak STOP (przerwane?)';
  r.wallStepping = Number(m(/Time Stepping Wall Clock Time \(s\):\s*([\d.]+)/)) || null;
  r.wallTotal = Number(m(/Total Elapsed Wall Clock Time \(s\):\s*([\d.]+)/)) || null;
  // step blocks
  const steps = [];
  const re = /Time Step\s+(\d+)\s+(\w+ \d+, \d{4})\s+(\d\d:\d\d:\d\d)\s+Step Size:\s+([\d.E+-]+) s, Total Time:\s+([\d.]+) s(?:\s+Pressure Iterations:\s+(\d+))?/g;
  let x;
  while ((x = re.exec(text))) steps.push({ n: Number(x[1]), clock: new Date(`${x[2]} ${x[3]}`), dt: Number(x[4]), t: Number(x[5]), piter: x[6] ? Number(x[6]) : null });
  // compact diagnostics format (one line per step)
  const re2 = /Time Step:\s+(\d+), Simulation Time:\s+([\d.]+) s, Step Size:\s+([\d.E+-]+) s(?:, Pressure Iterations:\s+(\d+))?/g;
  while ((x = re2.exec(text))) steps.push({ n: Number(x[1]), clock: null, dt: Number(x[3]), t: Number(x[2]), piter: x[4] ? Number(x[4]) : null });
  r.samples = steps;
  const last = steps[steps.length - 1];
  if (last) {
    r.nSteps = last.n; r.tReached = last.t;
    r.dtMean = last.t / last.n;
    const pi = steps.filter(s => s.piter !== null).map(s => s.piter);
    r.pIterMean = pi.length ? pi.reduce((a, b) => a + b) / pi.length : null;
    const wall = r.wallStepping || (last.clock - steps[0].clock) / 1000;
    r.wallPerStep = wall / last.n;
  }
  return r;
}

if (require.main === module) {
  const dir = process.argv[2];
  fs.readdirSync(dir).filter(f => f.endsWith('.out')).sort().forEach(f => {
    const r = parseOut(fs.readFileSync(path.join(dir, f), 'utf8'));
    const fmt = (v, d = 2) => (v == null || Number.isNaN(v) ? '-' : Number(v).toFixed(d));
    console.log(`${f.replace('.out', '').padEnd(52)} ${r.version} mpi=${r.mpi} omp=${r.omp ?? '-'} cells=${r.cells} steps=${r.nSteps} t=${fmt(r.tReached, 0)}/${fmt(r.tEnd, 0)} dt=${fmt(r.dtMean * 1000, 2)}ms wall=${fmt((r.wallStepping || 0) / 3600)}h s/step=${fmt(r.wallPerStep, 3)} piter=${fmt(r.pIterMean, 1)} | ${r.status}`);
    // dt over sim time in 10 buckets
    const b = Array.from({ length: 10 }, () => []);
    r.samples.forEach(s => { const i = Math.min(9, Math.floor(s.t / (r.tEnd || r.tReached) * 10)); b[i].push(s); });
    console.log('   dt[ms] by 10% of sim:', b.map(g => g.length ? (g.reduce((a, s) => a + s.dt, 0) / g.length * 1000).toFixed(1) : '-').join(' '));
    console.log('   piter by 10% of sim: ', b.map(g => { const p = g.filter(s => s.piter != null); return p.length ? (p.reduce((a, s) => a + s.piter, 0) / p.length).toFixed(0) : '-'; }).join(' '));
  });
}
module.exports = { parseOut };
