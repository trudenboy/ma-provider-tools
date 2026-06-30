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
