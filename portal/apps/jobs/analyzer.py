"""Bridge to analyzer/fds-analyzer.js (one implementation shared with the browser)."""

import json
import subprocess
from pathlib import Path

from django.conf import settings

ANALYZER_CLI = Path(settings.BASE_DIR).parent / "analyzer" / "cli.js"


class AnalyzerError(Exception):
    pass


def analyze_file(path: Path, multiplier: float | None = None) -> dict:
    cmd = ["node", str(ANALYZER_CLI), str(path), "--eur-pln", str(settings.PRICING["eur_pln"])]
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
    if getattr(user, "kind", "company") == "student":
        return settings.PRICING["multiplier_student"]
    return settings.PRICING["multiplier_company"]
