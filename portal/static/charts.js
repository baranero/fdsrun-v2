// Live charts for a job page: one canvas per unit, drawn from /wykresy.json.
(function () {
  const root = document.getElementById('charts');
  if (!root) return;
  const url = root.dataset.url, active = root.dataset.active === '1';
  const COLORS = ['#c2410c', '#3b5b7a', '#17733f', '#9a5a00', '#7c3aed', '#0e7490', '#b42318', '#4d7c0f', '#6d28d9', '#a16207', '#1d4ed8', '#be185d'];
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  function draw(canvas, series, tEnd, title) {
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = 260;
    canvas.width = W * dpr; canvas.height = H * dpr;
    const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
    const padL = 56, padR = 12, padT = 28, padB = 30;
    const xs = series.flatMap(s => s.points.map(p => p[0]));
    const ys = series.flatMap(s => s.points.map(p => p[1]));
    const xMax = Math.max(tEnd || 0, ...xs, 1), yMinRaw = Math.min(0, ...ys), yMaxRaw = Math.max(...ys, 1);
    const nice = v => { const p = Math.pow(10, Math.floor(Math.log10(v))); const f = v / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; };
    const step = nice(((yMaxRaw - yMinRaw) || 1) / 4);
    const yMin = Math.floor(yMinRaw / step) * step, yMax = Math.ceil((yMaxRaw + step * 0.05) / step) * step;
    const X = x => padL + (x / xMax) * (W - padL - padR);
    const Y = y => padT + (1 - (y - yMin) / (yMax - yMin)) * (H - padT - padB);
    ctx.clearRect(0, 0, W, H);
    ctx.font = '11px IBM Plex Mono, monospace';
    ctx.fillStyle = css('--muted'); ctx.strokeStyle = css('--line'); ctx.lineWidth = 1;
    for (let v = yMin; v <= yMax + 1e-9; v += step) {
      const y = Y(v);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
      ctx.textAlign = 'right'; ctx.fillText(fmt(v), padL - 6, y + 4);
    }
    const xTicks = 6;
    for (let i = 0; i <= xTicks; i++) {
      const v = xMax * i / xTicks, x = X(v);
      ctx.textAlign = 'center'; ctx.fillText(Math.round(v) + ' s', x, H - 10);
    }
    series.forEach((s, i) => {
      ctx.strokeStyle = COLORS[i % COLORS.length]; ctx.lineWidth = 1.6; ctx.beginPath();
      s.points.forEach((p, j) => { const x = X(p[0]), y = Y(p[1]); j ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
    });
    ctx.fillStyle = css('--fg'); ctx.font = '600 13px IBM Plex Sans, sans-serif'; ctx.textAlign = 'left';
    ctx.fillText(title, padL, 16);
  }

  function fmt(v) { const a = Math.abs(v); return a >= 1000 ? Math.round(v).toLocaleString('pl-PL') : a >= 10 ? v.toFixed(0) : v.toFixed(1); }

  function legend(series) {
    return series.map((s, i) => `<span class="lg"><i style="background:${COLORS[i % COLORS.length]}"></i>${s.name} <b class="mono">${fmt(s.last)}</b></span>`).join('');
  }

  function render(data) {
    const blocks = [];
    if (data.hrr.length) blocks.push({ key: 'hrr', title: 'Moc pożaru HRR [kW]', series: data.hrr });
    Object.entries(data.devc).forEach(([unit, series]) => blocks.push({ key: 'devc-' + unit.replace(/\W/g, '_'), title: `Urządzenia pomiarowe [${unit}]`, series }));
    if (!blocks.length) { root.innerHTML = '<p class="muted">Wykresy pojawią się, gdy FDS zapisze pierwsze wyniki (zwykle po kilku minutach).</p>'; return; }
    blocks.forEach(b => {
      let el = document.getElementById('chart-' + b.key);
      if (!el) {
        el = document.createElement('div'); el.id = 'chart-' + b.key; el.className = 'chart';
        el.innerHTML = '<canvas></canvas><div class="legend"></div>';
        root.appendChild(el);
      }
      draw(el.querySelector('canvas'), b.series, data.t_end, b.title);
      el.querySelector('.legend').innerHTML = legend(b.series);
    });
  }

  let last = null;
  async function load() {
    try { const r = await fetch(url, { credentials: 'same-origin' }); last = await r.json(); render(last); }
    catch (e) { /* keep the previous chart */ }
  }
  load();
  if (active) setInterval(load, 30000);
  window.addEventListener('resize', () => last && render(last));
})();
