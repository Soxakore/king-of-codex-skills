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
│   └── validate.sh
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
