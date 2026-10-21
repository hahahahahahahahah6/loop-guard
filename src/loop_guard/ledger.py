"""Append-only per-session event ledger (JSONL). Standard library only.

Each coding-agent session gets one ``<session_id>.jsonl`` file under the
loop-guard data directory. Events are small dicts like::

    {"t": 1730000000.0, "kind": "edit", "file": "src/app.py"}
    {"t": 1730000001.0, "kind": "bash", "command": "pytest -q", "is_test": true}

A companion ``<session_id>.state.json`` holds breaker state
(``breaker_tripped``, audit trail of resets/bypasses).
"""

import json
import os
import re
import time

_SESSION_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def data_dir():
    """Return the loop-guard data directory, creating it if needed."""
    d = os.environ.get("LOOP_GUARD_DIR") or os.path.join(
        os.path.expanduser("~"), ".config", "loop-guard"
    )
    os.makedirs(d, exist_ok=True)
    return d


def safe_session(session_id):
    """Sanitize a session id so it is safe as a file name."""
    sid = str(session_id or "default")
    sid = _SESSION_RE.sub("-", sid).strip("-. ") or "default"
    return sid[:128]


def ledger_path(session_id):
    return os.path.join(data_dir(), safe_session(session_id) + ".jsonl")


def state_path(session_id):
    return os.path.join(data_dir(), safe_session(session_id) + ".state.json")


def append(session_id, event):
    """Append one event dict to the session ledger. Never raises."""
    try:
        event = dict(event)
        event.setdefault("t", time.time())
        with open(ledger_path(session_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read(session_id, limit=None):
    """Read session events, skipping corrupt lines. Never raises."""
    events = []
    try:
        with open(ledger_path(session_id), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    events.append(obj)
    except OSError:
        pass
    if limit is not None:
        events = events[-limit:]
    return events


def load_state(session_id):
    """Load breaker state dict. Returns {} when absent or corrupt."""
    try:
        with open(state_path(session_id), encoding="utf-8") as f:
            obj = json.load(f)
            return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(session_id, state):
    """Persist breaker state dict. Never raises."""
    try:
        with open(state_path(session_id), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def clear(session_id):
    """Remove ledger and state for a session. Never raises."""
    try:
        paths = (ledger_path(session_id), state_path(session_id))
    except OSError:
        return
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass
