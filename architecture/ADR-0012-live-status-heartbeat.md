---
slug: live-status-heartbeat
status: accepted
date: 2026-08-18
---

# ADR-0012: Live Process Status: Heartbeat Line Every Second and Motivation Questions in Feedback

## Context

After step-completed markers and during long agent steps, the wrapper prints nothing — an outside
observer perceives the process as hung. Causes (by code, ADR-0011): a live line appears only after the
first step-finish event of a role, updates only on step-finish events, and is cleared at a step
boundary; while a gate menu is open, the live block is hidden and everything is buffered; on non-TTY,
one line is printed per step-finish event.

On the cursor backend there is no line at all: the current cursor agent does not emit token-carrying
step-finish events — tokens arrive in the usage objects of result events (read only by the run
statistics collector), and the CLI does not return cost.

Agreed with the user in three motivation rounds (study.md rev. 3, proposal.md): the line is needed for
**all** steps and always; the animation is a spinner next to the running step's name that does **not
shift** the text; the heartbeat must not be written to the log; during an open gate menu the heartbeat
is not shown; cursor behavior must become the same as opencode (tokens visible); only **numbered**
questions from the document where the LLM writes them are copied into feedback.md; no list → empty
file; the interval is a fixed constant (no key in config); the line signature without a role is
`[harness]`.

## Decision

1. **An always-visible line with a spinner (TTY).** While the current step has no agent event yet, the
   live block shows a synthesized harness line `[hh:mm:ss] [harness] <spin> [<step> N/M]` — without a
   tokens section. The step's first agent event of any type creates the process line `[<role>]` (or
   `[<role>#<fork>]` with parallel review forks — one line per fork) and replaces the harness line. The
   spinner is a single-column frame (width exactly one column, e.g. Braille or ASCII frames — the
   implementation's choice) placed between the role signature and the step part; the frame advances at
   most once per second, and the block is redrawn on every monitor tick (0.5 s), so the line "breathes"
   even between model turns. The tokens section (`cache · reasoning · input · output · price`) shows
   only for processes with cumulative sums; `price` only when the backend returns cost (opencode;
   cursor — without price). At a step boundary the harness line and process lines are pinned into
   history and the step marker is printed as now; on the next tick the new step's line is drawn (a
   window without a line ≤ 0.5 s). Gates are unchanged: while the menu is open the block is hidden and
   output is buffered (the ADR-0011 policy).

2. **Non-TTY.** No ANSI block is drawn. On a step change, one ordinary line
   `[hh:mm:ss] [harness] [<step> N/M]` is printed once at step start, if the step has no agent line yet.
   Event lines remain: opencode — on step-finish, cursor — on an event with usage (≤ one line per agent
   turn). No heartbeat lines are written to the log.

3. **Cursor tokens (parity with opencode).** The live lines accumulate usage from cursor events in the
   same shapes the run statistics collector already parses, extended: a result event with a top-level
   usage object (input/output/reasoning tokens, cache as read/write or equivalent snake_case and
   camelCase forms), or the event's own top-level token fields, with a fallback for old cursor versions
   to step-finish events with tokens and cost, like opencode. A process is considered active from its
   first event of any type. One malformed event is skipped entirely (the existing pattern) — the monitor
   does not crash. The current cursor emits one result event per call with the whole iteration's usage:
   tokens update at the end of a turn, and the spinner breathes between turns — like opencode between
   step-finish events.

4. **Seeding feedback.md with questions.** When creating a new feedback file (the "never overwrite an
   existing one" rule is preserved): the source document is selected by the gate's step id — a
   motivation gate seeds from study.md, an ADR gate from adr.md, otherwise no seeding (an empty file).
   Only numbered questions are extracted: from the section whose heading (a `^#` line) contains
   `open questions` or `открытые вопросы` (case-insensitive), the lines matching `^\d+\.` up to the next
   heading; no section → no questions extracted. Questions are written into feedback.md before the
   editor opens; no questions → the file stays empty.

5. **Wiring.** The backend (opencode/cursor) is forwarded from the pipeline runner through the live
   monitor to the live lines — to omit price on cursor. The feedback editor receives the state
   directory and the gate's step id, so it can seed the questions.

## Alternatives

- **The rich library (Live/Progress/SpinnerColumn).** Rejected: an extra dependency; the existing ANSI
  block mechanics already handle redraw and width truncation; only a spinner frame once a second is
  needed.
- **Animated dots `., .., ...` (initial proposal).** Rejected by the user in favor of the spinner.
- **An elapsed-time counter instead of the spinner.** Not chosen: the user chose the spinner.
- **Tokens via an export command every tick.** Rejected: heavy and slow; the logs already carry
  everything (the same decision as in ADR-0011).
- **Heartbeat lines in the non-TTY log every second.** Rejected by the user: pollutes the log.
- **Copy the whole study.md into feedback.md.** Rejected by the user: only questions.
- **Seeding via a workflow step (showing the file in the gate message).** Rejected: the questions are
  needed in the file opened in a separate editor window; the gate message is not visible at that
  moment.
- **Heartbeat over the open gate menu.** Rejected by the user: the menu itself is visible status.

## Consequences

- Positive: no silence on any step — the harness line appears instantly, the spinner breathes every
  second, and at step boundaries the window without a line is ≤ 0.5 s; an observer always sees the
  process is alive.
- Positive: tokens are visible on both backends; the "no tokens → only spinner + status" degradation is
  built in.
- Positive: non-TTY logs are clean (one line per step transition); questions in feedback.md are right
  in front of the eyes when answering; an existing file is not touched.
- Negative: on short shell steps the harness line may flash for < 1 s (minimal visual noise).
- Negative: cursor usage shapes change between CLI versions; with an unrecognized shape the line simply
  stays without tokens (the spinner keeps working) — the risk is limited.
- Negative: on cursor tokens update once per agent turn (at the end of the call); between turns — only
  the spinner (like opencode between step-finish events).

## Acceptance Criteria

- Every step shows a live status line with a breathing spinner and no silence windows.
- The spinner shifts nothing on screen.
- Tokens are shown on both backends.
- Non-TTY logs stay clean.
- Gate menus are never overwritten.
- Feedback files are seeded only with the numbered open questions.
