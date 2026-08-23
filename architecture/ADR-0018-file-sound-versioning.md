---
slug: file-sound-versioning
status: accepted
date: 2026-08-23
---

# ADR-0018: File-Based Task Input, Configurable Sound Alert, and Git-Tag Versioning

## Context

Three user-facing gaps in the modus-operandi CLI:

1. The task pipeline accepts its description only as inline command-line text. Long or pre-prepared descriptions are awkward to type (shell quoting, argument-size limits), and there is no way to pass a file with the text.
2. The completion sound alert is hardwired: always on, always the shipped victory.wav. The user wants to disable it or use their own sound file via the config. ADR-0003 explicitly deferred configurability with the contract that defaults remain unchanged.
3. The package version is stamped from a git tag only in CI at release time, yet the repository itself carries the released-looking version `0.1.0`, misleading readers and local builds into believing a release exists.

## Decision

One ADR records the three decisions:

1. **File-based task input.** The `task` command accepts the task description either as inline text or as a path to a file containing the text. File mode is auto-detected: a single argument naming an existing file is read as the description; passing a file together with additional text is an error. A missing, unreadable or non-UTF-8 file is rejected as an invocation error. The description — from a file or inline alike — is automatically converted to a shell-safe escaped form instead of being rejected for special characters, so both input modes behave identically and the user never has to care about quoting. No artificial size limit is imposed. The feature is limited to `task`, which is the only subcommand with a text input.

2. **Configurable sound alert.** A dedicated `sound:` config section exposes an enabled flag in question form (`is_sound_alert_enabled`) and a custom sound file path (`sound_file`). The defaults keep the existing contract: the alert is enabled and plays the shipped sound for all events (gate open, success, failure; the feedback gate never signals), and playback never affects the exit code of a finished run. Unlike the lenient handling of other config keys, invalid values in the sound section are hard errors: a non-boolean flag, or an enabled alert whose sound file does not exist, fails with an explanation of why and how to fix it (point to an existing file or disable the alert) before the run starts. Relative sound file paths resolve against the config file's directory, so behavior does not depend on where the command is launched from.

3. **Git-tag versioning with an honest dev placeholder.** The repository carries the PEP 440 development placeholder `0.0.0.dev0` instead of the released-looking `0.1.0` — a bare "dev" is not a valid version and cannot be built, and `0.0.0.dev0` is the neutral, conventional "not yet released" marker that always sorts below any real tag. The release mechanism stays: on a tag push, CI stamps the tag name into the version declarations, builds and publishes; tags remain without a `v` prefix and are validated against PEP 440 so an invalid tag fails the build early instead of publishing a broken version. The two version declarations stay in sync.

## Alternatives

- **An explicit `--file`/`--prompt-file` flag** (the LLM-CLI convention, e.g. copilot-cli) — rejected by the user: auto-detection keeps the command minimal, and the "file plus text is an error" rule follows the established conflict-is-an-error convention, covering the ambiguity risk.
- **The `@file` prefix convention** — rejected: it expands a list of arguments rather than a single text, and it is a rarely used, conflict-prone convention.
- **stdin (`-`) as the input channel** — rejected: the wrapper already owns stdin through a pty for interactive gates, and the requirement was a file, not a stream.
- **Stripping or replacing forbidden characters** instead of escaping — rejected: it silently corrupts the user's description; reversible escaping preserves the text losslessly.
- **Relaxing the shell-safety validation to accept anything** — rejected: the description is interpolated into shell contexts inside the pipeline; escaping plus keeping raw forbidden characters invalid preserves the injection defense.
- **Sound keys inside the existing `workflow:` section** — rejected by the user: a separate `sound:` section is clearer.
- **The conventional boolean name without the `is` prefix** (e.g. `sound_enabled`, per OpenStack/AEP/HashiCorp/OpenTelemetry conventions) — rejected by the user: the question-form name was explicitly chosen even though it deviates from the ecosystem convention.
- **Silent degradation of invalid sound settings** (as for other config keys) — rejected: a silently disabled alert or a silent missing file is worse than an explicit error with a fix hint.
- **Full dynamic versioning from git tags** (setuptools-scm/hatch-vcs/uv-dynamic-versioning) — rejected: it requires switching the build backend (the current one does not support dynamic versions), which the user judged as unnecessary complexity; the CI stamping already works.
- **A next-release dev placeholder** (e.g. `0.1.1.dev0`) — rejected: it claims a specific future release; `0.0.0.dev0` is neutral and matches the established "not yet published" convention.

## Consequences

- Positive: long and prepared task descriptions can be passed as files with no new flags; text and file inputs behave identically and accept special characters without user action.
- Positive: the sound alert can be disabled or personalized through the config, while the default behavior and the "sound never changes the exit code" property remain intact.
- Positive: the repository and local builds no longer masquerade as a released version; the release version still comes solely from the git tag, and invalid tags are caught in CI.
- Negative: an inline text argument that happens to match an existing file path is interpreted as a file — a small, documented ambiguity inherent to auto-detection.
- Negative: file content is still delivered through the command line, so the natural argument-size limits (Linux ~2 MB, Windows ~32 KB) remain.
- Negative: the sound section deliberately breaks the otherwise lenient "malformed config still runs" behavior for its own keys: a bad sound setting aborts the run before it starts, with an explanation.
- Negative: the version placeholder keeps digits (`0.0.0.dev0`) although a bare "dev" was preferred — a bare "dev" cannot be built.

## Acceptance Criteria

- `modus-operandi task <path-to-existing-file>` runs the pipeline with the file's content as the task description; mixing a file with additional text is rejected with an error; a missing, unreadable or non-UTF-8 file is rejected with a clear error and a nonzero exit.
- Special characters that previously failed validation pass for both inline and file input without user intervention and without changing the description's meaning.
- The config exposes `sound.is_sound_alert_enabled` (default true) and `sound.sound_file` (default the shipped victory.wav); disabling the flag silences the alert on all events; a custom file is played when it exists.
- An invalid sound value (a non-boolean flag, or an enabled alert whose sound file does not exist) produces an error explaining how to fix it and does not start the run.
- The repository version is a dev placeholder that builds successfully; a tag push builds and publishes the exact tag version, and an invalid (non-PEP 440) tag fails the build.
- The default sound behavior (enabled, victory.wav, one signal per event, no effect on the exit code) is unchanged unless the user configures otherwise.
