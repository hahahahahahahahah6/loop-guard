"""Tests for loop_guard.cli hook flow (temp LOOP_GUARD_DIR, fake stdin)."""

import io
import json
import sys

import pytest

from loop_guard import cli


@pytest.fixture(autouse=True)
def temp_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOP_GUARD_DIR", str(tmp_path))
    monkeypatch.delenv("LOOP_GUARD_YOLO", raising=False)
    return tmp_path


class Args:
    def __init__(self, event="pre", session=None):
        self.event = event
        self.session = session


def run_hook(payload, event="pre", monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    else:
        sys.stdin = io.StringIO(json.dumps(payload))
    try:
        return cli.cmd_hook(Args(event=event))
    finally:
        if monkeypatch is None:
            sys.stdin = sys.__stdin__


def hook_payload(tool_name, tool_input, session_id="s1"):
    return {"session_id": session_id, "hook_event_name": "PreToolUse",
            "tool_name": tool_name, "tool_input": tool_input}


def test_event_from_hook_edit():
    ev = cli.event_from_hook(hook_payload("Edit", {"file_path": "a.py"}))
    assert ev == {"kind": "edit", "file": "a.py", "tool": "Edit"}


def test_event_from_hook_bash_test():
    ev = cli.event_from_hook(hook_payload("Bash", {"command": "pytest -q"}))
    assert ev["kind"] == "bash" and ev["is_test"] is True


def test_event_from_hook_bash_other():
    ev = cli.event_from_hook(hook_payload("Bash", {"command": "ls"}))
    assert ev["kind"] == "bash" and ev["is_test"] is False


def test_event_from_hook_empty():
    assert cli.event_from_hook({}) is None


def test_pre_allows_normal_use(monkeypatch):
    rc = run_hook(hook_payload("Edit", {"file_path": "a.py"}),
                  monkeypatch=monkeypatch)
    assert rc == 0


def test_pre_blocks_churn_loop(monkeypatch):
    rc = 0
    for _ in range(6):
        rc = run_hook(hook_payload("Edit", {"file_path": "a.py"}),
                      monkeypatch=monkeypatch)
        rc = run_hook(hook_payload("Bash", {"command": "pytest"}),
                      monkeypatch=monkeypatch)
    assert rc == 2  # BLOCK_EXIT


def test_stays_tripped_until_reset(monkeypatch):
    for _ in range(6):
        run_hook(hook_payload("Edit", {"file_path": "a.py"}),
                 monkeypatch=monkeypatch)
        run_hook(hook_payload("Bash", {"command": "pytest"}),
                 monkeypatch=monkeypatch)
    # Even an innocent call is now blocked until reset.
    rc = run_hook(hook_payload("Bash", {"command": "ls"}),
                  monkeypatch=monkeypatch)
    assert rc == 2
    assert cli.cmd_reset(Args(session="s1")) == 0
    rc = run_hook(hook_payload("Bash", {"command": "ls"}),
                  monkeypatch=monkeypatch)
    assert rc == 0


def test_yolo_bypass_is_audited(monkeypatch, tmp_path):
    monkeypatch.setenv("LOOP_GUARD_YOLO", "1")
    rc = run_hook(hook_payload("Edit", {"file_path": "a.py"}),
                  monkeypatch=monkeypatch)
    assert rc == 0
    from loop_guard import ledger
    kinds = [e["kind"] for e in ledger.read("s1")]
    assert "bypass" in kinds


def test_post_is_record_only(monkeypatch):
    rc = run_hook(hook_payload("Bash", {"command": "pytest"}), event="post",
                  monkeypatch=monkeypatch)
    assert rc == 0


def test_status_runs(monkeypatch, capsys):
    run_hook(hook_payload("Edit", {"file_path": "a.py"}),
             monkeypatch=monkeypatch)
    assert cli.cmd_status(Args(session="s1")) == 0
    out = capsys.readouterr().out
    assert "session: s1" in out and "breaker: ok" in out


def test_bad_stdin_json_does_not_crash(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("{not json"))
    assert cli.cmd_hook(Args(event="pre")) == 0
