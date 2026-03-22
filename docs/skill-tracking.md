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
- `scripts/sync_codex_skill_runs.py`
  Auto-sync skill runs from real Codex desktop and CLI session logs under `~/.codex/sessions`.
- `scripts/render_skill_report.py`
  Turn the log into a Markdown report with a Mermaid graph.
- `scripts/render_skill_dashboard.py`
  Build a live market-style HTML dashboard and JSON snapshot from the same telemetry.
- `scripts/install_launch_agent.sh`
  Install a background macOS `launchd` job that refreshes the auto log and report every 30 minutes.
- `scripts/serve_skill_dashboard.py`
  Serve the live dashboard over local HTTP so the page can poll fresh JSON without full reloads.
- `telemetry/skill-runs.sample.jsonl`
  Safe sample data you can copy from.
- `telemetry/skill-report.sample.md`
  Sample generated report.

Your live files should stay local:

- `telemetry/skill-runs.jsonl`
- `telemetry/skill-runs.auto.jsonl`
- `telemetry/skill-report.md`
- `telemetry/skill-dashboard.html`
- `telemetry/skill-dashboard.json`

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

Auto-sync from Codex session history and render the combined report:

```bash
python3 ./scripts/sync_codex_skill_runs.py --render
```

Install the background refresh job on macOS:

```bash
bash ./scripts/install_launch_agent.sh
```

Serve the live dashboard locally:

```bash
python3 ./scripts/serve_skill_dashboard.py
```

Then open:

```text
http://127.0.0.1:8765/skill-dashboard.html
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

## Live Dashboard

The HTML dashboard is meant to feel more like a market board than a static report. It ranks skills using:

- total usage
- day, week, and month activity windows
- efficiency
- delivery index
- momentum
- token usage
- friction and time cost

It also shows:

- a calmer core board that stays visible on the main page
- tabs for overview, rankings, calendar, tokens, pressure, and tape
- top movers
- cooling skills
- pressure/watchlist lanes
- a 42-day calendar heatmap
- a 30-day usage chart for the top-ranked skills
- token mix and per-skill token leaders
- recent tracked runs

If you open the dashboard directly from the filesystem, it falls back to the embedded snapshot and auto-reloads once a minute. If you serve it over HTTP with `serve_skill_dashboard.py`, it will poll `skill-dashboard.json` every 20 seconds for a smoother live view.

## Automatic Sync Heuristics

The auto-sync script reads local Codex session logs and looks for turns where the assistant explicitly announced skill usage, for example:

- `I'm using \`repo-pilot\` ...`
- `Using \`verified-operator\` ...`

For each detected turn it will:

- capture the user task label from the turn prompt
- estimate duration from the start of the turn to completion
- infer friction from command failures and challenge language
- extract token usage from Codex session events when available
- infer challenge tags from repeated patterns like `timeout`, `race`, `permission`, or `path portability`
- map those tags into upgrade candidates

This keeps the auto log honest about one important limit: it only tracks turns where skill usage was made explicit in the transcript.

## Fully Automatic Mode

If you want this to stay current without thinking about it:

1. install the launch agent with `bash ./scripts/install_launch_agent.sh`
2. let it scan `~/.codex/sessions` every 30 minutes
3. open `telemetry/skill-report.md` whenever you want the latest graph

Remove it later with:

```bash
bash ./scripts/uninstall_launch_agent.sh
```

## Recommended Workflow

1. Do the task.
2. Log the run if it produced meaningful signal.
3. Render the report.
4. Review the challenge hotspots and upgrade backlog.
5. When the same challenge appears more than once, promote the upgrade candidate into a real repo change.

That is the constant-upgrade loop: use the skill, log the friction, build the fix, then watch the graph change over time.
