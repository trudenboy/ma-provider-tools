# Adding a New Provider

## 1. Create the provider repository

Create a new GitHub repository under `trudenboy/` following the naming convention `ma-provider-<domain>`.

## 2. Add to `providers.yml`

Add an entry to `providers.yml` in this repository:

```yaml
- domain: my_provider          # must match manifest.json domain field
  repo: trudenboy/ma-provider-my-provider
  default_branch: main
  manifest_path: provider/manifest.json
  provider_path: provider/
  provider_type: music_provider  # or player_provider
```

**`provider_type` values:**
- `music_provider` — uses upstream `music-assistant/server` for testing (lighter CI)
- `player_provider` — uses `trudenboy/ma-server` fork with symlink (heavier CI with ruff + mypy)

## 3. Run the distribute workflow

After merging the `providers.yml` update, the `distribute.yml` workflow automatically creates PRs
in the new provider repo with the initial wrapper workflow files. The PRs have auto-merge
(squash) enabled — they merge themselves once CI passes.

Alternatively, run manually:
```bash
pip install jinja2 pyyaml
GH_TOKEN=<your-pat> python3 scripts/distribute.py
```

## 4. Add `FORK_SYNC_PAT` secret

The provider repo needs `FORK_SYNC_PAT` set to a PAT with `contents:write` on `trudenboy/ma-server`:

```bash
gh secret set FORK_SYNC_PAT --body "$PAT" --repo trudenboy/ma-provider-my-provider
```

## 5. Update `ma-server` references

The `create-upstream-pr.yml` workflow in `trudenboy/ma-server` reads providers from this registry
dynamically — no manual update needed.
