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
