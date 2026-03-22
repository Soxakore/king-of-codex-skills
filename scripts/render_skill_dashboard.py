#!/usr/bin/env python3
"""Render a live stock-board style skill telemetry dashboard."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from render_skill_report import DEFAULT_INPUTS, avg, load_runs_from_path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML_OUTPUT = REPO_ROOT / "telemetry" / "skill-dashboard.html"
DEFAULT_JSON_OUTPUT = REPO_ROOT / "telemetry" / "skill-dashboard.json"
OUTCOME_SCORES = {
    "success": 1.0,
    "partial": 0.55,
    "failed": 0.0,
}
TIMEFRAMES = {
    "day": 1,
    "week": 7,
    "month": 30,
}
TOKEN_KEYS = [
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a ranked skill telemetry dashboard as HTML plus JSON."
    )
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Repeatable input JSONL path. If omitted, uses existing local telemetry logs.",
    )
    parser.add_argument("--html-output", default=str(DEFAULT_HTML_OUTPUT))
    parser.add_argument("--json-output", default=str(DEFAULT_JSON_OUTPUT))
    return parser.parse_args()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def get_input_paths(raw_inputs: list[str]) -> list[Path]:
    if raw_inputs:
        return [Path(item).expanduser().resolve() for item in raw_inputs]
    return [path.resolve() for path in DEFAULT_INPUTS if path.exists()]


def load_runs(paths: list[Path]) -> list[dict]:
    runs = []
    for path in paths:
        if not path.exists():
            raise SystemExit(f"Input log does not exist: {path}")
        runs.extend(load_runs_from_path(path))
    if not runs:
        raise SystemExit("No runs found in the provided telemetry logs.")
    runs.sort(key=lambda item: item["timestamp"])
    return runs


def empty_tokens() -> dict[str, int]:
    return {key: 0 for key in TOKEN_KEYS}


def get_tokens(run: dict) -> dict[str, int]:
    raw = run.get("token_usage") or {}
    tokens = empty_tokens()
    for key in TOKEN_KEYS:
        tokens[key] = int(raw.get(key) or 0)
    return tokens


def token_total(run: dict) -> int:
    return get_tokens(run)["total_tokens"]


def normalize_delta(current: float, previous: float) -> float:
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return ((current - previous) / previous) * 100


def daily_window(end_day: datetime, days: int) -> list[datetime]:
    start = end_day - timedelta(days=days - 1)
    return [start + timedelta(days=offset) for offset in range(days)]


def build_series(items: list[dict], end_day: datetime, days: int) -> dict[str, list[float]]:
    window = daily_window(end_day, days)
    run_counts = Counter()
    token_counts = Counter()
    efficiency_totals = defaultdict(list)
    for item in items:
        day_key = item["_dt"].date().isoformat()
        run_counts[day_key] += 1
        token_counts[day_key] += item["_token_total"]
        efficiency_totals[day_key].append(float(item["efficiency_score"]))

    dates = [day.date().isoformat() for day in window]
    return {
        "dates": dates,
        "runs": [run_counts.get(day_key, 0) for day_key in dates],
        "tokens": [token_counts.get(day_key, 0) for day_key in dates],
        "efficiency": [round(avg(efficiency_totals.get(day_key, [])), 1) for day_key in dates],
    }


def build_window_metrics(items: list[dict], end_at: datetime, days: int) -> dict:
    current_start = end_at - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)
    current_items = [item for item in items if item["_dt"] > current_start]
    previous_items = [item for item in items if previous_start < item["_dt"] <= current_start]

    current_runs = len(current_items)
    previous_runs = len(previous_items)
    current_tokens = sum(item["_token_total"] for item in current_items)
    previous_tokens = sum(item["_token_total"] for item in previous_items)

    base_items = current_items or items
    metrics = {
        "runs": current_runs,
        "previous_runs": previous_runs,
        "delta_runs": current_runs - previous_runs,
        "delta_runs_pct": round(normalize_delta(current_runs, previous_runs), 1),
        "tokens": current_tokens,
        "previous_tokens": previous_tokens,
        "delta_tokens": current_tokens - previous_tokens,
        "delta_tokens_pct": round(normalize_delta(current_tokens, previous_tokens), 1),
        "avg_efficiency": round(avg([float(item["efficiency_score"]) for item in base_items]), 1),
        "delivery": round(avg([OUTCOME_SCORES.get(item["outcome"], 0.0) for item in base_items]) * 100, 1),
        "friction": round(avg([float(item["friction_score"]) for item in base_items]), 1),
        "duration": round(avg([float(item["duration_minutes"]) for item in base_items]), 1),
        "value": round(avg([float(item["value_score"]) for item in base_items]), 1),
        "input_tokens": sum(item["_tokens"]["input_tokens"] for item in current_items),
        "cached_input_tokens": sum(item["_tokens"]["cached_input_tokens"] for item in current_items),
        "output_tokens": sum(item["_tokens"]["output_tokens"] for item in current_items),
        "reasoning_output_tokens": sum(item["_tokens"]["reasoning_output_tokens"] for item in current_items),
    }
    metrics["rank_score"] = round(
        (metrics["runs"] * 8.0)
        + min(metrics["tokens"] / 2500, 42)
        + (metrics["avg_efficiency"] * 0.52)
        + (metrics["delivery"] * 0.34)
        + max(metrics["delta_runs"], 0) * 5.5
        + max(metrics["delta_tokens"], 0) / 3200
        - (metrics["friction"] * 4.2)
        - (metrics["duration"] * 0.28),
        1,
    )
    metrics["state"] = classify_move(metrics)
    return metrics


def classify_move(metrics: dict) -> str:
    if metrics["runs"] >= 3 and metrics["delta_runs"] >= 2 and metrics["avg_efficiency"] >= 85:
        return "surging"
    if metrics["delta_runs"] > 0 or metrics["delta_tokens"] > 0:
        return "rising"
    if metrics["delta_runs"] < 0 or metrics["delta_tokens"] < 0:
        return "cooling"
    if metrics["delivery"] >= 90:
        return "steady"
    return "watch"


def build_calendar(items: list[dict], end_day: datetime, days: int = 42) -> list[dict]:
    window = daily_window(end_day, days)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        grouped[item["_dt"].date().isoformat()].append(item)

    cells = []
    for day in window:
        day_key = day.date().isoformat()
        group = grouped.get(day_key, [])
        cells.append(
            {
                "date": day_key,
                "runs": len(group),
                "tokens": sum(item["_token_total"] for item in group),
                "avg_efficiency": round(avg([float(item["efficiency_score"]) for item in group]), 1),
                "weekday": day.weekday(),
                "day": day.day,
            }
        )
    return cells


def build_skill_entries(runs: list[dict], last_run_at: datetime, end_day: datetime) -> list[dict]:
    skill_runs: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        for skill in run.get("skills", []):
            skill_runs[skill].append(run)

    entries = []
    for skill, items in skill_runs.items():
        items = sorted(items, key=lambda item: item["_dt"])
        windows = {
            timeframe: build_window_metrics(items, last_run_at, days)
            for timeframe, days in TIMEFRAMES.items()
        }
        entry = {
            "skill": skill,
            "total_runs": len(items),
            "total_tokens": sum(item["_token_total"] for item in items),
            "all_time_efficiency": round(avg([float(item["efficiency_score"]) for item in items]), 1),
            "all_time_delivery": round(avg([OUTCOME_SCORES.get(item["outcome"], 0.0) for item in items]) * 100, 1),
            "all_time_friction": round(avg([float(item["friction_score"]) for item in items]), 1),
            "last_seen": iso(items[-1]["_dt"]),
            "usage_share": round((len(items) / max(len(runs), 1)) * 100, 1),
            "windows": windows,
            "series_30d": build_series(items, end_day, 30),
        }
        entries.append(entry)
    return entries


def top_for_frame(entries: list[dict], timeframe: str, limit: int = 12) -> list[dict]:
    ordered = sorted(
        entries,
        key=lambda item: (
            -item["windows"][timeframe]["rank_score"],
            -item["windows"][timeframe]["runs"],
            item["skill"],
        ),
    )
    result = []
    for index, item in enumerate(ordered[:limit], start=1):
        clone = dict(item)
        clone["rank"] = index
        result.append(clone)
    return result


def build_challenges(runs: list[dict]) -> list[dict]:
    challenge_counts: Counter[str] = Counter()
    challenge_skills: dict[str, set[str]] = defaultdict(set)
    for run in runs:
        for challenge in run.get("challenge_tags", []):
            challenge_counts[challenge] += 1
            for skill in run.get("skills", []):
                challenge_skills[challenge].add(skill)
    return [
        {
            "challenge": challenge,
            "hits": count,
            "skills": sorted(challenge_skills[challenge]),
        }
        for challenge, count in challenge_counts.most_common(10)
    ]


def build_recent_runs(runs: list[dict]) -> list[dict]:
    ordered = sorted(runs, key=lambda item: item["timestamp"], reverse=True)[:14]
    return [
        {
            "timestamp": run["timestamp"],
            "skills": run.get("skills", []),
            "outcome": run["outcome"],
            "efficiency": float(run["efficiency_score"]),
            "task": run["task"],
            "total_tokens": run["_token_total"],
        }
        for run in ordered
    ]


def build_overview(runs: list[dict], last_run_at: datetime) -> dict:
    frames = {
        timeframe: build_window_metrics(runs, last_run_at, days)
        for timeframe, days in TIMEFRAMES.items()
    }
    return {
        "total_runs": len(runs),
        "active_skills": len({skill for run in runs for skill in run.get("skills", [])}),
        "avg_efficiency": round(avg([float(run["efficiency_score"]) for run in runs]), 1),
        "avg_delivery": round(avg([OUTCOME_SCORES.get(run["outcome"], 0.0) for run in runs]) * 100, 1),
        "total_tokens": sum(run["_token_total"] for run in runs),
        "frames": frames,
    }


def build_payload(runs: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    for run in runs:
        run["_dt"] = parse_ts(run["timestamp"])
        run["_tokens"] = get_tokens(run)
        run["_token_total"] = run["_tokens"]["total_tokens"]

    last_run_at = max(run["_dt"] for run in runs)
    end_day = datetime.combine(last_run_at.date(), datetime.min.time(), tzinfo=timezone.utc)

    entries = build_skill_entries(runs, last_run_at, end_day)
    overview = build_overview(runs, last_run_at)
    calendar = build_calendar(runs, end_day, 42)
    challenges = build_challenges(runs)
    recent_runs = build_recent_runs(runs)

    leaders = {
        timeframe: top_for_frame(entries, timeframe, 16)
        for timeframe in TIMEFRAMES
    }
    movers = {}
    cooling = {}
    token_leaders = {}
    watchlist = {}
    for timeframe in TIMEFRAMES:
        ordered = leaders[timeframe]
        movers[timeframe] = sorted(
            ordered,
            key=lambda item: (
                -item["windows"][timeframe]["delta_runs"],
                -item["windows"][timeframe]["delta_tokens_pct"],
                -item["windows"][timeframe]["rank_score"],
            ),
        )[:6]
        cooling[timeframe] = sorted(
            ordered,
            key=lambda item: (
                item["windows"][timeframe]["delta_runs"],
                item["windows"][timeframe]["delta_tokens_pct"],
                -item["windows"][timeframe]["rank_score"],
            ),
        )[:6]
        token_leaders[timeframe] = sorted(
            entries,
            key=lambda item: (
                -item["windows"][timeframe]["tokens"],
                -item["windows"][timeframe]["output_tokens"],
                item["skill"],
            ),
        )[:10]
        watchlist[timeframe] = sorted(
            entries,
            key=lambda item: (
                item["windows"][timeframe]["avg_efficiency"]
                + item["windows"][timeframe]["delivery"]
                - item["windows"][timeframe]["friction"] * 20
                - min(item["windows"][timeframe]["tokens"] / 5000, 20),
                item["windows"][timeframe]["rank_score"],
            ),
        )[:8]

    payload = {
        "generated_at": iso(now),
        "last_run_at": iso(last_run_at),
        "overview": overview,
        "timeframes": list(TIMEFRAMES.keys()),
        "leaders": leaders,
        "movers": movers,
        "cooling": cooling,
        "watchlist": watchlist,
        "token_leaders": token_leaders,
        "skills": entries,
        "calendar": calendar,
        "calendar_days": [cell["date"] for cell in calendar],
        "challenges": challenges,
        "recent_runs": recent_runs,
    }
    return payload


def render_html(payload: dict) -> str:
    bootstrap_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex Skill Exchange</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%23080d17'/%3E%3Cpath d='M14 43V21h8.5l7.1 12.6L36.7 21H45v22h-5.8V30.8l-7.1 12.1h-5L20 30.8V43Z' fill='%2356d7ff'/%3E%3C/svg%3E">
  <style>
    :root {
      --bg: #04070d;
      --bg-soft: #090f18;
      --panel: rgba(8, 13, 23, 0.94);
      --panel-strong: rgba(4, 8, 14, 0.98);
      --panel-glow: linear-gradient(180deg, rgba(23, 31, 48, 0.94), rgba(8, 13, 23, 0.98));
      --line: rgba(124, 155, 196, 0.14);
      --cyan: #57d8ff;
      --cyan-2: #89e7ff;
      --green: #30d48a;
      --red: #ff5c7c;
      --amber: #ffbd63;
      --violet: #8193ff;
      --ink: #edf5ff;
      --muted: #7f92ad;
      --muted-2: #617089;
      --radius: 20px;
      --radius-sm: 13px;
      --shadow: 0 22px 60px rgba(0, 0, 0, 0.28);
    }

    * { box-sizing: border-box; }

    html, body {
      margin: 0;
      min-height: 100%;
      background:
        radial-gradient(circle at 12% 12%, rgba(69, 122, 255, 0.18), transparent 26%),
        radial-gradient(circle at 88% 16%, rgba(87, 216, 255, 0.12), transparent 20%),
        radial-gradient(circle at 48% 100%, rgba(38, 184, 117, 0.08), transparent 24%),
        linear-gradient(180deg, #04070d 0%, #03060c 100%);
      color: var(--ink);
      font-family: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
    }

    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(102, 134, 179, 0.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(102, 134, 179, 0.042) 1px, transparent 1px);
      background-size: 28px 28px;
      mask-image: linear-gradient(180deg, rgba(255,255,255,0.85), rgba(255,255,255,0.15));
    }

    .app-shell {
      max-width: 1680px;
      margin: 0 auto;
      padding: 22px;
    }

    .panel {
      background: var(--panel-glow);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
      backdrop-filter: blur(18px);
    }

    .command-bar {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      grid-template-areas:
        "brand controls"
        "meta meta";
      gap: 18px 24px;
      align-items: start;
      padding: 22px 24px;
      margin-bottom: 18px;
    }

    .brand-cluster {
      grid-area: brand;
      display: flex;
      align-items: center;
      gap: 16px;
      min-width: 0;
    }

    .brand-mark {
      width: 48px;
      height: 48px;
      border-radius: 14px;
      display: grid;
      place-items: center;
      font-weight: 800;
      letter-spacing: 0.08em;
      background:
        radial-gradient(circle at top, rgba(87, 216, 255, 0.32), transparent 70%),
        linear-gradient(180deg, rgba(35, 52, 79, 0.96), rgba(13, 21, 35, 1));
      border: 1px solid rgba(87, 216, 255, 0.18);
      color: var(--cyan-2);
      box-shadow: inset 0 0 30px rgba(87, 216, 255, 0.08);
    }

    .eyebrow {
      color: var(--cyan-2);
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.22em;
    }

    .desk-title {
      margin-top: 4px;
      font-size: clamp(1.6rem, 2.6vw, 2.4rem);
      letter-spacing: -0.05em;
      font-weight: 720;
    }

    .desk-subtitle {
      margin-top: 6px;
      color: var(--muted);
      font-size: 0.9rem;
    }

    .control-cluster {
      grid-area: controls;
      display: grid;
      gap: 12px;
      justify-items: end;
      align-content: start;
    }

    .segmented {
      display: inline-flex;
      flex-wrap: wrap;
      gap: 10px;
      padding: 10px;
      background: rgba(8, 14, 24, 0.88);
      border: 1px solid rgba(124, 155, 196, 0.12);
      border-radius: 999px;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.015);
    }

    .segmented.compact {
      padding: 6px;
      gap: 6px;
    }

    .segmented button,
    .nav-button {
      border: 0;
      background: rgba(54, 73, 99, 0.16);
      color: var(--muted);
      cursor: pointer;
      transition: transform 120ms ease, background 120ms ease, color 120ms ease, box-shadow 120ms ease;
    }

    .segmented button {
      border-radius: 999px;
      padding: 9px 14px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.7rem;
      font-weight: 600;
    }

    .segmented button:hover,
    .nav-button:hover {
      transform: translateY(-1px);
      color: var(--ink);
    }

    .segmented button.is-active,
    .nav-button.is-active {
      background: linear-gradient(180deg, rgba(23, 55, 91, 0.96), rgba(12, 35, 59, 0.94));
      color: var(--cyan-2);
      box-shadow: inset 0 0 0 1px rgba(87, 216, 255, 0.22);
    }

    .command-meta {
      grid-area: meta;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      min-width: 0;
    }

    .meta-chip {
      padding: 12px 14px;
      border-radius: var(--radius-sm);
      background: rgba(11, 17, 28, 0.92);
      border: 1px solid rgba(124, 155, 196, 0.11);
    }

    .meta-chip span {
      display: block;
      color: var(--muted-2);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.66rem;
      margin-bottom: 6px;
    }

    .meta-chip strong {
      display: block;
      font-size: 0.95rem;
      letter-spacing: -0.02em;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .workspace {
      display: grid;
      grid-template-columns: 82px minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }

    .left-rail {
      position: sticky;
      top: 18px;
      padding: 18px 12px;
      display: grid;
      gap: 18px;
    }

    .rail-label {
      color: var(--muted-2);
      text-transform: uppercase;
      letter-spacing: 0.22em;
      font-size: 0.62rem;
      text-align: center;
    }

    .nav-stack {
      display: grid;
      gap: 8px;
    }

    .nav-button {
      border-radius: 16px;
      padding: 11px 6px;
      display: grid;
      gap: 5px;
      justify-items: center;
      min-height: 64px;
    }

    .nav-icon {
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
      font-size: 0.72rem;
      letter-spacing: 0.15em;
      color: var(--cyan-2);
      opacity: 0.88;
    }

    .nav-text {
      font-size: 0.58rem;
      text-transform: uppercase;
      letter-spacing: 0.16em;
    }

    .rail-footer {
      padding-top: 8px;
      border-top: 1px solid rgba(124, 155, 196, 0.08);
      color: var(--muted);
      text-align: center;
      font-size: 0.66rem;
      line-height: 1.5;
    }

    .rail-footer strong {
      display: block;
      color: var(--ink);
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
      font-size: 0.92rem;
      margin-top: 4px;
    }

    .desk {
      display: grid;
      gap: 18px;
    }

    .summary-strip {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
    }

    .status-card {
      padding: 18px 18px 16px;
      min-height: 118px;
      border-radius: var(--radius);
      background: var(--panel-glow);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }

    .status-label,
    .panel-title {
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.15em;
      font-size: 0.69rem;
    }

    .status-value {
      margin-top: 10px;
      font-size: clamp(1.15rem, 1.6vw, 1.7rem);
      font-weight: 720;
      letter-spacing: -0.04em;
      line-height: 1.02;
    }

    .status-note {
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.8rem;
      line-height: 1.45;
    }

    .main-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.7fr) 344px;
      gap: 18px;
      align-items: start;
    }

    .chart-panel,
    .side-panel,
    .dock {
      min-width: 0;
    }

    .panel-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 18px;
      padding: 18px 22px;
      border-bottom: 1px solid rgba(124, 155, 196, 0.09);
    }

    .panel-head-copy {
      min-width: 0;
    }

    .panel-subtitle {
      margin-top: 7px;
      color: var(--muted);
      font-size: 0.87rem;
      line-height: 1.45;
    }

    .panel-value {
      color: var(--cyan-2);
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
      font-size: 0.78rem;
      white-space: nowrap;
    }

    .panel-body {
      padding: 22px;
    }

    .chart-shell {
      display: grid;
      gap: 18px;
      padding: 22px;
    }

    .chart-summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }

    .mini-metric {
      padding: 15px 16px;
      border-radius: 14px;
      background: rgba(10, 17, 28, 0.92);
      border: 1px solid rgba(124, 155, 196, 0.09);
    }

    .mini-metric .label {
      font-size: 0.66rem;
      text-transform: uppercase;
      letter-spacing: 0.15em;
      color: var(--muted-2);
    }

    .mini-metric .value {
      margin-top: 8px;
      font-size: 1.18rem;
      font-weight: 700;
      letter-spacing: -0.03em;
    }

    .chart-frame {
      position: relative;
      padding: 18px 18px 14px;
      border-radius: 20px;
      background:
        linear-gradient(180deg, rgba(5, 10, 18, 0.9), rgba(6, 10, 16, 0.96)),
        radial-gradient(circle at 12% 10%, rgba(87, 216, 255, 0.08), transparent 30%);
      border: 1px solid rgba(124, 155, 196, 0.1);
      overflow: hidden;
    }

    .chart-overlay {
      position: absolute;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(rgba(124, 155, 196, 0.05) 1px, transparent 1px),
        linear-gradient(90deg, rgba(124, 155, 196, 0.045) 1px, transparent 1px);
      background-size: 78px 78px;
      mask-image: linear-gradient(180deg, rgba(255,255,255,0.72), rgba(255,255,255,0.1));
    }

    .hero-chart {
      position: relative;
      z-index: 1;
      width: 100%;
      height: 430px;
      display: block;
    }

    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }

    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      color: var(--muted);
      font-size: 0.84rem;
    }

    .legend-dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      box-shadow: 0 0 18px currentColor;
    }

    .side-panel {
      display: grid;
      gap: 12px;
      padding: 12px;
      align-content: start;
    }

    .side-section {
      padding: 18px 20px;
      border: 1px solid rgba(124, 155, 196, 0.09);
      border-radius: 16px;
      background: rgba(9, 15, 25, 0.84);
    }

    .side-section:last-child {
      border-bottom: 0;
    }

    .ticker-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.69rem;
    }

    .ticker-list,
    .watch-rows {
      display: grid;
      gap: 12px;
    }

    .ticker-item,
    .watch-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      align-items: center;
      padding: 12px 0;
      border-bottom: 1px dashed rgba(124, 155, 196, 0.09);
    }

    .ticker-item:last-child,
    .watch-row:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }

    .watch-left {
      display: grid;
      grid-template-columns: 30px minmax(0, 1fr);
      gap: 12px;
      align-items: center;
    }

    .watch-rank {
      width: 30px;
      height: 30px;
      border-radius: 10px;
      display: grid;
      place-items: center;
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
      font-size: 0.72rem;
      color: var(--cyan-2);
      background: rgba(20, 41, 69, 0.9);
      border: 1px solid rgba(87, 216, 255, 0.12);
    }

    .ticker-main {
      font-weight: 650;
    }

    .ticker-sub {
      margin-top: 4px;
      font-size: 0.77rem;
      color: var(--muted);
    }

    .delta {
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
      font-weight: 700;
      white-space: nowrap;
    }

    .delta.up { color: var(--green); }
    .delta.down { color: var(--red); }
    .delta.flat { color: var(--amber); }

    .dock {
      min-height: 560px;
    }

    .dock-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      padding: 18px 22px;
      border-bottom: 1px solid rgba(124, 155, 196, 0.09);
    }

    .tab-stage {
      min-height: 500px;
      padding: 22px;
    }

    .tab-panel {
      display: none;
      animation: fadeIn 180ms ease;
    }

    .tab-panel.is-active {
      display: block;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .overview-grid,
    .token-grid,
    .calendar-grid {
      display: grid;
      gap: 18px;
    }

    .overview-grid {
      grid-template-columns: minmax(0, 1.18fr) minmax(320px, 0.82fr);
    }

    .token-grid {
      grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
    }

    .calendar-grid {
      grid-template-columns: minmax(0, 1.2fr) minmax(300px, 0.8fr);
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.91rem;
    }

    thead th {
      text-align: left;
      padding: 12px 14px;
      color: var(--muted);
      font-size: 0.69rem;
      text-transform: uppercase;
      letter-spacing: 0.15em;
      border-bottom: 1px solid rgba(124, 155, 196, 0.08);
    }

    tbody td {
      padding: 12px 14px;
      border-bottom: 1px solid rgba(124, 155, 196, 0.06);
      vertical-align: middle;
    }

    tbody tr:hover {
      background: rgba(17, 32, 52, 0.54);
    }

    .rank-cell {
      width: 52px;
      color: var(--cyan-2);
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
    }

    .skill-name {
      font-weight: 700;
      letter-spacing: -0.02em;
    }

    .skill-state {
      margin-top: 4px;
      color: var(--muted);
      font-size: 0.73rem;
      text-transform: uppercase;
      letter-spacing: 0.13em;
    }

    .mono {
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
    }

    .spark {
      width: 128px;
      height: 34px;
      display: block;
    }

    .calendar-strip {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }

    .calendar-stat {
      padding: 14px 16px;
      border-radius: 14px;
      background: rgba(10, 17, 28, 0.92);
      border: 1px solid rgba(124, 155, 196, 0.08);
    }

    .calendar-stat .label {
      color: var(--muted);
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.14em;
    }

    .calendar-stat .value {
      margin-top: 10px;
      font-size: 1.45rem;
      font-weight: 700;
      letter-spacing: -0.03em;
    }

    .calendar-heatmap {
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      gap: 8px;
    }

    .calendar-cell {
      border-radius: 14px;
      padding: 10px 8px;
      min-height: 74px;
      background: rgba(12, 18, 30, 0.88);
      border: 1px solid rgba(124, 155, 196, 0.07);
      display: grid;
      align-content: space-between;
      gap: 8px;
    }

    .calendar-cell.is-dim {
      opacity: 0.46;
    }

    .calendar-cell .day {
      font-size: 0.78rem;
      color: var(--muted);
    }

    .calendar-cell .figure {
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
      font-size: 0.92rem;
      font-weight: 700;
    }

    .calendar-cell .sub {
      color: var(--muted);
      font-size: 0.68rem;
    }

    .token-stack {
      display: grid;
      gap: 12px;
    }

    .token-breakdown {
      display: grid;
      gap: 10px;
    }

    .token-bar-row {
      display: grid;
      grid-template-columns: 120px minmax(0, 1fr) 92px;
      gap: 12px;
      align-items: center;
    }

    .token-label {
      color: var(--muted);
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.13em;
    }

    .token-bar {
      height: 10px;
      border-radius: 999px;
      background: rgba(124, 155, 196, 0.08);
      overflow: hidden;
    }

    .token-bar-fill {
      height: 100%;
      border-radius: inherit;
    }

    .tape {
      display: grid;
      gap: 10px;
    }

    .tape-item {
      display: grid;
      grid-template-columns: 152px minmax(0, 1fr) auto;
      gap: 14px;
      align-items: center;
      padding: 12px 0;
      border-bottom: 1px dashed rgba(124, 155, 196, 0.08);
    }

    .tape-item:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }

    .tape-time {
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
      color: var(--muted);
      font-size: 0.8rem;
    }

    .tape-task {
      font-weight: 600;
    }

    .tape-skills {
      margin-top: 4px;
      color: var(--muted);
      font-size: 0.78rem;
    }

    .footer {
      margin-top: 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      color: var(--muted);
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
      font-size: 0.8rem;
    }

    @media (max-width: 1400px) {
      .command-bar {
        grid-template-columns: 1fr;
        grid-template-areas:
          "brand"
          "controls"
          "meta";
      }

      .command-meta {
        min-width: 0;
      }
    }

    @media (max-width: 1260px) {
      .main-grid,
      .overview-grid,
      .token-grid,
      .calendar-grid {
        grid-template-columns: 1fr;
      }

      .summary-strip {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }

      .chart-summary {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }

    @media (max-width: 920px) {
      .workspace {
        grid-template-columns: 1fr;
      }

      .left-rail {
        position: static;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        align-items: start;
      }

      .nav-stack {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }

      .summary-strip {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .chart-summary,
      .command-meta {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .command-meta {
        min-width: 0;
      }
    }

    @media (max-width: 720px) {
      .app-shell {
        padding: 14px;
      }

      .chart-summary,
      .summary-strip,
      .command-meta,
      .calendar-strip {
        grid-template-columns: 1fr;
      }

      .segmented {
        width: 100%;
        overflow: auto;
      }

      .nav-stack {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      thead {
        display: none;
      }

      tbody tr,
      .tape-item {
        display: block;
      }

      tbody td {
        display: block;
        padding: 8px 14px;
        border-bottom: 0;
      }

      tbody tr {
        border-bottom: 1px solid rgba(124, 155, 196, 0.08);
        padding: 8px 0;
      }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <header class="command-bar panel">
      <div class="brand-cluster">
        <div class="brand-mark">CE</div>
        <div>
          <div class="eyebrow">live telemetry terminal</div>
          <div class="desk-title">Skill Exchange Desk</div>
          <div class="desk-subtitle">TradingView-inspired telemetry layout with a chart-first overview and separate workspaces for deeper analysis.</div>
        </div>
      </div>
      <div class="control-cluster">
        <div class="segmented" id="timeframeTabs"></div>
        <div class="segmented compact" id="chartModeTabs"></div>
      </div>
      <div class="command-meta">
        <div class="meta-chip"><span>Window</span><strong id="selectedWindow">Week desk</strong></div>
        <div class="meta-chip"><span>Leader</span><strong id="leaderChip">repo-pilot</strong></div>
        <div class="meta-chip"><span>Updated</span><strong id="updatedChip">Generated</strong></div>
      </div>
    </header>

    <div class="workspace">
      <aside class="left-rail panel">
        <div class="rail-label">Panels</div>
        <div class="nav-stack" id="navRail"></div>
        <div class="rail-footer">
          total tokens
          <strong id="railTokenTotal">0</strong>
        </div>
      </aside>

      <main class="desk">
        <section class="summary-strip" id="statusGrid"></section>

        <section class="main-grid" id="mainWorkspace">
          <section class="panel chart-panel">
            <div class="panel-head">
              <div class="panel-head-copy">
                <div class="panel-title">Composite Tape</div>
                <div class="panel-subtitle" id="chartSubtitle">Daily desk flow, leader movement, and token pressure in one chart surface.</div>
              </div>
              <div class="panel-value" id="chartMeta">Window: Week</div>
            </div>
            <div class="chart-shell">
              <div class="chart-summary" id="chartSummary"></div>
              <div class="chart-frame">
                <div class="chart-overlay"></div>
                <svg class="hero-chart" id="heroChart" viewBox="0 0 1120 430" preserveAspectRatio="none"></svg>
              </div>
              <div class="legend" id="legend"></div>
            </div>
          </section>

          <aside class="panel side-panel">
            <section class="side-section">
              <div class="ticker-head"><span>Watchlist</span><span id="watchlistMeta">top board</span></div>
              <div class="watch-rows" id="leadersWatch"></div>
            </section>
            <section class="side-section">
              <div class="ticker-head"><span>Top Risers</span><span id="moverLabel">week flow</span></div>
              <div class="ticker-list" id="moversUp"></div>
            </section>
            <section class="side-section">
              <div class="ticker-head"><span>Cooling</span><span>cool-off</span></div>
              <div class="ticker-list" id="moversDown"></div>
            </section>
            <section class="side-section">
              <div class="ticker-head"><span>Pressure Queue</span><span>risk</span></div>
              <div class="ticker-list" id="watchlist"></div>
            </section>
          </aside>
        </section>

        <section class="panel dock" id="detailWorkspace" style="display:none;">
          <div class="dock-head">
            <div>
              <div class="panel-title" id="detailTitle">Detail Workspace</div>
              <div class="panel-subtitle" id="detailSubtitle">Open a dedicated workspace when you want to go deeper without crowding the overview screen.</div>
            </div>
          </div>
          <div class="tab-stage">
            <section class="tab-panel is-active" data-tab="overview">
              <div class="overview-grid">
                <section class="panel">
                  <div class="panel-head">
                    <div class="panel-title">Top Board</div>
                    <div class="panel-value">usage + delivery + momentum</div>
                  </div>
                  <div style="overflow:auto;">
                    <table>
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>Skill</th>
                          <th>Runs</th>
                          <th>Tokens</th>
                          <th>Chg</th>
                          <th>Eff</th>
                          <th>Delivery</th>
                          <th>Momentum</th>
                          <th>Trend</th>
                        </tr>
                      </thead>
                      <tbody id="overviewTable"></tbody>
                    </table>
                  </div>
                </section>
                <section class="panel">
                  <div class="panel-head">
                    <div class="panel-title">Window Snapshot</div>
                    <div class="panel-value">day / week / month</div>
                  </div>
                  <div class="panel-body" id="windowSnapshot"></div>
                </section>
              </div>
            </section>

            <section class="tab-panel" data-tab="rankings">
              <section class="panel">
                <div class="panel-head">
                  <div class="panel-title">Full Rankings</div>
                  <div class="panel-value" id="rankingsMeta">sorted for week</div>
                </div>
                <div style="overflow:auto;">
                  <table>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Skill</th>
                        <th>Runs</th>
                        <th>Tokens</th>
                        <th>Input</th>
                        <th>Output</th>
                        <th>Chg</th>
                        <th>Eff</th>
                        <th>Delivery</th>
                        <th>Friction</th>
                        <th>Score</th>
                      </tr>
                    </thead>
                    <tbody id="rankingsTable"></tbody>
                  </table>
                </div>
              </section>
            </section>

            <section class="tab-panel" data-tab="calendar">
              <div class="calendar-grid">
                <section class="panel">
                  <div class="panel-head">
                    <div class="panel-title">Activity Calendar</div>
                    <div class="panel-value">last 42 days</div>
                  </div>
                  <div class="panel-body">
                    <div class="calendar-strip" id="calendarStats"></div>
                    <div class="calendar-heatmap" id="calendarHeatmap"></div>
                  </div>
                </section>
                <section class="panel">
                  <div class="panel-head">
                    <div class="panel-title">Calendar Legend</div>
                    <div class="panel-value">daily runs + tokens</div>
                  </div>
                  <div class="panel-body" id="calendarLegend"></div>
                </section>
              </div>
            </section>

            <section class="tab-panel" data-tab="tokens">
              <div class="token-grid">
                <section class="panel">
                  <div class="panel-head">
                    <div class="panel-title">Token Leaders</div>
                    <div class="panel-value" id="tokenMeta">window token spend</div>
                  </div>
                  <div style="overflow:auto;">
                    <table>
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>Skill</th>
                          <th>Total</th>
                          <th>Input</th>
                          <th>Cached</th>
                          <th>Output</th>
                          <th>Reasoning</th>
                          <th>Runs</th>
                        </tr>
                      </thead>
                      <tbody id="tokenTable"></tbody>
                    </table>
                  </div>
                </section>
                <section class="token-stack">
                  <section class="panel">
                    <div class="panel-head">
                      <div class="panel-title">Token Mix</div>
                      <div class="panel-value" id="tokenMixMeta">selected window</div>
                    </div>
                    <div class="panel-body">
                      <div class="token-breakdown" id="tokenBreakdown"></div>
                    </div>
                  </section>
                  <section class="panel">
                    <div class="panel-head">
                      <div class="panel-title">Token Snapshot</div>
                      <div class="panel-value">aggregate usage</div>
                    </div>
                    <div class="panel-body" id="tokenSnapshot"></div>
                  </section>
                </section>
              </div>
            </section>

            <section class="tab-panel" data-tab="pressure">
              <div class="overview-grid">
                <section class="panel">
                  <div class="panel-head">
                    <div class="panel-title">Challenge Pressure</div>
                    <div class="panel-value">repeated friction by skill usage</div>
                  </div>
                  <div style="overflow:auto;">
                    <table>
                      <thead>
                        <tr>
                          <th>Challenge</th>
                          <th>Hits</th>
                          <th>Skills</th>
                        </tr>
                      </thead>
                      <tbody id="challengeTable"></tbody>
                    </table>
                  </div>
                </section>
                <section class="panel">
                  <div class="panel-head">
                    <div class="panel-title">Watchlist</div>
                    <div class="panel-value">where to upgrade next</div>
                  </div>
                  <div class="panel-body">
                    <div class="ticker-list" id="watchlistDeep"></div>
                  </div>
                </section>
              </div>
            </section>

            <section class="tab-panel" data-tab="tape">
              <section class="panel">
                <div class="panel-head">
                  <div class="panel-title">Recent Tape</div>
                  <div class="panel-value">latest tracked turns</div>
                </div>
                <div class="panel-body">
                  <div class="tape" id="recentTape"></div>
                </div>
              </section>
            </section>
          </div>
        </section>
      </main>
    </div>

    <footer class="footer">
      <div id="lastUpdated">Generated…</div>
      <div id="refreshMode">Mode: embedded snapshot</div>
    </footer>
  </div>

  <script>
    const BOOTSTRAP_DATA = __BOOTSTRAP_DATA__;
    const DASHBOARD_JSON_URL = "./skill-dashboard.json";
    const PALETTE = ["#57d8ff", "#30d48a", "#ffbd63", "#8193ff", "#d06cff", "#ff5c7c"];
    const TIMEFRAME_LABELS = { day: "Day", week: "Week", month: "Month" };
    const TAB_LABELS = {
      overview: "Overview",
      rankings: "Rankings",
      calendar: "Calendar",
      tokens: "Tokens",
      pressure: "Pressure",
      tape: "Tape"
    };
    const VIEW_SUBTITLES = {
      overview: "Keep the chart workspace calm, then open a dedicated workspace only when you want more depth.",
      rankings: "Full rankings take over the workspace here so you can compare skills without the chart and side panels competing for attention.",
      calendar: "The calendar view gets the full canvas, making it easier to read patterns across days instead of squeezing it under the overview.",
      tokens: "Token usage gets its own workspace so spend, mix, and per-skill leaders are easier to inspect without crowding the overview.",
      pressure: "Repeated friction, challenge hotspots, and upgrade pressure live here as a dedicated risk workspace.",
      tape: "Recent tracked runs get their own tape view so the event stream is readable like a terminal feed."
    };
    const NAV_SHORT = {
      overview: "OV",
      rankings: "RK",
      calendar: "CL",
      tokens: "TK",
      pressure: "PR",
      tape: "TP"
    };
    const CHART_MODE_LABELS = {
      market: "Market",
      tokens: "Tokens",
      efficiency: "Efficiency"
    };
    let state = {
      timeframe: "week",
      tab: "overview",
      chartMode: "market",
      data: BOOTSTRAP_DATA
    };

    function fmt(value, digits = 1) {
      return Number(value || 0).toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits
      });
    }

    function fmtInt(value) {
      return Number(value || 0).toLocaleString();
    }

    function shortTokens(value) {
      const numeric = Number(value || 0);
      if (numeric >= 1000000) return `${(numeric / 1000000).toFixed(2)}M`;
      if (numeric >= 1000) return `${(numeric / 1000).toFixed(1)}k`;
      return `${numeric}`;
    }

    function pct(value) {
      const numeric = Number(value || 0);
      const sign = numeric > 0 ? "+" : "";
      return `${sign}${fmt(numeric, 1)}%`;
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    }

    function monoDate(value) {
      const date = new Date(value);
      return date.toLocaleString([], {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit"
      });
    }

    function deltaClass(value) {
      if (value > 0) return "up";
      if (value < 0) return "down";
      return "flat";
    }

    function currentLeaders() {
      return state.data.leaders[state.timeframe] || [];
    }

    function currentFrame() {
      return state.data.overview.frames[state.timeframe];
    }

    function currentTokens() {
      const frame = currentFrame();
      return {
        total_tokens: frame.tokens,
        input_tokens: frame.input_tokens,
        cached_input_tokens: frame.cached_input_tokens,
        output_tokens: frame.output_tokens,
        reasoning_output_tokens: frame.reasoning_output_tokens
      };
    }

    function sparklineSvg(points, color) {
      const width = 130;
      const height = 34;
      const max = Math.max(...points, 1);
      const min = Math.min(...points, 0);
      const range = Math.max(max - min, 1);
      const coords = points.map((value, index) => {
        const x = (index / Math.max(points.length - 1, 1)) * width;
        const y = height - (((value - min) / range) * (height - 6) + 3);
        return [x, y];
      });
      const line = coords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
      return `
        <svg class="spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
          <polyline fill="none" stroke="rgba(124,155,196,0.10)" stroke-width="1" points="0,${height-1} ${width},${height-1}"></polyline>
          <polyline fill="none" stroke="${color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" points="${line}"></polyline>
        </svg>
      `;
    }

    function lastNDays(days = 30) {
      return (state.data.calendar || []).slice(-days);
    }

    function drawGrid(width, height, pad, steps = 5) {
      return Array.from({ length: steps }, (_, index) => {
        const y = pad.top + (index / (steps - 1)) * (height - pad.top - pad.bottom);
        return `<line x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}" stroke="rgba(124,155,196,0.08)" stroke-width="1" />`;
      }).join("");
    }

    function pathFromSeries(values, width, height, pad, maxValue, minValue = 0) {
      const span = Math.max(maxValue - minValue, 1);
      const toX = (index) => pad.left + (index / Math.max(values.length - 1, 1)) * (width - pad.left - pad.right);
      const toY = (value) => height - pad.bottom - (((value - minValue) / span) * (height - pad.top - pad.bottom));
      return values.map((value, index) => `${index === 0 ? "M" : "L"}${toX(index).toFixed(1)},${toY(value).toFixed(1)}`).join(" ");
    }

    function renderMarketChart(svg) {
      const width = 1120;
      const height = 430;
      const pad = { top: 26, right: 28, bottom: 34, left: 44 };
      const days = lastNDays(30);
      const dates = days.map(item => item.date.slice(5));
      const tokenValues = days.map(item => item.tokens);
      const runValues = days.map(item => item.runs);
      const leader = currentLeaders()[0];
      const leaderValues = (leader?.series_30d?.runs || []).slice(-days.length);
      const barMax = Math.max(...tokenValues, 1);
      const lineMax = Math.max(...runValues, ...leaderValues, 1);
      const usableWidth = width - pad.left - pad.right;
      const chartHeight = height - pad.top - pad.bottom;
      const barWidth = usableWidth / Math.max(days.length, 1) * 0.58;
      const toX = (index) => pad.left + (index / Math.max(days.length - 1, 1)) * usableWidth;
      const toBarY = (value) => height - pad.bottom - (value / barMax) * chartHeight;
      const toLineY = (value) => height - pad.bottom - (value / lineMax) * chartHeight;
      const runPath = pathFromSeries(runValues, width, height, pad, lineMax);
      const leaderPath = leaderValues.length
        ? pathFromSeries(leaderValues, width, height, pad, lineMax)
        : "";
      const bars = tokenValues.map((value, index) => {
        const x = toX(index) - barWidth / 2;
        const y = toBarY(value);
        const h = Math.max(3, height - pad.bottom - y);
        return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${h.toFixed(1)}" rx="4" fill="rgba(87,216,255,0.18)" stroke="rgba(87,216,255,0.18)" />`;
      }).join("");
      const ticks = dates.filter((_, index) => index % 5 === 0 || index === dates.length - 1).map(label => {
        const idx = dates.indexOf(label);
        return `<text x="${toX(idx)}" y="${height - 9}" fill="rgba(198,219,255,0.42)" font-size="11" text-anchor="middle">${label}</text>`;
      }).join("");
      const lastIndex = runValues.length - 1;
      const runLastX = toX(lastIndex);
      const runLastY = toLineY(runValues[lastIndex] || 0);
      const leaderLastY = leaderValues.length ? toLineY(leaderValues[leaderValues.length - 1] || 0) : runLastY;
      svg.innerHTML = `
        ${drawGrid(width, height, pad)}
        ${bars}
        <path d="${runPath}" fill="none" stroke="${PALETTE[1]}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></path>
        <circle cx="${runLastX}" cy="${runLastY}" r="5" fill="${PALETTE[1]}"></circle>
        ${leaderPath ? `<path d="${leaderPath}" fill="none" stroke="${PALETTE[0]}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></path>` : ""}
        ${leaderPath ? `<circle cx="${runLastX}" cy="${leaderLastY}" r="5" fill="${PALETTE[0]}"></circle>` : ""}
        ${ticks}
      `;
      const leaderName = leader ? escapeHtml(leader.skill) : "leader skill";
      document.getElementById("legend").innerHTML = `
        <span class="legend-item"><span class="legend-dot" style="background:${PALETTE[0]}; color:${PALETTE[0]};"></span><span>${leaderName} run line</span></span>
        <span class="legend-item"><span class="legend-dot" style="background:${PALETTE[1]}; color:${PALETTE[1]};"></span><span>desk run line</span></span>
        <span class="legend-item"><span class="legend-dot" style="background:rgba(87,216,255,0.7); color:rgba(87,216,255,0.7);"></span><span>daily token bars</span></span>
      `;
      document.getElementById("chartSubtitle").textContent = `${TIMEFRAME_LABELS[state.timeframe]} market view with total runs, leader runs, and token pressure bars.`;
    }

    function renderLineModeChart(svg, metricKey, label) {
      const width = 1120;
      const height = 430;
      const pad = { top: 26, right: 28, bottom: 34, left: 44 };
      const series = currentLeaders().slice(0, 4);
      const dates = series[0]?.series_30d?.dates || lastNDays(30).map(item => item.date);
      const valuesBySkill = series.map(item => ({
        skill: item.skill,
        values: item.series_30d[metricKey] || [],
        score: item.windows[state.timeframe].rank_score
      }));
      const maxValue = Math.max(1, ...valuesBySkill.flatMap(item => item.values));
      const grid = drawGrid(width, height, pad);
      const lines = valuesBySkill.map((item, index) => {
        const color = PALETTE[index % PALETTE.length];
        const d = pathFromSeries(item.values, width, height, pad, maxValue);
        const endX = pad.left + (Math.max(item.values.length - 1, 0) / Math.max(item.values.length - 1, 1)) * (width - pad.left - pad.right);
        const endY = height - pad.bottom - (((item.values[item.values.length - 1] || 0) / maxValue) * (height - pad.top - pad.bottom));
        return `
          <path d="${d}" fill="none" stroke="${color}" stroke-width="${index === 0 ? 3.4 : 2.6}" stroke-linecap="round" stroke-linejoin="round"></path>
          <circle cx="${endX}" cy="${endY}" r="${index === 0 ? 5 : 4}" fill="${color}"></circle>
        `;
      }).join("");
      const ticks = dates.filter((_, index) => index % 5 === 0 || index === dates.length - 1).map(labelText => {
        const idx = dates.indexOf(labelText);
        const x = pad.left + (idx / Math.max(dates.length - 1, 1)) * (width - pad.left - pad.right);
        return `<text x="${x}" y="${height - 9}" fill="rgba(198,219,255,0.42)" font-size="11" text-anchor="middle">${labelText.slice(5)}</text>`;
      }).join("");
      svg.innerHTML = `${grid}${lines}${ticks}`;
      document.getElementById("legend").innerHTML = valuesBySkill.map((item, index) => `
        <span class="legend-item">
          <span class="legend-dot" style="background:${PALETTE[index % PALETTE.length]}; color:${PALETTE[index % PALETTE.length]};"></span>
          <span>${escapeHtml(item.skill)} <span style="color:var(--muted)">· ${label}</span></span>
        </span>
      `).join("");
      document.getElementById("chartSubtitle").textContent = `${TIMEFRAME_LABELS[state.timeframe]} ${label.toLowerCase()} view across the current top four skills.`;
    }

    function buildHeroChart() {
      const svg = document.getElementById("heroChart");
      if (state.chartMode === "market") {
        renderMarketChart(svg);
      } else if (state.chartMode === "tokens") {
        renderLineModeChart(svg, "tokens", "token flow");
      } else {
        renderLineModeChart(svg, "efficiency", "efficiency");
      }
    }

    function renderTimeframeTabs() {
      document.getElementById("timeframeTabs").innerHTML = Object.keys(TIMEFRAME_LABELS).map(key => `
        <button class="${state.timeframe === key ? "is-active" : ""}" data-timeframe="${key}">${TIMEFRAME_LABELS[key]}</button>
      `).join("");
      document.querySelectorAll("[data-timeframe]").forEach(button => {
        button.onclick = () => {
          state.timeframe = button.dataset.timeframe;
          renderAll();
        };
      });
    }

    function renderChartModeTabs() {
      document.getElementById("chartModeTabs").innerHTML = Object.entries(CHART_MODE_LABELS).map(([key, label]) => `
        <button class="${state.chartMode === key ? "is-active" : ""}" data-chart-mode="${key}">${label}</button>
      `).join("");
      document.querySelectorAll("[data-chart-mode]").forEach(button => {
        button.onclick = () => {
          state.chartMode = button.dataset.chartMode;
          renderAll();
        };
      });
    }

    function renderSectionTabs() {
      document.getElementById("navRail").innerHTML = Object.entries(TAB_LABELS).map(([key, label]) => `
        <button class="nav-button ${state.tab === key ? "is-active" : ""}" data-tab-button="${key}" aria-selected="${state.tab === key ? "true" : "false"}">
          <span class="nav-icon">${NAV_SHORT[key]}</span>
          <span class="nav-text">${label}</span>
        </button>
      `).join("");
      document.querySelectorAll("[data-tab-button]").forEach(button => {
        button.onclick = () => {
          const target = button.dataset.tabButton;
          if (!target) return;
          state.tab = target;
          renderAll();
        };
      });
    }

    function renderTabVisibility() {
      const isOverview = state.tab === "overview";
      document.getElementById("mainWorkspace").style.display = isOverview ? "" : "none";
      document.getElementById("detailWorkspace").style.display = isOverview ? "none" : "";
      document.getElementById("chartModeTabs").style.display = isOverview ? "" : "none";
      document.querySelectorAll(".tab-panel").forEach(panel => {
        panel.classList.toggle("is-active", !isOverview && panel.dataset.tab === state.tab);
      });
      document.getElementById("detailTitle").textContent = `${TAB_LABELS[state.tab]} Workspace`;
      document.getElementById("detailSubtitle").textContent = VIEW_SUBTITLES[state.tab];
    }

    function renderHeaderMeta() {
      const frame = currentFrame();
      const leaders = currentLeaders();
      document.getElementById("selectedWindow").textContent = `${TIMEFRAME_LABELS[state.timeframe]} desk`;
      document.getElementById("leaderChip").textContent = leaders[0] ? leaders[0].skill : "n/a";
      document.getElementById("updatedChip").textContent = monoDate(state.data.generated_at);
      document.getElementById("railTokenTotal").textContent = shortTokens(state.data.overview.total_tokens);
      document.getElementById("watchlistMeta").textContent = `${TIMEFRAME_LABELS[state.timeframe].toLowerCase()} board`;
      document.getElementById("moverLabel").textContent = `${TIMEFRAME_LABELS[state.timeframe].toLowerCase()} flow`;
      document.getElementById("chartMeta").textContent = `Window: ${TIMEFRAME_LABELS[state.timeframe]} · ${shortTokens(frame.tokens)} tokens`;
    }

    function renderStatusGrid() {
      const frames = state.data.overview.frames;
      const frame = currentFrame();
      const cards = [
        {
          label: "Day",
          value: fmtInt(frames.day.runs),
          note: `${shortTokens(frames.day.tokens)} · eff ${fmt(frames.day.avg_efficiency, 1)}`
        },
        {
          label: "Week",
          value: fmtInt(frames.week.runs),
          note: `${shortTokens(frames.week.tokens)} · eff ${fmt(frames.week.avg_efficiency, 1)}`
        },
        {
          label: "Month",
          value: fmtInt(frames.month.runs),
          note: `${shortTokens(frames.month.tokens)} · eff ${fmt(frames.month.avg_efficiency, 1)}`
        },
        {
          label: `${TIMEFRAME_LABELS[state.timeframe]} Pulse`,
          value: shortTokens(frame.tokens),
          note: `${pct(frame.delta_tokens_pct)} vs previous · ${fmt(frame.delivery, 1)}% delivery`
        }
      ];
      document.getElementById("statusGrid").innerHTML = cards.map(card => `
        <div class="status-card">
          <div class="status-label">${card.label}</div>
          <div class="status-value">${card.value}</div>
          <div class="status-note">${card.note}</div>
        </div>
      `).join("");
    }

    function renderChartSummary() {
      const frame = currentFrame();
      const tokens = currentTokens();
      const leaders = currentLeaders();
      const summary = [
        { label: "window", value: TIMEFRAME_LABELS[state.timeframe], note: `${fmtInt(frame.runs)} runs` },
        { label: "token flow", value: shortTokens(tokens.total_tokens), note: `${pct(frame.delta_tokens_pct)} window move` },
        { label: "leader", value: leaders[0] ? escapeHtml(leaders[0].skill) : "n/a", note: leaders[0] ? `${fmt(leaders[0].windows[state.timeframe].rank_score, 1)} score` : "no data" },
        { label: "delivery", value: `${fmt(frame.delivery, 1)}%`, note: `${fmt(frame.avg_efficiency, 1)} avg efficiency` }
      ];
      document.getElementById("chartSummary").innerHTML = summary.map(item => `
        <div class="mini-metric">
          <div class="label">${item.label}</div>
          <div class="value">${item.value}</div>
          <div class="status-note">${item.note}</div>
        </div>
      `).join("");
    }

    function renderTicker(targetId, items, mode) {
      document.getElementById(targetId).innerHTML = items.map(item => {
        const window = item.windows[state.timeframe];
        const deltaValue = mode === "watch"
          ? `${fmt(window.friction, 1)} friction`
          : pct(window.delta_runs_pct);
        const deltaNumeric = mode === "watch"
          ? -Math.abs(window.friction)
          : window.delta_runs_pct;
        return `
          <div class="ticker-item">
            <div>
              <div class="ticker-main">${escapeHtml(item.skill)}</div>
              <div class="ticker-sub">${TIMEFRAME_LABELS[state.timeframe]} runs: ${window.runs} · ${shortTokens(window.tokens)} · ${window.state}</div>
            </div>
            <div class="delta ${deltaClass(deltaNumeric)}">${escapeHtml(deltaValue)}</div>
          </div>
        `;
      }).join("");
    }

    function renderWatchlist() {
      const leaders = currentLeaders().slice(0, 8);
      document.getElementById("leadersWatch").innerHTML = leaders.map((item, index) => {
        const window = item.windows[state.timeframe];
        return `
          <div class="watch-row">
            <div class="watch-left">
              <div class="watch-rank">${index + 1}</div>
              <div>
                <div class="ticker-main">${escapeHtml(item.skill)}</div>
                <div class="ticker-sub">${shortTokens(window.tokens)} · ${window.runs} runs · ${window.state}</div>
              </div>
            </div>
            <div class="delta ${deltaClass(window.delta_runs_pct)}">${pct(window.delta_runs_pct)}</div>
          </div>
        `;
      }).join("");
    }

    function buildTableRows(items, full = false) {
      return items.map((item, index) => {
        const window = item.windows[state.timeframe];
        const sparkColor = window.delta_runs > 0 ? "var(--green)" : window.delta_runs < 0 ? "var(--red)" : "var(--cyan)";
        const spark = sparklineSvg(item.series_30d.runs.slice(-14), sparkColor);
        if (!full) {
          return `
            <tr>
              <td class="rank-cell">${index + 1}</td>
              <td>
                <div class="skill-name">${escapeHtml(item.skill)}</div>
                <div class="skill-state">${window.state} · score ${fmt(window.rank_score, 1)}</div>
              </td>
              <td class="mono">${fmtInt(window.runs)}</td>
              <td class="mono">${shortTokens(window.tokens)}</td>
              <td><span class="delta ${deltaClass(window.delta_runs_pct)}">${pct(window.delta_runs_pct)}</span></td>
              <td class="mono">${fmt(window.avg_efficiency, 1)}</td>
              <td class="mono">${fmt(window.delivery, 1)}%</td>
              <td><span class="delta ${deltaClass(window.delta_runs + (window.delta_tokens / 1000))}">${window.delta_runs > 0 ? "+" : ""}${fmt(window.rank_score, 1)}</span></td>
              <td>${spark}</td>
            </tr>
          `;
        }
        return `
          <tr>
            <td class="rank-cell">${index + 1}</td>
            <td>
              <div class="skill-name">${escapeHtml(item.skill)}</div>
              <div class="skill-state">${window.state}</div>
            </td>
            <td class="mono">${fmtInt(window.runs)}</td>
            <td class="mono">${shortTokens(window.tokens)}</td>
            <td class="mono">${shortTokens(window.input_tokens)}</td>
            <td class="mono">${shortTokens(window.output_tokens)}</td>
            <td><span class="delta ${deltaClass(window.delta_runs_pct)}">${pct(window.delta_runs_pct)}</span></td>
            <td class="mono">${fmt(window.avg_efficiency, 1)}</td>
            <td class="mono">${fmt(window.delivery, 1)}%</td>
            <td class="mono">${fmt(window.friction, 1)}</td>
            <td class="mono">${fmt(window.rank_score, 1)}</td>
          </tr>
        `;
      }).join("");
    }

    function renderOverview() {
      const leaders = currentLeaders();
      document.getElementById("overviewTable").innerHTML = buildTableRows(leaders.slice(0, 8), false);
      document.getElementById("windowSnapshot").innerHTML = Object.entries(TIMEFRAME_LABELS).map(([key, label]) => {
        const frame = state.data.overview.frames[key];
        return `
          <div class="calendar-stat" style="margin-bottom:12px;">
            <div class="label">${label}</div>
            <div class="value">${fmtInt(frame.runs)} runs</div>
            <div class="status-note">${shortTokens(frame.tokens)} tokens · eff ${fmt(frame.avg_efficiency, 1)} · ${fmt(frame.delivery, 1)}% delivery</div>
          </div>
        `;
      }).join("");
    }

    function renderRankings() {
      const leaders = currentLeaders();
      document.getElementById("rankingsMeta").textContent = `sorted for ${TIMEFRAME_LABELS[state.timeframe].toLowerCase()}`;
      document.getElementById("rankingsTable").innerHTML = buildTableRows(leaders, true);
    }

    function renderCalendar() {
      const stats = Object.entries(TIMEFRAME_LABELS).map(([key, label]) => {
        const frame = state.data.overview.frames[key];
        return `
          <div class="calendar-stat">
            <div class="label">${label}</div>
            <div class="value">${fmtInt(frame.runs)}</div>
            <div class="status-note">${shortTokens(frame.tokens)} tokens · eff ${fmt(frame.avg_efficiency, 1)}</div>
          </div>
        `;
      }).join("");
      document.getElementById("calendarStats").innerHTML = stats;

      const maxRuns = Math.max(...state.data.calendar.map(item => item.runs), 1);
      const cells = state.data.calendar.map(cell => {
        const intensity = cell.runs === 0 ? 0.08 : Math.min(0.9, 0.16 + (cell.runs / maxRuns) * 0.7);
        return `
          <div class="calendar-cell ${cell.runs === 0 ? "is-dim" : ""}" style="box-shadow: inset 0 0 0 1px rgba(87,216,255,0.04); background: linear-gradient(180deg, rgba(9,16,26,0.94), rgba(9,16,26,0.98)), rgba(0,0,0,1); border-color: rgba(124,155,196,${Math.min(0.26, intensity * 0.22)}); box-shadow: 0 0 0 1px rgba(255,255,255,0.01), inset 0 -28px 40px rgba(87,216,255,${intensity * 0.16});" title="${cell.date} · ${cell.runs} runs · ${shortTokens(cell.tokens)} tokens · eff ${fmt(cell.avg_efficiency, 1)}">
            <div class="day">${cell.day}</div>
            <div class="figure">${fmtInt(cell.runs)}</div>
            <div class="sub">${shortTokens(cell.tokens)}</div>
          </div>
        `;
      }).join("");
      document.getElementById("calendarHeatmap").innerHTML = cells;

      const frame = currentFrame();
      document.getElementById("calendarLegend").innerHTML = `
        <div class="calendar-stat" style="margin-bottom:12px;">
          <div class="label">Selected Window</div>
          <div class="value">${TIMEFRAME_LABELS[state.timeframe]}</div>
          <div class="status-note">${fmtInt(frame.runs)} runs · ${shortTokens(frame.tokens)} tokens · ${fmt(frame.delivery, 1)}% delivery</div>
        </div>
        <div class="status-note" style="line-height:1.7;">
          Each square is one day of tracked skill usage. The glow intensity follows activity density, while the sub-label keeps token pressure visible so you can read both throughput and cost at the same time.
        </div>
      `;
    }

    function renderTokens() {
      const tokenLeaders = state.data.token_leaders[state.timeframe] || [];
      document.getElementById("tokenMeta").textContent = `${TIMEFRAME_LABELS[state.timeframe].toLowerCase()} token spend`;
      document.getElementById("tokenTable").innerHTML = tokenLeaders.map((item, index) => {
        const window = item.windows[state.timeframe];
        return `
          <tr>
            <td class="rank-cell">${index + 1}</td>
            <td>
              <div class="skill-name">${escapeHtml(item.skill)}</div>
              <div class="skill-state">${window.runs} runs · eff ${fmt(window.avg_efficiency, 1)}</div>
            </td>
            <td class="mono">${shortTokens(window.tokens)}</td>
            <td class="mono">${shortTokens(window.input_tokens)}</td>
            <td class="mono">${shortTokens(window.cached_input_tokens)}</td>
            <td class="mono">${shortTokens(window.output_tokens)}</td>
            <td class="mono">${shortTokens(window.reasoning_output_tokens)}</td>
            <td class="mono">${fmtInt(window.runs)}</td>
          </tr>
        `;
      }).join("");

      const mix = currentTokens();
      const max = Math.max(mix.input_tokens, mix.cached_input_tokens, mix.output_tokens, mix.reasoning_output_tokens, 1);
      const rows = [
        ["Input", mix.input_tokens, "var(--cyan)"],
        ["Cached", mix.cached_input_tokens, "var(--violet)"],
        ["Output", mix.output_tokens, "var(--green)"],
        ["Reasoning", mix.reasoning_output_tokens, "var(--amber)"],
      ];
      document.getElementById("tokenBreakdown").innerHTML = rows.map(([label, value, color]) => `
        <div class="token-bar-row">
          <div class="token-label">${label}</div>
          <div class="token-bar"><div class="token-bar-fill" style="width:${Math.max(4, (value / max) * 100)}%; background:${color};"></div></div>
          <div class="mono">${shortTokens(value)}</div>
        </div>
      `).join("");

      document.getElementById("tokenMixMeta").textContent = `${TIMEFRAME_LABELS[state.timeframe].toLowerCase()} usage`;
      document.getElementById("tokenSnapshot").innerHTML = `
        <div class="calendar-stat" style="margin-bottom:12px;">
          <div class="label">Selected Window</div>
          <div class="value">${shortTokens(mix.total_tokens)}</div>
          <div class="status-note">total tokens in the ${TIMEFRAME_LABELS[state.timeframe].toLowerCase()} window</div>
        </div>
        <div class="calendar-stat" style="margin-bottom:12px;">
          <div class="label">All Time</div>
          <div class="value">${shortTokens(state.data.overview.total_tokens)}</div>
          <div class="status-note">${fmtInt(state.data.overview.total_runs)} tracked runs across ${fmtInt(state.data.overview.active_skills)} active skills</div>
        </div>
      `;
    }

    function renderPressure() {
      document.getElementById("challengeTable").innerHTML = state.data.challenges.map(item => `
        <tr>
          <td><div class="skill-name">${escapeHtml(item.challenge)}</div></td>
          <td class="mono">${fmtInt(item.hits)}</td>
          <td style="color:var(--muted)">${escapeHtml(item.skills.slice(0, 4).join(", "))}${item.skills.length > 4 ? " +" + (item.skills.length - 4) : ""}</td>
        </tr>
      `).join("");
      renderTicker("watchlistDeep", state.data.watchlist[state.timeframe] || [], "watch");
    }

    function renderTape() {
      document.getElementById("recentTape").innerHTML = state.data.recent_runs.map(item => `
        <div class="tape-item">
          <div class="tape-time">${monoDate(item.timestamp)}</div>
          <div>
            <div class="tape-task">${escapeHtml(item.task)}</div>
            <div class="tape-skills">${escapeHtml(item.skills.join(", "))} · ${shortTokens(item.total_tokens)} tokens</div>
          </div>
          <div class="delta ${item.outcome === "success" ? "up" : item.outcome === "failed" ? "down" : "flat"}">${item.outcome} · ${fmt(item.efficiency, 1)}</div>
        </div>
      `).join("");
    }

    function renderFooter(mode) {
      document.getElementById("lastUpdated").textContent = `Generated ${monoDate(state.data.generated_at)} · last tracked run ${monoDate(state.data.last_run_at)}`;
      document.getElementById("refreshMode").textContent = mode;
    }

    function renderAll(mode = null) {
      renderTimeframeTabs();
      renderChartModeTabs();
      renderSectionTabs();
      renderTabVisibility();
      renderHeaderMeta();
      renderStatusGrid();
      renderChartSummary();
      buildHeroChart();
      renderWatchlist();
      renderTicker("moversUp", state.data.movers[state.timeframe] || [], "up");
      renderTicker("moversDown", state.data.cooling[state.timeframe] || [], "down");
      renderTicker("watchlist", state.data.watchlist[state.timeframe] || [], "watch");
      renderOverview();
      renderRankings();
      renderCalendar();
      renderTokens();
      renderPressure();
      renderTape();
      renderFooter(mode || (location.protocol.startsWith("http") ? "live polling · refresh every 20s" : "file snapshot · reload every 60s"));
    }

    async function refreshJson() {
      if (!location.protocol.startsWith("http")) {
        renderFooter("file snapshot · reload every 60s");
        return;
      }
      try {
        const response = await fetch(`${DASHBOARD_JSON_URL}?ts=${Date.now()}`, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        state.data = await response.json();
        renderAll("live polling · refresh every 20s");
      } catch (error) {
        renderFooter("live polling paused · using last good snapshot");
      }
    }

    renderAll(location.protocol.startsWith("http") ? "live polling · refresh every 20s" : "file snapshot · reload every 60s");
    setInterval(refreshJson, 20000);
    if (!location.protocol.startsWith("http")) {
      setTimeout(() => location.reload(), 60000);
    }
  </script>
</body>
</html>
"""
    return template.replace("__BOOTSTRAP_DATA__", bootstrap_json)


def main() -> int:
    args = parse_args()
    input_paths = get_input_paths(args.input)
    if not input_paths:
      raise SystemExit("No input logs found. Pass --input or create telemetry logs first.")
    runs = load_runs(input_paths)
    payload = build_payload(runs)

    html_output = Path(args.html_output).expanduser().resolve()
    json_output = Path(args.json_output).expanduser().resolve()
    html_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.parent.mkdir(parents=True, exist_ok=True)

    json_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    html_output.write_text(render_html(payload), encoding="utf-8")

    print(f"Wrote dashboard json -> {json_output}")
    print(f"Wrote dashboard html -> {html_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
