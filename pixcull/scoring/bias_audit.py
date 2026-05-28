"""v0.13-P0-4 — Bias audit dashboard backend.

Aggregates ``annotations.jsonl`` + ``scores.csv`` across every run
under ``~/.pixcull/runs/`` and surfaces "the rescorer over/under-fires
in <bucket>" findings.

Buckets
=======
* **scene tag** (wedding / landscape / portrait / etc.)
* **time-of-day** (derived from EXIF capture time bucket-3h)
* **aperture bracket** (f/1.4-1.8 / f/2-2.8 / f/4-5.6 / f/8+)

For each bucket we compute:
  * sample count
  * keep rate per the *user's* decision
  * cull rate per the *model's* decision (score_final < 0.40)
  * reversal rate (user_decision ≠ model_decision)

Outliers (z-score > 1.5 vs global mean of the same bucket family)
get flagged as "over/under-firing" with a suggestion.

Cache: ``~/.pixcull/cache/bias_audit.json``, TTL 24h.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


# Sample counts below this are not statistically meaningful; we still
# report them but mark `under_sampled=True` so the UI greys them.
_MIN_BUCKET_N = 10
# Outlier threshold — z-score over global mean for the same bucket family.
_OUTLIER_Z = 1.5


@dataclass
class BucketStats:
    """Aggregated stats for one (bucket_family, bucket_value) pair."""
    family: str       # "scene" / "time_of_day" / "aperture"
    value: str        # "wedding" / "evening" / "f1.4-1.8"
    n: int = 0
    n_keep: int = 0
    n_maybe: int = 0
    n_cull: int = 0
    n_model_keep: int = 0
    n_model_cull: int = 0
    n_reversals: int = 0  # model_decision ≠ user_decision

    @property
    def keep_rate(self) -> float:
        return self.n_keep / self.n if self.n else 0.0

    @property
    def cull_rate(self) -> float:
        return self.n_cull / self.n if self.n else 0.0

    @property
    def model_cull_rate(self) -> float:
        return self.n_model_cull / self.n if self.n else 0.0

    @property
    def reversal_rate(self) -> float:
        return self.n_reversals / self.n if self.n else 0.0

    @property
    def under_sampled(self) -> bool:
        return self.n < _MIN_BUCKET_N


@dataclass
class BiasFinding:
    """One actionable finding for the dashboard."""
    family: str
    value: str
    metric: str           # "cull_rate" / "reversal_rate"
    bucket_value: float
    global_mean: float
    z_score: float
    suggestion: str


@dataclass
class BiasReport:
    timestamp_built: float = 0.0
    n_total_rows: int = 0
    n_total_runs: int = 0
    buckets: list[BucketStats] = field(default_factory=list)
    findings: list[BiasFinding] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp_built": self.timestamp_built,
            "n_total_rows": self.n_total_rows,
            "n_total_runs": self.n_total_runs,
            "buckets": [asdict(b) | {
                "keep_rate": b.keep_rate,
                "cull_rate": b.cull_rate,
                "model_cull_rate": b.model_cull_rate,
                "reversal_rate": b.reversal_rate,
                "under_sampled": b.under_sampled,
            } for b in self.buckets],
            "findings": [asdict(f) for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Bucket derivers — keep simple + composable
# ---------------------------------------------------------------------------


def _bucket_time_of_day(hour: int | None) -> str | None:
    if hour is None:
        return None
    if 5 <= hour < 9:
        return "early_morning"
    if 9 <= hour < 12:
        return "morning"
    if 12 <= hour < 15:
        return "midday"
    if 15 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 21:
        return "evening"
    return "night"


def _bucket_aperture(aperture: float | None) -> str | None:
    if aperture is None or aperture <= 0:
        return None
    if aperture < 1.9:
        return "f1.4-1.8"
    if aperture < 3:
        return "f2-2.8"
    if aperture < 6:
        return "f4-5.6"
    return "f8+"


# ---------------------------------------------------------------------------
# Annotation walker
# ---------------------------------------------------------------------------


def _iter_annotation_rows(runs_root: Path) -> Iterable[tuple[str, dict]]:
    """Yield (run_name, row) for every annotation across every run."""
    if not runs_root.exists():
        return
    for ann_path in runs_root.rglob("annotations.jsonl"):
        run_name = ann_path.parent.name
        try:
            with ann_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        yield run_name, row
        except OSError:
            continue


def build_report(runs_root: Path) -> BiasReport:
    """Walk every annotation + bucket-aggregate.

    For each row we read:
      * `decision` / `overall_label` — user's truth
      * `model_decision` (v0.12-P0-3 wrote this) — model's prediction
      * `scene` / `vertical` — scene bucket
      * `capture_time` / `capture_hour` — time-of-day bucket
      * `aperture` — aperture bracket

    Missing fields silently skip the row from that bucket family
    (but it still contributes to other families it has data for).
    """
    buckets: dict[tuple[str, str], BucketStats] = {}
    n_rows = 0
    runs_seen: set[str] = set()

    def _get(fam: str, val: str) -> BucketStats:
        key = (fam, val)
        if key not in buckets:
            buckets[key] = BucketStats(family=fam, value=val)
        return buckets[key]

    for run_name, row in _iter_annotation_rows(runs_root):
        n_rows += 1
        runs_seen.add(run_name)
        user_dec = (row.get("decision")
                    or row.get("overall_label") or "").strip().lower()
        model_dec = (row.get("model_decision")
                     or row.get("rescorer_pred") or "").strip().lower()

        # Bucket family 1 — scene
        scene = (row.get("scene")
                 or row.get("vertical") or "").strip().lower()
        if scene:
            b = _get("scene", scene)
            _accumulate(b, user_dec, model_dec)

        # Family 2 — time-of-day
        cap_hour = None
        if isinstance(row.get("capture_hour"), (int, float)):
            cap_hour = int(row["capture_hour"])
        elif isinstance(row.get("capture_time"), str):
            # Best-effort parse: ISO like "2024-06-15T14:35:00"
            try:
                cap_hour = int(row["capture_time"][11:13])
            except (TypeError, ValueError):
                pass
        tod = _bucket_time_of_day(cap_hour)
        if tod:
            b = _get("time_of_day", tod)
            _accumulate(b, user_dec, model_dec)

        # Family 3 — aperture
        ap = None
        if isinstance(row.get("aperture"), (int, float)):
            ap = float(row["aperture"])
        ap_b = _bucket_aperture(ap)
        if ap_b:
            b = _get("aperture", ap_b)
            _accumulate(b, user_dec, model_dec)

    report = BiasReport(
        timestamp_built=time.time(),
        n_total_rows=n_rows,
        n_total_runs=len(runs_seen),
        buckets=list(buckets.values()),
    )
    report.findings = _compute_findings(report.buckets)
    return report


def _accumulate(b: BucketStats, user_dec: str, model_dec: str) -> None:
    b.n += 1
    if user_dec == "keep":
        b.n_keep += 1
    elif user_dec == "maybe":
        b.n_maybe += 1
    elif user_dec == "cull":
        b.n_cull += 1
    if model_dec == "keep":
        b.n_model_keep += 1
    elif model_dec == "cull":
        b.n_model_cull += 1
    if user_dec and model_dec and user_dec != model_dec:
        b.n_reversals += 1


# ---------------------------------------------------------------------------
# Outlier detection
# ---------------------------------------------------------------------------


def _compute_findings(buckets: list[BucketStats]) -> list[BiasFinding]:
    """For each (family, metric), z-score buckets against the family
    mean and emit findings for outliers."""
    findings: list[BiasFinding] = []
    # Group by family
    by_family: dict[str, list[BucketStats]] = {}
    for b in buckets:
        by_family.setdefault(b.family, []).append(b)
    for family, fam_buckets in by_family.items():
        eligible = [b for b in fam_buckets if not b.under_sampled]
        if len(eligible) < 3:
            continue   # not enough buckets to score outliers
        for metric_name in ("cull_rate", "reversal_rate"):
            values = [getattr(b, metric_name) for b in eligible]
            mean = sum(values) / len(values)
            var = sum((v - mean) ** 2 for v in values) / len(values)
            std = var ** 0.5
            if std < 1e-6:
                continue
            for b in eligible:
                v = getattr(b, metric_name)
                z = (v - mean) / std
                if abs(z) < _OUTLIER_Z:
                    continue
                direction = "高" if z > 0 else "低"
                if metric_name == "cull_rate":
                    suggestion = (
                        f"rescorer 在 {family} = {b.value} 上 cull rate "
                        f"{v*100:.1f}% (全局均值 {mean*100:.1f}%) — "
                        f"模型可能过{'严' if z > 0 else '松'}"
                    )
                else:
                    suggestion = (
                        f"{family} = {b.value} 反转率 {v*100:.1f}% "
                        f"(均值 {mean*100:.1f}%) — 标注/模型分歧严重"
                    )
                findings.append(BiasFinding(
                    family=family,
                    value=b.value,
                    metric=metric_name,
                    bucket_value=v,
                    global_mean=mean,
                    z_score=z,
                    suggestion=suggestion,
                ))
    findings.sort(key=lambda f: -abs(f.z_score))
    return findings


# ---------------------------------------------------------------------------
# Cache layer
# ---------------------------------------------------------------------------


_CACHE_TTL_SEC = 24 * 3600


def _cache_path() -> Path:
    p = Path.home() / ".pixcull" / "cache" / "bias_audit.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_report(runs_root: Path, *, force: bool = False) -> BiasReport:
    """Cached entry point.  Use ``force=True`` from the admin panel."""
    cache = _cache_path()
    if not force and cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if (time.time() - data.get("timestamp_built", 0)) < _CACHE_TTL_SEC:
                return _report_from_dict(data)
        except (OSError, json.JSONDecodeError):
            pass
    report = build_report(runs_root)
    try:
        cache.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        pass
    return report


def _report_from_dict(d: dict) -> BiasReport:
    """Inverse of BiasReport.to_dict()."""
    buckets = []
    for b in d.get("buckets", []):
        buckets.append(BucketStats(
            family=b["family"], value=b["value"],
            n=b["n"], n_keep=b["n_keep"], n_maybe=b["n_maybe"],
            n_cull=b["n_cull"], n_model_keep=b["n_model_keep"],
            n_model_cull=b["n_model_cull"],
            n_reversals=b["n_reversals"],
        ))
    findings = [BiasFinding(**f) for f in d.get("findings", [])]
    return BiasReport(
        timestamp_built=d.get("timestamp_built", 0.0),
        n_total_rows=d.get("n_total_rows", 0),
        n_total_runs=d.get("n_total_runs", 0),
        buckets=buckets, findings=findings,
    )
