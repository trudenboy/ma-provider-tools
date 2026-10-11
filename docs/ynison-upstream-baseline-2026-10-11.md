# Ynison upstream guard baseline, 2026-10-11

Supersedes the reviewed baseline in
[`ynison-upstream-baseline-2026-10-02.md`](ynison-upstream-baseline-2026-10-02.md);
the residual differences recorded there still apply.

## Reviewed snapshots

- Provider: [v4.3.8](https://github.com/trudenboy/ma-provider-yandex-ynison/tree/v4.3.8).
- Upstream: [5456607](https://github.com/music-assistant/server/tree/5456607e50f70fe7b5d9446d6909121c8487f952),
  full SHA `5456607e50f70fe7b5d9446d6909121c8487f952`.

## Symptom

Every stable release since v4.3.5 failed both forward-sync jobs of the release
pipeline with "Upstream music-assistant/server is ahead of this provider repo",
and incident issue trudenboy/ma-provider-yandex-ynison#176 collected the
failures. The upstream PR branch was refreshed only by re-dispatching the manual
sync with `ack_upstream_ahead=true`.

## Upstream changes since the previous baseline

| Upstream PR | Files | Provider status |
| --- | --- | --- |
| [#6714](https://github.com/music-assistant/server/pull/6714) | `manifest.json`, `tests/test_provider.py` | Auth pin bump applied to the obsolete manifest that still lists `segno`; the provider pins the same library in its own release (v4.3.6). The test-stub change targets the removed own/borrow credential tests; linked-credential tests already stub `get_setup_value`. |
| [#6741](https://github.com/music-assistant/server/pull/6741) | `manifest.json` | Same auth pin as provider v4.3.8; only the obsolete `segno` entry differs. |
| [#6887](https://github.com/music-assistant/server/pull/6887) | `provider.py`, `ynison_client.py` | Two `noqa: S311` suppressions, ported byte-identically in provider PR [#188](https://github.com/trudenboy/ma-provider-yandex-ynison/pull/188). |

No upstream behavior is lost by the forward sync once provider PR #188 is in the
released provider. The #6887 delta is acknowledged here only because the guard
compares against the v4.3.8 tag; the next release carries the port.

## Validation

Run from the tools checkout against a provider worktree at tag `v4.3.8`, with
`ruff==0.16.5` available so the boundary transform matches CI:

```bash
python scripts/check_upstream_ahead.py \
  --domain yandex_ynison --provider-path provider/ \
  --provider-dir /path/to/provider-v4.3.8 \
  --upstream-ref 5456607e50f70fe7b5d9446d6909121c8487f952 \
  --acknowledged-upstream-ref <baseline>
```

- Baseline `ef4ba48c…`: exits 1 and lists `provider/manifest.json`,
  `provider/provider.py`, `provider/ynison_client.py`, `tests/test_provider.py`,
  which reproduces the pipeline failure.
- Baseline `5456607e…`: exits 0.

`test_ynison_distribution_preserves_guard_for_all_sync_entrypoints` fails with
the old registry SHA and passes with the new one; the full tools suite passes.
