// Build the single-file analyzer page with sample files and calibration data embedded.
const fs = require('fs');
const path = require('path');
const A = require('./fds-analyzer.js');
const dir = process.argv[2], outFile = process.argv[3];

const outDir = process.argv[4];
const samples = {};
fs.readdirSync(dir).filter(f => f.endsWith('.fds')).sort().forEach(f => { samples[f] = fs.readFileSync(path.join(dir, f), 'utf8'); });
const calib = JSON.parse(require('child_process').execFileSync('node', [path.join(__dirname, 'calibrate.js'), dir, outDir, '--json']).toString());

const safe = o => JSON.stringify(o).replace(/<\//g, '<\\/');
let html = fs.readFileSync(path.join(__dirname, 'page.template.html'), 'utf8');
html = html.replace('/*__ANALYZER__*/', () => fs.readFileSync(path.join(__dirname, 'fds-analyzer.js'), 'utf8').replace(/<\//g, '<\\/'))
  .replace('/*__SAMPLES__*/', () => safe(samples))
  .replace('/*__CALIB__*/', () => safe(calib));
fs.writeFileSync(outFile, html);
console.log('wrote', outFile, (html.length / 1024).toFixed(0), 'KB,', calib.length, 'calibration rows');
