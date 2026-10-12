"""Write a translation result: SED2 document, model files and import report; validate with libsed2 first."""

from __future__ import annotations

import json
from pathlib import Path

from .mapping import Result

EXIT_WRITTEN, EXIT_UNREADABLE, EXIT_NOT_TRANSLATABLE, EXIT_ERROR = 0, 10, 11, 12


def validate(sed2: dict) -> list[str]:
    """Problems libsed2 finds; raises ImportError when libsed2 is not installed (a document is never written unvalidated)."""
    import libsed2
    doc = libsed2.read_from_string(json.dumps(sed2))
    return [f"{p.rule_id} ({p.severity}) at {p.location}: {p.message}" for p in doc.validate()]


def write_result(result: Result, out: Path, report: Path | None) -> int:
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
    if result.status == "not-translatable" or result.sed2 is None:
        if report is not None:
            report.write_text(json.dumps(result.report(), indent=2) + "\n", encoding="ascii")
        return EXIT_NOT_TRANSLATABLE
    try:
        problems = validate(result.sed2)
    except ImportError:
        result.reasons.append("libsed2 is not installed: the SED2 document cannot be validated, so it is not written")
        result.status = "not-translatable"
        if report is not None:
            report.write_text(json.dumps(result.report(), indent=2) + "\n", encoding="ascii")
        return EXIT_ERROR
    errors = [p for p in problems if "(error)" in p]
    if errors:
        result.reasons.extend("libsed2: " + p for p in errors)
        result.status = "not-translatable"
        if report is not None:
            report.write_text(json.dumps(result.report(), indent=2) + "\n", encoding="ascii")
        return EXIT_ERROR
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result.sed2, indent=2) + "\n", encoding="ascii")
    for name, text in result.model_files.items():
        (out.parent / name).write_text(text, encoding="utf-8")
    if report is not None:
        report.write_text(json.dumps(result.report(), indent=2) + "\n", encoding="ascii")
    return EXIT_WRITTEN
