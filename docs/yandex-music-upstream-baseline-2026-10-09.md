# Yandex Music sync baseline, 2026-10-09

Reviewed upstream: `music-assistant/server@d22d28c087ded4289c67c8121c7697f02d9f6e62`.
Provider release: `v3.8.15` (`9027c2d776e34f539f9c052664c2ab4709fb62b0`).

The preflight flags only `provider/api_client.py`. Upstream PR #6774 changed
this file relative to provider v3.8.12 as follows:

- Removed four redundant None checks for list-returning library APIs: preserved.
- Copied album and playlist ID lists: preserved using starred list expressions.
- Validated the landing-block response as a dictionary: preserved using the
  public request property and returning None otherwise.
- Validated the raw get-file-info response as a dictionary: superseded by the
  library's typed tracks_file_info response, with download-info and URL guards.

The provider additionally uses library radio-session methods, preserves final
radio batches, recovers expired sessions and coalesces URL requests. Restoring
upstream's older raw HTTP implementation would undo these released changes.
The file does not match a historical release, and the textual port detector
cannot establish equivalent behavior across the library migration.

The immutable baseline acknowledges only upstream blobs that remain unchanged
since this review. New upstream edits still fail closed. No unconditional
ack_upstream_ahead override is enabled. The setting is rendered into both
pipeline sync jobs, manual sync and backport wrappers from providers.yml.

Validation: live preflight against v3.8.15 succeeds with this baseline; existing
core guard tests cover changed blobs, missing paths and baseline lookup failure.
