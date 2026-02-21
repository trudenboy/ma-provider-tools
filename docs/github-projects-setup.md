# MA Ecosystem — GitHub Projects Setup

Project URL: <https://github.com/users/trudenboy/projects/3>

## What Was Automated

The following was configured via CLI and is already active:

| Resource | ID |
|----------|----|
| Project number | 3 |
| Project node ID | `PVT_kwHOCFMIf84BPvYe` |

### Custom Fields

| Field | Type | Field ID |
|-------|------|----------|
| Status | Single select | `PVTSSF_lAHOCFMIf84BPvYezg-EBfE` |
| Provider | Single select | `PVTSSF_lAHOCFMIf84BPvYezg-EBos` |
| Incident Type | Single select | `PVTSSF_lAHOCFMIf84BPvYezg-EBow` |
| Priority | Single select | `PVTSSF_lAHOCFMIf84BPvYezg-EBo0` |
| Version | Text | `PVTF_lAHOCFMIf84BPvYezg-EBpg` |

### Status Field Options

| Option | ID | Used by |
|--------|----|---------|
| Triage | `0a72259f` | Incident Board |
| In Progress | `6325b19f` | Incident Board |
| Blocked | `d42de83c` | Incident Board |
| Done | `6185362d` | Incident Board |
| Released | `05135656` | Release Pipeline (set by `reusable-release.yml`) |
| Synced to Fork | `3e9d1353` | Release Pipeline (set by `reusable-sync-to-fork.yml`) |

### Linked Repositories

All 5 provider repos are linked to the project:
- `trudenboy/ma-provider-yandex-music`
- `trudenboy/ma-provider-kion-music`
- `trudenboy/ma-provider-zvuk-music`
- `trudenboy/ma-provider-msx-bridge`
- `trudenboy/ma-server`

---

## Manual Steps Required in GitHub UI

### 1. Update FORK_SYNC_PAT Scope (Required for workflow automation)

The `FORK_SYNC_PAT` secret must have **`project` scope** (classic PAT) or **`projects:write`** (fine-grained PAT).

Without this, the "Track release/sync in MA Ecosystem project" steps will be skipped (they use `continue-on-error: true` so CI won't break).

Steps:
1. Go to GitHub → Settings → Developer settings → Personal access tokens
2. Edit the PAT used as `FORK_SYNC_PAT`
3. Enable the **`project`** scope
4. Update the secret in each provider repo and in this (`ma-provider-tools`) repo

### 2. Create Views

Navigate to <https://github.com/users/trudenboy/projects/3> and create the following views:

#### Incident Board (Board layout)
- Layout: **Board**
- Group by: **Status**
- Sort by: **Priority**
- Filter: `status:Triage,In Progress,Blocked,Done`

#### Release Pipeline (Table layout)
- Layout: **Table**
- Columns: Repository, Version, Status
- Filter: `status:Released,"Synced to Fork"`
- Sort by: **Repository**

#### Backlog (Table layout)
- Layout: **Table**
- Sort by: **Priority** → **Incident Type** → **Repository**
- Filter: open items only (default)

### 3. Configure Built-in Automations

In the project → **Workflows** tab, enable:

| Workflow | Trigger | Action |
|----------|---------|--------|
| Auto-add to project | Issue opened with label `incident:ci` in any linked repo | Add to project, Status = Triage |
| Auto-add to project | Issue opened with label `incident:bug` | Add to project, Status = Triage |
| Auto-add to project | Issue opened with label `incident:upstream` | Add to project, Status = Triage |
| Auto-add to project | Issue opened with label `incident:security` | Add to project, Status = Triage |
| Auto-add to project | Issue opened with label `incident:proposal` | Add to project, Status = Triage |
| Auto-archive | Item closed | Archive after 7 days |
| Auto-close | PR merged | Status = Done |

### 4. Add Existing Open Incidents

Manually add any existing open issues from provider repos:
```
gh issue list --repo trudenboy/ma-provider-yandex-music --label "incident:ci,incident:bug,incident:upstream,incident:security,incident:proposal" --state open
```
Then add each to the project via the UI or:
```bash
gh project item-add 3 --owner trudenboy --url <ISSUE_URL>
```

---

## How Workflow Automation Works

### On Release (`reusable-release.yml`)

When a provider release succeeds, the workflow:
1. Creates a draft project item titled `"Release {repo-name} v{version}"`
2. Sets **Status = Released**
3. Sets **Version = v{version}**

Requires `FORK_SYNC_PAT` with `project` scope passed to the reusable workflow:
```yaml
secrets:
  FORK_SYNC_PAT: ${{ secrets.FORK_SYNC_PAT }}
```

### On Sync (`reusable-sync-to-fork.yml`)

When a sync PR is created in `trudenboy/ma-server`, the workflow:
1. Adds the PR URL as a project item
2. Sets **Status = Synced to Fork**

Uses the existing `FORK_SYNC_PAT` secret (already required by this workflow).
