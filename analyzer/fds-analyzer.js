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
        out.push({ name, body: text.slice(j, k), line: startLine, closed: k < n });
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
    const vel = estimateVelocity(by, meshes, issues);

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

  // Characteristic velocity [m/s]: max of fire-plume velocity and forced flows.
  function estimateVelocity(by, meshes, issues) {
    const surfs = new Map(by('SURF').map(g => [str(g.p, 'ID', ''), g]));
    const ramps = new Map();
    by('RAMP').forEach(g => {
      const id = str(g.p, 'ID', '');
      if (!ramps.has(id)) ramps.set(id, []);
      ramps.get(id).push(num(g.p, 'F', 0));
    });
    const rampMax = id => (ramps.has(id) ? Math.max(...ramps.get(id)) : 1);
    const area = (b, faceTop) => {
      const ex = Math.abs(b[1] - b[0]), ey = Math.abs(b[3] - b[2]), ez = Math.abs(b[5] - b[4]);
      if (faceTop) return ex * ey;
      const dims = [ex, ey, ez].sort((a, c) => c - a);
      return dims[0] * dims[1];
    };

    let fireQ = 0, forced = 0, sources = [];
    const consider = (surfId, a, label) => {
      const s = surfs.get(surfId);
      if (!s) return;
      const hrrpua = num(s.p, 'HRRPUA', 0);
      if (hrrpua > 0) {
        const q = hrrpua * a * rampMax(str(s.p, 'RAMP_Q', ''));
        fireQ += q;
        sources.push({ label, q });
      }
      const v = Math.abs(num(s.p, 'VEL', 0));
      if (v) forced = Math.max(forced, v);
      const vf = Math.abs(num(s.p, 'VOLUME_FLOW', 0));
      if (vf && a > 0) forced = Math.max(forced, vf / a);
    };
    by('VENT').forEach(g => { const b = xb(g.p); if (b) consider(str(g.p, 'SURF_ID', ''), area(b, false), str(g.p, 'ID', 'VENT')); });
    by('OBST').forEach(g => {
      const b = xb(g.p);
      if (!b) return;
      if (g.p.SURF_IDS) consider(g.p.SURF_IDS[0], area(b, true), str(g.p, 'ID', 'OBST'));
      else consider(str(g.p, 'SURF_ID', ''), area(b, true), str(g.p, 'ID', 'OBST'));
    });
    // HVAC fans: volume flow over the area of their vents
    const ventArea = new Map(by('VENT').map(g => [str(g.p, 'ID', ''), xb(g.p) ? area(xb(g.p), false) : 0]));
    const fans = new Map(by('HVAC').filter(g => /FAN/i.test(str(g.p, 'TYPE_ID', ''))).map(g => [str(g.p, 'ID', ''), num(g.p, 'VOLUME_FLOW', 0)]));
    by('HVAC').filter(g => /NODE/i.test(str(g.p, 'TYPE_ID', ''))).forEach(g => {
      const a = ventArea.get(str(g.p, 'VENT_ID', '')) || 0;
      const duct = by('HVAC').find(d => str(d.p, 'ID', '') === str(g.p, 'DUCT_ID', ''));
      const fan = duct ? fans.get(str(duct.p, 'FAN_ID', '')) : 0;
      if (fan && a > 0) forced = Math.max(forced, Math.abs(fan) / a);
    });

    // McCaffrey-like centreline plume velocity ~ 1.9 Q^(1/5), Q in kW
    const largest = sources.reduce((m, s) => Math.max(m, s.q), 0);
    const plume = largest > 0 ? 1.9 * Math.pow(largest, 0.2) : 0;
    const u = Math.max(plume, forced, 1.0);
    return { u: round(u, 2), plume: round(plume, 2), forced: round(forced, 2), fireQ: Math.round(fireQ), largestFire: Math.round(largest) };
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
    kSecPerCellStep: 2.1e-6,   // median of 6 stairwell runs on cpx42 (Sep 2026)
    cfl: 0.9,
    servers: [                 // effective rates from the old portal's Hetzner costs
      { name: 'cpx32', vcpu: 4, eurPerHour: 0.055 },
      { name: 'cpx42', vcpu: 8, eurPerHour: 0.111 },
      { name: 'cpx62', vcpu: 16, eurPerHour: 0.208 },
    ],
    eurPln: 4.25,
    multiplier: 2.0,
  };

  // Longest-processing-time partition of meshes into k processes
  function partition(meshCells, k) {
    const bins = Array(k).fill(0);
    [...meshCells].sort((a, b) => b - a).forEach(c => {
      let i = 0;
      for (let j = 1; j < k; j++) if (bins[j] < bins[i]) i = j;
      bins[i] += c;
    });
    return Math.max(...bins);
  }

  function steps(model, cfg) {
    return model.simTime * model.velocity.u / (cfg.cfl * model.dxMin);
  }

  // How much to trust a file-only estimate. Calibration: stairwells within
  // -30%/+60%; car-park models with jet fans/HVAC ran 2-10x longer than estimated.
  function confidence(model) {
    const complex = model.counts.hvac > 0 || model.velocity.forced > 3 || model.meshes.length > 20;
    return complex
      ? { level: 'low', low: 0.8, high: 10, note: 'Model z wentylacją mechaniczną, HVAC lub wieloma siatkami — czas liczenia potrafi być kilka razy dłuższy niż wynika z pliku. Dokładny czas poda dopiero bieg testowy.' }
      : { level: 'ok', low: 0.7, high: 1.6, note: 'Szacunek z pliku; bieg testowy zawęzi go do ok. ±15%.' };
  }

  function estimate(model, cfg = DEFAULTS, maxLoad = model.maxLoad) {
    const s = steps(model, cfg);
    const sec = cfg.kSecPerCellStep * maxLoad * s;
    return { hours: sec / 3600, steps: Math.round(s), confidence: confidence(model) };
  }

  function advise(model, cfg = DEFAULTS) {
    const cells = model.meshes.map(m => m.cells);
    const options = [];
    const maxK = Math.min(cells.length, Math.max(...cfg.servers.map(s => s.vcpu)));
    for (let k = 1; k <= maxK; k++) {
      const load = k === model.nProc && model.hasMpi ? model.maxLoad : partition(cells, k);
      const server = cfg.servers.find(s => s.vcpu >= k);
      if (!server) continue;
      const { hours } = estimate(model, cfg, load);
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

  const api = { parse, analyze, estimate, advise, partition, DEFAULTS, fmtInt, fmtHours };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FDSAnalyzer = api;
})(typeof window !== 'undefined' ? window : globalThis);
