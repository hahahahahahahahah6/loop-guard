"""Loop detection. Pure functions: events in, findings out.

Three signals:

* ``churn_loop`` (block) - the same file is edited over and over again while
  tests keep being run: the classic "edit -> test -> fail -> edit" death
  spiral. Real case: a user watched an agent burn 53% -> 14% of a 5-hour
  quota in 7 minutes stuck in exactly this loop.
* ``test_loop`` (block) - the same test command is re-run again and again
  with no intervening source change.
* ``burn`` (warn) - the session is very large (many tool calls). Advisory
  only: big sessions can be legitimate.
"""

TEST_RUNNERS = (
    "pytest",
    "py.test",
    "npm test",
    "yarn test",
    "pnpm test",
    "bun test",
    "go test",
    "cargo test",
    "jest",
    "vitest",
    "mocha",
    "rspec",
    "phpunit",
    "deno test",
)

DEFAULTS = {
    "max_file_edits": 6,   # edits of one file before churn_loop trips
    "max_test_runs": 6,     # identical test commands before test_loop trips
    "max_tool_calls": 200,  # tool calls before burn warns
}


def is_test_command(command):
    """Heuristic: does this shell command look like a test run?"""
    if not command:
        return False
    cmd = str(command).strip()
    return any(cmd == r or cmd.startswith(r + " ") for r in TEST_RUNNERS)


def normalize_command(command):
    """Collapse whitespace so trivially different invocations compare equal."""
    return " ".join(str(command or "").split())


def detect(events, thresholds=None):
    """Return a list of findings for the given ledger events.

    Each finding is a dict with ``signal``, ``severity`` ("block" or "warn"),
    ``summary`` and ``questions`` (3 questions for the human).
    """
    th = dict(DEFAULTS)
    if thresholds:
        th.update(thresholds)
    findings = []

    edits = {}        # file -> [event, ...]
    test_runs = {}    # normalized command -> count
    tool_calls = 0
    saw_test_after_first_edit = set()

    for ev in events:
        kind = ev.get("kind")
        if kind == "edit":
            tool_calls += 1
            f = ev.get("file") or ""
            edits.setdefault(f, []).append(ev)
        elif kind == "bash":
            tool_calls += 1
            cmd = normalize_command(ev.get("command"))
            if is_test_command(cmd):
                test_runs[cmd] = test_runs.get(cmd, 0) + 1
                for f in edits:
                    saw_test_after_first_edit.add(f)
        elif kind:
            tool_calls += 1

    for f, evs in edits.items():
        if len(evs) >= th["max_file_edits"] and f in saw_test_after_first_edit:
            findings.append({
                "signal": "churn_loop",
                "severity": "block",
                "summary": (
                    "File edited %d times with test runs in between and no "
                    "progress: %s" % (len(evs), f or "(unknown file)")
                ),
                "detail": {"file": f, "edits": len(evs)},
                "questions": [
                    "What is the actual root cause here - the code, the test, or the spec?",
                    "What is the smallest change that would prove real progress?",
                    "Should a human take over this file now instead of another loop?",
                ],
            })

    for cmd, count in test_runs.items():
        if count >= th["max_test_runs"]:
            findings.append({
                "signal": "test_loop",
                "severity": "block",
                "summary": (
                    "Same test command run %d times: %s" % (count, cmd)
                ),
                "detail": {"command": cmd, "runs": count},
                "questions": [
                    "What did the last 3 runs change, if anything?",
                    "Is the failure in the test or in the code under test?",
                    "What would you try if you only had one run left?",
                ],
            })

    if tool_calls >= th["max_tool_calls"]:
        findings.append({
            "signal": "burn",
            "severity": "warn",
            "summary": (
                "Session has %d tool calls and is still going; large sessions "
                "burn quota fast when unattended." % tool_calls
            ),
            "detail": {"tool_calls": tool_calls},
            "questions": [
                "Is someone still watching this session?",
                "What is the single most valuable remaining step?",
                "At what point should this session be wrapped up?",
            ],
        })

    return findings


def format_finding(finding):
    """Render a finding as the block message shown to the agent."""
    lines = [
        "loop-guard: CIRCUIT BREAKER TRIPPED (%s)" % finding["signal"],
        "",
        finding["summary"],
        "",
        "Do not continue the loop. Summarize where you are stuck and answer:",
    ]
    for i, q in enumerate(finding.get("questions", []), 1):
        lines.append("  %d. %s" % (i, q))
    lines += [
        "",
        "To resume after a human has reviewed, run: loop-guard reset",
        "Emergency bypass (audited): LOOP_GUARD_YOLO=1",
    ]
    return "\n".join(lines)
