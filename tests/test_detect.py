"""Tests for loop_guard.detect (pure functions, no I/O)."""

from loop_guard import detect


def ev(kind, **kw):
    e = {"t": 1.0, "kind": kind}
    e.update(kw)
    return e


def test_churn_loop_trips():
    events = []
    for _ in range(6):
        events.append(ev("edit", file="src/app.py"))
        events.append(ev("bash", command="pytest -q", is_test=True))
    findings = detect.detect(events)
    signals = [f["signal"] for f in findings]
    assert "churn_loop" in signals
    f = next(x for x in findings if x["signal"] == "churn_loop")
    assert f["severity"] == "block"
    assert len(f["questions"]) == 3
    assert "src/app.py" in f["summary"]


def test_healthy_tdd_does_not_trip():
    # 3 edits + 3 test runs: normal TDD, below thresholds.
    events = []
    for _ in range(3):
        events.append(ev("edit", file="src/app.py"))
        events.append(ev("bash", command="pytest -q", is_test=True))
    findings = detect.detect(events)
    assert [f for f in findings if f["severity"] == "block"] == []


def test_edits_without_tests_do_not_trip_churn():
    # Many edits but no test runs: not the edit->test death spiral.
    events = [ev("edit", file="src/app.py") for _ in range(10)]
    findings = detect.detect(events)
    assert "churn_loop" not in [f["signal"] for f in findings]


def test_test_loop_trips():
    events = [ev("bash", command="npm test", is_test=True) for _ in range(6)]
    findings = detect.detect(events)
    f = next(x for x in findings if x["signal"] == "test_loop")
    assert f["severity"] == "block"
    assert "npm test" in f["summary"]


def test_test_command_whitespace_normalized():
    events = [ev("bash", command="pytest   -q", is_test=True) for _ in range(6)]
    findings = detect.detect(events)
    assert "test_loop" in [f["signal"] for f in findings]


def test_burn_warns_but_does_not_block():
    events = [ev("bash", command="ls", is_test=False) for _ in range(200)]
    findings = detect.detect(events)
    f = next(x for x in findings if x["signal"] == "burn")
    assert f["severity"] == "warn"


def test_empty_session_clean():
    assert detect.detect([]) == []


def test_thresholds_configurable():
    events = [ev("edit", file="a.py") for _ in range(3)]
    events += [ev("bash", command="pytest", is_test=True)]
    findings = detect.detect(events, {"max_file_edits": 3})
    assert "churn_loop" in [f["signal"] for f in findings]


def test_is_test_command():
    assert detect.is_test_command("pytest -q")
    assert detect.is_test_command("npm test")
    assert detect.is_test_command("go test ./...")
    assert not detect.is_test_command("ls -la")
    assert not detect.is_test_command("pytest-cov")  # prefix, not the runner
    assert not detect.is_test_command("")


def test_format_finding_has_questions():
    f = {"signal": "churn_loop", "summary": "x",
         "questions": ["a?", "b?", "c?"]}
    out = detect.format_finding(f)
    assert "CIRCUIT BREAKER TRIPPED" in out
    assert "loop-guard reset" in out
    assert "1. a?" in out
