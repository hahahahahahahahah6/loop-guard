# loop-guard

Circuit breaker for runaway loops in coding-agent sessions. Standard library only, no dependencies.

Coding agents fail in loops, not in single mistakes. Real cases:

- An agent stuck in **edit → test → fail → edit** burned 53% → 14% of a 5-hour quota in 7 minutes.
- An unattended agent's "infinite monitor loop" ran up **$900 in extra usage** while its owner was at dinner.
- An agent "testing" a paid API fired 16 requests and triggered a **$10 auto-recharge** — with zero approval.

`loop-guard` watches a session through Claude Code hooks, detects the loop patterns, and trips a breaker: the agent is stopped and forced to output a stuck-summary plus three questions for the human, instead of burning more tokens.

## How it works

Two hooks, one append-only ledger (`~/.config/loop-guard/<session>.jsonl`):

| Hook | What it does |
|---|---|
| `PreToolUse` | Records the tool call, runs detection. Exit `2` blocks the call when a loop is found. |
| `PostToolUse` | Record-only (reserved for result-aware signals). |

Three signals:

- **`churn_loop`** (block) — the same file edited N times with test runs in between and no progress. Default N=6.
- **`test_loop`** (block) — the same test command re-run N times. Default N=6.
- **`burn`** (warn) — the session passed N tool calls and is still going. Default N=200. Advisory only.

Once tripped, the breaker **stays tripped** until a human runs `loop-guard reset` (the reset is written to the ledger, so the bypass trail survives). Emergency bypass: `LOOP_GUARD_YOLO=1` — also audited in the ledger.

## Install

```bash
pip install loop-guard
```

## Hook setup (Claude Code)

Add to your Claude Code settings (see `snippets/hooks.json`):

```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Edit|Write|Bash",
       "hooks": [{"type": "command", "command": "loop-guard hook --event pre"}]}
    ],
    "PostToolUse": [
      {"matcher": "Bash",
       "hooks": [{"type": "command", "command": "loop-guard hook --event post"}]}
    ]
  }
}
```

## CLI

```bash
loop-guard status [--session ID]   # session summary + current findings
loop-guard reset [--session ID]    # clear the breaker (audited)
```

## Configuration

`~/.config/loop-guard/config.json` (or environment overrides):

```json
{"max_file_edits": 6, "max_test_runs": 6, "max_tool_calls": 200}
```

Environment: `LOOP_GUARD_DIR`, `LOOP_GUARD_MAX_FILE_EDITS`, `LOOP_GUARD_MAX_TEST_RUNS`, `LOOP_GUARD_MAX_TOOL_CALLS`, `LOOP_GUARD_YOLO=1`.

## Design notes

- **Fail-open.** Detection failures never block the agent; only a confidently detected loop trips the breaker.
- **No network.** Everything is local. The ledger is plain JSONL you can read.
- **Audited escape hatches.** Both `reset` and `YOLO=1` leave a record — a breaker you can silently bypass is not a breaker.
- **Thresholds, not magic.** Repetition counting is a heuristic. Tune the numbers to your workflow; the summary always shows the evidence.

## License

MIT
