from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "replicator" / "ui" / "app.py"


def test_app_renders_without_exception():
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    assert len(at.tabs) == 9
    labels = [t.label for t in at.tabs]
    assert {"Supervisor", "Golden set", "Review queue"} <= set(labels)


def test_empty_knowledge_base_renders(tmp_path, monkeypatch):
    import replicator.config as config
    monkeypatch.setattr(config, "KB_DIR", tmp_path)
    at = AppTest.from_file(str(APP), default_timeout=90).run()
    assert not at.exception
    blob = " ".join(getattr(e, "value", "") for e in list(at.error) + list(at.exception))
    assert "Traceback" not in blob
    labels = [b.label for b in at.button]
    assert "Add to library" in labels
    assert "Run thorough extraction" in labels
    assert "Extract spec" not in labels
    assert "Run" in labels
    by_label = {b.label: b for b in at.button}
    assert by_label["Add to library"].disabled
    assert by_label["Run thorough extraction"].disabled
    assert by_label["Run"].disabled
