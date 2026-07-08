from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

APP_VERSION = "1.1.0"
MAX_FILE_SIZE_MB = 25
ALLOWED_EXTENSIONS = {".xlsx"}
MAX_ROWS = 200_000
DEFAULT_OUTPUT_DIR = "outputs"
LOG = logging.getLogger("project_health_agent")


class AgentError(Exception):
    """Safe, user-facing application error."""


@dataclass(frozen=True)
class Columns:
    task: str | None
    status: str | None
    percent: str | None
    end_date: str | None
    variance: str | None
    critical: str | None


def safe_json_value(value: Any) -> Any:
    """Convert numpy/pandas values to strict JSON-safe Python values."""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def validate_input_file(path_text: str) -> Path:
    """Validate local input before parsing. No network access, macros, or executable formats."""
    path = Path(path_text).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise AgentError(f"Input file not found: {path.name}")
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise AgentError(f"Unsupported file type: {path.suffix}. Only .xlsx is allowed.")
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise AgentError(f"File too large: {size_mb:.1f} MB. Limit is {MAX_FILE_SIZE_MB} MB.")
    return path


def safe_output_dir(path_text: str) -> Path:
    """Create an output directory without deleting or overwriting unrelated files."""
    path = Path(path_text).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise AgentError("Output path is not a directory.")
    return path


def normalize_status(value: Any) -> str:
    s = str(value).strip().lower()
    if s in {"", "nan", "none", "null"}:
        return "Unknown"
    if "not started" in s:
        return "Not Started"
    if "in progress" in s or "progress" in s:
        return "In Progress"
    if "on hold" in s or s == "hold":
        return "On Hold"
    if "complete" in s or s in {"done", "closed"}:
        return "Completed"
    return str(value).strip()[:100]


def parse_variance(value: Any) -> float:
    if pd.isna(value):
        return np.nan
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        return np.nan
    try:
        number = float(match.group())
        return number if math.isfinite(number) else np.nan
    except (TypeError, ValueError, OverflowError):
        return np.nan


def discover_plan_sheet(xls: pd.ExcelFile) -> str:
    candidates = [s for s in xls.sheet_names if s.strip().lower() not in {"comments", "summary"}]
    if not candidates:
        raise AgentError("No project-plan worksheet found.")
    return candidates[0]


def map_columns(df: pd.DataFrame) -> Columns:
    lookup = {str(c).strip().lower(): c for c in df.columns}
    return Columns(
        task=lookup.get("task name"),
        status=lookup.get("status"),
        percent=lookup.get("% complete"),
        end_date=lookup.get("end date"),
        variance=lookup.get("variance2") or lookup.get("variance"),
        critical=lookup.get("critical ?") or lookup.get("critical"),
    )


def read_comments(path: Path, xls: pd.ExcelFile) -> str:
    sheet = next((s for s in xls.sheet_names if s.strip().lower() == "comments"), None)
    if not sheet:
        return ""
    try:
        raw = pd.read_excel(path, sheet_name=sheet, header=None, nrows=10_000)
        # Formula-like strings are treated as plain text and never executed.
        return " ".join(
            str(v)[:500]
            for v in raw.to_numpy().ravel()
            if pd.notna(v)
        )[:100_000].lower()
    except Exception as exc:
        LOG.warning("Comments sheet could not be read: %s", type(exc).__name__)
        return ""


def analyze(path_text: str, as_of_text: str) -> dict[str, Any]:
    path = validate_input_file(path_text)
    try:
        as_of = pd.Timestamp(as_of_text)
    except Exception as exc:
        raise AgentError("Invalid --as-of date. Use YYYY-MM-DD.") from exc

    if pd.isna(as_of):
        raise AgentError("Invalid --as-of date. Use YYYY-MM-DD.")

    try:
        xls = pd.ExcelFile(path, engine="openpyxl")
        sheet = discover_plan_sheet(xls)
        df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    except AgentError:
        raise
    except Exception as exc:
        raise AgentError(f"Workbook could not be read safely ({type(exc).__name__}).") from exc

    if len(df) == 0:
        raise AgentError("Project-plan worksheet is empty.")
    if len(df) > MAX_ROWS:
        raise AgentError(f"Too many rows: {len(df)}. Limit is {MAX_ROWS}.")

    cols = map_columns(df)
    missing_required = [name for name, col in {
        "Task Name": cols.task, "Status": cols.status, "End Date": cols.end_date
    }.items() if col is None]
    if missing_required:
        raise AgentError("Missing required column(s): " + ", ".join(missing_required))

    statuses = df[cols.status].map(normalize_status)
    ends = pd.to_datetime(df[cols.end_date], errors="coerce")
    variance = df[cols.variance].map(parse_variance) if cols.variance else pd.Series(np.nan, index=df.index)
    critical = (
        df[cols.critical].fillna(False).astype(str).str.strip().str.lower()
        .isin({"true", "1", "yes", "y"})
        if cols.critical else pd.Series(False, index=df.index)
    )

    overdue = ends.notna() & (ends < as_of) & (statuses != "Completed")
    critical_overdue = overdue & critical
    severe_variance = variance.notna() & (variance <= -10)
    on_hold = statuses.eq("On Hold")

    comments = read_comments(path, xls)
    blocker_terms = ("blocked", "dependency", "awaiting", "not received", "pending", "delay", "risk", "issue")
    blocker_hits = sum(comments.count(term) for term in blocker_terms)

    negative_hits = sum(comments.count(term) for term in ("delay", "impacted", "pending", "issue", "risk", "blocked"))
    positive_hits = sum(comments.count(term) for term in ("completed", "on track", "approved", "done"))
    sentiment = (
        "Negative" if negative_hits > positive_hits + 1
        else "Positive" if positive_hits > negative_hits + 1
        else "Neutral / insufficient"
    )

    schedule = min(
        35.0,
        float(overdue.sum()) / max(1, len(df)) * 150.0
        + min(20.0, float(critical_overdue.sum()) * 4.0)
        + min(10.0, float(severe_variance.sum()) * 1.5),
    )
    milestone = min(25.0, float(critical_overdue.sum()) * 5.0 + float(on_hold.sum()) * 2.0)
    blockers = min(20.0, float(blocker_hits) * 2.5)
    sentiment_score = {"Negative": 10.0, "Neutral / insufficient": 4.0, "Positive": 0.0}[sentiment]

    essential = [cols.task, cols.status, cols.end_date] + ([cols.percent] if cols.percent else [])
    completeness = round(float(100 * (1 - df[essential].isna().mean().mean())), 1)
    data_quality_penalty = min(10.0, max(0.0, (100.0 - completeness) / 10.0))
    score = min(100.0, round(schedule + milestone + blockers + sentiment_score + data_quality_penalty, 1))

    # Explicit overrides: severe evidence cannot be averaged away.
    # Absolute-count safeguards prevent large projects from diluting material overdue work.
    if critical_overdue.sum() >= 3:
        rag = "RED"
        status_driver = f"Critical override: {int(critical_overdue.sum())} critical overdue task(s)"
    elif severe_variance.sum() >= 8:
        rag = "RED"
        status_driver = f"Critical override: {int(severe_variance.sum())} severe variance task(s)"
    elif score >= 55:
        rag = "RED"
        status_driver = f"Weighted score: {score}/100 reached Red threshold"
    elif overdue.sum() >= 20:
        rag = "AMBER"
        status_driver = f"Absolute overdue safeguard: {int(overdue.sum())} overdue open task(s)"
    elif score >= 28:
        rag = "AMBER"
        status_driver = f"Weighted score: {score}/100 reached Amber threshold"
    elif critical_overdue.sum() > 0:
        rag = "AMBER"
        status_driver = f"Critical-task safeguard: {int(critical_overdue.sum())} critical overdue task(s)"
    elif on_hold.sum() > 0:
        rag = "AMBER"
        status_driver = f"On-hold safeguard: {int(on_hold.sum())} task(s) on hold"
    else:
        rag = "GREEN"
        status_driver = f"Weighted score: {score}/100 with no override triggered"

    reasons = []
    if critical_overdue.sum():
        reasons.append(f"{int(critical_overdue.sum())} critical overdue task(s)")
    if overdue.sum():
        reasons.append(f"{int(overdue.sum())} overdue open task(s)")
    if on_hold.sum():
        reasons.append(f"{int(on_hold.sum())} task(s) on hold")
    if severe_variance.sum():
        reasons.append(f"{int(severe_variance.sum())} severe variance task(s)")
    if blocker_hits:
        reasons.append(f"{int(blocker_hits)} blocker/risk signal(s)")
    if not reasons:
        reasons.append("No material threshold breaches detected")

    confidence = "High" if completeness >= 90 else "Medium" if completeness >= 70 else "Low"

    result = {
        "agent_version": APP_VERSION,
        "file": path.name,
        "as_of": as_of.date().isoformat(),
        "rag": rag,
        "risk_score": score,
        "status_driver": status_driver,
        "confidence": confidence,
        "data_completeness_pct": completeness,
        "counts": {
            "tasks": int(len(df)),
            "completed": int(statuses.eq("Completed").sum()),
            "in_progress": int(statuses.eq("In Progress").sum()),
            "not_started": int(statuses.eq("Not Started").sum()),
            "on_hold": int(on_hold.sum()),
            "overdue_open": int(overdue.sum()),
            "critical_overdue": int(critical_overdue.sum()),
            "severe_variance": int(severe_variance.sum()),
        },
        "signals": {
            "schedule": round(schedule, 1),
            "milestone": round(milestone, 1),
            "blockers": round(blockers, 1),
            "sentiment": sentiment,
            "data_quality_penalty": round(data_quality_penalty, 1),
        },
        "reasoning": f"{rag} — {status_driver}. Evidence: " + "; ".join(reasons) + ".",
        "limitations": [
            "Missing budget data is Unknown, never assumed Green.",
            "Keyword-based comment sentiment is a weak signal and should be human-reviewed.",
            "The agent does not execute workbook formulas, macros, links, or external content.",
        ],
    }
    return json.loads(json.dumps(result, default=safe_json_value, allow_nan=False))


def atomic_write_json(output_path: Path, data: dict[str, Any]) -> None:
    """Write via a temporary file, then replace atomically to avoid partial/corrupt output."""
    temp = output_path.with_suffix(output_path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temp.replace(output_path)


def safe_output_name(input_path: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(input_path).stem)[:120].strip("._")
    return (stem or "project") + "_health.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Explainable Project Health Reporting Agent")
    parser.add_argument("files", nargs="+", help="Local .xlsx project-plan files")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Reporting date: YYYY-MM-DD")
    parser.add_argument("--out", default=DEFAULT_OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    output_dir = safe_output_dir(args.out)
    failures = 0

    for file_text in args.files:
        try:
            result = analyze(file_text, args.as_of)
            output_path = output_dir / safe_output_name(file_text)
            atomic_write_json(output_path, result)
            print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        except AgentError as exc:
            failures += 1
            LOG.error("%s: %s", Path(file_text).name, exc)
        except Exception as exc:
            # Prevent raw stack traces and internal details from leaking by default.
            failures += 1
            LOG.error("%s: unexpected processing failure (%s)", Path(file_text).name, type(exc).__name__)

    return 1 if failures else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
