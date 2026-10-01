"""v3.90 — why a run came back with fewer frames than it was given.

Issue #3: offline, 23 photographs, every one failing with the same
``ConnectTimeout``. The reasons went to stderr one line at a time and were
kept nowhere, so the run ended as ``Analyzed 0/23`` / ``No analyzable
images`` and the review server, finding no ``scores.csv``, answered

    425 results not ready — pipeline may still be running

about a pipeline that had finished two minutes earlier. A folder of
unreadable files, a missing model and a dead network all looked the same,
and all three looked like "wait".

The reasons are collected now (``parallel_analyze(failures=…)``), grouped
by exception type and written beside the run's other outputs, so anything
that reports on the run can say what happened to it.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

FILENAME = "analysis_failures.json"
_MAX_KINDS = 5
_MAX_MESSAGE = 300


def summarize_failures(failures: list[dict], *, total: int,
                       analyzed: int) -> dict | None:
    """Group per-frame failures by exception type; ``None`` when there were
    none. Grouped by type rather than by full message because a message
    usually carries the file's own path, which would make every one unique.
    """
    if not failures:
        return None
    kinds = [f["error"].split(":", 1)[0].strip() or "Error" for f in failures]
    first: dict[str, dict] = {}
    for kind, f in zip(kinds, failures):
        first.setdefault(kind, f)
    errors = []
    for kind, count in Counter(kinds).most_common(_MAX_KINDS):
        f = first[kind]
        errors.append({
            "error": f["error"][:_MAX_MESSAGE],
            "count": count,
            # The name only: the summary is read back into a web page.
            "example": Path(f["path"]).name,
        })
    return {"schema_version": 1, "total": int(total),
            "analyzed": int(analyzed), "failed": len(failures),
            "errors": errors}


def write_failure_summary(output_dir: Path, summary: dict | None) -> None:
    """Write the summary, or remove a stale one.

    Removing matters as much as writing: a second run into the same
    directory that succeeds must not leave the first run's failure standing.
    """
    path = Path(output_dir) / FILENAME
    if summary is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def read_failure_summary(output_dir: Path) -> dict | None:
    """The summary on disk, or ``None`` — never raises."""
    try:
        data = json.loads((Path(output_dir) / FILENAME).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("errors"):
        return None
    return data


def no_results_message(summary: dict | None) -> str:
    """What to tell someone whose run produced nothing."""
    if summary is None:
        return "没有可分析的图片"
    top = summary["errors"][0]
    return (f"没有可分析的图片:{summary['failed']} 张全部分析失败。"
            f"最常见的原因({top['count']} 次):{top['error']}")
