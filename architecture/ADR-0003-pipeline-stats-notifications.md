---
slug: pipeline-stats-notifications
status: accepted
date: 2026-08-14
---

# ADR-0003: Token/Time Statistics and Sound Notifications in run-pipeline.py

## Context

Upon completion of any run — currently `adr-pipeline` and `review-pipeline`, but effectively any workflow launched
through the common wrapper — the user wants statistics on token usage (input, output, reasoning, cache) and wall time.
A sound signal is also needed when human participation is required: when spec-kit waits for interactive input (a human
gate — ADR approval), when the pipeline fails with an error, and when it simply finishes.

Verified facts about the current implementation:

- All pipelines run through a single common wrapper: `adr-pipeline …` and `review-pipeline …`. It already streams live
  output with timestamps, tracks the run state, tails agent logs, and prints the final status (exit code + resume
  command). This is the single entry point — functionality added there becomes the default for both (and any future)
  pipelines.
- The planner and executor session ids are already saved by the run scripts into a per-task sessions file (the task id
  comes from the current-task symlink). So there is no need to track tokens during the run — these saved ids are enough.
- opencode can return session statistics by id: `opencode export <sessionID>` prints session JSON to stdout (a status
  line goes to stderr). The `info` field of that JSON holds the needed numbers: `info.tokens` = `{input, output,
  reasoning, cache: {read, write}}`, `info.cost`, and also `info.time = {created, updated}` and `info.agent`.
- The wrapper already detects a human gate opening by the menu's first line (starts with `┌─ Gate`); the exit code is
  known after the run ends.
- The user provided the sound file `victory.wav`.

One caveat discovered during implementation: pipe capture of `opencode export` output truncates large exports — a
known upstream bug causes the export to exit before its stdout is fully flushed into the pipe once the export exceeds
the pipe buffer (the JSON is silently cut to a multiple of 65536 bytes). The export output is therefore captured via a
temporary file instead.

## Decision

Implement both capabilities in the common wrapper, not in the individual workflows:

1. **Token statistics via `opencode export`, without in-process accumulation.** After the run ends, the wrapper
   resolves the saved session ids for both roles (planner and executor), runs `opencode export <sessionID>` for each,
   parses the returned JSON, and takes `info.tokens.input`, `info.tokens.output`, `info.tokens.reasoning`,
   `info.tokens.cache.read`, `info.tokens.cache.write` (and `info.cost`). The values of the two roles are summed.
   Because opencode itself knows each session's full usage, no live token accumulator is needed.
2. **Wall time.** The wrapper measures the run's wall-clock time itself, from launch until the run ends — this is the
   honest measure for all termination paths (success, error, abort/cancel at a gate), including human wait time.
   Printed in `HH:MM:SS` format (e.g. `01:45:01`).
3. **Final statistics block.** After the run, on all termination paths — success, error, abort — a block is printed:
   wall time, token sums (input, output, reasoning), cache on its own line (read/write), and cost. All token numbers
   use space thousands separators (`321 213`, not `321213`). If a session id is not found or `opencode export` fails —
   the affected line/value is marked unavailable (zero/dash), but the wrapper does not crash.
4. **One sound for all events.** The same `victory.wav` sound plays at all three moments: human gate opening (detected
   in the live output), successful completion (`rc == 0`), and error/abort (`rc != 0`). Different sounds for different
   events are not needed. Playback uses the system player, is non-blocking, and degrades silently: without the file or
   a player, or in a non-TTY run — the sound is just skipped.
5. **Sound file delivery.** `victory.wav` ships with the installation, deployed next to the installed wrapper, and the
   wrapper references it by the path resolved at install time.

## Alternatives

* **Live token accumulation from agent step events (initial variant).** Rejected in favor of `opencode export`:
  requires parsing the run's JSON event stream, an accumulator, and scoping to the current run (logs of past tasks
  remain on disk). Requesting statistics from opencode by saved session id is simpler and more accurate — opencode
  itself knows the session's full usage.
* **A final reporting step appended to each workflow.** Rejected: requires editing every workflow and does not cover
  "any pipeline"; the sound still needs the wrapper (gate detection via output and exit code), so splitting statistics
  and sound across different places would complicate the implementation.
* **Session timestamps (`updated - created`) as run time.** Rejected: that is the sessions' active time without idle
  periods (including human wait at a gate); the user asked for run-time statistics — the honest measure is the overall
  wall-clock of the run, which the wrapper measures directly.
* **Different sounds for different events (attention/success/error).** Rejected by user feedback: one signal is
  enough; `victory.wav` is played for all three events.
* **Sound via a third-party library or system notifications.** Rejected: adds dependencies; a system player for a
  local `.wav` is enough, and for headless runs sound is not needed anyway.
* **Configurable sound/statistics (on/off, sound selection).** Deferred: the user did not ask for configuration;
  default-on with silent degradation is enough. An option can be added later without changing the contract.

## Consequences

- Positive: a single implementation in the wrapper — statistics and sound become the default for `adr-pipeline`,
  `review-pipeline`, and any future workflows without editing each workflow.
- Positive: statistics are accurate and complete — taken directly from opencode by session id, covering all steps of
  both roles without a custom accumulator and without scoping to past runs.
- Positive: changes are additive and localized to the wrapper plus copying the sound file at install time; workflows,
  run scripts, sessions, and the step contract do not change.
- Positive: sound and statistics do not affect the exit code or output; nothing breaks in CI/headless.
- Negative: statistics depend on `opencode` being in PATH and `opencode export <sessionID>` working at the end of the
  run (if the command is unavailable — degrades to dashes/zeros).
- Negative: works only when launched via the wrapper; a direct workflow launch gives neither statistics nor sound.
- Negative: `opencode export` returns the whole session export (including messages) although only `info` is needed; on
  large sessions this is slower/heavier than the minimum necessary.
- Negative: sound playback depends on the environment (presence of a system player, terminal sound enabled); on some
  systems the signal may not play — silent degradation.

## Acceptance Criteria

- After any run, the wrapper prints a statistics block with wall time and token/cache/cost sums for both roles, on all
  termination paths (success, error, abort), with space thousands separators for tokens and `HH:MM:SS` wall time.
- The same `victory.wav` sound plays at gate-open, on success, and on failure.
- Sound and statistics never change the exit code: missing file/player or a non-TTY run terminates exactly as without
  them.
