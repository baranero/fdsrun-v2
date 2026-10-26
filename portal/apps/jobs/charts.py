"""Read FDS result CSVs (CHID_hrr.csv, CHID_devc.csv) into compact series for the live charts.

FDS CSV layout: first row units, second row column names, then data. Files grow while
the run goes on, so a trailing half-written line is skipped.
"""

import csv
import math
from pathlib import Path

MAX_POINTS = 400
MAX_SERIES = 12


def _read(path: Path):
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            rows = list(csv.reader(f))
    except OSError:
        return None
    if len(rows) < 3:
        return None
    units, names, data = rows[0], rows[1], rows[2:]
    cols = []
    for r in data:
        if len(r) != len(names):
            continue
        try:
            cols.append([float(v) for v in r])
        except ValueError:
            continue
    if not cols:
        return None
    return units, names, cols


def _thin(points):
    if len(points) <= MAX_POINTS:
        return points
    step = len(points) / MAX_POINTS
    return [points[int(i * step)] for i in range(MAX_POINTS)] + [points[-1]]


def _series(table, pick):
    units, names, data = table
    out = []
    for idx in pick:
        name, unit = names[idx], units[idx]
        pts = [[r[0], r[idx]] for r in data if math.isfinite(r[idx])]
        if not pts:
            continue
        out.append({"name": name, "unit": unit, "points": _thin(pts), "last": pts[-1][1], "max": max(p[1] for p in pts)})
    return out


def hrr_series(results_dir: Path, chid: str):
    table = _read(results_dir / f"{chid}_hrr.csv")
    if not table:
        return []
    names = table[1]
    pick = [i for i, n in enumerate(names) if n in ("HRR", "Q_RADI", "Q_CONV")][:3]
    return _series(table, pick)


def devc_series(results_dir: Path, chid: str):
    table = _read(results_dir / f"{chid}_devc.csv")
    if not table:
        return {}
    units, names, _ = table
    groups = {}
    for i in range(1, len(names)):
        groups.setdefault(units[i], []).append(i)
    out = {}
    for unit, idx in groups.items():
        series = _series(table, idx[:MAX_SERIES])
        if series:
            out[unit] = series
    return out
