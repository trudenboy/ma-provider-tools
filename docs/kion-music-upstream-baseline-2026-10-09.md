# KION Music sync baseline, 2026-10-09

Reviewed upstream: `music-assistant/server@d22d28c087ded4289c67c8121c7697f02d9f6e62`.
Provider release: `v3.0.12` (`34475de`, aligned on yandex-music[async]==3.2.1).

Music integration sync requires KION's matching shared dependency pin. KION
preflight currently flags api_client.py, provider.py, conftest.py,
test_provider.py and test_recommendations.py. No upstream implementation or
regression test is missing from the provider tree. Review used full diffs and
AST comparisons to distinguish method reordering from behavior changes.

- API client: all upstream methods are present. The provider removes redundant
  guards for list results, uses the public request property and returns None
  for invalid landing responses. Non-dictionary file-info responses still
  return None. BadRequest is deliberately terminal, and rejected batch fetches
  raise rather than return an empty successful response, preserving sync state.
- Provider: every upstream method is present. The only method-body difference
  records omitted library IDs in sync_run_state, a released provider fix.
- Tests: all upstream functions remain with identical ASTs. The deserialization
  fixture uses ClientAsync() rather than an unnecessary fake token. Additional
  tests protect the provider's released fixes.

The textual detector flags method reordering and equivalent compatibility
changes. The immutable baseline acknowledges only unchanged upstream blobs;
new edits and baseline lookup failures remain blocking. No unconditional
ack_upstream_ahead override is enabled. This is distributed through the registry
rather than hand-editing rendered provider workflows.
