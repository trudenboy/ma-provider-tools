# Workflow System Overview

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│               trudenboy/ma-provider-tools                │
│                                                         │
│  providers.yml          ← registry of all providers     │
│  .github/workflows/                                     │
│    reusable-sync-to-fork.yml  ← shared sync logic       │
│    reusable-release.yml       ← shared release logic    │
│    reusable-test.yml          ← shared CI logic         │
│    distribute.yml             ← auto-push wrappers      │
│  wrappers/                                              │
│    sync-to-fork.yml.j2  ← template for provider repos   │
│    release.yml.j2                                       │
│    test.yml.j2                                          │
└─────────────┬───────────────────────────────────────────┘
              │  distribute.yml creates PRs on change
              ▼
┌─────────────────────┐  ┌──────────────┐  ┌──────────────┐
│ ma-provider-        │  │ ma-provider- │  │ ma-provider- │
│ yandex-music        │  │ kion-music   │  │ msx-bridge   │
│                     │  │              │  │              │
│ sync-to-fork.yml    │  │     ...      │  │     ...      │
│  uses: reusable ──►─┘  │              │  │              │
└─────────────────────┘  └──────────────┘  └──────────────┘
```

## How It Works

### 1. providers.yml — Registry

Single source of truth for all provider metadata:
- `domain` — provider domain (matches manifest.json)
- `repo` — GitHub repository
- `manifest_path` — path to manifest.json inside the provider repo
- `provider_path` — path to rsync to `music_assistant/providers/<domain>/`
- `provider_type` — `music_provider` or `player_provider`

### 2. Reusable Workflows

Located in `.github/workflows/reusable-*.yml`. These use `workflow_call` and contain
all the actual logic. Provider repos call them with provider-specific parameters.

| Workflow | Purpose |
|----------|---------|
| `reusable-sync-to-fork.yml` | Syncs provider files to `trudenboy/ma-server` |
| `reusable-release.yml` | Creates git tag, GitHub release, triggers sync |
| `reusable-test.yml` | Runs CI (lint + tests), adapts to provider type |

### 3. Wrapper Templates

Located in `wrappers/*.j2`. These are Jinja2 templates rendered by `distribute.py` for each
provider. The rendered files are small (~20 lines) and only contain provider-specific inputs,
delegating everything else to the reusable workflows.

| Template | Destination | Purpose |
|----------|-------------|---------|
| `sync-to-fork.yml.j2` | `.github/workflows/sync-to-fork.yml` | Sync provider files to fork |
| `release.yml.j2` | `.github/workflows/release.yml` | Create releases |
| `test.yml.j2` | `.github/workflows/test.yml` | CI (lint + tests) |
| `sync-labels.yml.j2` | `.github/workflows/sync-labels.yml` | Sync issue labels |
| `labels.yml.j2` | `.github/labels.yml` | Label definitions |
| `copilot-triage.yml.j2` | `.github/workflows/copilot-triage.yml` | AI-assisted issue triage |
| `SECURITY.md.j2` | `SECURITY.md` | Security policy |
| `issue-bug.yml.j2` | `.github/ISSUE_TEMPLATE/bug_report.yml` | Bug report form |
| `issue-upstream.yml.j2` | `.github/ISSUE_TEMPLATE/upstream_api_change.yml` | Upstream API change form |
| `issue-proposal.yml.j2` | `.github/ISSUE_TEMPLATE/improvement_proposal.yml` | Improvement proposal form |
| `issue-config.yml.j2` | `.github/ISSUE_TEMPLATE/config.yml` | Issue chooser config |

### 4. distribute.yml — Auto-Distribution

Triggers on push to `main` when `wrappers/` or `providers.yml` changes.
Runs `scripts/distribute.py` which:
1. Reads `providers.yml`
2. Renders wrapper templates for each provider
3. Creates a PR in each provider repo with the updated files
4. Enables auto-merge (squash) on the PR — merges automatically once CI passes

## Updating Shared Logic

To change something that affects all providers (e.g., how sync works):

1. Edit `reusable-sync-to-fork.yml` in this repo
2. Commit and push to `main`
3. All provider repos automatically use the updated logic on next workflow run (no PRs needed)

To change how wrapper files look (e.g., add a new input):

1. Edit `wrappers/*.j2` templates
2. Commit and push to `main`
3. `distribute.yml` auto-creates PRs in all provider repos with updated wrappers

## Secrets

| Secret | Where | Purpose |
|--------|-------|---------|
| `FORK_SYNC_PAT` | Each provider repo | Allows sync-to-fork to push to `trudenboy/ma-server` |
| `FORK_SYNC_PAT` | `ma-provider-tools` | Allows distribute.yml to create PRs in provider repos |
