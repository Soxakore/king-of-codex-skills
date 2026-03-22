# Codex Engineering Skills

Battle-tested Codex skills for real work in repos and live systems.

This repository packages reusable Codex skills in a clean GitHub-friendly format so they can be:

- published and shared
- installed into a local Codex setup
- validated before release
- expanded over time without turning into a messy one-off dump

## Featured Skills

### `verified-operator`

Operate across live systems with verification, receipts, recovery, and state tracking.

Best for tasks where Codex needs to do more than explain:

- coordinate terminals, files, APIs, browsers, devices, or external services
- make bounded changes and verify each one with evidence
- recover from drift or partial failure
- leave a trustworthy summary instead of a hand-wavy “should be fixed”

Skill files live at [skills/verified-operator](./skills/verified-operator).

### `repo-pilot`

Map unfamiliar repositories quickly, choose the smallest safe implementation path, and land verified code changes with minimal diff.

Best for tasks where Codex should understand the codebase before editing:

- fix bugs in unfamiliar repos
- add small or medium features without widening scope
- trace behavior through an existing codebase
- prefer minimal-diff, review-ready changes with the cheapest useful proofs

Skill files live at [skills/repo-pilot](./skills/repo-pilot).

## Repo Layout

```text
codex-engineering-skills/
├── docs/
│   └── skill-tracking.md
├── automation/
│   └── com.soxakore.codex-skill-telemetry.plist.sample
├── skills/
│   ├── repo-pilot/
│   │   ├── SKILL.md
│   │   ├── agents/
│   │   ├── references/
│   │   └── examples/
│   └── verified-operator/
│       ├── SKILL.md
│       ├── agents/
│       ├── templates/
│       └── examples/
├── scripts/
│   ├── install.sh
│   ├── install_launch_agent.sh
│   ├── log_skill_run.py
│   ├── render_skill_dashboard.py
│   ├── run_auto_sync.sh
│   ├── serve_skill_dashboard.py
│   ├── render_skill_report.py
│   ├── sync_codex_skill_runs.py
│   ├── uninstall_launch_agent.sh
│   └── validate.sh
├── telemetry/
│   ├── skill-report.sample.md
│   └── skill-runs.sample.jsonl
├── CONTRIBUTING.md
├── LICENSE
├── NOTICE
└── README.md
```

## Quick Start

Install the packaged skills into your local Codex setup:

```bash
git clone https://github.com/Soxakore/codex-engineering-skills.git
cd codex-engineering-skills
bash ./scripts/install.sh
```

By default, skills are installed into:

```text
${CODEX_HOME:-$HOME/.codex}/skills
```

## Validate Skills

Before publishing changes, run:

```bash
bash ./scripts/validate.sh
```

This uses Codex's local validator if it exists on the machine.

## Track Skill Effectiveness

This repo also includes lightweight local telemetry for a continuous improvement loop:

- log meaningful skill runs to `telemetry/skill-runs.jsonl`
- auto-sync explicit skill usage from local Codex session logs into `telemetry/skill-runs.auto.jsonl`
- generate a report and Mermaid graph from that history
- render a live tabbed dashboard with a calmer core view plus deeper rankings, calendar, pressure, tape, and token usage sections
- switch between day, week, and month windows without leaving the main board
- track token volume from real Codex session logs, including input, cached input, output, and reasoning tokens
- turn repeated challenge tags into concrete upgrade candidates

Quick example:

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
  --upgrade "add README release checklist"

python3 ./scripts/render_skill_report.py

python3 ./scripts/sync_codex_skill_runs.py --render

python3 ./scripts/serve_skill_dashboard.py
```

See [docs/skill-tracking.md](./docs/skill-tracking.md) for the full workflow.

## Publish To GitHub

This repo is already live on GitHub:

[Soxakore/codex-engineering-skills](https://github.com/Soxakore/codex-engineering-skills)

## Suggested GitHub Metadata

These work well when you create the repo:

- Description:
  `Battle-tested Codex skills for repo navigation, verified operations, and safer agent workflows.`
- Topics:
  `codex`, `openai`, `skills`, `ai-agents`, `automation`, `developer-tools`

## Adding More Skills

Add each skill under:

```text
skills/<skill-name>/
```

A good skill package usually includes:

- `SKILL.md`
- `agents/` for display metadata
- `templates/` for repeatable task scaffolds
- `examples/` for realistic usage patterns

Keep each skill self-contained so people can inspect or copy it without hunting through the whole repo.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for contribution guidelines.

## License

This repository is licensed under Apache 2.0. See [LICENSE](./LICENSE).
