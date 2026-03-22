#!/usr/bin/env python3
"""Append a structured skill run record to a local JSONL log."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = REPO_ROOT / "telemetry" / "skill-runs.jsonl"
OUTCOME_SCORES = {
    "success": 1.0,
    "partial": 0.55,
    "failed": 0.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Log a Codex skill run to a local JSONL file."
    )
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--skill", action="append", required=True, dest="skills")
    parser.add_argument("--task", required=True, help="Short label for the task.")
    parser.add_argument(
        "--outcome",
        choices=sorted(OUTCOME_SCORES),
        required=True,
        help="How the run ended.",
    )
    parser.add_argument(
        "--duration-minutes",
        type=float,
        required=True,
        help="Approximate runtime in minutes.",
    )
    parser.add_argument(
        "--value-score",
        type=int,
        default=3,
        help="User or business value from 1-5.",
    )
    parser.add_argument(
        "--effort-score",
        type=int,
        default=3,
        help="Implementation effort from 1-5.",
    )
    parser.add_argument(
        "--friction-score",
        type=int,
        default=3,
        help="Friction encountered from 1-5.",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.75,
        help="Confidence in the outcome from 0.0-1.0.",
    )
    parser.add_argument(
        "--challenge",
        action="append",
        default=[],
        dest="challenge_tags",
        help="Repeatable challenge tag. Can be passed multiple times.",
    )
    parser.add_argument(
        "--upgrade",
        action="append",
        default=[],
        dest="upgrade_candidates",
        help="Improvement idea triggered by the run. Can be passed multiple times.",
    )
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="Optional receipt such as a file path, test command, or commit hash.",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional short note about what happened.",
    )
    parser.add_argument(
        "--timestamp",
        default="",
        help="Override ISO-8601 timestamp. Defaults to now in UTC.",
    )
    return parser.parse_args()


def clamp_score(name: str, value: int) -> int:
    if value < 1 or value > 5:
        raise SystemExit(f"{name} must be between 1 and 5.")
    return value


def clamp_confidence(value: float) -> float:
    if value < 0 or value > 1:
        raise SystemExit("confidence must be between 0.0 and 1.0.")
    return value


def compute_efficiency(
    outcome: str,
    value_score: int,
    effort_score: int,
    friction_score: int,
    confidence: float,
) -> float:
    outcome_component = OUTCOME_SCORES[outcome]
    value_component = value_score / 5
    effort_component = (6 - effort_score) / 5
    friction_component = (6 - friction_score) / 5
    score = 100 * (
        0.40 * outcome_component
        + 0.20 * value_component
        + 0.15 * effort_component
        + 0.15 * friction_component
        + 0.10 * confidence
    )
    return round(score, 1)


def normalize_timestamp(raw: str) -> str:
    if raw:
        return raw
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main() -> int:
    args = parse_args()
    value_score = clamp_score("value-score", args.value_score)
    effort_score = clamp_score("effort-score", args.effort_score)
    friction_score = clamp_score("friction-score", args.friction_score)
    confidence = clamp_confidence(args.confidence)
    efficiency_score = compute_efficiency(
        outcome=args.outcome,
        value_score=value_score,
        effort_score=effort_score,
        friction_score=friction_score,
        confidence=confidence,
    )

    log_path = Path(args.log_path).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "version": 1,
        "run_id": uuid.uuid4().hex[:12],
        "timestamp": normalize_timestamp(args.timestamp),
        "skills": sorted(set(args.skills)),
        "task": args.task.strip(),
        "outcome": args.outcome,
        "duration_minutes": round(args.duration_minutes, 2),
        "value_score": value_score,
        "effort_score": effort_score,
        "friction_score": friction_score,
        "confidence": round(confidence, 2),
        "efficiency_score": efficiency_score,
        "challenge_tags": sorted(set(args.challenge_tags)),
        "upgrade_candidates": sorted(set(args.upgrade_candidates)),
        "evidence": args.evidence,
        "notes": args.notes.strip(),
    }

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")

    print(f"Logged run {record['run_id']} -> {log_path}")
    print(f"Skills: {', '.join(record['skills'])}")
    print(f"Efficiency score: {efficiency_score}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
