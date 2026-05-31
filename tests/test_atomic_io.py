import json

from atomic_io import atomic_open, atomic_write_text


def test_atomic_write_text_creates_file(tmp_path):
    target = tmp_path / "sub" / "out.txt"
    atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"


def test_atomic_open_replaces_existing(tmp_path):
    target = tmp_path / "out.json"
    target.write_text('{"old": true}', encoding="utf-8")

    with atomic_open(target, "w", encoding="utf-8") as handle:
        json.dump({"new": True}, handle)

    assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}


def test_atomic_open_keeps_original_on_failure(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("original", encoding="utf-8")

    class Boom(RuntimeError):
        pass

    try:
        with atomic_open(target, "w", encoding="utf-8") as handle:
            handle.write("partial")
            raise Boom()
    except Boom:
        pass

    assert target.read_text(encoding="utf-8") == "original"
    leftover = [p.name for p in tmp_path.iterdir() if p.name != "out.txt"]
    assert leftover == [], f"tmp file not cleaned up: {leftover}"


def test_atomic_open_rejects_read_mode(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        with atomic_open(tmp_path / "x.txt", "r"):
            pass
