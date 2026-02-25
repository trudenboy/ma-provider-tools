---
title: Workflow System Overview
description: Architecture of the shared CI/CD system — reusable workflows, wrapper templates, and automated distribution.
---

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
│    reusable-report-incident.yml ← CI failure → issue    │
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
- `locale` — language for issue templates and docs (`en` or `ru`)
- `skip_wrappers` — list of template filenames to skip for this repo

### 2. Reusable Workflows

Located in `.github/workflows/reusable-*.yml`. These use `workflow_call` and contain
all the actual logic. Provider repos call them with provider-specific parameters.

| Workflow | Purpose |
|----------|---------|
| `reusable-sync-to-fork.yml` | Syncs provider files to `trudenboy/ma-server` |
| `reusable-release.yml` | Creates git tag, GitHub release, triggers sync |
| `reusable-test.yml` | Runs CI (lint + tests), adapts to provider type |
| `reusable-report-incident.yml` | Creates/updates GitHub issue on CI failure |

### 3. Wrapper Templates

Located in `wrappers/*.j2`. These are Jinja2 templates rendered by `distribute.py` for each
provider. The rendered files are small and only contain provider-specific inputs,
delegating everything else to the reusable workflows.

| Template | Destination | Purpose |
|----------|-------------|---------|
| `sync-to-fork.yml.j2` | `.github/workflows/sync-to-fork.yml` | Sync provider files to fork |
| `release.yml.j2` | `.github/workflows/release.yml` | Create releases |
| `test.yml.j2` | `.github/workflows/test.yml` | CI (lint + tests) |
| `security.yml.j2` | `.github/workflows/security.yml` | Security audit (Dependabot/Trivy) |
| `sync-labels.yml.j2` | `.github/workflows/sync-labels.yml` | Sync issue labels |
| `labels.yml.j2` | `.github/labels.yml` | Label definitions |
| `copilot-triage.yml.j2` | `.github/workflows/copilot-triage.yml` | AI-assisted issue triage |
| `issue-project.yml.j2` | `.github/workflows/issue-project.yml` | Add issues to project board |
| `SECURITY.md.j2` | `SECURITY.md` | Security policy |
| `issue-bug.yml.j2` | `.github/ISSUE_TEMPLATE/bug_report.yml` | Bug report form |
| `issue-upstream.yml.j2` | `.github/ISSUE_TEMPLATE/upstream_api_change.yml` | Upstream API change form |
| `issue-proposal.yml.j2` | `.github/ISSUE_TEMPLATE/improvement_proposal.yml` | Improvement proposal form |
| `issue-config.yml.j2` | `.github/ISSUE_TEMPLATE/config.yml` | Issue chooser config |
| `contributing.md.j2` | `docs/contributing.md` | Contribution guide |
| `docker-compose.dev.yml.j2` | `docker-compose.dev.yml` | Docker dev environment |
| `scripts/docker-init.sh.j2` | `scripts/docker-init.sh` | Docker init script |
| `docs/dev-docker.md.j2` | `docs/dev-docker.md` | Docker dev guide |
| `docs/testing.md.j2` | `docs/testing.md` | Testing guide |
| `docs/incident-management.md.j2` | `docs/incident-management.md` | Incident management guide |
| `.github/PULL_REQUEST_TEMPLATE.md.j2` | `.github/PULL_REQUEST_TEMPLATE.md` | PR checklist |
| `docs.yml.j2` | `.github/workflows/docs.yml` | GitHub Pages deploy (Astro Starlight → Pages) |
| `docs/index.md.j2` | `docs-site/src/content/docs/index.md` | Landing page |
| `docs/known-issues.md.j2` | `docs-site/src/content/docs/known-issues.md` | Common issues (music providers only) |

### 4. distribute.yml — Auto-Distribution

Triggers on push to `main` when `wrappers/` or `providers.yml` changes.
Runs `scripts/distribute.py` which:
1. Reads `providers.yml`
2. Renders wrapper templates for each provider
3. Creates a PR in each provider repo with the updated files
4. Enables auto-merge (squash) on the PR — merges automatically once CI passes

### 5. Docker Dev Environment

Each provider repo receives `docker-compose.dev.yml` and `scripts/docker-init.sh`, which let
contributors run a full Music Assistant instance locally without installing Python, FFmpeg, or
other dependencies:

```bash
docker compose -f docker-compose.dev.yml up
```

The provider code is mounted via symlink — no image rebuild needed after code changes.
See `docs/dev-docker.md` in each provider repo for full instructions.

### 6. Incident Pipeline

CI failures automatically become tracked GitHub issues:

```
test.yml fails
    ↓
reusable-report-incident.yml
    ↓
GitHub Issue created (incident:ci + priority:high)
    ↓
issue-project.yml triggered
    ↓
Issue added to MA Ecosystem project board
    ↓
[optional] Add label "copilot"
    ↓
copilot-triage.yml → @copilot assigned → may submit a PR
```

Deduplication: if an open issue for the same failure type already exists, a comment is added
instead of creating a duplicate.

Other incident types: `incident:sync` (fork sync failure), `incident:security` (security audit
failure), `incident:release` (release pipeline failure).

### 7. GitHub Pages Documentation

Each provider repo receives a full Astro Starlight documentation site, deployed automatically to GitHub Pages on push to `default_branch`.

The site is **bilingual** — language is controlled by the `locale` field in `providers.yml` (`ru` or `en`). The `site_url` and `edit_uri` are derived from the `repo` and `default_branch` fields.

Nav includes a **Known Issues** page only for `music_provider` repos (skipped for `player_provider` via `skip_wrappers`).

**One-time setup** per provider repo (not automated):

```bash
# Enable GitHub Pages via GitHub Actions source in Settings → Pages → Source: GitHub Actions
```

After enabling, the site is live at `https://trudenboy.github.io/<repo-name>/`.

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
