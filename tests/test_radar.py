import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reverse_sync_radar as r  # noqa: E402
import reverse_sync_state as st  # noqa: E402

ECHO = {"github-actions[bot]", "trudenboy"}


def test_is_echo():
    assert r.is_echo({"user": {"login": "trudenboy"}}, ECHO) is True
    assert r.is_echo({"user": {"login": "alice"}}, ECHO) is False


def test_touches_provider():
    files = [
        "music_assistant/providers/yandex_music/api.py",
        "music_assistant/server.py",
    ]
    assert r.touches_provider(files, "yandex_music") is True
    assert r.touches_provider(["music_assistant/server.py"], "yandex_music") is False


def test_touches_provider_test_files():
    # Test-only files under tests/providers/<domain>/ must be detected.
    assert (
        r.touches_provider(["tests/providers/yandex_music/test_api.py"], "yandex_music")
        is True
    )
    # Mixed: source + test both under the domain -> True
    assert (
        r.touches_provider(
            [
                "music_assistant/providers/yandex_music/api.py",
                "tests/providers/yandex_music/test_api.py",
            ],
            "yandex_music",
        )
        is True
    )
    # Foreign test (different domain) -> False
    assert (
        r.touches_provider(
            ["tests/providers/other_provider/test_api.py"], "yandex_music"
        )
        is False
    )
    # Purely foreign source -> False
    assert r.touches_provider(["music_assistant/server.py"], "yandex_music") is False


def test_pr_files_includes_previous_filename_for_rename_out(monkeypatch):
    captured: list[list[str]] = []

    def fake_gh(args):
        captured.append(args)
        return json.dumps(
            [
                "music_assistant/helpers/api.py",
                "music_assistant/providers/yandex_music/api.py",
            ]
        )

    monkeypatch.setattr(r, "_gh", fake_gh)

    files = r._pr_files(123)

    assert r.touches_provider(files, "yandex_music") is True
    assert "previous_filename" in captured[0][-1]


def test_select_unhandled_filters_handled_and_cursor():
    data = {}
    st.mark_handled(data, "d", 100)
    prs = [
        {"number": 100, "updated_at": "2026-06-01T00:00:00Z", "user": {"login": "x"}},
        {"number": 101, "updated_at": "2026-06-02T00:00:00Z", "user": {"login": "x"}},
        {"number": 102, "updated_at": "2026-05-01T00:00:00Z", "user": {"login": "x"}},
    ]
    out = r.select_unhandled(prs, data, "d", cursor="2026-05-15T00:00:00Z")
    # 100 handled, 102 below cursor -> only 101 remains
    assert [p["number"] for p in out] == [101]


def test_upstream_default_branch_valid(monkeypatch):
    monkeypatch.setattr(r, "_gh", lambda args: "main\n")
    assert r._upstream_default_branch() == "main"


def test_upstream_default_branch_empty_falls_back(monkeypatch):
    monkeypatch.setattr(r, "_gh", lambda args: "\n")
    assert r._upstream_default_branch() == "dev"


def test_upstream_default_branch_null_falls_back(monkeypatch):
    monkeypatch.setattr(r, "_gh", lambda args: "null\n")
    assert r._upstream_default_branch() == "dev"


def test_upstream_default_branch_error_falls_back(monkeypatch):
    def boom(args):
        raise RuntimeError("api down")

    monkeypatch.setattr(r, "_gh", boom)
    assert r._upstream_default_branch() == "dev"


def test_run_saves_state_on_unexpected_exception(monkeypatch, tmp_path):
    """Fix 2: st.save must run via finally even when an unexpected (non-CalledProcessError)
    exception propagates out of the provider loop.  The exception must still re-raise."""
    providers_yml = tmp_path / "providers.yml"
    providers_yml.write_text(
        "providers:\n"
        "  - domain: test_provider\n"
        "    repo: owner/test-repo\n"
        "    default_branch: dev\n"
        "    manifest_path: provider/manifest.json\n"
        "    provider_path: provider/\n"
        "    provider_type: music_provider\n"
    )
    state_path = tmp_path / "reverse-sync.json"

    monkeypatch.setattr(r, "PROVIDERS_PATH", str(providers_yml))
    monkeypatch.setattr(r, "STATE_PATH", str(state_path))
    monkeypatch.setattr(r, "_upstream_default_branch", lambda: "dev")

    # _anchor raises KeyError — NOT caught by the per-provider
    # "except subprocess.CalledProcessError", so it propagates out of the for loop.
    def boom_anchor(domain, default_branch):
        raise KeyError("unexpected_key")

    monkeypatch.setattr(r, "_anchor", boom_anchor)

    with pytest.raises(KeyError):
        r.run()

    # Despite the exception, st.save must have been called (finally block).
    assert state_path.exists(), "st.save was NOT called — finally block missing"


# ---------------------------------------------------------------------------
# _merged_prs pagination tests
# ---------------------------------------------------------------------------


def _page_from_args(args: list[str]) -> int:
    """Extract the &page=N value from the gh api URL argument."""
    url = next(a for a in args if "pulls?" in a)
    page_part = next(p for p in url.split("&") if p.startswith("page="))
    return int(page_part.split("=")[1])


def test_merged_prs_aggregates_multiple_pages(monkeypatch):
    """Results from multiple pages are combined into one list."""
    pages = {
        1: [
            {
                "number": 10,
                "updated_at": "2026-06-10T00:00:00Z",
                "user": {"login": "alice"},
            }
        ],
        2: [
            {
                "number": 9,
                "updated_at": "2026-06-09T00:00:00Z",
                "user": {"login": "bob"},
            }
        ],
        3: [],  # empty page → stops pagination
    }

    def fake_gh(args):
        return json.dumps(pages.get(_page_from_args(args), []))

    monkeypatch.setattr(r, "_gh", fake_gh)
    result = r._merged_prs("dev", cursor=None)
    assert [pr["number"] for pr in result] == [10, 9]


def test_merged_prs_stops_at_cursor(monkeypatch):
    """Pagination stops as soon as a page contains a PR with updated_at <= cursor."""
    pages = {
        1: [
            {
                "number": 10,
                "updated_at": "2026-06-10T00:00:00Z",
                "user": {"login": "alice"},
            }
        ],
        2: [
            {
                "number": 9,
                "updated_at": "2026-06-09T00:00:00Z",
                "user": {"login": "bob"},
            },
            # This PR is at/below the cursor → should trigger stop
            {
                "number": 8,
                "updated_at": "2026-05-01T00:00:00Z",
                "user": {"login": "carol"},
            },
        ],
        3: [
            {
                "number": 7,
                "updated_at": "2026-04-01T00:00:00Z",
                "user": {"login": "dave"},
            }
        ],
    }
    pages_fetched: list[int] = []

    def fake_gh(args):
        p = _page_from_args(args)
        pages_fetched.append(p)
        return json.dumps(pages.get(p, []))

    monkeypatch.setattr(r, "_gh", fake_gh)
    result = r._merged_prs("dev", cursor="2026-06-01T00:00:00Z")
    # PRs from pages 1 and 2 are returned; page 2 stops iteration
    assert [pr["number"] for pr in result] == [10, 9, 8]
    # Page 3 must never be fetched
    assert 3 not in pages_fetched


def test_merged_prs_stops_at_max_pages(monkeypatch, capsys):
    """With cursor=None, pagination stops at MAX_PAGES and emits a warning."""
    monkeypatch.setattr(r, "MAX_PAGES", 2)

    pages_fetched: list[int] = []

    def fake_gh(args):
        p = _page_from_args(args)
        pages_fetched.append(p)
        # Always return a non-empty page so only MAX_PAGES limits the scan
        return json.dumps(
            [
                {
                    "number": 100 - p,
                    "updated_at": f"2026-06-{10 - p:02d}T00:00:00Z",
                    "user": {"login": "x"},
                }
            ]
        )

    monkeypatch.setattr(r, "_gh", fake_gh)
    result = r._merged_prs("dev", cursor=None)

    # Exactly MAX_PAGES pages were fetched
    assert pages_fetched == [1, 2]
    # Results from both pages accumulated
    assert len(result) == 2
    # Warning must be emitted to stderr
    captured = capsys.readouterr()
    assert "WARNING" in captured.err


def _write_radar_inputs(tmp_path: Path, *, handled: bool = True) -> tuple[Path, Path]:
    providers = tmp_path / "providers.yml"
    providers.write_text(
        "providers:\n"
        "  - domain: fastmcp_server\n"
        "    repo: trudenboy/ma-provider-mcp\n"
        "    default_branch: dev\n"
        "    provider_path: provider/\n"
    )
    state = tmp_path / "reverse-sync.json"
    state.write_text(
        json.dumps(
            {
                "fastmcp_server": {
                    "last_synced_sha": "anchor",
                    "handled_prs": [5782] if handled else [],
                    "pulls_cursor": "2026-08-19T12:00:00Z",
                    "digest_issue": None,
                }
            }
        )
    )
    return providers, state


def _merged_target_pr() -> dict:
    return {
        "number": 5782,
        "updated_at": "2026-08-01T00:00:00Z",
        "merged_at": "2026-08-01T01:00:00Z",
        "user": {"login": "alice"},
    }


def _configure_targeted(monkeypatch, tmp_path: Path, *, handled: bool = True):
    providers, state = _write_radar_inputs(tmp_path, handled=handled)
    monkeypatch.setattr(r, "PROVIDERS_PATH", str(providers))
    monkeypatch.setattr(r, "STATE_PATH", str(state))
    monkeypatch.setattr(r, "_upstream_pr", lambda number: _merged_target_pr())
    monkeypatch.setattr(
        r,
        "_pr_files",
        lambda number: ["tests/providers/fastmcp_server/test_debug.py"],
    )
    monkeypatch.setattr(r, "_clone_provider", lambda *args: None)
    return state


def test_targeted_retry_bypasses_handled_and_cursor_for_only_selected_pair(
    monkeypatch, tmp_path
):
    state = _configure_targeted(monkeypatch, tmp_path, handled=True)
    opened: list[tuple[str, int]] = []

    def fake_open(**kwargs):
        opened.append((kwargs["domain"], kwargs["pr_number"]))
        return {
            "skipped": False,
            "reason": None,
            "pr_url": "https://github.com/trudenboy/ma-provider-mcp/pull/278",
            "conflicts": False,
            "reused": True,
            "applied_paths": ["tests/test_debug.py"],
            "conflicted_paths": [],
            "label_failures": [],
        }

    monkeypatch.setattr(r.opener, "open_reverse_pr", fake_open)

    assert r.run(retry_domain="fastmcp_server", retry_pr="5782") == 0
    assert opened == [("fastmcp_server", 5782)]
    saved = json.loads(state.read_text())["fastmcp_server"]
    assert saved["handled_prs"] == [5782]
    assert saved["pulls_cursor"] == "2026-08-19T12:00:00Z"


@pytest.mark.parametrize(
    ("domain", "number", "merged"),
    [
        ("fastmcp_server", None, True),
        (None, "5782", True),
        ("missing", "5782", True),
        ("fastmcp_server", "0", True),
        ("fastmcp_server", "not-a-number", True),
        ("fastmcp_server", "5782", False),
    ],
)
def test_invalid_targeted_retry_fails_before_state_access(
    monkeypatch, tmp_path, domain, number, merged
):
    providers, _ = _write_radar_inputs(tmp_path)
    monkeypatch.setattr(r, "PROVIDERS_PATH", str(providers))
    monkeypatch.setattr(
        r,
        "_upstream_pr",
        lambda pr_number: (
            _merged_target_pr() | ({"merged_at": None} if not merged else {})
        ),
        raising=False,
    )
    monkeypatch.setattr(
        r.st,
        "load",
        lambda path: (_ for _ in ()).throw(AssertionError("state loaded")),
    )
    monkeypatch.setattr(
        r.st,
        "save",
        lambda path, data: (_ for _ in ()).throw(AssertionError("state saved")),
    )

    with pytest.raises((ValueError, RuntimeError)):
        r.run(retry_domain=domain, retry_pr=number)


def test_targeted_apply_failure_stays_retryable_and_creates_incident(
    monkeypatch, tmp_path
):
    state = _configure_targeted(monkeypatch, tmp_path, handled=False)
    incidents: list[tuple[str, str]] = []
    monkeypatch.setattr(
        r.opener,
        "open_reverse_pr",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("no apply outcome")),
    )
    monkeypatch.setattr(
        r.reverse_sync_notify,
        "upsert_issue",
        lambda repo, label, title, body: incidents.append((title, body)) or 1,
    )

    assert r.run(retry_domain="fastmcp_server", retry_pr="5782") == 1
    saved = json.loads(state.read_text())["fastmcp_server"]
    assert 5782 not in saved["handled_prs"]
    assert saved["pulls_cursor"] == "2026-08-19T12:00:00Z"
    assert incidents == [
        (
            "reverse-sync failed — fastmcp_server PR#5782",
            "reverse_sync_radar failed to open reverse PR for `fastmcp_server` "
            "upstream PR#5782:\n\n```\nno apply outcome\n```",
        )
    ]


def test_targeted_non_durable_opener_result_stays_retryable(monkeypatch, tmp_path):
    state = _configure_targeted(monkeypatch, tmp_path, handled=False)
    incidents: list[str] = []
    monkeypatch.setattr(
        r.opener,
        "open_reverse_pr",
        lambda **kwargs: {
            "skipped": False,
            "reason": None,
            "pr_url": None,
            "conflicts": False,
            "reused": False,
            "applied_paths": ["provider/api.py"],
            "conflicted_paths": [],
            "label_failures": [],
        },
    )
    monkeypatch.setattr(
        r.reverse_sync_notify,
        "upsert_issue",
        lambda repo, label, title, body: incidents.append(body) or 1,
    )

    assert r.run(retry_domain="fastmcp_server", retry_pr="5782") == 1
    assert 5782 not in json.loads(state.read_text())["fastmcp_server"]["handled_prs"]
    assert "non-durable" in incidents[0]


def test_targeted_label_failure_creates_incident_but_remains_handled(
    monkeypatch, tmp_path
):
    state = _configure_targeted(monkeypatch, tmp_path, handled=False)
    incidents: list[tuple[str, str]] = []
    monkeypatch.setattr(
        r.opener,
        "open_reverse_pr",
        lambda **kwargs: {
            "skipped": False,
            "reason": None,
            "pr_url": "https://github.com/trudenboy/ma-provider-mcp/pull/278",
            "conflicts": True,
            "reused": True,
            "applied_paths": ["tests/test_debug.py"],
            "conflicted_paths": [],
            "label_failures": [
                {"label": "needs-human", "diagnostic": "HTTP 422 missing label"}
            ],
        },
    )
    monkeypatch.setattr(
        r.reverse_sync_notify,
        "upsert_issue",
        lambda repo, label, title, body: incidents.append((title, body)) or 1,
    )

    assert r.run(retry_domain="fastmcp_server", retry_pr="5782") == 0
    saved = json.loads(state.read_text())["fastmcp_server"]
    assert saved["handled_prs"] == [5782]
    assert saved["pulls_cursor"] == "2026-08-19T12:00:00Z"
    assert incidents[0][0] == "reverse-sync labels failed — fastmcp_server PR#5782"
    assert "pull/278" in incidents[0][1]
    assert "needs-human" in incidents[0][1]
    assert "HTTP 422 missing label" in incidents[0][1]


def test_scheduled_run_keeps_cursor_semantics(monkeypatch, tmp_path):
    state = _configure_targeted(monkeypatch, tmp_path, handled=False)
    entry = json.loads(state.read_text())
    entry["fastmcp_server"]["pulls_cursor"] = "2026-07-01T00:00:00Z"
    state.write_text(json.dumps(entry))
    monkeypatch.setattr(r, "_upstream_default_branch", lambda: "dev")
    monkeypatch.setattr(r, "_anchor", lambda domain, branch: "new-anchor")
    monkeypatch.setattr(r, "_merged_prs", lambda branch, cursor: [_merged_target_pr()])
    monkeypatch.setattr(
        r.opener,
        "open_reverse_pr",
        lambda **kwargs: {
            "skipped": True,
            "reason": "already present",
            "pr_url": None,
            "conflicts": False,
            "reused": False,
            "applied_paths": [],
            "conflicted_paths": [],
            "label_failures": [],
        },
    )

    assert r.run() == 0
    saved = json.loads(state.read_text())["fastmcp_server"]
    assert saved["last_synced_sha"] == "new-anchor"
    assert saved["handled_prs"] == [5782]
    assert saved["pulls_cursor"] == "2026-08-01T00:00:00Z"
