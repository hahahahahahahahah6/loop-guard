"""Tests for loop_guard.ledger (uses a temp LOOP_GUARD_DIR)."""

import json
import os

import pytest

from loop_guard import ledger


@pytest.fixture(autouse=True)
def temp_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOP_GUARD_DIR", str(tmp_path))
    return tmp_path


def test_append_and_read_roundtrip():
    ledger.append("s1", {"kind": "edit", "file": "a.py"})
    ledger.append("s1", {"kind": "bash", "command": "pytest"})
    events = ledger.read("s1")
    assert len(events) == 2
    assert events[0]["file"] == "a.py"
    assert "t" in events[0]


def test_sessions_isolated():
    ledger.append("s1", {"kind": "edit", "file": "a.py"})
    assert ledger.read("s2") == []


def test_corrupt_lines_skipped():
    path = ledger.ledger_path("s1")
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"kind": "edit"}\n')
        f.write("not json at all\n")
        f.write('{"kind": "bash"}\n')
    events = ledger.read("s1")
    assert len(events) == 2


def test_missing_session_reads_empty():
    assert ledger.read("nope") == []


def test_state_roundtrip():
    assert ledger.load_state("s1") == {}
    ledger.save_state("s1", {"breaker_tripped": True})
    assert ledger.load_state("s1") == {"breaker_tripped": True}


def test_clear_removes_files(tmp_path):
    ledger.append("s1", {"kind": "edit"})
    ledger.save_state("s1", {"x": 1})
    ledger.clear("s1")
    assert list(tmp_path.iterdir()) == []


def test_session_id_sanitized():
    assert ledger.safe_session("../../etc/passwd") == "etc-passwd"
    assert ledger.safe_session("") == "default"
    assert ledger.safe_session(None) == "default"


def test_never_raises_on_unwritable_dir(monkeypatch):
    monkeypatch.setenv("LOOP_GUARD_DIR", "/proc/definitely-not-here-xyz")
    ledger.append("s1", {"kind": "edit"})  # must not raise
    assert ledger.read("s1") == []
    assert ledger.load_state("s1") == {}
    ledger.save_state("s1", {"x": 1})  # must not raise
    ledger.clear("s1")  # must not raise
