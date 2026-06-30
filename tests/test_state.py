import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reverse_sync_state as st  # noqa: E402


def test_load_missing_returns_empty(tmp_path):
    assert st.load(tmp_path / "nope.json") == {}


def test_entry_creates_default():
    data = {}
    e = st.entry(data, "yandex_music")
    assert e == {
        "last_synced_sha": None,
        "handled_prs": [],
        "pulls_cursor": None,
        "digest_issue": None,
    }
    assert data["yandex_music"] is e  # stored back


def test_mark_and_is_handled():
    data = {}
    assert st.is_handled(data, "d", 4313) is False
    st.mark_handled(data, "d", 4313)
    assert st.is_handled(data, "d", 4313) is True
    st.mark_handled(data, "d", 4313)  # idempotent
    assert st.entry(data, "d")["handled_prs"] == [4313]


def test_save_roundtrip(tmp_path):
    data = {"d": st.DEFAULT_ENTRY | {"handled_prs": [1, 2]}}
    p = tmp_path / "s.json"
    st.save(p, data)
    text = p.read_text()
    assert text.endswith("\n")
    assert json.loads(text)["d"]["handled_prs"] == [1, 2]
