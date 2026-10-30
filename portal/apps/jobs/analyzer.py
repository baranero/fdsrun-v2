"""Bridge to analyzer/fds-analyzer.js (one implementation shared with the browser)."""

import json
import subprocess
from pathlib import Path

from django.conf import settings

ANALYZER_CLI = Path(settings.BASE_DIR).parent / "analyzer" / "cli.js"


class AnalyzerError(Exception):
    pass


def analyze_file(path: Path, multiplier: float | None = None) -> dict:
    from apps.compute.models import ServerCalibration

    cmd = ["node", str(ANALYZER_CLI), str(path), "--eur-pln", str(settings.PRICING["eur_pln"])] + ServerCalibration.as_cli_args()
    if multiplier:
        cmd += ["--multiplier", str(multiplier)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except FileNotFoundError as e:
        raise AnalyzerError("Brak środowiska Node.js na serwerze") from e
    except subprocess.TimeoutExpired as e:
        raise AnalyzerError("Analiza pliku trwała zbyt długo") from e
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError as e:
        raise AnalyzerError(f"Analizator zwrócił niepoprawną odpowiedź: {out.stderr[:300]}") from e
    if not data.get("ok"):
        raise AnalyzerError(data.get("error", "Nieznany błąd analizy"))
    return data


def multiplier_for(user) -> float:
    if getattr(user, "kind", "company") == "student" and getattr(user, "student_verified", False):
        return settings.PRICING["multiplier_student"]
    return settings.PRICING["multiplier_company"]


def prepare_run_file(src: Path, dst: Path, procs: int) -> dict:
    """Write a copy of the input with every mesh assigned to one of `procs` MPI processes."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    out = subprocess.run(["node", str(ANALYZER_CLI), str(src), "--assign", str(procs), "--out", str(dst)], capture_output=True, text=True, timeout=60, check=False)
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError as e:
        raise AnalyzerError(f"Nie udało się przygotować pliku do obliczeń: {out.stderr[:300]}") from e
    if not data.get("ok"):
        raise AnalyzerError(data.get("error", "Nie udało się przygotować pliku do obliczeń"))
    return data


def make_restart_input(src: Path, dst: Path) -> None:
    """Copy of the input with RESTART=.TRUE. in &MISC, so FDS continues from CHID_n.restart."""
    import re

    text = src.read_text(errors="replace")
    misc = re.search(r"&MISC\b", text, re.I)
    if misc:
        # drop an existing RESTART=… inside the first &MISC group, then add ours right after &MISC
        end = text.find("/", misc.end())
        group = re.sub(r"\bRESTART\s*=\s*\.?\w+\.?\s*,?", "", text[misc.end():end], flags=re.I)
        text = text[:misc.end()] + " RESTART=.TRUE.," + group + text[end:]
    else:
        head = re.search(r"&HEAD\b[^/]*/", text, re.I | re.S)
        at = head.end() if head else 0
        text = text[:at] + "\n&MISC RESTART=.TRUE. /\n" + text[at:]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text)
