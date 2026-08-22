---
slug: gate-log-suspension
status: accepted
date: 2026-08-14
---

# ADR-0002: Suspending run-pipeline.py Log Output While Waiting for Interactive Input at a Human Gate

## Context

`run-pipeline.py` runs the engine's workflow command with captured stdout and in parallel spins a live monitor that
periodically prints completed steps (from `state.json`) and events from agent logs to stdout. When the specification
reaches a human gate (`adr-gate`, `adr-feedback-gate`, `adr-approval-gate`), the engine draws an interactive
selection menu and blocks in `input()` until the user answers. Meanwhile, the monitor thread keeps printing, and log
lines land right on top of the menu window, breaking its rendering.

Separately: the agent log tailer currently prints not only meaningful events but also marker lines
`step-start` / `step-finish` (and `text` with an empty payload) — they carry no information and only add noise to the
output. Only pipeline failure causes and work progression are needed from the logs, not everything.

Verified facts about `specify-cli` v0.16.x:

- The gate menu is drawn via `print()`: the first line of the window starts with the characters `┌─ Gate`.
- `input()` flushes stdout before reading, so the whole menu window arrives in the wrapper's pipe as a single packet
  at the moment the gate opens; after that the pipe is silent until the user answers. On invalid input the engine
  prints "Invalid choice. …" and waits for input again — the gate stays open.
- While the gate waits for input, `state.json` contains the `current_step_id` of that gate step (including in loop
  iterations — suffixed ids like `adr-loop:adr-gate:1`); when the user answers, the engine moves to the next step and
  the id changes. On reject/abort the run terminates, and the id may remain at the gate.
- The interactive menu appears only if stdin is a TTY; with `human_gates: false` (auto-approve via
  `verdict_input`) and with non-TTY stdin (gate pause), the menu is not drawn at all.
- An early implementation captured the gate step id on a periodic monitor tick; a bug review found this races with a
  fast user response — the tick can observe the id of the next step and keep suppression active through a whole
  subsequent step. The id is therefore captured synchronously at the moment the menu opens.

## Decision

Add to `run-pipeline.py` suppression of its own log output while a gate menu is open on screen:

1. **Gate opening.** The wrapper's main stdout-reading loop detects the menu opener line (after stripping, it starts
   with `┌─ Gate`). On match, a shared thread-safe "gate open" flag is set, and the gate step id is captured
   synchronously at that moment (from `state.json`), so the id always belongs to the gate step itself.
2. **While the gate is open.** The live monitor keeps polling `state.json` and reading logs, but does not print:
   completed step events and agent log lines are accumulated in a buffer. The wrapper's echo of the engine's own
   lines (the menu, "Invalid choice…") is unchanged — that is the normal timestamped echo.
3. **Gate closing.** The flag is cleared when the monitor sees that `current_step_id` differs from the id captured
   at gate-open time (the gate step finished, the engine moved on), or when the wrapper finishes (EOF/stop —
   covers abort/reject, where `current_step_id` may stay at the gate). When the flag is cleared, the buffer is
   flushed to screen and normal live printing resumes.
4. **Repeated gates.** Detection re-arms on every menu window: after one gate closes, the flag is raised again when
   the next one is drawn, including repeated loop rounds.
5. **Log event filtering.** The agent log tailer prints only events with useful content: `text` parts with
   non-empty text (agent work progression). Marker lines `step-start` / `step-finish` and `text` with an empty
   payload are not printed at all. Pipeline failure causes remain visible as before — via the failed step result
   (stdout/stderr with the `[err]` prefix) and the final status block.

## Alternatives

* **Detect gate waiting only via `state.json` plus parsing the YAML workflow** (find all `type: gate` steps,
  including suffixed ids in loops, and compare against `current_step_id`). Rejected: tied to the engine's internal
  id grammar (`parent:child:N`) and to the semantics of `current_step_id`, requires resolving the installed
  workflow, and is noticeably more code; meanwhile "menu on screen" is directly observed only via stdout, not state.
* **Suppress on a stdout silence timeout** (no lines for N seconds → assume waiting for input). Rejected: agent
  steps take minutes and are also silent on stdout — precisely when live logs are most valuable; false positives
  are unavoidable.
* **Print monitor events to stderr while the gate is open.** Rejected: stderr and stdout render into the same
  terminal, the menu would still be flooded with lines.
* **Run the engine under a pseudo-terminal (pty).** Rejected: full screen control, but that means rewriting the
  wrapper — input forwarding, echo, timestamps of interactive output; complexity is disproportionate to the task.
* **Do not buffer; discard events during the wait.** Rejected: losing information contradicts the wrapper's purpose
  (log tail and transparency); the buffer is small and bounded by human wait time.

## Consequences

* Positive: the gate menu window stays intact while the user chooses; events arriving during the wait are not lost —
  they are printed right after the choice (or when the wrapper finishes), and live output continues as before.
* Positive: the change is local and does not affect behavior when no gate is open, including `human_gates: false`
  and non-TTY runs (no menu — no suppression).
* Positive: works for all workflow gates (including repeated rounds) without depending on menu item or prompt text.
* Negative: open detection is tied to the engine's current menu format (the `┌─ Gate` marker); if the menu format
  changes in future versions, logs will again be printed over the menu (silent degradation to current behavior).
* Negative: false positive — if some step's output contains a line starting with `┌─ Gate`, live printing will be
  suppressed until that step completes (self-healing: `current_step_id` changes, the buffer flushes).
* Negative: while waiting at a gate, log lines are delayed until the answer — the price for not flooding the menu;
  the buffer volume is bounded by human wait time, and the lines are small.

## Acceptance Criteria

* While the engine waits for interactive input at a gate (the "┌─ Gate" window on screen), the wrapper prints
  neither completed step lines nor agent log lines; the timestamped echo of the menu lines themselves is preserved.
* Events accumulated during the wait are printed after the gate closes (before or at the first post-choice output),
  and when the wrapper terminates with the gate open — on the final flush: nothing is lost.
* A repeated gate in the same run again suspends printing (detection re-arms on every menu window).
* Without an open gate behavior is unchanged: steps and logs are printed on the usual interval; runs with
  `human_gates: false` and non-TTY runs (gate pause) do not suppress output.
* From agent logs, only `text` events with non-empty content are printed; marker lines `step-start` / `step-finish`
  and `text` with an empty payload are not output. The failed step output (stderr with the `[err]` prefix) and the
  final status block are printed as before.
