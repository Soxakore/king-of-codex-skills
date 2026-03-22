#!/usr/bin/env python3
"""Render a markdown report and Mermaid graph from local skill run telemetry."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "telemetry" / "skill-runs.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "telemetry" / "skill-report.md"
OUTCOME_SCORES = {
    "success": 1.0,
    "partial": 0.55,
    "failed": 0.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a skill effectiveness report from a JSONL log."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--graph-limit",
        type=int,
        default=6,
        help="Maximum number of skills, challenges, and upgrades to include in the graph.",
    )
    return parser.parse_args()


def load_runs(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"Input log does not exist: {path}")
    runs = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            runs.append(json.loads(line))
    if not runs:
        raise SystemExit(f"No runs found in: {path}")
    return runs


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "node"


def format_percent(value: float) -> str:
    return f"{value:.1f}%"


def format_float(value: float) -> str:
    return f"{value:.1f}"


def mermaid_escape(value: str) -> str:
    return value.replace('"', "'")


def aggregate_runs(runs: list[dict]) -> dict:
    skill_stats: dict[str, dict[str, list[float] | int]] = defaultdict(
        lambda: {
            "runs": 0,
            "efficiency_scores": [],
            "duration_minutes": [],
            "value_scores": [],
            "friction_scores": [],
            "completion_scores": [],
        }
    )
    challenge_counts: Counter[str] = Counter()
    upgrade_counts: Counter[str] = Counter()
    skill_challenge_counts: dict[str, Counter[str]] = defaultdict(Counter)
    challenge_upgrade_counts: dict[str, Counter[str]] = defaultdict(Counter)
    challenge_skills: dict[str, set[str]] = defaultdict(set)
    upgrade_skills: dict[str, set[str]] = defaultdict(set)
    upgrade_friction: dict[str, list[float]] = defaultdict(list)

    for run in runs:
        outcome_score = OUTCOME_SCORES.get(run["outcome"], 0.0)
        skills = run.get("skills", [])
        challenges = run.get("challenge_tags", [])
        upgrades = run.get("upgrade_candidates", [])

        for skill in skills:
            stats = skill_stats[skill]
            stats["runs"] += 1
            stats["efficiency_scores"].append(float(run["efficiency_score"]))
            stats["duration_minutes"].append(float(run["duration_minutes"]))
            stats["value_scores"].append(float(run["value_score"]))
            stats["friction_scores"].append(float(run["friction_score"]))
            stats["completion_scores"].append(outcome_score)
            for challenge in challenges:
                skill_challenge_counts[skill][challenge] += 1
                challenge_skills[challenge].add(skill)
            for upgrade in upgrades:
                upgrade_skills[upgrade].add(skill)
                upgrade_friction[upgrade].append(float(run["friction_score"]))

        for challenge in challenges:
            challenge_counts[challenge] += 1
            for upgrade in upgrades:
                challenge_upgrade_counts[challenge][upgrade] += 1

        for upgrade in upgrades:
            upgrade_counts[upgrade] += 1

    return {
        "skill_stats": skill_stats,
        "challenge_counts": challenge_counts,
        "upgrade_counts": upgrade_counts,
        "skill_challenge_counts": skill_challenge_counts,
        "challenge_upgrade_counts": challenge_upgrade_counts,
        "challenge_skills": challenge_skills,
        "upgrade_skills": upgrade_skills,
        "upgrade_friction": upgrade_friction,
    }


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_overview_table(skill_stats: dict[str, dict]) -> str:
    lines = [
        "| Skill | Runs | Avg efficiency | Delivery index | Avg friction | Avg duration |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    ordered = sorted(
        skill_stats.items(),
        key=lambda item: (-item[1]["runs"], -avg(item[1]["efficiency_scores"])),
    )
    for skill, stats in ordered:
        delivery_index = avg(stats["completion_scores"]) * 100
        lines.append(
            "| {skill} | {runs} | {efficiency} | {delivery} | {friction} | {duration} min |".format(
                skill=skill,
                runs=stats["runs"],
                efficiency=format_float(avg(stats["efficiency_scores"])),
                delivery=format_percent(delivery_index),
                friction=format_float(avg(stats["friction_scores"])),
                duration=format_float(avg(stats["duration_minutes"])),
            )
        )
    return "\n".join(lines)


def build_challenge_table(
    challenge_counts: Counter[str], challenge_skills: dict[str, set[str]]
) -> str:
    lines = [
        "| Challenge tag | Hits | Skills impacted |",
        "| --- | ---: | --- |",
    ]
    for challenge, count in challenge_counts.most_common():
        lines.append(
            f"| {challenge} | {count} | {', '.join(sorted(challenge_skills[challenge]))} |"
        )
    return "\n".join(lines)


def build_upgrade_table(
    upgrade_counts: Counter[str],
    upgrade_skills: dict[str, set[str]],
    upgrade_friction: dict[str, list[float]],
) -> str:
    lines = [
        "| Upgrade candidate | Mentions | Skills helped | Avg friction behind it | Priority score |",
        "| --- | ---: | --- | ---: | ---: |",
    ]
    ordered = sorted(
        upgrade_counts.items(),
        key=lambda item: (
            -(item[1] * avg(upgrade_friction[item[0]])),
            -item[1],
            item[0],
        ),
    )
    for upgrade, mentions in ordered:
        friction = avg(upgrade_friction[upgrade])
        priority = mentions * friction * 10
        lines.append(
            "| {upgrade} | {mentions} | {skills} | {friction} | {priority} |".format(
                upgrade=upgrade,
                mentions=mentions,
                skills=", ".join(sorted(upgrade_skills[upgrade])),
                friction=format_float(friction),
                priority=format_float(priority),
            )
        )
    return "\n".join(lines)


def build_recent_runs(runs: list[dict], limit: int = 10) -> str:
    lines = [
        "| Timestamp | Skills | Outcome | Eff. | Task |",
        "| --- | --- | --- | ---: | --- |",
    ]
    ordered = sorted(runs, key=lambda item: item["timestamp"], reverse=True)[:limit]
    for run in ordered:
        lines.append(
            "| {timestamp} | {skills} | {outcome} | {efficiency} | {task} |".format(
                timestamp=run["timestamp"],
                skills=", ".join(run["skills"]),
                outcome=run["outcome"],
                efficiency=format_float(float(run["efficiency_score"])),
                task=run["task"],
            )
        )
    return "\n".join(lines)


def build_mermaid(
    skill_stats: dict[str, dict],
    challenge_counts: Counter[str],
    upgrade_counts: Counter[str],
    skill_challenge_counts: dict[str, Counter[str]],
    challenge_upgrade_counts: dict[str, Counter[str]],
    graph_limit: int,
) -> str:
    top_skills = sorted(
        skill_stats,
        key=lambda skill: (-skill_stats[skill]["runs"], -avg(skill_stats[skill]["efficiency_scores"])),
    )[:graph_limit]
    top_challenges = [name for name, _ in challenge_counts.most_common(graph_limit)]
    top_upgrades = [name for name, _ in upgrade_counts.most_common(graph_limit)]

    lines = ["graph LR"]

    for skill in top_skills:
        label = mermaid_escape(
            f"{skill}\\nruns: {skill_stats[skill]['runs']}\\navg eff: {format_float(avg(skill_stats[skill]['efficiency_scores']))}"
        )
        lines.append(f'  skill_{slug(skill)}["{label}"]')

    for challenge in top_challenges:
        label = mermaid_escape(f"{challenge}\\nhits: {challenge_counts[challenge]}")
        lines.append(f'  challenge_{slug(challenge)}["{label}"]')

    for upgrade in top_upgrades:
        label = mermaid_escape(f"{upgrade}\\nmentions: {upgrade_counts[upgrade]}")
        lines.append(f'  upgrade_{slug(upgrade)}["{label}"]')

    for skill in top_skills:
        for challenge, count in skill_challenge_counts[skill].most_common(graph_limit):
            if challenge not in top_challenges:
                continue
            lines.append(
                f"  skill_{slug(skill)} -->|{count}| challenge_{slug(challenge)}"
            )

    for challenge in top_challenges:
        for upgrade, count in challenge_upgrade_counts[challenge].most_common(graph_limit):
            if upgrade not in top_upgrades:
                continue
            lines.append(
                f"  challenge_{slug(challenge)} -->|{count}| upgrade_{slug(upgrade)}"
            )

    return "\n".join(lines)


def build_report(runs: list[dict], aggregates: dict, graph_limit: int) -> str:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    mermaid = build_mermaid(
        skill_stats=aggregates["skill_stats"],
        challenge_counts=aggregates["challenge_counts"],
        upgrade_counts=aggregates["upgrade_counts"],
        skill_challenge_counts=aggregates["skill_challenge_counts"],
        challenge_upgrade_counts=aggregates["challenge_upgrade_counts"],
        graph_limit=graph_limit,
    )
    report = f"""# Skill Effectiveness Report

Generated: `{generated_at}`

Tracked runs: **{len(runs)}**

## Usage Overview

{build_overview_table(aggregates["skill_stats"])}

## Challenge Hotspots

{build_challenge_table(aggregates["challenge_counts"], aggregates["challenge_skills"])}

## Upgrade Backlog

{build_upgrade_table(
    aggregates["upgrade_counts"],
    aggregates["upgrade_skills"],
    aggregates["upgrade_friction"],
)}

## Graph

```mermaid
{mermaid}
```

## Recent Runs

{build_recent_runs(runs)}

## How To Use This

- Log each notable skill run, especially when a task was harder than expected or produced a reusable lesson.
- Watch for repeated challenge tags. Once a tag appears more than once, it should usually become a template, checklist, script, or skill update.
- Use the upgrade backlog as the maintenance queue. Higher priority scores mean the same pain keeps showing up with real friction.
"""
    return report


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    runs = load_runs(input_path)
    aggregates = aggregate_runs(runs)
    report = build_report(runs, aggregates, args.graph_limit)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Wrote report -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
