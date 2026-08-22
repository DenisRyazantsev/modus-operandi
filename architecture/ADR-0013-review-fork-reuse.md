---
slug: review-fork-reuse
status: accepted
date: 2026-08-18
---

# ADR-0013: Reusing Review Fork Sessions, Strictly Our Log Format, Removing --reset, 4 fps Spinner

## Context

The review loop (ADR-0009) runs each failed check kind (`srp`, `bugs`, `review`, `comment`) in a **new** fork of the
warm planner session on every iteration, and the fork id is never recorded — so each iteration re-reads the scope and
code from scratch and the reviewer does not remember its previous findings. The user requires: the planner session is
forked **once per check kind**, and each kind **reuses** its fork session for the rest of the loop. At the same time
the user requires: the engine's progress lines are removed from the output and logging happens strictly in our format —
engine errors and diagnostics are not dropped but converted to our format; gate menus remain as UI, not logs. Also
required: removal of the `--reset` flag, used by neither the workflow nor the user, and a livelier spinner (4 fps
instead of 1 fps).

Verified facts: `opencode run --session <id>` continues a session without `--fork`, while `--fork` creates an
isolated fork; a nonexistent session id fails with "Session not found". cursor-agent has no fork primitive — a fork
call is a fresh chat whose id is not saved; it offers chat creation and `--resume <chatId>`. The live-output block is
redrawn on a fixed monitor tick, so the effective spinner cadence is limited by that tick as well as by the heartbeat.

## Decision

1. **Per-kind fork reuse.** Each check kind gets one fork of the warm planner session, created on its first use and
   reused on every subsequent iteration. The recorded id is kept in a separate record per kind, so parallel first
   writes cannot lose updates. If a recorded session is lost (continue fails with "Session not found"), the record is
   cleared and the fork is re-created; the parent warm session is never mutated. The CLI flag for this mode is
   `--review-fork <kind>`; prompts and snapshots do not change.
2. **Backend parity.** On the cursor backend the same reuse applies via its native mechanisms: a warm chat per kind is
   created once and resumed afterwards, and the parent's warm role chat is never resumed or mutated.
3. **Stable per-kind log streams.** Logs are stable per kind, which gives our live lines a per-kind label and lets
   token sums continue across iterations.
4. **Strict output format.** Engine progress lines (step-start markers and workflow/version/status/run-id headers) are
   removed from the output. Engine errors and diagnostics are shown in our format; gate menus and unknown lines are
   echoed unchanged (fail-open). The run id is still parsed so failure resumption keeps working. The same filtering
   applies whether or not a terminal is attached.
5. **Remove `--reset`.** The flag is removed from the CLI and from the documentation.
6. **4 fps spinner.** The live spinner runs at 4 fps with time-based frame selection, so frames advance by elapsed
   time without shifting the surrounding text; the monitor redraw cadence matches the new heartbeat.

## Alternatives

- **Re-forking every iteration (status quo)** — rejected: exactly the behavior to eliminate (token waste, context
  loss between iterations).
- **One shared session record with per-kind keys** — rejected: lost-update races from four parallel first writes
  without locking; a separate record per kind is simpler and race-free.
- **Per-invocation unique log names when reusing** — rejected: stable per-kind names give the kind label and
  continuing token sums.
- **Session export/recreation instead of continuing** — rejected: heavier and slower than natively continuing the
  existing session.
- **Removing only step-start lines, keeping the other headers** — rejected: the requirement is strictly our format.
- **A spinner library** — rejected earlier as an extra dependency (ADR-0011/0012); only its time-based frame
  principle is borrowed.
- **Keeping `--reset`** — rejected: used by neither the workflow nor the user.

## Consequences

- Positive: the scope is read by a per-kind session once per run; iterations no longer reopen context (token and time
  savings); the reviewer remembers its previous findings and can check their fix; cursor gets warm per-kind chats
  instead of a fresh chat per check; logs flow in one our-format stream; less code without `--reset`; the spinner is
  lively.
- Negative: a per-kind session's context grows with iterations (bounded by the maximum fix-iteration cap); a
  per-kind session remembers the old code state (mitigated by prompts that review the current state and the diff
  against the snapshot); a lost session is handled by the "Session not found" fallback, which re-forks; resuming a
  chat on cursor depends on the CLI retaining chat ids (the risk already accepted for warm role chats); the faster
  tick doubles the polling frequency of runtime state (negligible).
- Partially supersedes ADR-0009 (fork id not recorded) and ADR-0012 (spinner frame at most once per second);
  ADR-0008 historically describes `--reset`, whose removal is fixed here.

## Acceptance Criteria

- Each check kind gets one fork of the warm session, created once and reused across loop iterations; a lost session
  is detected and the fork is re-created, and the parent session is never mutated.
- Engine progress lines are removed from the output, while engine errors and diagnostics are shown in our format; gate
  menus and other engine output are still shown as before.
- The `--reset` flag no longer exists.
- The spinner runs at 4 fps, advances by elapsed time, and does not shift the surrounding text.
- On the cursor backend, each kind's chat is created once and resumed afterwards.
- Live output identifies the check kind, and token counts accumulate across iterations.
