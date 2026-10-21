"""Command-line interface.

Subcommands:

* ``loop-guard hook --event pre``   - Claude Code PreToolUse hook entry.
  Reads the hook JSON from stdin, records the event, runs detection.
  Exit 0 = allow, exit 2 = block (Claude Code convention).
* ``loop-guard hook --event post``  - Claude Code PostToolUse hook entry.
  Record-only, always exits 0.
* ``loop-guard status [--session ID]`` - print the current session summary.
* ``loop-guard reset [--session ID]``  - clear breaker state (audited).

Environment:

* ``LOOP_GUARD_YOLO=1`` - emergency bypass. The bypass itself is written to
  the ledger as an audit event, so "who skipped the breaker" is on record.
* ``LOOP_GUARD_DIR`` - data directory (default ~/.config/loop-guard).
* ``LOOP_GUARD_MAX_FILE_EDITS`` / ``LOOP_GUARD_MAX_TEST_RUNS`` /
  ``LOOP_GUARD_MAX_TOOL_CALLS`` - threshold overrides.
"""

import argparse
import json
import os
import sys
import time

from . import __version__, detect, ledger

BLOCK_EXIT = 2


def load_config():
    """Config file values, overridden by environment variables."""
    cfg = {}
    path = os.path.join(ledger.data_dir(), "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
            if isinstance(obj, dict):
                cfg.update(obj)
    except (OSError, ValueError):
        pass
    thresholds = dict(detect.DEFAULTS)
    for key, env in (("max_file_edits", "LOOP_GUARD_MAX_FILE_EDITS"),
                     ("max_test_runs", "LOOP_GUARD_MAX_TEST_RUNS"),
                     ("max_tool_calls", "LOOP_GUARD_MAX_TOOL_CALLS")):
        if key in cfg:
            thresholds[key] = cfg[key]
        if env in os.environ:
            try:
                thresholds[key] = int(os.environ[env])
            except ValueError:
                pass
    return thresholds


def read_stdin_json():
    try:
        raw = sys.stdin.read()
        obj = json.loads(raw) if raw.strip() else {}
        return obj if isinstance(obj, dict) else {}
    except ValueError:
        return {}


def event_from_hook(payload):
    """Translate a Claude Code hook payload into a ledger event (or None)."""
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    if tool in ("Edit", "Write"):
        path = tool_input.get("file_path")
        if path:
            return {"kind": "edit", "file": str(path), "tool": tool}
    elif tool == "Bash":
        cmd = tool_input.get("command")
        if cmd:
            return {"kind": "bash",
                    "command": detect.normalize_command(cmd),
                    "is_test": detect.is_test_command(cmd)}
    elif tool:
        return {"kind": "other", "tool": str(tool)}
    return None


def cmd_hook(args):
    payload = read_stdin_json()
    session_id = payload.get("session_id") or "default"
    yolo = os.environ.get("LOOP_GUARD_YOLO") == "1"

    if yolo:
        ledger.append(session_id, {"kind": "bypass",
                                   "note": "LOOP_GUARD_YOLO=1"})
        return 0

    state = ledger.load_state(session_id)
    if state.get("breaker_tripped") and args.event == "pre":
        # Stay tripped until a human resets; keep showing the summary.
        finding = state.get("finding") or {}
        sys.stderr.write(detect.format_finding(finding) + "\n")
        return BLOCK_EXIT

    if args.event == "pre":
        ev = event_from_hook(payload)
        if ev:
            ledger.append(session_id, ev)
        findings = detect.detect(ledger.read(session_id), load_config())
        blocks = [f for f in findings if f["severity"] == "block"]
        warns = [f for f in findings if f["severity"] == "warn"]
        for w in warns:
            sys.stderr.write("loop-guard warning: %s\n" % w["summary"])
        if blocks:
            finding = blocks[0]
            ledger.save_state(session_id, {
                "breaker_tripped": True,
                "tripped_at": time.time(),
                "finding": finding,
            })
            sys.stderr.write(detect.format_finding(finding) + "\n")
            return BLOCK_EXIT
    return 0


def cmd_status(args):
    session_id = args.session or "default"
    events = ledger.read(session_id)
    state = ledger.load_state(session_id)
    edits = sum(1 for e in events if e.get("kind") == "edit")
    bashes = sum(1 for e in events if e.get("kind") == "bash")
    tests = sum(1 for e in events if e.get("is_test"))
    print("session: %s" % ledger.safe_session(session_id))
    print("events: %d (edits: %d, bash: %d, test runs: %d)"
          % (len(events), edits, bashes, tests))
    print("breaker: %s" % ("TRIPPED" if state.get("breaker_tripped")
                           else "ok"))
    findings = detect.detect(events, load_config())
    for f in findings:
        print("[%s] %s: %s" % (f["severity"], f["signal"], f["summary"]))
    return 0


def cmd_reset(args):
    session_id = args.session or "default"
    # Audit the reset before clearing, so the bypass trail survives.
    ledger.append(session_id, {"kind": "reset",
                               "note": "breaker state cleared by human"})
    ledger.clear(session_id)
    print("loop-guard: breaker reset for session %s"
          % ledger.safe_session(session_id))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="loop-guard",
        description="Circuit breaker for runaway loops in coding-agent sessions.")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("hook", help="Claude Code hook entry point")
    h.add_argument("--event", choices=("pre", "post"), required=True)
    h.set_defaults(func=cmd_hook)

    s = sub.add_parser("status", help="Show session summary")
    s.add_argument("--session", default=None)
    s.set_defaults(func=cmd_status)

    r = sub.add_parser("reset", help="Clear breaker state (audited)")
    r.add_argument("--session", default=None)
    r.set_defaults(func=cmd_reset)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
