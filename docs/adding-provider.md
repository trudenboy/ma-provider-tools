---
id: adding-provider
sidebar_position: 2
---

# Adding a New Provider

## 1. Create the provider repository

Create a new GitHub repository under `trudenboy/` following the naming convention `ma-provider-<domain>`.

## 2. Add to `providers.yml`

Add an entry to `providers.yml` in this repository:

```yaml
- domain: my_provider          # must match manifest.json domain field
  display_name: My Provider    # human-readable name used in docs and issue templates
  repo: trudenboy/ma-provider-my-provider
  default_branch: main
  manifest_path: provider/manifest.json
  provider_path: provider/
  provider_type: music_provider  # or player_provider
  locale: en                   # en or ru — controls language in docs and issue templates
```

### `provider_type` values

- `music_provider` — uses upstream `music-assistant/server` for testing (lighter CI)
- `player_provider` — uses `trudenboy/ma-server` fork with symlink (heavier CI with ruff + mypy)

### Optional fields

| Field | Type | Description |
|-------|------|-------------|
| `locale` | `en` \| `ru` | Language for distributed docs and issue templates. Defaults to `en`. |
| `skip_wrappers` | list of filenames | Template files to skip for this repo. Use to preserve manual files or exclude irrelevant templates. |
| `legacy_files` | list of paths | Files to delete from the provider repo during distribution (superseded by wrapper files). |

### `skip_wrappers` example

```yaml
skip_wrappers:
  - contributing.md.j2         # repo has a custom contributing guide
  - docs/testing.md.j2         # not applicable (e.g., server fork)
```

## 3. Run the distribute workflow

After merging the `providers.yml` update, the `distribute.yml` workflow automatically creates PRs
in the new provider repo with the initial wrapper files. The PRs have auto-merge (squash) enabled —
they merge themselves once CI passes.

Alternatively, run manually:

```bash
pip install jinja2 pyyaml
GH_TOKEN=<your-pat> python3 scripts/distribute.py

# Dry run (no PRs created):
GH_TOKEN=<your-pat> python3 scripts/distribute.py --dry-run
```

### Default distributed files (24 templates)

| Template | Destination |
|----------|-------------|
| `sync-to-fork.yml.j2` | `.github/workflows/sync-to-fork.yml` |
| `release.yml.j2` | `.github/workflows/release.yml` |
| `test.yml.j2` | `.github/workflows/test.yml` |
| `security.yml.j2` | `.github/workflows/security.yml` |
| `sync-labels.yml.j2` | `.github/workflows/sync-labels.yml` |
| `labels.yml.j2` | `.github/labels.yml` |
| `copilot-triage.yml.j2` | `.github/workflows/copilot-triage.yml` |
| `issue-project.yml.j2` | `.github/workflows/issue-project.yml` |
| `SECURITY.md.j2` | `SECURITY.md` |
| `issue-bug.yml.j2` | `.github/ISSUE_TEMPLATE/bug_report.yml` |
| `issue-upstream.yml.j2` | `.github/ISSUE_TEMPLATE/upstream_api_change.yml` |
| `issue-proposal.yml.j2` | `.github/ISSUE_TEMPLATE/improvement_proposal.yml` |
| `issue-config.yml.j2` | `.github/ISSUE_TEMPLATE/config.yml` |
| `contributing.md.j2` | `docs/contributing.md` |
| `docker-compose.dev.yml.j2` | `docker-compose.dev.yml` |
| `scripts/docker-init.sh.j2` | `scripts/docker-init.sh` |
| `docs/dev-docker.md.j2` | `docs/dev-docker.md` |
| `docs/testing.md.j2` | `docs/testing.md` |
| `docs/incident-management.md.j2` | `docs/incident-management.md` |
| `.github/PULL_REQUEST_TEMPLATE.md.j2` | `.github/PULL_REQUEST_TEMPLATE.md` |
| `docs.yml.j2` | `.github/workflows/docs.yml` |
| `mkdocs.yml.j2` | `mkdocs.yml` |
| `docs/index.md.j2` | `docs/index.md` |
| `docs/known-issues.md.j2` | `docs/known-issues.md` _(music_provider only)_ |

## 4. Add `FORK_SYNC_PAT` secret

The provider repo needs `FORK_SYNC_PAT` set to a PAT with `contents:write` on `trudenboy/ma-server`:

```bash
gh secret set FORK_SYNC_PAT --body "$PAT" --repo trudenboy/ma-provider-my-provider
```

## 5. Enable GitHub Pages

The `docs.yml` workflow builds and deploys MkDocs documentation, but GitHub Pages must be enabled once per repo:

1. Go to **Settings → Pages → Source** → set to **GitHub Actions**
2. Or via CLI:
   ```bash
   # After the first docs.yml run, enable Pages:
   gh api repos/trudenboy/ma-provider-my-provider/pages --method POST \
     --field build_type=workflow
   ```

The docs site will be live at `https://trudenboy.github.io/ma-provider-my-provider/` after the first successful `docs.yml` run.

> **Note:** For `player_provider`, `docs/known-issues.md.j2` is automatically skipped (add it to `skip_wrappers` is not needed — the template type check handles it). The `mkdocs.yml` and `docs/index.md` conditional nav/links are also adapted automatically via `provider_type`.

## 6. Update `ma-server` references

The `create-upstream-pr.yml` workflow in `trudenboy/ma-server` reads providers from this registry
dynamically — no manual update needed.
