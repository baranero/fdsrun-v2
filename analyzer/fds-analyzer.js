/*
 * FDS analyzer — parses an FDS input file, checks it for common problems,
 * advises on MPI process count and estimates run time and cost.
 * Works in Node (module.exports) and in the browser (window.FDSAnalyzer).
 */
(function (root) {
  'use strict';

  // ---------- 1. Parsing ----------

  // Split file text into namelist groups: { name, body, line }
  function splitNamelists(text) {
    const out = [];
    let i = 0, line = 1;
    const n = text.length;
    while (i < n) {
      const c = text[i];
      if (c === '\n') { line++; i++; continue; }
      if (c === '&' && /[A-Za-z]/.test(text[i + 1] || '')) {
        // read name
        let j = i + 1;
        while (j < n && /[A-Za-z_]/.test(text[j])) j++;
        const name = text.slice(i + 1, j).toUpperCase();
        const startLine = line;
        // read body until '/' outside quotes
        let k = j, q = null;
        while (k < n) {
          const ch = text[k];
          if (ch === '\n') line++;
          if (q) { if (ch === q) q = null; }
          else if (ch === "'" || ch === '"') q = ch;
          else if (ch === '/') break;
          k++;
        }
        out.push({ name, body: text.slice(j, k), line: startLine, closed: k < n, start: i, end: Math.min(n, k + 1) });
        i = k + 1;
        continue;
      }
      i++;
    }
    return out;
  }

  // Parse "KEY=val, KEY2=v1,v2" into { KEY: [values] } (keys upper-cased, indices kept)
  function parseParams(body) {
    // mask quoted strings so the key regex does not match inside them
    const masked = body.replace(/'[^']*'|"[^"]*"/g, m => 'Q'.repeat(m.length));
    const re = /([A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?)\s*=/g;
    const keys = [];
    let m;
    while ((m = re.exec(masked))) keys.push({ key: m[1].toUpperCase(), start: m.index, valStart: re.lastIndex });
    const params = {};
    keys.forEach((k, idx) => {
      const end = idx + 1 < keys.length ? keys[idx + 1].start : body.length;
      const raw = body.slice(k.valStart, end);
      params[k.key] = splitValues(raw);
    });
    return params;
  }

  function splitValues(raw) {
    const vals = [];
    let cur = '', q = null;
    for (const ch of raw) {
      if (q) { cur += ch; if (ch === q) q = null; continue; }
      if (ch === "'" || ch === '"') { q = ch; cur += ch; continue; }
      if (ch === ',') { vals.push(cur); cur = ''; continue; }
      cur += ch;
    }
    vals.push(cur);
    return vals.map(v => v.trim()).filter(v => v !== '').map(v => {
      if (/^['"].*['"]$/s.test(v)) return v.slice(1, -1);
      if (/^\.?(TRUE|T)\.?$/i.test(v)) return true;
      if (/^\.?(FALSE|F)\.?$/i.test(v)) return false;
      const num = Number(v.replace(/[dD]/, 'E'));
      return Number.isFinite(num) ? num : v;
    });
  }

  function parse(text) {
    const groups = splitNamelists(text).map(g => ({ ...g, p: parseParams(g.body) }));
    const by = name => groups.filter(g => g.name === name);
    return { groups, by };
  }

  // ---------- helpers ----------
  const first = (p, k, d) => (p[k] && p[k].length ? p[k][0] : d);
  const num = (p, k, d) => { const v = first(p, k, d); return typeof v === 'number' ? v : d; };
  const str = (p, k, d) => { const v = first(p, k, d); return typeof v === 'string' ? v : d; };
  const xb = p => (p.XB && p.XB.length >= 6 && p.XB.slice(0, 6).every(v => typeof v === 'number') ? p.XB.slice(0, 6) : null);
  const EPS = 1e-6;
  const round = (v, d = 3) => Math.round(v * 10 ** d) / 10 ** d;

  function inBox(pt, b, tol = 1e-6) {
    return pt[0] >= b[0] - tol && pt[0] <= b[1] + tol &&
           pt[1] >= b[2] - tol && pt[1] <= b[3] + tol &&
           pt[2] >= b[4] - tol && pt[2] <= b[5] + tol;
  }
  function boxesOverlap(a, b, tol = 1e-6) {
    return a[0] < b[1] - tol && a[1] > b[0] + tol &&
           a[2] < b[3] - tol && a[3] > b[2] + tol &&
           a[4] < b[5] - tol && a[5] > b[4] + tol;
  }
  function boxesTouchOrOverlap(a, b, tol = 1e-6) {
    return a[0] <= b[1] + tol && a[1] >= b[0] - tol &&
           a[2] <= b[3] + tol && a[3] >= b[2] - tol &&
           a[4] <= b[5] + tol && a[5] >= b[4] - tol;
  }

  // ---------- 2. Analysis ----------

  const BUILTIN_SURF = new Set(['INERT', 'OPEN', 'MIRROR', 'PERIODIC', 'HVAC', 'PERIODIC FLOW ONLY', 'MASSLESS TRACER', 'DEFAULT']);

  function analyze(text, opts = {}) {
    const issues = [];
    const add = (level, code, msg, extra) => issues.push({ level, code, msg, ...(extra || {}) });

    const { groups, by } = parse(text);
    const unclosed = groups.filter(g => !g.closed);
    if (unclosed.length) add('error', 'UNCLOSED', `Niezamknięta grupa &${unclosed[0].name} (brak znaku "/") w linii ${unclosed[0].line}.`);

    const head = by('HEAD')[0];
    const chid = head ? str(head.p, 'CHID', '') : '';
    const title = head ? str(head.p, 'TITLE', '') : '';
    if (!head || !chid) add('error', 'NO_CHID', 'Brak &HEAD z CHID — FDS nie wie, jak nazwać pliki wynikowe.');
    else if (/[\s.]/.test(chid)) add('warn', 'CHID_CHARS', `CHID "${chid}" zawiera spacje lub kropki — część narzędzi źle to obsługuje.`);

    if (!by('TAIL').length) add('error', 'NO_TAIL', 'Brak &TAIL / na końcu pliku — FDS nie uruchomi obliczeń.');

    const time = by('TIME')[0];
    const tBegin = time ? num(time.p, 'T_BEGIN', 0) : 0;
    const tEnd = time ? num(time.p, 'T_END', 1) : 1;
    if (!time || !time.p.T_END) add('warn', 'NO_T_END', 'Brak T_END w &TIME — FDS przyjmie 1 sekundę symulacji.');
    const simTime = Math.max(0, tEnd - tBegin);

    const misc = by('MISC')[0];
    const tmpa = misc ? num(misc.p, 'TMPA', 20) : 20;

    const dump = by('DUMP')[0];
    const dtRestart = dump ? num(dump.p, 'DT_RESTART', null) : null;
    const nframes = dump ? num(dump.p, 'NFRAMES', 1000) : 1000;
    const dtSlcf = dump ? num(dump.p, 'DT_SLCF', simTime / nframes) : simTime / nframes;

    // ----- meshes -----
    const meshes = [];
    by('MESH').forEach((g, idx) => {
      const b = xb(g.p);
      const ijk = g.p.IJK;
      if (!b || !ijk || ijk.length < 3) {
        add('error', 'MESH_BAD', `&MESH w linii ${g.line} nie ma poprawnych IJK lub XB.`);
        return;
      }
      const mult = by('MULT').find(m => str(m.p, 'ID', null) === str(g.p, 'MULT_ID', '__none__'));
      if (mult) add('warn', 'MULT_MESH', `Siatka w linii ${g.line} używa MULT_ID — analizator liczy ją jako jedną kopię.`);
      const [I, J, K] = ijk.map(Number);
      const dx = (b[1] - b[0]) / I, dy = (b[3] - b[2]) / J, dz = (b[5] - b[4]) / K;
      meshes.push({
        id: str(g.p, 'ID', `MESH_${idx + 1}`), line: g.line, xb: b, ijk: [I, J, K],
        dx, dy, dz, cells: I * J * K,
        mpi: g.p.MPI_PROCESS !== undefined ? num(g.p, 'MPI_PROCESS', null) : null,
      });
    });
    if (!meshes.length) add('error', 'NO_MESH', 'Brak &MESH — nie ma siatki obliczeniowej.');

    const totalCells = meshes.reduce((s, m) => s + m.cells, 0);
    const dxMin = meshes.length ? Math.min(...meshes.map(m => Math.min(m.dx, m.dy, m.dz))) : 0;

    meshes.forEach(m => {
      const ar = Math.max(m.dx, m.dy, m.dz) / Math.min(m.dx, m.dy, m.dz);
      if (ar > 2.01) add('warn', 'ASPECT', `Siatka "${m.id}": komórki mocno niesześcienne (${round(m.dx)}×${round(m.dy)}×${round(m.dz)} m, proporcja ${round(ar, 1)}:1). Zalecane do 2:1.`);
    });

    // overlaps and resolution jumps between neighbouring meshes
    for (let a = 0; a < meshes.length; a++) {
      for (let b = a + 1; b < meshes.length; b++) {
        const A = meshes[a], B = meshes[b];
        if (boxesOverlap(A.xb, B.xb)) {
          add('warn', 'MESH_OVERLAP', `Siatki "${A.id}" i "${B.id}" nachodzą na siebie — FDS liczy wtedy ten obszar podwójnie lub niepoprawnie wymienia dane.`);
        } else if (boxesTouchOrOverlap(A.xb, B.xb)) {
          const r = Math.max(A.dx, B.dx) / Math.min(A.dx, B.dx);
          if (Math.abs(r - Math.round(r)) > 0.02) add('warn', 'MESH_RATIO', `Siatki "${A.id}" i "${B.id}" stykają się, a stosunek rozmiarów komórek (${round(r, 2)}) nie jest liczbą całkowitą.`);
          else if (r > 2.01) add('info', 'MESH_JUMP', `Siatki "${A.id}" i "${B.id}": skok rozdzielczości ${Math.round(r)}:1 — zalecane najwyżej 2:1.`);
        }
      }
    }

    // ----- MPI processes -----
    const hasMpi = meshes.some(m => m.mpi !== null);
    let procLoads;
    if (hasMpi) {
      const nProc = Math.max(...meshes.map(m => (m.mpi === null ? 0 : m.mpi))) + 1;
      procLoads = Array(nProc).fill(0);
      meshes.forEach((m, i) => { procLoads[m.mpi === null ? i : m.mpi] += m.cells; });
      const empty = procLoads.map((v, i) => (v === 0 ? i : null)).filter(v => v !== null);
      if (empty.length) add('error', 'MPI_GAP', `MPI_PROCESS pomija numery ${empty.join(', ')} — FDS wymaga kolejnych numerów od 0.`);
      // FDS requires meshes to be listed in non-decreasing MPI_PROCESS order
      for (let i = 1; i < meshes.length; i++) {
        if ((meshes[i].mpi ?? 0) < (meshes[i - 1].mpi ?? 0)) { add('error', 'MPI_ORDER', `Siatka "${meshes[i].id}" ma mniejszy MPI_PROCESS niż poprzednia — FDS wymaga rosnącej kolejności.`); break; }
      }
    } else {
      procLoads = meshes.map(m => m.cells);
    }
    const nProc = procLoads.length;
    const maxLoad = procLoads.length ? Math.max(...procLoads) : 0;
    const meanLoad = procLoads.length ? totalCells / procLoads.length : 0;
    const balance = maxLoad ? meanLoad / maxLoad : 1;
    if (nProc > 1 && balance < 0.75) add('warn', 'IMBALANCE', `Nierówny podział pracy: najwolniejszy proces ma ${fmtInt(maxLoad)} komórek przy średniej ${fmtInt(meanLoad)} (wykorzystanie ${Math.round(balance * 100)}%). Reszta rdzeni czeka na niego.`);

    // ----- reference sets -----
    const ids = name => new Set(by(name).map(g => str(g.p, 'ID', null)).filter(Boolean));
    const surfIds = ids('SURF'), rampIds = ids('RAMP'), devcIds = ids('DEVC'), ctrlIds = ids('CTRL'), matlIds = ids('MATL'), specIds = ids('SPEC');

    const refCheck = (setName, set, val, where, builtin) => {
      if (typeof val !== 'string' || !val) return;
      if (builtin && builtin.has(val.toUpperCase())) return;
      if (!set.has(val)) add('error', 'BAD_REF', `${where} odwołuje się do ${setName} "${val}", którego nie zdefiniowano.`);
    };
    const seenRef = new Set();
    const refOnce = (setName, set, val, where, builtin) => {
      const key = setName + '|' + val;
      if (seenRef.has(key)) return;
      seenRef.add(key);
      refCheck(setName, set, val, where, builtin);
    };

    by('OBST').concat(by('VENT')).forEach(g => {
      ['SURF_ID', 'SURF_ID6'].forEach(k => (g.p[k] || []).forEach(v => refOnce('SURF', surfIds, v, `&${g.name} (linia ${g.line})`, BUILTIN_SURF)));
      (g.p.SURF_IDS || []).forEach(v => refOnce('SURF', surfIds, v, `&${g.name} (linia ${g.line})`, BUILTIN_SURF));
      refOnce('DEVC', devcIds, str(g.p, 'DEVC_ID', ''), `&${g.name} (linia ${g.line})`);
      refOnce('CTRL', ctrlIds, str(g.p, 'CTRL_ID', ''), `&${g.name} (linia ${g.line})`);
    });
    by('SURF').forEach(g => {
      Object.keys(g.p).filter(k => k.startsWith('RAMP_')).forEach(k => refOnce('RAMP', rampIds, str(g.p, k, ''), `&SURF "${str(g.p, 'ID', '')}"`));
      Object.keys(g.p).filter(k => k.startsWith('MATL_ID')).forEach(k => g.p[k].forEach(v => refOnce('MATL', matlIds, v, `&SURF "${str(g.p, 'ID', '')}"`)));
    });
    by('MATL').forEach(g => Object.keys(g.p).filter(k => /_RAMP$/.test(k)).forEach(k => refOnce('RAMP', rampIds, str(g.p, k, ''), `&MATL "${str(g.p, 'ID', '')}"`)));
    by('HVAC').forEach(g => { if (str(g.p, 'DEVC_ID', '')) refOnce('DEVC', devcIds, str(g.p, 'DEVC_ID', ''), `&HVAC "${str(g.p, 'ID', '')}"`); });

    // ----- devices inside the domain -----
    let devcOutside = [];
    by('DEVC').forEach(g => {
      const xyz = g.p.XYZ && g.p.XYZ.length >= 3 ? g.p.XYZ.slice(0, 3) : null;
      const pts = xyz ? [xyz] : (xb(g.p) ? [[xb(g.p)[0], xb(g.p)[2], xb(g.p)[4]], [xb(g.p)[1], xb(g.p)[3], xb(g.p)[5]]] : []);
      const q = str(g.p, 'QUANTITY', '');
      if (q === 'TIME' || q === 'CONTROL') return;
      if (pts.some(pt => !meshes.some(m => inBox(pt, m.xb)))) devcOutside.push(str(g.p, 'ID', `linia ${g.line}`));
    });
    if (devcOutside.length) add('error', 'DEVC_OUT', `${devcOutside.length} urządzeń pomiarowych leży poza siatkami: ${listShort(devcOutside)}. FDS przerwie obliczenia lub je pominie.`);

    // ----- obstructions -----
    const obst = by('OBST');
    const sig = new Map();
    let dup = 0, thin = 0, outside = 0;
    obst.forEach(g => {
      const b = xb(g.p);
      if (!b) return;
      const key = b.map(v => round(v, 4)).join(',') + '|' + (g.p.SURF_ID || g.p.SURF_IDS || []).join(',');
      if (sig.has(key)) dup++; else sig.set(key, 1);
      if (Math.abs(b[1] - b[0]) < EPS || Math.abs(b[3] - b[2]) < EPS || Math.abs(b[5] - b[4]) < EPS) thin++;
      if (!meshes.some(m => boxesTouchOrOverlap(b, m.xb))) outside++;
    });
    if (dup) add('info', 'OBST_DUP', `${dup} przeszkód (&OBST) to dokładne duplikaty innych — można je usunąć, model się nie zmieni.`);
    if (thin) add('info', 'OBST_THIN', `${thin} przeszkód ma zerową grubość — FDS przyciągnie je do najbliższej ściany komórki.`);
    if (outside) add('warn', 'OBST_OUT', `${outside} przeszkód leży całkowicie poza siatkami — nie biorą udziału w obliczeniach.`);

    // ----- initial temperatures of walls -----
    const initTemps = by('INIT').map(g => num(g.p, 'TEMPERATURE', null)).filter(v => v !== null);
    const usedSurf = new Set();
    obst.concat(by('VENT')).forEach(g => ['SURF_ID', 'SURF_IDS', 'SURF_ID6'].forEach(k => (g.p[k] || []).forEach(v => usedSurf.add(v))));
    const wallSurfs = by('SURF').filter(g => Object.keys(g.p).some(k => k.startsWith('MATL_ID')) && usedSurf.has(str(g.p, 'ID', '')));
    const noInner = wallSurfs.filter(g => g.p.TMP_INNER === undefined).map(g => str(g.p, 'ID', ''));
    if (noInner.length && initTemps.length && initTemps.some(t => Math.abs(t - tmpa) >= 2)) {
      add('warn', 'TMP_INNER_DEFAULT', `${noInner.length} przegród nie ma TMP_INNER (${listShort(noInner)}) — wystartują w temperaturze otoczenia TMPA = ${tmpa} °C, choć powietrze wewnątrz (&INIT) ma ${uniq(initTemps).join(', ')} °C. Sprawdź, czy to zamierzone.`);
    }
    const refTemps = [tmpa, ...initTemps];
    wallSurfs.forEach(g => {
      const t = num(g.p, 'TMP_INNER', null);
      if (t === null) return;
      const d = Math.min(...refTemps.map(r => Math.abs(r - t)));
      if (d >= 10) add('warn', 'TMP_OUTLIER', `Przegroda "${str(g.p, 'ID', '')}" ma TMP_INNER = ${t} °C, a otoczenie ${tmpa} °C i powietrze ${uniq(initTemps).join(', ') || '—'} °C. Sprawdź, czy wartość pasuje do tego wariantu.`);
    });

    // ----- restart -----
    if (!dtRestart) add('info', 'NO_RESTART', 'Brak DT_RESTART w &DUMP. Dodanie np. DT_RESTART=300 pozwala wznowić obliczenia po awarii serwera zamiast liczyć od zera.');

    // ----- characteristic velocity (drives the time step) -----
    const vel = flowModel(by, meshes, simTime, tmpa);

    // ----- slice output volume -----
    const sliceBytes = estimateSliceBytes(by('SLCF'), meshes, simTime, dtSlcf);

    const model = {
      chid, title, tEnd, simTime, tmpa, dtRestart,
      meshes, totalCells, dxMin, nProc, procLoads, maxLoad, balance, hasMpi,
      counts: { obst: obst.length, vent: by('VENT').length, devc: by('DEVC').length, slcf: by('SLCF').length, hvac: by('HVAC').length },
      velocity: vel, sliceBytes,
    };
    return { model, issues };
  }

  // Time-dependent characteristic velocity u(t) [m/s] that sets the FDS time
  // step (dt ≈ 0.9·Δx/u). Calibrated on Sep 2026 .out files (FDS 6.10.1):
  //   stairwells — fire plume, stack effect, residual floor of 2.2 m/s;
  //   car park   — mechanical supply/exhaust raised u to ~4.5× the vent velocity.
  const FLOW = { floor: 2.2, stackCd: 0.8, plumeC: 1.9, ventFactor: 4.5, hvacFactor: 1.9, samples: 200 };

  function flowModel(by, meshes, simTime, tmpa) {
    const surfs = new Map(by('SURF').map(g => [str(g.p, 'ID', ''), g]));
    const ramps = new Map();
    by('RAMP').forEach(g => {
      const id = str(g.p, 'ID', '');
      if (!ramps.has(id)) ramps.set(id, []);
      ramps.get(id).push({ t: num(g.p, 'T', 0), f: num(g.p, 'F', 0) });
    });
    ramps.forEach(r => r.sort((a, b) => a.t - b.t));
    const rampAt = (id, t) => {
      const r = ramps.get(id);
      if (!r || !r.length) return 1;
      if (t <= r[0].t) return r[0].f;
      for (let i = 1; i < r.length; i++) if (t <= r[i].t) { const a = r[i - 1], b = r[i]; return a.f + (b.f - a.f) * (t - a.t) / ((b.t - a.t) || 1); }
      return r[r.length - 1].f;
    };
    const devcs = new Map(by('DEVC').map(g => [str(g.p, 'ID', ''), g]));
    // returns a function t -> active? for an object controlled by DEVC_ID / CTRL_ID
    const activeFn = p => {
      const d = devcs.get(str(p, 'DEVC_ID', ''));
      if (!d) return () => true;
      if (str(d.p, 'QUANTITY', '') !== 'TIME') return () => true; // detector-driven: assume on (conservative)
      const sp = num(d.p, 'SETPOINT', 0), init = first(d.p, 'INITIAL_STATE', false) === true;
      return t => (init ? t < sp : t >= sp);
    };
    const faceArea = b => { const e = [Math.abs(b[1] - b[0]), Math.abs(b[3] - b[2]), Math.abs(b[5] - b[4])].sort((a, c) => c - a); return e[0] * e[1]; };
    const meshAt = pt => meshes.find(m => inBox(pt, m.xb));
    // area of a vent as FDS rasterises it (circular vents: count cell faces inside RADIUS)
    const ventArea = g => {
      const b = xb(g.p);
      if (!b) return 0;
      const r = num(g.p, 'RADIUS', 0);
      const c = g.p.XYZ && g.p.XYZ.length >= 3 ? g.p.XYZ : [(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2];
      const m = meshAt(c);
      if (!r || !m) return faceArea(b);
      const axis = [0, 1, 2].find(k => Math.abs(b[2 * k + 1] - b[2 * k]) < 1e-9);
      const ax = [0, 1, 2].filter(k => k !== axis);
      const d = [m.dx, m.dy, m.dz];
      let n = 0;
      for (let i = 0; i < m.ijk[ax[0]]; i++) {
        const u = m.xb[2 * ax[0]] + (i + 0.5) * d[ax[0]];
        if (Math.abs(u - c[ax[0]]) > r) continue;
        for (let j = 0; j < m.ijk[ax[1]]; j++) {
          const v = m.xb[2 * ax[1]] + (j + 0.5) * d[ax[1]];
          if ((u - c[ax[0]]) ** 2 + (v - c[ax[1]]) ** 2 <= r * r) n++;
        }
      }
      return Math.max(1, n) * d[ax[0]] * d[ax[1]];
    };

    // fire sources
    const fires = [];
    const addFire = (surfId, a, label) => {
      const s = surfs.get(surfId);
      const q = s ? num(s.p, 'HRRPUA', 0) : 0;
      if (q > 0) fires.push({ label, q: q * a, ramp: str(s.p, 'RAMP_Q', '') });
    };
    by('VENT').forEach(g => { const b = xb(g.p); if (b) addFire(str(g.p, 'SURF_ID', ''), faceArea(b), str(g.p, 'ID', 'VENT')); });
    by('OBST').forEach(g => { const b = xb(g.p); if (b) addFire((g.p.SURF_IDS || g.p.SURF_ID || [''])[0], Math.abs(b[1] - b[0]) * Math.abs(b[3] - b[2]), str(g.p, 'ID', 'OBST')); });
    const qAt = t => fires.reduce((m, f) => Math.max(m, f.q * rampAt(f.ramp, t)), 0);
    const largest = fires.reduce((m, f) => Math.max(m, f.q * (ramps.has(f.ramp) ? Math.max(...ramps.get(f.ramp).map(x => x.f)) : 1)), 0);

    // forced flows: vents with VEL / VOLUME_FLOW, and HVAC fans
    const forced = [];
    by('VENT').forEach(g => {
      const s = surfs.get(str(g.p, 'SURF_ID', ''));
      if (!s) return;
      const a = ventArea(g);
      const v = Math.max(Math.abs(num(s.p, 'VEL', 0)), a > 0 ? Math.abs(num(s.p, 'VOLUME_FLOW', 0)) / a : 0);
      if (v > 0) forced.push({ label: str(g.p, 'ID', 'VENT'), v, u: v * FLOW.ventFactor, on: activeFn(g.p) });
    });
    const hv = by('HVAC');
    const hvId = new Map(hv.map(g => [str(g.p, 'ID', ''), g]));
    const ventById = new Map(by('VENT').map(g => [str(g.p, 'ID', ''), g]));
    hv.filter(g => /DUCT/i.test(str(g.p, 'TYPE_ID', ''))).forEach(duct => {
      const fan = hvId.get(str(duct.p, 'FAN_ID', ''));
      const vf = fan ? Math.abs(num(fan.p, 'VOLUME_FLOW', 0)) : Math.abs(num(duct.p, 'VOLUME_FLOW', 0));
      if (!vf) return;
      (duct.p.NODE_ID || []).forEach(nid => {
        const node = hvId.get(nid);
        const vent = node && ventById.get(str(node.p, 'VENT_ID', ''));
        if (!vent) return;
        const v = vf / (ventArea(vent) || 1);
        forced.push({ label: str(duct.p, 'ID', 'HVAC'), v, u: v * FLOW.hvacFactor, on: activeFn(duct.p) });
      });
    });

    // stack effect from &INIT regions warmer or colder than outside
    let uStack = 0;
    by('INIT').forEach(g => {
      const t = num(g.p, 'TEMPERATURE', null), b = xb(g.p);
      if (t === null || !b) return;
      const h = Math.abs(b[5] - b[4]), dT = Math.abs(t - tmpa);
      uStack = Math.max(uStack, FLOW.stackCd * Math.sqrt(2 * 9.81 * h * dT / (tmpa + 273.15)));
    });

    const uAt = t => {
      const q = qAt(t);
      const parts = {
        floor: FLOW.floor,
        stack: uStack,
        fire: q > 0 ? FLOW.plumeC * Math.pow(q, 0.2) : 0,
        forced: forced.reduce((m, x) => (x.on(t) ? Math.max(m, x.u) : m), 0),
      };
      const key = Object.keys(parts).reduce((a, b) => (parts[b] > parts[a] ? b : a));
      return { u: parts[key], key };
    };
    const n = FLOW.samples, T = Math.max(simTime, 1e-9);
    let integral = 0, uMax = 0;
    const share = { floor: 0, stack: 0, fire: 0, forced: 0 };
    const cumulative = [];
    for (let i = 0; i < n; i++) { const { u, key } = uAt((i + 0.5) * T / n); integral += u * T / n; share[key] += u * T / n; uMax = Math.max(uMax, u); cumulative.push(integral); }
    // cumulative share of the predicted step count at 20 evenly spaced simulation times:
    // lets the portal turn "steps done so far" into "steps left" while the job runs
    const profile = Array.from({ length: 20 }, (_, j) => round(cumulative[Math.min(n - 1, Math.floor((j + 1) * n / 20) - 1)] / integral, 4));
    const driver = Object.keys(share).reduce((a, b) => (share[b] > share[a] ? b : a));
    const topForced = forced.reduce((a, b) => (a && a.v >= b.v ? a : b), null);
    return {
      u: round(integral / T, 2),          // time-averaged
      uMax: round(uMax, 2),
      plume: round(largest > 0 ? FLOW.plumeC * Math.pow(largest, 0.2) : 0, 2),
      stack: round(uStack, 2),
      forced: topForced ? round(topForced.v, 2) : 0,
      forcedLabel: topForced ? topForced.label : null,
      hasForced: forced.length > 0,
      largestFire: Math.round(largest),
      driver,                             // what limits the time step most of the run
      integral,                           // ∫u dt [m]
      profile,                            // cumulative fraction of steps at t = T/20, 2T/20, …, T
    };
  }

  // Slice file size: cells in each slice plane × frames × 4 bytes (×3 for vectors)
  function estimateSliceBytes(slcfs, meshes, simTime, dtSlcf) {
    const frames = dtSlcf > 0 ? Math.ceil(simTime / dtSlcf) + 1 : 1000;
    let bytes = 0;
    slcfs.forEach(g => {
      const comps = g.p.VECTOR && g.p.VECTOR[0] === true ? 4 : 1;
      const axes = ['PBX', 'PBY', 'PBZ'];
      meshes.forEach(m => {
        let cells = 0;
        axes.forEach((ax, ai) => {
          if (g.p[ax] === undefined) return;
          const v = num(g.p, ax, null);
          if (v === null || v < m.xb[ai * 2] - 1e-9 || v > m.xb[ai * 2 + 1] + 1e-9) return;
          const others = [0, 1, 2].filter(k => k !== ai).map(k => m.ijk[k] + 1);
          cells += others[0] * others[1];
        });
        const b = xb(g.p);
        if (b && !axes.some(a => g.p[a] !== undefined)) {
          const ov = [0, 1, 2].map(k => Math.max(0, Math.min(b[2 * k + 1], m.xb[2 * k + 1]) - Math.max(b[2 * k], m.xb[2 * k])));
          const d = [m.dx, m.dy, m.dz];
          const n = [0, 1, 2].map(k => (Math.abs(b[2 * k + 1] - b[2 * k]) < 1e-9 ? 1 : Math.round(ov[k] / d[k]) + 1));
          if (ov.filter((v, k) => v > 0 || Math.abs(b[2 * k + 1] - b[2 * k]) < 1e-9).length === 3) cells += n[0] * n[1] * n[2];
        }
        bytes += cells * comps * 4 * frames;
      });
    });
    return bytes;
  }

  // ---------- 3. Advice and estimate ----------

  // Default calibration (see calibrate.js): seconds of wall time per
  // (cell of the busiest process × time step), and server price list.
  const DEFAULTS = {
    cfl: 0.9,
    // k = wall seconds per (cell on the busiest process × time step), from .out files
    // (FDS 6.10.1, one MPI process per vCPU). cpx32 not measured yet: assumed as cpx42.
    servers: [                 // effective rates from the old portal's Hetzner costs
      { name: 'cpx32', vcpu: 4, eurPerHour: 0.055, k: 3.4e-6 },
      { name: 'cpx42', vcpu: 8, eurPerHour: 0.111, k: 3.4e-6 },
      { name: 'cpx62', vcpu: 16, eurPerHour: 0.208, k: 5.3e-6 },
    ],
    eurPln: 4.25,
    multiplier: 2.0,
  };

  // Longest-processing-time partition of meshes into k processes.
  // Returns the heaviest bin; partitionAssign returns the bin index of every mesh.
  function partitionAssign(meshCells, k) {
    const bins = Array(k).fill(0);
    const assign = Array(meshCells.length).fill(0);
    meshCells.map((c, i) => [c, i]).sort((a, b) => b[0] - a[0]).forEach(([c, idx]) => {
      let i = 0;
      for (let j = 1; j < k; j++) if (bins[j] < bins[i]) i = j;
      bins[i] += c;
      assign[idx] = i;
    });
    return { assign, bins };
  }
  function partition(meshCells, k) {
    return Math.max(...partitionAssign(meshCells, k).bins);
  }

  // Rewrite the file so that its meshes run on exactly k MPI processes:
  // every &MESH gets MPI_PROCESS=n, meshes are grouped by process (FDS requires
  // non-decreasing process numbers in mesh order). Nothing else in the file changes.
  function assignProcesses(text, k) {
    const groups = splitNamelists(text).filter(g => g.name === 'MESH');
    if (!groups.length) return text;
    const cells = groups.map(g => { const p = parseParams(g.body); const ijk = p.IJK || [1, 1, 1]; return Number(ijk[0]) * Number(ijk[1]) * Number(ijk[2]); });
    k = Math.max(1, Math.min(k, groups.length));
    // the author already laid out exactly k processes: respect that layout
    const own = groups.map(g => { const p = parseParams(g.body); return p.MPI_PROCESS !== undefined ? Number(p.MPI_PROCESS[0]) : null; });
    if (own.every(v => v !== null) && new Set(own).size === k && Math.max(...own) === k - 1) return text;
    const { assign } = partitionAssign(cells, k);
    // renumber bins in order of first appearance so the file reads naturally
    const order = [...new Set(assign.slice().sort((a, b) => a - b))];
    const renum = new Map(order.map((b, i) => [b, i]));
    const items = groups.map((g, i) => ({ g, proc: renum.get(assign[i]), i }));
    items.sort((a, b) => a.proc - b.proc || a.i - b.i);
    const rewritten = items.map(({ g, proc }) => {
      let body = g.body.replace(/,?\s*MPI_PROCESS\s*=\s*\d+/i, '');
      body = body.replace(/\s*$/, '') + `, MPI_PROCESS=${proc}`;
      return '&MESH' + body + '/';
    });
    // splice: drop every original mesh, put the new block where the first one was
    let out = '', pos = 0;
    groups.forEach((g, i) => {
      out += text.slice(pos, g.start);
      if (i === 0) out += rewritten.join('\n');
      pos = g.end;
      // swallow the line break that followed a removed mesh so the file stays tidy
      if (i > 0) { if (text[pos] === '\r') pos++; if (text[pos] === '\n') pos++; }
    });
    out += text.slice(pos);
    return out;
  }

  function steps(model, cfg) {
    return model.velocity.integral / (cfg.cfl * model.dxMin);
  }

  // How much to trust a file-only estimate. Calibration: stairwells within
  // -30%/+60%; car-park models with jet fans/HVAC ran 2-10x longer than estimated.
  // How much to trust a file-only estimate. Sep 2026 check: stairwells within
  // ±15% of real time; the one car-park geometry within ±10% after calibration,
  // but forced ventilation is calibrated on a single geometry so its range stays wide.
  function confidence(model) {
    if (model.velocity.hasForced) return { level: 'medium', low: 0.6, high: 1.8, note: 'Model z wentylacją mechaniczną. Szacunek opiera się na jednym skalibrowanym garażu, więc rzeczywisty czas może różnić się nawet o połowę. Portal przelicza czas na bieżąco w trakcie obliczeń.' };
    return { level: 'ok', low: 0.8, high: 1.25, note: 'Na Twoich klatkach schodowych szacunek trafiał w rzeczywisty czas z dokładnością ±15%.' };
  }

  const serverFor = (cfg, procs) => cfg.servers.find(s => s.vcpu >= procs) || cfg.servers[cfg.servers.length - 1];

  function estimate(model, cfg = DEFAULTS, maxLoad = model.maxLoad, server = serverFor(cfg, model.nProc)) {
    const s = steps(model, cfg);
    const sec = server.k * maxLoad * s;
    return { hours: sec / 3600, steps: Math.round(s), server: server.name, confidence: confidence(model) };
  }

  function advise(model, cfg = DEFAULTS) {
    const cells = model.meshes.map(m => m.cells);
    const options = [];
    const maxK = Math.min(cells.length, Math.max(...cfg.servers.map(s => s.vcpu)));
    for (let k = 1; k <= maxK; k++) {
      const load = k === model.nProc && model.hasMpi ? model.maxLoad : partition(cells, k);
      const server = cfg.servers.find(s => s.vcpu >= k);
      if (!server) continue;
      const { hours } = estimate(model, cfg, load, server);
      const cost = hours * server.eurPerHour;
      options.push({ procs: k, load, server: server.name, vcpu: server.vcpu, hours, costEur: cost, pricePln: cost * cfg.eurPln * cfg.multiplier });
    }
    // keep, for each server, the smallest process count reaching its best time;
    // drop servers that are not meaningfully faster than a cheaper one
    const best = [];
    cfg.servers.forEach(sv => {
      const opts = options.filter(o => o.server === sv.name);
      if (!opts.length) return;
      const fastest = Math.min(...opts.map(o => o.hours));
      const pick = opts.find(o => o.hours <= fastest * 1.02);
      const prev = best[best.length - 1];
      if (!prev || pick.hours < prev.hours * 0.95) best.push(pick);
    });
    const current = options.find(o => o.procs === model.nProc) || null;
    const fastest = best.reduce((a, b) => (a && a.hours <= b.hours ? a : b), null);
    const cheapest = best.reduce((a, b) => (a && a.costEur <= b.costEur ? a : b), null);
    const tips = [];
    // processes that add no speed
    if (current) {
      const same = options.filter(o => o.procs < model.nProc && o.hours <= current.hours * 1.02);
      if (same.length) tips.push(`Te same ${fmtHours(current.hours)} da się osiągnąć na ${same[0].procs} procesach zamiast ${model.nProc} — wystarczy połączyć małe siatki w jeden proces.`);
    }
    const biggest = model.meshes.reduce((a, b) => (a.cells >= b.cells ? a : b), model.meshes[0]);
    if (biggest && model.meshes.length > 1 && biggest.cells >= model.maxLoad * 0.99) {
      const second = sortDesc(model.meshes.map(m => m.cells))[1] || 0;
      const gain = 1 - Math.max(biggest.cells / 2, second) / biggest.cells;
      if (gain >= 0.1) tips.push(`Największa siatka "${biggest.id}" (${fmtInt(biggest.cells)} komórek) dyktuje tempo całego modelu. Podzielenie jej na dwie skróci obliczenia o ok. ${Math.round(gain * 100)}%.`);
    }
    if (model.meshes.length < 4 && model.totalCells > 300000) tips.push(`Model ma tylko ${model.meshes.length} siatk${model.meshes.length === 1 ? 'ę' : 'i'}, więc może liczyć się najwyżej na ${model.meshes.length} rdzeniach. Podział na więcej siatek pozwoli użyć mocniejszego serwera.`);
    return { options, best, current, fastest, cheapest, tips };
  }

  // ---------- formatting ----------
  function fmtInt(n) { return Math.round(n).toLocaleString('pl-PL'); }
  function fmtHours(h) {
    if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
    const H = Math.floor(h), M = Math.round((h - H) * 60);
    return M ? `${H} h ${M} min` : `${H} h`;
  }
  function listShort(arr, n = 4) { const u = uniq(arr); return u.slice(0, n).join(', ') + (u.length > n ? ` i ${u.length - n} innych` : ''); }
  function uniq(a) { return [...new Set(a)]; }
  function sortDesc(a) { return [...a].sort((x, y) => y - x); }

  const api = { parse, analyze, estimate, advise, partition, partitionAssign, assignProcesses, DEFAULTS, fmtInt, fmtHours };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FDSAnalyzer = api;
})(typeof window !== 'undefined' ? window : globalThis);
