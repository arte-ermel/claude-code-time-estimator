#!/usr/bin/env python3
"""
Universal Time Estimator — framework-agnostic task time estimation.

Usage:
    python3 time_estimator.py estimate --summary "..." --domain web_app --framework-tags react,gsd --artifact-type code --size-hint M --complexity 3
    python3 time_estimator.py log_outcome --summary "..." --domain web_app --framework-tags react --artifact-type code --size-hint M --complexity 3 --actual-minutes 70 --status done [--estimate-low 40] [--estimate-high 90] [--id T-2026-03-08-001] [--project DealOS]
    python3 time_estimator.py calibration_summary
    python3 time_estimator.py project_summary --project DealOS [--from 2026-03-01] [--to 2026-03-08]
"""

import argparse
import json
import os
import re
import sys
import math
from datetime import datetime, date
from pathlib import Path
from collections import defaultdict

LOG_PATH = Path.home() / ".claude" / "universal_time_log.jsonl"

# Generic priors: baseline minutes by (size_hint, artifact_type)
# Used when fewer than 3 similar historical records exist
PRIORS = {
    # size_hint: {artifact_type: baseline_minutes}
    "XS": {"code": 15, "workflow": 10, "infra": 10, "doc": 10},
    "S":  {"code": 35, "workflow": 25, "infra": 25, "doc": 20},
    "M":  {"code": 75, "workflow": 50, "infra": 55, "doc": 45},
    "L":  {"code": 150, "workflow": 100, "infra": 120, "doc": 90},
    "XL": {"code": 300, "workflow": 200, "infra": 250, "doc": 180},
}

# Spread factors for low/high from baseline (multiplier)
SPREAD = {
    "XS": 0.40,
    "S":  0.35,
    "M":  0.35,
    "L":  0.30,
    "XL": 0.30,
}


def ensure_log():
    """Create the log file if it doesn't exist."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        LOG_PATH.touch()


def load_log():
    """Load all records from the JSONL log."""
    ensure_log()
    records = []
    with open(LOG_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def append_record(record):
    """Append a single record to the log."""
    ensure_log()
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def generate_id():
    """Generate a unique task ID like T-2026-03-08-001."""
    today = date.today().isoformat()
    prefix = f"T-{today}-"
    records = load_log()
    # Count existing records with today's date
    today_count = sum(1 for r in records if r.get("id", "").startswith(prefix))
    return f"{prefix}{today_count + 1:03d}"


def days_ago(record):
    """How many days ago was this record created?"""
    rid = record.get("id", "")
    try:
        # Try to extract date from ID format T-YYYY-MM-DD-NNN
        parts = rid.split("-")
        if len(parts) >= 4 and parts[0] == "T":
            record_date = date.fromisoformat(f"{parts[1]}-{parts[2]}-{parts[3]}")
            return (date.today() - record_date).days
    except (ValueError, IndexError):
        pass
    # Check for a timestamp field
    ts = record.get("timestamp")
    if ts:
        try:
            record_date = datetime.fromisoformat(ts).date()
            return (date.today() - record_date).days
        except ValueError:
            pass
    return 365  # Unknown age, treat as old


def compute_weight(record):
    """Weight recent records more heavily. Last 90 days get 2x."""
    age = days_ago(record)
    if age <= 90:
        return 2.0
    elif age <= 365:
        return 1.0
    else:
        return 0.5


def tag_overlap(tags_a, tags_b):
    """Count how many tags overlap between two lists."""
    return len(set(tags_a) & set(tags_b))


STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "not", "no", "so",
    "if", "then", "than", "that", "this", "it", "its", "all", "each",
    "new", "add", "update", "fix", "set", "get",
})


def extract_keywords(text):
    """Extract meaningful keywords from a summary for similarity matching."""
    words = re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())
    return set(w for w in words if w not in STOP_WORDS)


def text_similarity(summary_a, summary_b):
    """Jaccard similarity between two summaries (0-1)."""
    kw_a = extract_keywords(summary_a)
    kw_b = extract_keywords(summary_b)
    if not kw_a or not kw_b:
        return 0.0
    return len(kw_a & kw_b) / len(kw_a | kw_b)


def compute_empirical_baseline(records, domain, size_hint, artifact_type):
    """
    Compute empirical baseline from ALL logged tasks — not just those
    with prior estimates. This lets the system learn from retroactively
    logged tasks too (which are often the majority of data).

    Returns (median_minutes, sample_count) or (None, 0) if insufficient data.
    """
    matching = [
        r for r in records
        if r.get("status") in ("done", "partial")
        and r.get("actual_minutes") is not None
        and r.get("domain") == domain
        and r.get("size_hint") == size_hint
    ]

    if len(matching) < 3:
        return None, 0

    actuals = sorted(r["actual_minutes"] for r in matching)
    n = len(actuals)
    median = actuals[n // 2] if n % 2 == 1 else (actuals[n // 2 - 1] + actuals[n // 2]) / 2
    return median, n


def compute_dynamic_spread(similar_records, base_spread):
    """
    Narrow the estimate range as more data accumulates. With few data
    points, fall back to the static spread. With many, use the empirical
    coefficient of variation (capped to avoid overconfidence).
    """
    actuals = [
        r.get("actual_minutes", 0)
        for _, r in similar_records
        if r.get("actual_minutes") and r.get("actual_minutes") > 0
    ]

    if len(actuals) < 5:
        return base_spread

    mean = sum(actuals) / len(actuals)
    if mean <= 0:
        return base_spread

    variance = sum((a - mean) ** 2 for a in actuals) / len(actuals)
    cv = math.sqrt(variance) / mean

    # Clamp empirical CV: floor at 0.10 (never overconfident), cap at 1.5x base
    empirical_spread = max(0.10, min(cv, base_spread * 1.5))

    # Blend: trust empirical more as sample grows (full trust at 15+ samples)
    data_weight = min(len(actuals) / 15, 1.0)
    return base_spread * (1 - data_weight) + empirical_spread * data_weight


def similarity_score(record, domain, framework_tags, size_hint, complexity, summary=""):
    """Score how similar a historical record is to the query (0-13 scale)."""
    score = 0.0

    # Domain match (strong signal)
    if record.get("domain") == domain:
        score += 3.0

    # Tag overlap
    rec_tags = record.get("framework_tags", [])
    overlap = tag_overlap(rec_tags, framework_tags)
    if overlap > 0:
        score += min(overlap * 1.5, 3.0)

    # Size hint match
    size_order = ["XS", "S", "M", "L", "XL"]
    try:
        rec_idx = size_order.index(record.get("size_hint", "M"))
        query_idx = size_order.index(size_hint)
        size_diff = abs(rec_idx - query_idx)
        if size_diff == 0:
            score += 2.0
        elif size_diff == 1:
            score += 1.0
    except ValueError:
        pass

    # Complexity match
    rec_complexity = record.get("complexity", 3)
    complexity_diff = abs(rec_complexity - complexity)
    if complexity_diff == 0:
        score += 2.0
    elif complexity_diff == 1:
        score += 1.0

    # Text similarity on summaries (bonus up to 3 points)
    if summary and record.get("summary"):
        sim = text_similarity(summary, record["summary"])
        score += sim * 3.0

    return score


def find_similar(records, domain, framework_tags, size_hint, complexity, summary="", min_score=3.0):
    """Find records similar to the query, sorted by relevance."""
    scored = []
    for r in records:
        # Only consider completed tasks with actual times
        if r.get("status") not in ("done", "partial"):
            continue
        if r.get("actual_minutes") is None:
            continue
        s = similarity_score(r, domain, framework_tags, size_hint, complexity, summary)
        if s >= min_score:
            scored.append((s, r))

    # Sort by score descending
    scored.sort(key=lambda x: -x[0])
    return scored


def compute_correction_factor(similar_records):
    """Compute weighted correction factor from similar records."""
    if not similar_records:
        return 1.0

    weighted_sum = 0.0
    weight_total = 0.0

    for score, record in similar_records:
        actual = record.get("actual_minutes", 0)
        est_low = record.get("estimate_low_min")
        est_high = record.get("estimate_high_min")

        if est_low is not None and est_high is not None and est_low > 0 and est_high > 0:
            midpoint = (est_low + est_high) / 2.0
            if midpoint > 0:
                ratio = actual / midpoint
                w = compute_weight(record) * (score / 10.0)
                weighted_sum += ratio * w
                weight_total += w

    if weight_total > 0:
        return weighted_sum / weight_total
    return 1.0


def compute_confidence(similar_records, correction_factor):
    """Compute confidence 0-1 based on sample size and consistency."""
    n = len(similar_records)
    if n == 0:
        return 0.2  # Very low confidence, pure priors

    # Base confidence from sample size (logarithmic)
    size_confidence = min(math.log(n + 1) / math.log(20), 1.0)  # Maxes at ~20 samples

    # Consistency: how tight are the correction factors?
    if n >= 2:
        factors = []
        for score, record in similar_records:
            actual = record.get("actual_minutes", 0)
            est_low = record.get("estimate_low_min")
            est_high = record.get("estimate_high_min")
            if est_low and est_high and est_low > 0 and est_high > 0:
                midpoint = (est_low + est_high) / 2.0
                if midpoint > 0:
                    factors.append(actual / midpoint)

        if len(factors) >= 2:
            mean_f = sum(factors) / len(factors)
            variance = sum((f - mean_f) ** 2 for f in factors) / len(factors)
            std_dev = math.sqrt(variance)
            # Lower std_dev = more consistent = higher confidence
            consistency = max(0.0, 1.0 - std_dev)
        else:
            consistency = 0.5
    else:
        consistency = 0.4

    # Blend: 60% sample size, 40% consistency
    confidence = 0.6 * size_confidence + 0.4 * consistency
    return round(min(max(confidence, 0.1), 0.95), 2)


def estimate(summary, domain, framework_tags, artifact_type, size_hint, complexity):
    """Estimate time for a task."""
    records = load_log()

    # Get static prior baseline
    static_prior = PRIORS.get(size_hint, PRIORS["M"]).get(artifact_type, PRIORS["M"]["code"])
    base_spread = SPREAD.get(size_hint, 0.35)

    # Try to compute an empirical baseline from ALL logged tasks (including
    # those without prior estimates). This is the key improvement: tasks logged
    # retroactively still teach us how long things take in a given bucket.
    empirical, emp_count = compute_empirical_baseline(records, domain, size_hint, artifact_type)

    if empirical is not None:
        # Blend static prior with empirical: trust empirical more as data grows
        # At 3 samples, 50/50. At 10+, almost fully empirical.
        emp_weight = min((emp_count - 2) / 8, 1.0)  # 0 at n=2, 1.0 at n=10
        prior = static_prior * (1 - emp_weight) + empirical * emp_weight
    else:
        prior = static_prior

    # Find similar records (now with text similarity on summaries)
    similar = find_similar(records, domain, framework_tags, size_hint, complexity, summary)

    # Compute correction factor from records that have estimate data
    correction = compute_correction_factor(similar)

    # Complexity multiplier: differentiates tasks of the same size.
    # Complexity 3 is neutral (1.0x). Each step adds/removes ~15%.
    # This prevents all M-sized tasks from getting identical estimates.
    complexity_multiplier = 1.0 + (complexity - 3) * 0.15

    # Apply correction and complexity to the blended prior
    best_guess = round(prior * correction * complexity_multiplier)

    # Dynamic spread: narrows with more data instead of staying fixed
    spread = compute_dynamic_spread(similar, base_spread)

    low = round(best_guess * (1 - spread))
    high = round(best_guess * (1 + spread))

    # Ensure reasonable bounds
    low = max(5, low)
    high = max(low + 5, high)
    best_guess = max(low, min(best_guess, high))

    # Compute confidence
    confidence = compute_confidence(similar, correction)

    # Build similar examples for basis
    similar_examples = []
    for score, record in similar[:5]:
        similar_examples.append({
            "id": record.get("id", "unknown"),
            "actual_minutes": record.get("actual_minutes"),
            "summary": record.get("summary", ""),
        })

    result = {
        "estimate_low_min": low,
        "estimate_high_min": high,
        "best_guess_min": best_guess,
        "confidence": confidence,
        "basis": {
            "sample_count": len(similar),
            "similar_examples": similar_examples,
            "correction_factor": round(correction, 3),
        },
    }

    return result


def log_outcome(
    summary, domain, framework_tags, artifact_type, size_hint, complexity,
    actual_minutes, status, estimate_low=None, estimate_high=None, task_id=None,
    project=None
):
    """Log the actual outcome of a task."""
    if task_id is None:
        task_id = generate_id()

    record = {
        "id": task_id,
        "timestamp": datetime.now().isoformat(),
        "summary": summary,
        "domain": domain,
        "framework_tags": framework_tags,
        "artifact_type": artifact_type,
        "size_hint": size_hint,
        "complexity": complexity,
        "actual_minutes": actual_minutes,
        "status": status,
    }

    if estimate_low is not None:
        record["estimate_low_min"] = estimate_low
    if estimate_high is not None:
        record["estimate_high_min"] = estimate_high
    if project is not None:
        record["project"] = project

    append_record(record)

    # Compute updated stats for the relevant bucket
    all_records = load_log()
    bucket_records = [
        r for r in all_records
        if r.get("domain") == domain
        and r.get("size_hint") == size_hint
        and r.get("status") in ("done", "partial")
        and r.get("actual_minutes") is not None
    ]

    # Compute bucket stats
    bucket_count = len(bucket_records)
    errors = []
    factors = []
    for r in bucket_records:
        est_low = r.get("estimate_low_min")
        est_high = r.get("estimate_high_min")
        actual = r.get("actual_minutes", 0)
        if est_low is not None and est_high is not None:
            midpoint = (est_low + est_high) / 2.0
            if midpoint > 0:
                factors.append(actual / midpoint)
                errors.append(abs(actual - midpoint))

    avg_correction = round(sum(factors) / len(factors), 3) if factors else 1.0
    avg_error = round(sum(errors) / len(errors), 1) if errors else 0.0

    return {
        "logged_id": task_id,
        "record": record,
        "bucket_stats": {
            "domain": domain,
            "size_hint": size_hint,
            "task_count": bucket_count,
            "avg_correction_factor": avg_correction,
            "avg_absolute_error_min": avg_error,
        },
    }


def calibration_summary():
    """Produce a calibration summary of estimation accuracy."""
    records = load_log()

    # Filter to records with both estimates and actuals
    valid = [
        r for r in records
        if r.get("status") in ("done", "partial")
        and r.get("actual_minutes") is not None
        and r.get("estimate_low_min") is not None
        and r.get("estimate_high_min") is not None
    ]

    if not valid:
        return {
            "total_tasks": len(records),
            "tasks_with_estimates": 0,
            "message": "No tasks with both estimates and actuals found yet. Log some outcomes to see calibration data.",
            "by_domain_size": [],
            "by_framework_tag": [],
        }

    # By (domain, size_hint)
    domain_size_buckets = defaultdict(list)
    for r in valid:
        key = (r["domain"], r["size_hint"])
        midpoint = (r["estimate_low_min"] + r["estimate_high_min"]) / 2.0
        actual = r["actual_minutes"]
        factor = actual / midpoint if midpoint > 0 else 1.0
        error = abs(actual - midpoint)
        domain_size_buckets[key].append({
            "factor": factor,
            "error": error,
            "days_ago": days_ago(r),
        })

    domain_size_summary = []
    for (domain, size_hint), items in sorted(domain_size_buckets.items()):
        count = len(items)
        mean_factor = sum(i["factor"] for i in items) / count
        mean_error = sum(i["error"] for i in items) / count

        # Trend: compare recent (last 30 days) vs older
        recent = [i for i in items if i["days_ago"] <= 30]
        older = [i for i in items if i["days_ago"] > 30]
        if len(recent) >= 2 and len(older) >= 2:
            recent_error = sum(i["error"] for i in recent) / len(recent)
            older_error = sum(i["error"] for i in older) / len(older)
            if recent_error < older_error * 0.8:
                trend = "improving"
            elif recent_error > older_error * 1.2:
                trend = "degrading"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        domain_size_summary.append({
            "domain": domain,
            "size_hint": size_hint,
            "count": count,
            "mean_correction_factor": round(mean_factor, 3),
            "avg_absolute_error_min": round(mean_error, 1),
            "trend": trend,
        })

    # By framework_tag (top tags)
    tag_buckets = defaultdict(list)
    for r in valid:
        midpoint = (r["estimate_low_min"] + r["estimate_high_min"]) / 2.0
        actual = r["actual_minutes"]
        factor = actual / midpoint if midpoint > 0 else 1.0
        error = abs(actual - midpoint)
        for tag in r.get("framework_tags", []):
            tag_buckets[tag].append({"factor": factor, "error": error})

    tag_summary = []
    for tag, items in sorted(tag_buckets.items(), key=lambda x: -len(x[1])):
        count = len(items)
        mean_factor = sum(i["factor"] for i in items) / count
        mean_error = sum(i["error"] for i in items) / count
        tag_summary.append({
            "tag": tag,
            "count": count,
            "mean_correction_factor": round(mean_factor, 3),
            "avg_absolute_error_min": round(mean_error, 1),
        })

    # Overall stats
    all_factors = []
    all_errors = []
    for r in valid:
        midpoint = (r["estimate_low_min"] + r["estimate_high_min"]) / 2.0
        actual = r["actual_minutes"]
        if midpoint > 0:
            all_factors.append(actual / midpoint)
            all_errors.append(abs(actual - midpoint))

    overall_correction = round(sum(all_factors) / len(all_factors), 3) if all_factors else 1.0
    overall_error = round(sum(all_errors) / len(all_errors), 1) if all_errors else 0.0

    return {
        "total_tasks": len(records),
        "tasks_with_estimates": len(valid),
        "overall_mean_correction_factor": overall_correction,
        "overall_avg_absolute_error_min": overall_error,
        "by_domain_size": domain_size_summary,
        "by_framework_tag": tag_summary[:10],  # Top 10 tags
    }


def get_record_date(record):
    """Extract the date from a record (from timestamp or ID)."""
    ts = record.get("timestamp")
    if ts:
        try:
            return datetime.fromisoformat(ts).date()
        except ValueError:
            pass
    rid = record.get("id", "")
    try:
        parts = rid.split("-")
        if len(parts) >= 4 and parts[0] == "T":
            return date.fromisoformat(f"{parts[1]}-{parts[2]}-{parts[3]}")
    except (ValueError, IndexError):
        pass
    return None


def project_summary(project, date_from=None, date_to=None):
    """Summarize time spent on a project, broken down by date."""
    records = load_log()

    # Filter to project
    project_records = [
        r for r in records
        if r.get("project", "").lower() == project.lower()
        and r.get("status") in ("done", "partial")
        and r.get("actual_minutes") is not None
    ]

    if not project_records:
        return {
            "project": project,
            "message": f"No logged tasks found for project '{project}'.",
            "total_minutes": 0,
            "total_tasks": 0,
            "by_date": [],
            "by_domain": [],
        }

    # Apply date filters
    if date_from:
        from_date = date.fromisoformat(date_from)
        project_records = [r for r in project_records if (get_record_date(r) or date.min) >= from_date]
    if date_to:
        to_date = date.fromisoformat(date_to)
        project_records = [r for r in project_records if (get_record_date(r) or date.max) <= to_date]

    total_minutes = sum(r["actual_minutes"] for r in project_records)
    total_tasks = len(project_records)

    # Group by date
    by_date_map = defaultdict(lambda: {"minutes": 0, "tasks": 0, "summaries": []})
    for r in project_records:
        d = get_record_date(r)
        date_key = d.isoformat() if d else "unknown"
        by_date_map[date_key]["minutes"] += r["actual_minutes"]
        by_date_map[date_key]["tasks"] += 1
        by_date_map[date_key]["summaries"].append(r.get("summary", ""))

    by_date = []
    for date_key in sorted(by_date_map.keys()):
        entry = by_date_map[date_key]
        by_date.append({
            "date": date_key,
            "minutes": round(entry["minutes"], 1),
            "hours": round(entry["minutes"] / 60, 2),
            "tasks": entry["tasks"],
            "summaries": entry["summaries"],
        })

    # Group by domain
    by_domain_map = defaultdict(lambda: {"minutes": 0, "tasks": 0})
    for r in project_records:
        domain = r.get("domain", "unknown")
        by_domain_map[domain]["minutes"] += r["actual_minutes"]
        by_domain_map[domain]["tasks"] += 1

    by_domain = []
    for domain, data in sorted(by_domain_map.items(), key=lambda x: -x[1]["minutes"]):
        by_domain.append({
            "domain": domain,
            "minutes": round(data["minutes"], 1),
            "hours": round(data["minutes"] / 60, 2),
            "tasks": data["tasks"],
        })

    return {
        "project": project,
        "total_minutes": round(total_minutes, 1),
        "total_hours": round(total_minutes / 60, 2),
        "total_tasks": total_tasks,
        "date_range": {
            "from": by_date[0]["date"] if by_date else None,
            "to": by_date[-1]["date"] if by_date else None,
        },
        "by_date": by_date,
        "by_domain": by_domain,
    }


def offer_estimate(phases_file, buffer_pct=25, hourly_rate=None):
    """Estimate an entire project broken into phases, with buffer for offers."""
    with open(phases_file, "r") as f:
        phases = json.load(f)

    phase_results = []
    grand_low = 0
    grand_best = 0
    grand_high = 0
    grand_buffered = 0

    for phase in phases:
        phase_name = phase.get("name", "Unnamed Phase")
        tasks = phase.get("tasks", [])
        task_results = []
        phase_low = 0
        phase_best = 0
        phase_high = 0
        phase_confidences = []

        for task in tasks:
            tags = task.get("framework_tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]

            est = estimate(
                summary=task.get("summary", ""),
                domain=task.get("domain", "web_app"),
                framework_tags=tags,
                artifact_type=task.get("artifact_type", "code"),
                size_hint=task.get("size_hint", "M"),
                complexity=task.get("complexity", 3),
            )
            task_results.append({
                "summary": task.get("summary", ""),
                "low_min": est["estimate_low_min"],
                "best_min": est["best_guess_min"],
                "high_min": est["estimate_high_min"],
                "confidence": est["confidence"],
            })
            phase_low += est["estimate_low_min"]
            phase_best += est["best_guess_min"]
            phase_high += est["estimate_high_min"]
            phase_confidences.append(est["confidence"])

        # Phase-level confidence = average of task confidences
        avg_confidence = (sum(phase_confidences) / len(phase_confidences)) if phase_confidences else 0.2

        # Risk-adjusted buffer: lower confidence → higher buffer
        # Base buffer_pct is for high-confidence work; scale up for uncertainty
        if avg_confidence >= 0.7:
            effective_buffer = buffer_pct
        elif avg_confidence >= 0.5:
            effective_buffer = buffer_pct * 1.25
        elif avg_confidence >= 0.3:
            effective_buffer = buffer_pct * 1.5
        else:
            effective_buffer = buffer_pct * 2.0
        effective_buffer = round(effective_buffer, 1)

        buffered_best = round(phase_best * (1 + effective_buffer / 100))

        phase_result = {
            "name": phase_name,
            "tasks": task_results,
            "task_count": len(task_results),
            "low_min": phase_low,
            "best_min": phase_best,
            "high_min": phase_high,
            "avg_confidence": round(avg_confidence, 2),
            "buffer_pct": effective_buffer,
            "buffered_min": buffered_best,
            "low_hours": round(phase_low / 60, 1),
            "best_hours": round(phase_best / 60, 1),
            "high_hours": round(phase_high / 60, 1),
            "buffered_hours": round(buffered_best / 60, 1),
        }

        if hourly_rate:
            phase_result["buffered_cost"] = round(buffered_best / 60 * hourly_rate, 2)

        phase_results.append(phase_result)
        grand_low += phase_low
        grand_best += phase_best
        grand_high += phase_high
        grand_buffered += buffered_best

    result = {
        "phases": phase_results,
        "totals": {
            "phases": len(phase_results),
            "tasks": sum(p["task_count"] for p in phase_results),
            "low_min": grand_low,
            "best_min": grand_best,
            "high_min": grand_high,
            "buffered_min": grand_buffered,
            "low_hours": round(grand_low / 60, 1),
            "best_hours": round(grand_best / 60, 1),
            "high_hours": round(grand_high / 60, 1),
            "buffered_hours": round(grand_buffered / 60, 1),
        },
        "buffer_pct_base": buffer_pct,
    }

    if hourly_rate:
        result["totals"]["buffered_cost"] = round(grand_buffered / 60 * hourly_rate, 2)
        result["hourly_rate"] = hourly_rate

    return result


def main():
    parser = argparse.ArgumentParser(description="Universal Time Estimator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ESTIMATE
    est_parser = subparsers.add_parser("estimate", help="Estimate time for a task")
    est_parser.add_argument("--summary", required=True)
    est_parser.add_argument("--domain", required=True)
    est_parser.add_argument("--framework-tags", required=True, help="Comma-separated tags")
    est_parser.add_argument("--artifact-type", required=True)
    est_parser.add_argument("--size-hint", required=True, choices=["XS", "S", "M", "L", "XL"])
    est_parser.add_argument("--complexity", required=True, type=int, choices=range(1, 6))

    # LOG_OUTCOME
    log_parser = subparsers.add_parser("log_outcome", help="Log actual task outcome")
    log_parser.add_argument("--summary", required=True)
    log_parser.add_argument("--domain", required=True)
    log_parser.add_argument("--framework-tags", required=True, help="Comma-separated tags")
    log_parser.add_argument("--artifact-type", required=True)
    log_parser.add_argument("--size-hint", required=True, choices=["XS", "S", "M", "L", "XL"])
    log_parser.add_argument("--complexity", required=True, type=int, choices=range(1, 6))
    log_parser.add_argument("--actual-minutes", required=True, type=float)
    log_parser.add_argument("--status", required=True, choices=["done", "partial", "abandoned"])
    log_parser.add_argument("--estimate-low", type=float, default=None)
    log_parser.add_argument("--estimate-high", type=float, default=None)
    log_parser.add_argument("--id", default=None)
    log_parser.add_argument("--project", default=None, help="Project name for time tracking")

    # CALIBRATION_SUMMARY
    subparsers.add_parser("calibration_summary", help="Show estimation accuracy stats")

    # PROJECT_SUMMARY
    proj_parser = subparsers.add_parser("project_summary", help="Time spent on a project by date")
    proj_parser.add_argument("--project", required=True, help="Project name (case-insensitive)")
    proj_parser.add_argument("--from", dest="date_from", default=None, help="Start date YYYY-MM-DD")
    proj_parser.add_argument("--to", dest="date_to", default=None, help="End date YYYY-MM-DD")

    # OFFER_ESTIMATE
    offer_parser = subparsers.add_parser("offer_estimate", help="Estimate a full project for an offer")
    offer_parser.add_argument("--phases-file", required=True, help="Path to JSON file with phases and tasks")
    offer_parser.add_argument("--buffer", type=float, default=25, help="Base buffer percentage (default 25)")
    offer_parser.add_argument("--hourly-rate", type=float, default=None, help="Hourly rate for cost calculation")

    args = parser.parse_args()

    if args.command == "estimate":
        tags = [t.strip() for t in args.framework_tags.split(",") if t.strip()]
        result = estimate(
            summary=args.summary,
            domain=args.domain,
            framework_tags=tags,
            artifact_type=args.artifact_type,
            size_hint=args.size_hint,
            complexity=args.complexity,
        )
        print(json.dumps(result, indent=2))

    elif args.command == "log_outcome":
        tags = [t.strip() for t in args.framework_tags.split(",") if t.strip()]
        result = log_outcome(
            summary=args.summary,
            domain=args.domain,
            framework_tags=tags,
            artifact_type=args.artifact_type,
            size_hint=args.size_hint,
            complexity=args.complexity,
            actual_minutes=args.actual_minutes,
            status=args.status,
            estimate_low=args.estimate_low,
            estimate_high=args.estimate_high,
            task_id=args.id,
            project=args.project,
        )
        print(json.dumps(result, indent=2))

    elif args.command == "calibration_summary":
        result = calibration_summary()
        print(json.dumps(result, indent=2))

    elif args.command == "project_summary":
        result = project_summary(
            project=args.project,
            date_from=args.date_from,
            date_to=args.date_to,
        )
        print(json.dumps(result, indent=2))

    elif args.command == "offer_estimate":
        result = offer_estimate(
            phases_file=args.phases_file,
            buffer_pct=args.buffer,
            hourly_rate=args.hourly_rate,
        )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
