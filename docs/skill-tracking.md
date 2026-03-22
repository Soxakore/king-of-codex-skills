# Skill Tracking And Upgrade Loop

This repo now includes a lightweight way to track how often skills are used, how efficient they were, what friction showed up, and which improvements should be built next.

The goal is simple:

- register each notable skill run
- score how well it went
- capture repeatable challenge tags
- turn repeated pain into upgrade candidates
- review the graph so the repo gets better over time

## Files

- `scripts/log_skill_run.py`
  Append one structured run entry to a local JSONL log.
- `scripts/render_skill_report.py`
  Turn the log into a Markdown report with a Mermaid graph.
- `telemetry/skill-runs.sample.jsonl`
  Safe sample data you can copy from.
- `telemetry/skill-report.sample.md`
  Sample generated report.

Your live files should stay local:

- `telemetry/skill-runs.jsonl`
- `telemetry/skill-report.md`

Those live files are ignored by git on purpose so your public repo does not become a dump of private tasks.

## Quick Start

Log a run:

```bash
python3 ./scripts/log_skill_run.py \
  --skill repo-pilot \
  --task "Fix README drift" \
  --outcome success \
  --duration-minutes 12 \
  --value-score 4 \
  --effort-score 2 \
  --friction-score 2 \
  --confidence 0.9 \
  --challenge docs-drift \
  --upgrade "add README release checklist" \
  --evidence README.md \
  --notes "Minimal diff, validated cleanly."
```

Render the report and graph:

```bash
python3 ./scripts/render_skill_report.py
```

## Suggested Rating Guide

- `outcome`
  `success`, `partial`, or `failed`
- `value-score`
  `1` low value, `5` high value
- `effort-score`
  `1` small/simple, `5` large/heavy
- `friction-score`
  `1` smooth run, `5` repeated blockers
- `confidence`
  `0.0` uncertain, `1.0` strongly verified

The logger computes an `efficiency_score` automatically from those inputs. It rewards real delivery, high value, low effort, low friction, and stronger verification confidence.

## What To Log

Log the runs that teach you something. Good candidates:

- a skill solved a task unusually well
- a task drifted or got blocked
- the same pain appeared again
- you had to invent a workaround
- a skill needs a stronger template, script, or guardrail

You do not need to log every tiny run. The loop works best when it captures meaningful signal instead of noise.

## How The Graph Helps

The generated Mermaid graph shows:

- `skill -> challenge`
  which skills are hitting the same friction patterns
- `challenge -> upgrade`
  what improvement should be built to reduce that friction next time

That gives you a visible improvement loop instead of vague memory.

## Recommended Workflow

1. Do the task.
2. Log the run if it produced meaningful signal.
3. Render the report.
4. Review the challenge hotspots and upgrade backlog.
5. When the same challenge appears more than once, promote the upgrade candidate into a real repo change.

That is the constant-upgrade loop: use the skill, log the friction, build the fix, then watch the graph change over time.
