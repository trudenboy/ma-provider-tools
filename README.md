# ma-provider-tools

Central repository for shared GitHub Actions workflows and provider registry for Music Assistant custom providers.

## What's Here

| Path | Purpose |
|------|---------|
| `providers.yml` | Registry of all custom MA providers |
| `.github/workflows/reusable-*.yml` | Shared reusable workflows (sync, release, test) |
| `.github/workflows/distribute.yml` | Auto-distributes wrapper files to provider repos |
| `wrappers/*.j2` | Jinja2 templates for provider repo wrapper files |
| `scripts/distribute.py` | Script that renders templates and creates PRs |

## Provider Registry

See [providers.yml](providers.yml) for the list of all managed providers.

## Documentation

- [Workflow Overview](docs/workflow-overview.md) — architecture and how it works
- [Adding a Provider](docs/adding-provider.md) — step-by-step guide

## Updating Shared Logic

Edit `reusable-*.yml` workflows directly. Provider repos call them via `uses:`, so updates
take effect immediately on next run — no need to push to individual repos.

## Updating Wrapper Files

Edit `wrappers/*.j2` templates. The `distribute.yml` workflow auto-creates PRs in all provider
repos when these files change. PRs have auto-merge (squash) enabled and merge automatically
once CI passes.
