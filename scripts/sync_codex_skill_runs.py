#!/usr/bin/env python3
"""Auto-sync skill runs from local Codex session logs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CODEX_HOME = Path.home() / ".codex"
DEFAULT_AUTO_LOG = REPO_ROOT / "telemetry" / "skill-runs.auto.jsonl"
DEFAULT_REPORT = REPO_ROOT / "telemetry" / "skill-report.md"
DEFAULT_DASHBOARD_HTML = REPO_ROOT / "telemetry" / "skill-dashboard.html"
DEFAULT_DASHBOARD_JSON = REPO_ROOT / "telemetry" / "skill-dashboard.json"
MANUAL_LOG = REPO_ROOT / "telemetry" / "skill-runs.jsonl"

OUTCOME_SCORES = {
    "success": 1.0,
    "partial": 0.55,
    "failed": 0.0,
}

SKILL_ANNOUNCE_RE = re.compile(
    r"(?:i['` ]?m using|i am using|using|use)\s+((?:`[^`]+`|\$[\w.-]+|[\w.-]+)(?:\s*(?:,|and)\s*(?:`[^`]+`|\$[\w.-]+|[\w.-]+))*)",
    re.IGNORECASE,
)
BACKTICK_RE = re.compile(r"`([^`]+)`")
WORD_RE = re.compile(r"\$?([A-Za-z0-9][A-Za-z0-9_.-]*)")

CHALLENGE_PATTERNS = {
    "timeout-risk": [
        r"\btimeout\b",
        r"\bhanging\b",
        r"\bstall(?:ed|ing)?\b",
        r"\bstuck\b",
        r"\bheartbeat\b",
    ],
    "config-race": [
        r"\brace\b",
        r"\bcollision\b",
        r"\bclobber(?:ed)?\b",
        r"\batomic\b",
    ],
    "auth-or-permission": [
        r"\bauth\b",
        r"\bpermission\b",
        r"\bunauthori[sz]ed\b",
        r"\bpairing\b",
        r"\bdeny\b",
    ],
    "path-portability": [
        r"\bportable\b",
        r"\bportability\b",
        r"\bhardcoded\b",
        r"\bhard-coded\b",
        r"\babsolute path\b",
        r"\blocal path\b",
    ],
    "dependency-installs": [
        r"\bdependency\b",
        r"\bresolver\b",
        r"\binstall(?:er|ation)?\b",
        r"\bpackage install\b",
    ],
    "bootstrap-gaps": [
        r"\bbootstrap\b",
        r"\bsetup gap\b",
        r"\bmissing (?:config|directory|workspace|vault|setup)\b",
        r"\bmemory workspace\b",
    ],
    "docs-or-config-drift": [
        r"\bdrift\b",
        r"\bmismatch\b",
        r"\bstale\b",
        r"\binconsistent\b",
    ],
    "browser-session-boundary": [
        r"\bisolated\b",
        r"\bapple events\b",
        r"\balready-open chrome\b",
        r"\blive chrome session\b",
        r"\bbrowser bridge\b",
    ],
    "connectivity": [
        r"\bconnect(?:ion|ing)?\b",
        r"\bgateway\b",
        r"\breach(?:able|ability)?\b",
        r"\bnetwork\b",
    ],
}

UPGRADE_MAP = {
    "timeout-risk": "add timeout guardrails and heartbeat monitoring",
    "config-race": "prefer atomic single-write updates",
    "auth-or-permission": "add auth and pairing diagnostics",
    "path-portability": "remove hardcoded local paths and add portability checks",
    "dependency-installs": "add install progress monitors and version smoke checks",
    "bootstrap-gaps": "add bootstrap and setup checklists",
    "docs-or-config-drift": "add release consistency checklists",
    "browser-session-boundary": "add browser session preflight checks",
    "connectivity": "add network diagnostics and fallback paths",
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
        description="Auto-sync Codex skill runs from local session logs."
    )
    parser.add_argument("--codex-home", default=str(DEFAULT_CODEX_HOME))
    parser.add_argument("--output", default=str(DEFAULT_AUTO_LOG))
    parser.add_argument(
        "--render",
        action="store_true",
        help="Also regenerate the combined skill report after syncing.",
    )
    parser.add_argument(
        "--report-output",
        default=str(DEFAULT_REPORT),
        help="Where to write the combined report when --render is used.",
    )
    return parser.parse_args()


def empty_token_usage() -> dict[str, int]:
    return {key: 0 for key in TOKEN_KEYS}


def load_skill_names(skill_root: Path) -> list[str]:
    names = []
    if not skill_root.exists():
        return names
    for child in skill_root.iterdir():
        if child.is_dir() and (child / "SKILL.md").exists():
            names.append(child.name)
    return sorted(names, key=len, reverse=True)


def parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def normalize_user_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "Unknown task"
    return text.replace("\n", " ")[:180]


def extract_message_text(event: dict) -> str:
    payload = event.get("payload", {})
    if event.get("type") == "event_msg" and payload.get("type") == "agent_message":
        return payload.get("message", "")
    if event.get("type") == "response_item" and payload.get("type") == "message":
        pieces = []
        for item in payload.get("content", []):
            text = item.get("text")
            if text:
                pieces.append(text)
        return "\n".join(pieces)
    if event.get("type") == "event_msg" and payload.get("type") == "user_message":
        return payload.get("message", "")
    return ""


def extract_skill_mentions(text: str, skill_names: list[str]) -> set[str]:
    if not text:
        return set()
    mentions = set()

    for token in BACKTICK_RE.findall(text):
        if token in skill_names:
            mentions.add(token)

    for token in WORD_RE.findall(text):
        if token in skill_names and f"`{token}`" in text:
            mentions.add(token)

    for match in SKILL_ANNOUNCE_RE.finditer(text):
        block = match.group(1)
        for token in BACKTICK_RE.findall(block):
            if token in skill_names:
                mentions.add(token)
        for token in WORD_RE.findall(block):
            if token in skill_names:
                mentions.add(token)

    return mentions


def stringify_output(output: object) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "\n".join(stringify_output(item) for item in output)
    if isinstance(output, dict):
        return json.dumps(output, sort_keys=True)
    return str(output)


def parse_exit_code(output: object) -> int | None:
    text = stringify_output(output)
    match = re.search(r"Process exited with code (\d+)", text or "")
    if match:
        return int(match.group(1))
    metadata_match = re.search(r'"exit_code":\s*(\d+)', text or "")
    if metadata_match:
        return int(metadata_match.group(1))
    return None


def challenge_tags_from_text(text: str) -> list[str]:
    lowered = text.lower()
    tags = []
    for tag, patterns in CHALLENGE_PATTERNS.items():
        if any(re.search(pattern, lowered) for pattern in patterns):
            tags.append(tag)
    return tags


def compute_effort(duration_minutes: float) -> int:
    if duration_minutes <= 5:
        return 1
    if duration_minutes <= 15:
        return 2
    if duration_minutes <= 30:
        return 3
    if duration_minutes <= 60:
        return 4
    return 5


def compute_friction(nonzero_exit_codes: int, message_blob: str) -> int:
    score = 1
    if nonzero_exit_codes >= 1:
        score = 2
    if nonzero_exit_codes >= 2:
        score = 3
    if nonzero_exit_codes >= 4:
        score = 4
    if nonzero_exit_codes >= 6:
        score = 5
    if re.search(r"\b(stuck|stall|timeout|retry|collision|race|clobber|blocked)\b", message_blob, re.IGNORECASE):
        score = min(5, score + 1)
    return score


def compute_value(turn: dict) -> int:
    text = " ".join(turn["assistant_messages"])
    if re.search(r"\b(push|published|deployed|live|verified|installed|shipped)\b", text, re.IGNORECASE):
        return 4
    if turn["nonzero_exit_codes"] == 0 and turn["task_complete"]:
        return 3
    return 2


def compute_confidence(turn: dict) -> float:
    text = " ".join(turn["assistant_messages"])
    verification_hits = len(
        re.findall(
            r"\b(verified|validation|validate|doctor|status|tests?|check(?:ed|ing)?|smoke test|proof)\b",
            text,
            re.IGNORECASE,
        )
    )
    confidence = 0.65 + min(0.25, verification_hits * 0.05)
    if turn["nonzero_exit_codes"] >= 3:
        confidence -= 0.1
    return round(max(0.4, min(0.95, confidence)), 2)


def compute_outcome(turn: dict) -> str:
    text = " ".join(turn["assistant_messages"])
    lowered = text.lower()
    if not turn["task_complete"]:
        return "failed"
    partial_patterns = [
        r"not fully",
        r"not yet",
        r"partial",
        r"remaining blocker",
        r"still missing",
        r"still blocked",
        r"could not",
        r"couldn't",
        r"unable to",
    ]
    if any(re.search(pattern, lowered) for pattern in partial_patterns):
        return "partial"
    return "success"


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


def new_turn() -> dict:
    return {
        "turn_id": None,
        "session_id": None,
        "cwd": "",
        "started_at": None,
        "ended_at": None,
        "user_text": "",
        "assistant_messages": [],
        "skill_mentions": set(),
        "nonzero_exit_codes": 0,
        "evidence": [],
        "task_complete": False,
        "token_usage": empty_token_usage(),
        "last_total_token_usage": empty_token_usage(),
    }


def flush_turn(turn: dict, records: list[dict]) -> None:
    if not turn["turn_id"] or not turn["skill_mentions"] or not turn["task_complete"]:
        return
    start = turn["started_at"] or turn["ended_at"]
    end = turn["ended_at"] or start
    if not start or not end:
        return
    duration_minutes = max(0.1, round((end - start).total_seconds() / 60, 2))
    effort_score = compute_effort(duration_minutes)
    friction_score = compute_friction(
        turn["nonzero_exit_codes"], " ".join(turn["assistant_messages"])
    )
    value_score = compute_value(turn)
    confidence = compute_confidence(turn)
    outcome = compute_outcome(turn)
    challenge_tags = sorted(
        set(challenge_tags_from_text(" ".join(turn["assistant_messages"])))
    )
    upgrade_candidates = sorted(
        {UPGRADE_MAP[tag] for tag in challenge_tags if tag in UPGRADE_MAP}
    )
    record = {
        "version": 1,
        "source": "codex-session-sync",
        "run_id": turn["turn_id"],
        "session_id": turn["session_id"],
        "timestamp": iso(start),
        "skills": sorted(turn["skill_mentions"]),
        "task": normalize_user_text(turn["user_text"]),
        "outcome": outcome,
        "duration_minutes": duration_minutes,
        "value_score": value_score,
        "effort_score": effort_score,
        "friction_score": friction_score,
        "confidence": confidence,
        "efficiency_score": compute_efficiency(
            outcome=outcome,
            value_score=value_score,
            effort_score=effort_score,
            friction_score=friction_score,
            confidence=confidence,
        ),
        "challenge_tags": challenge_tags,
        "upgrade_candidates": upgrade_candidates,
        "evidence": turn["evidence"][:12],
        "token_usage": dict(turn["token_usage"]),
        "notes": f"Auto-synced from Codex session logs in {turn['cwd']}" if turn["cwd"] else "Auto-synced from Codex session logs",
    }
    records.append(record)


def parse_session_file(path: Path, skill_names: list[str]) -> list[dict]:
    records: list[dict] = []
    current = new_turn()
    session_id = ""

    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            event = json.loads(raw)
            timestamp = parse_ts(event["timestamp"])
            payload = event.get("payload", {})
            event_type = event.get("type")

            if event_type == "session_meta":
                session_id = payload.get("id", "")
                continue

            if event_type == "turn_context":
                flush_turn(current, records)
                current = new_turn()
                current["session_id"] = session_id
                current["turn_id"] = payload.get("turn_id")
                current["cwd"] = payload.get("cwd", "")
                current["started_at"] = timestamp
                continue

            if event_type == "event_msg" and payload.get("type") == "task_started":
                if not current["turn_id"]:
                    current = new_turn()
                    current["session_id"] = session_id
                    current["turn_id"] = payload.get("turn_id")
                    current["started_at"] = timestamp
                continue

            if event_type == "response_item" and payload.get("type") == "message":
                role = payload.get("role")
                text = extract_message_text(event)
                if role == "user" and not current["user_text"]:
                    current["user_text"] = text
                elif role == "assistant":
                    current["assistant_messages"].append(text)
                    current["skill_mentions"].update(extract_skill_mentions(text, skill_names))
                continue

            if event_type == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                last_usage = info.get("last_token_usage") or {}
                total_usage = info.get("total_token_usage") or {}
                for key in TOKEN_KEYS:
                    value = last_usage.get(key)
                    if value is not None:
                        current["token_usage"][key] += int(value)
                    total_value = total_usage.get(key)
                    if total_value is not None:
                        total_value = int(total_value)
                        previous_total = current["last_total_token_usage"][key]
                        if value is None and total_value > previous_total:
                            current["token_usage"][key] += total_value - previous_total
                        current["last_total_token_usage"][key] = max(
                            previous_total, total_value
                        )
                continue

            if event_type == "event_msg" and payload.get("type") == "user_message":
                if not current["user_text"]:
                    current["user_text"] = payload.get("message", "")
                continue

            if event_type == "event_msg" and payload.get("type") == "agent_message":
                text = payload.get("message", "")
                current["assistant_messages"].append(text)
                current["skill_mentions"].update(extract_skill_mentions(text, skill_names))
                continue

            if event_type == "response_item" and payload.get("type") in {
                "function_call_output",
                "custom_tool_call_output",
            }:
                output = payload.get("output", "")
                exit_code = parse_exit_code(output)
                if exit_code not in (None, 0):
                    current["nonzero_exit_codes"] += 1
                if exit_code == 0:
                    output_text = stringify_output(output)
                    snippet = output_text.splitlines()[0][:160] if output_text else ""
                    if snippet:
                        current["evidence"].append(snippet)
                continue

            if event_type == "event_msg" and payload.get("type") == "task_complete":
                current["task_complete"] = True
                current["ended_at"] = timestamp
                flush_turn(current, records)
                current = new_turn()
                current["session_id"] = session_id
                continue

    flush_turn(current, records)
    return records


def load_history_map(history_path: Path) -> dict[str, list[tuple[datetime, str]]]:
    history: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    if not history_path.exists():
        return history
    with history_path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            item = json.loads(raw)
            ts = datetime.fromtimestamp(item["ts"], timezone.utc)
            history[item["session_id"]].append((ts, item.get("text", "")))
    return history


def fill_missing_user_text(records: list[dict], history_map: dict[str, list[tuple[datetime, str]]]) -> None:
    used_indexes: dict[str, int] = defaultdict(int)
    for record in records:
        if record["task"] != "Unknown task":
            continue
        session_id = record.get("session_id", "")
        entries = history_map.get(session_id, [])
        if not entries:
            continue
        record_ts = parse_ts(record["timestamp"])
        idx = used_indexes[session_id]
        while idx < len(entries):
            entry_ts, text = entries[idx]
            if entry_ts <= record_ts + timedelta(minutes=5):
                record["task"] = normalize_user_text(text)
                idx += 1
                break
            idx += 1
        used_indexes[session_id] = idx


def dedupe_records(records: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    outcome_rank = {"failed": 0, "partial": 1, "success": 2}
    for record in records:
        current = best.get(record["run_id"])
        if current is None:
            best[record["run_id"]] = record
            continue
        current_key = (
            outcome_rank[current["outcome"]],
            current["efficiency_score"],
            current["timestamp"],
        )
        new_key = (
            outcome_rank[record["outcome"]],
            record["efficiency_score"],
            record["timestamp"],
        )
        if new_key > current_key:
            best[record["run_id"]] = record
    return sorted(best.values(), key=lambda item: (item["timestamp"], item["run_id"]))


def write_jsonl(path: Path, records: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in sorted(records, key=lambda item: (item["timestamp"], item["run_id"])):
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def run_render(output_path: Path, report_output: Path) -> None:
    report_script = REPO_ROOT / "scripts" / "render_skill_report.py"
    report_cmd = [
        "python3",
        str(report_script),
        "--input",
        str(output_path),
        "--output",
        str(report_output),
    ]
    if MANUAL_LOG.exists():
        report_cmd.extend(["--input", str(MANUAL_LOG)])
    subprocess.run(report_cmd, check=True)

    dashboard_script = REPO_ROOT / "scripts" / "render_skill_dashboard.py"
    dashboard_cmd = [
        "python3",
        str(dashboard_script),
        "--input",
        str(output_path),
        "--html-output",
        str(DEFAULT_DASHBOARD_HTML),
        "--json-output",
        str(DEFAULT_DASHBOARD_JSON),
    ]
    if MANUAL_LOG.exists():
        dashboard_cmd.extend(["--input", str(MANUAL_LOG)])
    subprocess.run(dashboard_cmd, check=True)


def main() -> int:
    args = parse_args()
    codex_home = Path(args.codex_home).expanduser().resolve()
    session_root = codex_home / "sessions"
    skill_root = codex_home / "skills"
    history_path = codex_home / "history.jsonl"
    output_path = Path(args.output).expanduser().resolve()
    report_output = Path(args.report_output).expanduser().resolve()

    skill_names = load_skill_names(skill_root)
    history_map = load_history_map(history_path)
    if not skill_names:
        raise SystemExit(f"No installed skills found in {skill_root}")
    if not session_root.exists():
        raise SystemExit(f"Codex session root does not exist: {session_root}")

    records = []
    for path in sorted(session_root.rglob("*.jsonl")):
        records.extend(parse_session_file(path, skill_names))
    fill_missing_user_text(records, history_map)
    records = dedupe_records(records)

    write_jsonl(output_path, records)
    print(f"Wrote {len(records)} auto-synced runs -> {output_path}")

    if args.render:
        run_render(output_path, report_output)
        print(f"Rendered combined report -> {report_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
