# Upstream Guard Baseline Design

## Goal

Allow the forward-sync guard to acknowledge reviewed, pre-existing upstream
divergence for one provider without weakening protection against later upstream
changes.

The immediate rollout target is `fastmcp_server`. Its acknowledged upstream
tree is `music-assistant/server@a91504084610a817212c17174662cf73a4829bd9`.

## Problem

`check_upstream_ahead.py` currently removes two classes of harmless
differences: upstream content matching an older provider release and textual
upstream edits already reflected in provider HEAD. The second comparison
cannot prove architectural ports where upstream files were replaced, split,
or intentionally removed in the provider repository.

The `fastmcp_server` pipeline therefore blocks on 19 files whose relevant
upstream changes were already reviewed and incorporated through replacement
provider changes. No source or test file below the upstream provider roots has
changed after the reviewed tree above.

The existing `ack_upstream_ahead` input is an unsuitable durable fix because it
skips the entire guard for a run, including genuinely new upstream work.

## Chosen Design

Add an optional per-provider `upstream_guard_baseline` field to
`providers.yml`. The value is a full 40-character lowercase Git commit SHA in
`music-assistant/server`.

The guard will list the provider source and test trees at both the current
upstream ref and the acknowledged baseline. After the existing direction and
already-ported checks, it will remove a still-flagged path only when all of the
following are true:

1. The current upstream path exists in the baseline tree.
2. The current upstream blob SHA exactly equals the baseline blob SHA.
3. The baseline tree was resolved successfully.

Consequently, a file added or modified after the baseline remains flagged. A
file absent from the baseline remains flagged. Failure to resolve or list the
baseline leaves every difference flagged and emits a warning. This is
fail-closed.

The comparison uses immutable Git blob identifiers and does not fetch or
interpret file contents. It therefore acknowledges the exact reviewed tree,
not a filename pattern or semantic approximation.

## Components and Data Flow

### Provider registry

`schemas/providers.schema.json` accepts the optional
`upstream_guard_baseline` field and validates it as a full lowercase SHA.
Only the `fastmcp_server` entry initially sets it.

Both wrapper-rendering contexts and template validation expose the field with
an empty-string default. Providers without it retain current behavior and
render no additional workflow input.

### Generated pipeline wrapper

`wrappers/pipeline.yml.j2` passes `upstream_guard_baseline` to both
`sync-integration` and `sync-upstream` only when configured. This keeps the
rendered output unchanged for all other providers.

### Reusable sync workflow

`.github/workflows/reusable-sync-to-fork.yml` declares an optional string
input named `upstream_guard_baseline`. The preflight command appends
`--acknowledged-upstream-ref <SHA>` only when the input is non-empty. The
existing one-run `ack_upstream_ahead` override remains available for manual
emergencies but is not used by this rollout.

### Guard implementation

`scripts/check_upstream_ahead.py` adds the optional
`--acknowledged-upstream-ref` argument and a focused filter over the current and
baseline upstream tree maps. It runs after `drop_provider_ahead` and
`drop_already_ported`, so the baseline only handles residual architectural
divergence and does not replace the existing automatic proofs.

Each removed path produces a GitHub Actions notice naming the baseline. A
baseline lookup exception produces a warning and leaves the residual list
unchanged.

## Error Handling and Safety

- Empty baseline: preserve current behavior exactly.
- Malformed registry SHA: reject in registry validation before distribution.
- Unresolvable baseline or GitHub API failure: warn and block the sync.
- Current upstream path missing from baseline: block the sync.
- Current blob differs from baseline: block the sync.
- Baseline path unchanged while provider differs architecturally: allow that
  path only.
- `ack_upstream_ahead=true`: retain its existing explicit whole-run override
  semantics; this design does not invoke it.

No workflow writes to `music-assistant/*`. The only upstream operations remain
read-only tree queries.

## Testing

Tests will prove:

1. An unchanged current blob present at the acknowledged baseline is removed
   from the residual ahead list.
2. A blob changed after the baseline remains flagged.
3. A current path absent from the baseline remains flagged.
4. A baseline lookup failure remains fail-closed.
5. The FastMCP pipeline renders the exact SHA into both sync jobs.
6. A provider without a baseline renders neither input, preserving its wrapper.
7. Schema validation accepts a full SHA and rejects branches, short SHAs, and
   uppercase SHAs.
8. Existing guard, template, registry, and full repository tests stay green.

## Rollout and Success Criteria

1. Merge the canonical tools change after human review.
2. Let the normal distribution workflow open the generated provider wrapper
   update; its mechanical PR may follow the documented auto-merge exception.
3. Dispatch a fresh provider Pipeline from `dev`, ensuring it resolves the new
   reusable-workflow revision.
4. Confirm both `sync-integration` and `sync-upstream` pass preflight and sync.
5. Confirm the guard would still block a synthetic blob change after the
   baseline through its unit tests.

Success means the current reviewed FastMCP divergence no longer blocks either
sync job, while any upstream source or test blob changed after the pinned SHA
still blocks by default.
