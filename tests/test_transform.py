import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _transform as t  # noqa: E402

DOMAIN = "yandex_music"
PP = "provider/"


def test_forward_path_source():
    assert t.forward_path("provider/manifest.json", DOMAIN, PP) == (
        "music_assistant/providers/yandex_music/manifest.json"
    )


def test_forward_path_tests():
    assert t.forward_path("tests/test_api.py", DOMAIN, PP) == (
        "tests/providers/yandex_music/test_api.py"
    )


def test_reverse_path_source():
    assert (
        t.reverse_path("music_assistant/providers/yandex_music/api.py", DOMAIN, PP)
        == "provider/api.py"
    )


def test_reverse_path_tests():
    assert (
        t.reverse_path("tests/providers/yandex_music/test_api.py", DOMAIN, PP)
        == "tests/test_api.py"
    )


def test_reverse_path_outside_returns_none():
    assert t.reverse_path("music_assistant/server.py", DOMAIN, PP) is None
    assert t.reverse_path("music_assistant/providers/other/api.py", DOMAIN, PP) is None


def test_test_import_roundtrip():
    src = (
        "from provider.api import Client\n"
        "from provider import Provider\n"
        'm = mock.patch("provider.api.Client")\n'
    )
    fwd = t.forward_content("tests/test_api.py", src, DOMAIN)
    assert "music_assistant.providers.yandex_music" in fwd
    assert (
        t.reverse_content("tests/providers/yandex_music/test_api.py", fwd, DOMAIN)
        == src
    )


def test_source_content_unchanged():
    # Provider source uses relative imports; content must not be rewritten.
    src = "from .api import Client\nVALUE = 1\n"
    assert t.forward_content("provider/__init__.py", src, DOMAIN) == src
    assert (
        t.reverse_content(
            "music_assistant/providers/yandex_music/__init__.py", src, DOMAIN
        )
        == src
    )


def test_reverse_diff_rewrites_headers_and_test_content():
    patch = (
        "diff --git a/music_assistant/providers/yandex_music/api.py "
        "b/music_assistant/providers/yandex_music/api.py\n"
        "--- a/music_assistant/providers/yandex_music/api.py\n"
        "+++ b/music_assistant/providers/yandex_music/api.py\n"
        "@@ -1,1 +1,2 @@\n"
        " from .base import X\n"
        "+Y = 2\n"
        "diff --git a/tests/providers/yandex_music/test_api.py "
        "b/tests/providers/yandex_music/test_api.py\n"
        "--- a/tests/providers/yandex_music/test_api.py\n"
        "+++ b/tests/providers/yandex_music/test_api.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-from music_assistant.providers.yandex_music.api import C\n"
        "+from music_assistant.providers.yandex_music.api import C2\n"
    )
    out = t.reverse_diff(patch, DOMAIN, PP)
    assert "a/provider/api.py" in out
    assert "b/tests/test_api.py" in out
    assert "music_assistant/providers/yandex_music" not in out
    # Source hunk content (relative import) preserved:
    assert " from .base import X" in out
    # Test hunk content rewritten on +/- lines:
    assert "-from provider.api import C\n" in out
    assert "+from provider.api import C2\n" in out


def test_reverse_diff_drops_foreign_files():
    patch = (
        "diff --git a/music_assistant/server.py b/music_assistant/server.py\n"
        "--- a/music_assistant/server.py\n"
        "+++ b/music_assistant/server.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-x\n"
        "+y\n"
    )
    assert t.reverse_diff(patch, DOMAIN, PP).strip() == ""
