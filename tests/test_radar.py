import sys
from pathlib import Path

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
