# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Does

Central infrastructure for Music Assistant custom providers. It manages two things:
1. **Shared reusable workflows** (`reusable-*.yml`) — logic called by all provider repos via `uses:`
2. **Wrapper file distribution** — Jinja2 templates rendered per-provider and pushed as PRs

Changes to `reusable-*.yml` take effect immediately in all provider repos (no PRs needed).
Changes to `wrappers/*.j2` or `providers.yml` trigger `distribute.yml`, which auto-creates PRs in every provider repo.

## Key Files

| File | Role |
|------|------|
| `providers.yml` | Registry of all providers — single source of truth |
| `scripts/distribute.py` | Renders Jinja2 templates and creates PRs in provider repos |
| `wrappers/*.j2` | Templates rendered once per provider; use `{% raw %}...{% endraw %}` around GitHub Actions expression syntax (`${{ }}`) to prevent Jinja2 from interpreting it |
| `.github/workflows/reusable-*.yml` | Shared logic called by provider repos via `workflow_call` |
| `.github/workflows/distribute.yml` | Runs `distribute.py` on push to `main` when wrappers or registry changes |

## Running distribute.py Locally

```bash
pip install jinja2 pyyaml
GH_TOKEN=<your-pat> python3 scripts/distribute.py

# Dry run (no PRs created):
GH_TOKEN=<your-pat> python3 scripts/distribute.py --dry-run
```

Requires `gh` CLI and a PAT with `contents:write` on all provider repos.

## providers.yml Schema

```yaml
providers:
  - domain: my_provider          # matches manifest.json domain field
    repo: trudenboy/ma-provider-my-provider
    default_branch: dev          # branch distribute.py targets for PRs
    manifest_path: provider/manifest.json
    provider_path: provider/
    provider_type: music_provider  # or player_provider
    legacy_files:                # optional: files to delete during distribution
      - .github/workflows/old.yml
```

`provider_type` controls CI behavior in `reusable-test.yml`:
- `music_provider` — uses upstream `music-assistant/server` (lighter CI)
- `player_provider` — uses `trudenboy/ma-server` fork with ruff + mypy (heavier CI)

## Jinja2 Template Conventions

Templates in `wrappers/` receive these variables: `domain`, `display_name`, `manifest_path`, `provider_path`, `provider_type`, `locale`.

GitHub Actions expressions (`${{ }}`) must be wrapped in `{% raw %}...{% endraw %}` blocks to prevent Jinja2 from interpreting them.

## Secrets

`FORK_SYNC_PAT` — a PAT with `contents:write` — must be set in:
- Each provider repo (for sync-to-fork and release workflows)
- This repo (for `distribute.yml` to create PRs in provider repos)

## Adding a Provider

1. Add entry to `providers.yml`
2. Push to `main` — `distribute.yml` auto-creates PRs with wrapper files in the new repo
3. Set `FORK_SYNC_PAT` secret in the new provider repo
