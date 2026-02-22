# ma-provider-tools

Central infrastructure repository for Music Assistant custom providers.
Manages shared CI/CD workflows and distributes standardized files to all provider repos automatically.

## Managed Providers

| Provider | Repo | Type |
|----------|------|------|
| Yandex Music | [ma-provider-yandex-music](https://github.com/trudenboy/ma-provider-yandex-music) | music_provider |
| KION Music | [ma-provider-kion-music](https://github.com/trudenboy/ma-provider-kion-music) | music_provider |
| Zvuk Music | [ma-provider-zvuk-music](https://github.com/trudenboy/ma-provider-zvuk-music) | music_provider |
| MSX Bridge | [ma-provider-msx-bridge](https://github.com/trudenboy/ma-provider-msx-bridge) | player_provider |

## What This Repo Does

### Shared Reusable Workflows

Located in `.github/workflows/reusable-*.yml`. Provider repos call them via `uses:` —
changes take effect immediately across all repos without any PRs.

| Workflow | Purpose |
|----------|---------|
| `reusable-sync-to-fork.yml` | Syncs provider files into `trudenboy/ma-server` |
| `reusable-release.yml` | Creates git tags, GitHub releases, triggers sync |
| `reusable-test.yml` | Runs CI: pytest + ruff + mypy + codespell + pre-commit |
| `reusable-report-incident.yml` | Creates/deduplicates GitHub issues on CI failures |

### Wrapper File Distribution

`scripts/distribute.py` renders 24 Jinja2 templates per provider and creates PRs with the results.
Triggered automatically by `distribute.yml` on push to `main` when `wrappers/` or `providers.yml` changes.

**CI & automation**

| Template → Destination | Purpose |
|------------------------|---------|
| `test.yml.j2` → `.github/workflows/test.yml` | Calls `reusable-test.yml` |
| `release.yml.j2` → `.github/workflows/release.yml` | Calls `reusable-release.yml` |
| `sync-to-fork.yml.j2` → `.github/workflows/sync-to-fork.yml` | Calls `reusable-sync-to-fork.yml` |
| `security.yml.j2` → `.github/workflows/security.yml` | Dependabot + Trivy security audit |
| `copilot-triage.yml.j2` → `.github/workflows/copilot-triage.yml` | Routes `copilot`-labeled issues to @copilot |
| `issue-project.yml.j2` → `.github/workflows/issue-project.yml` | Adds `incident:*` issues to project board |
| `sync-labels.yml.j2` → `.github/workflows/sync-labels.yml` | Keeps labels in sync |

**Labels & issue templates**

| Template → Destination | Purpose |
|------------------------|---------|
| `labels.yml.j2` → `.github/labels.yml` | Incident + priority + copilot labels |
| `issue-bug.yml.j2` → `.github/ISSUE_TEMPLATE/bug_report.yml` | Bug report form |
| `issue-upstream.yml.j2` → `.github/ISSUE_TEMPLATE/upstream_api_change.yml` | Upstream API change form |
| `issue-proposal.yml.j2` → `.github/ISSUE_TEMPLATE/improvement_proposal.yml` | Improvement proposal form |
| `issue-config.yml.j2` → `.github/ISSUE_TEMPLATE/config.yml` | Issue chooser config |
| `.github/PULL_REQUEST_TEMPLATE.md.j2` → `.github/PULL_REQUEST_TEMPLATE.md` | PR checklist |

**Documentation**

| Template → Destination | Purpose |
|------------------------|---------|
| `contributing.md.j2` → `docs/contributing.md` | Contribution guide |
| `docs/testing.md.j2` → `docs/testing.md` | Testing guide: pytest, CI, coverage |
| `docs/incident-management.md.j2` → `docs/incident-management.md` | Labels, auto-incidents, Copilot triage |
| `docs/dev-docker.md.j2` → `docs/dev-docker.md` | Docker dev environment guide |
| `SECURITY.md.j2` → `SECURITY.md` | Security policy |

**GitHub Pages docs** (skipped for `player_provider`: `docs/known-issues.md.j2`; skipped for providers with custom versions via `skip_wrappers`)

| Template → Destination | Purpose |
|------------------------|---------|
| `docs.yml.j2` → `.github/workflows/docs.yml` | MkDocs build + GitHub Pages deploy workflow |
| `mkdocs.yml.j2` → `mkdocs.yml` | MkDocs Material config (bilingual, `site_url` from `repo`) |
| `docs/index.md.j2` → `docs/index.md` | Landing page with links to key sections |
| `docs/known-issues.md.j2` → `docs/known-issues.md` | Common issues for music providers (OAuth, geo-blocks, etc.) |

**Docker dev environment**

| Template → Destination | Purpose |
|------------------------|---------|
| `docker-compose.dev.yml.j2` → `docker-compose.dev.yml` | Full MA stack via one command |
| `scripts/docker-init.sh.j2` → `scripts/docker-init.sh` | Init script for Docker environment |

### Incident Pipeline

CI failures are automatically tracked as GitHub issues and routed to a project board:

```
test.yml fails → reusable-report-incident → GitHub Issue (incident:ci + priority:high)
                                                    ↓
                                         issue-project.yml → MA Ecosystem board
                                                    ↓
                              add label "copilot" → copilot-triage → @copilot PR
```

Deduplication: existing open issue gets a comment instead of a duplicate.

## Repository Structure

```
.github/workflows/
  reusable-*.yml          ← shared logic (edit here to affect all providers instantly)
  distribute.yml          ← triggers distribute.py on push to main
wrappers/
  *.j2                    ← Jinja2 templates rendered per provider
  docs/*.j2
  scripts/*.j2
  .github/*.j2
scripts/
  distribute.py           ← renders templates, creates PRs in provider repos
providers.yml             ← registry: domain, repo, locale, skip_wrappers, ...
docs/
  workflow-overview.md    ← architecture deep-dive
  adding-provider.md      ← step-by-step guide for new providers
  github-projects-setup.md
```

## Quick Operations

**Update shared CI logic** (affects all providers immediately):
```bash
# Edit reusable-*.yml, commit, push to main
```

**Update wrapper files** (creates PRs in all provider repos):
```bash
# Edit wrappers/*.j2 or providers.yml, commit, push to main
```

**Run distribute manually**:
```bash
pip install jinja2 pyyaml
GH_TOKEN=<your-pat> python3 scripts/distribute.py

# Dry run:
GH_TOKEN=<your-pat> python3 scripts/distribute.py --dry-run
```

## Documentation

- [Workflow Overview](docs/workflow-overview.md) — full architecture, all workflows, incident pipeline
- [Adding a Provider](docs/adding-provider.md) — step-by-step, all `providers.yml` fields, 20-template table
- [GitHub Projects Setup](docs/github-projects-setup.md) — project board configuration
