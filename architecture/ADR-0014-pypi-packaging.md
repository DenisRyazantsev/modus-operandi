---
slug: pypi-packaging
status: accepted
date: 2026-08-19
---

# ADR-0014: Publishing modus-operandi via PyPI with Bootstrap Installation

## Context

The tool is currently distributed as a git repository: the user clones the project and runs an installer script that
copies artifacts from the source tree into the config locations and installs a launcher binary; source paths are
resolved relative to the checkout, which does not work from an installed package, and the project is not pip-installable
(no build system, no console entry point). The user requires: `pip install modus-operandi` works on any machine and the
command works immediately from the command line; updates come through PyPI (no self-update flags needed); removal
happens through `pip uninstall` plus an explicit full machine cleanup command; the standalone `adr` pipeline is
removed (leaving `task` and `review`); MIT license, author Denis Riazantsev <metacodeine@gmail.com>, semantic
versioning; publishing from CI via OIDC trusted publishing without secrets; the config directory is renamed to the
modus-operandi name.

Research: wheels do not support post-install hooks by design (PEP 427) — the accepted pattern is "initialization on
first run"; package data is shipped inside the package and read at runtime; trusted publishing is the modern standard
for CI publishing without secrets. The project name and the old name are free on PyPI. A later follow-up replaced the
literal mypy command named in the acceptance criteria with an equivalent configuration-based strict check, since a
bare module name is not a valid mypy argument under the chosen source layout.

## Decision

- **Package as `modus-operandi` on PyPI.** The project is renamed to `modus-operandi`, built as a standard wheel, and exposes a
  `modus-operandi` command with `task`, `review`, `edit`, and `uninstall` subcommands; the `adr` subcommand and pipeline
  are removed. The backend selection flag (`cursor|opencode`) is kept.
- **Self-contained package.** All runtime artifacts (agents, pipeline scripts, workflows, prompts, config example,
  sound file) ship inside the package and are read from the installed package, not from a checkout. Metadata:
  MIT license with a LICENSE file, author Denis Riazantsev <metacodeine@gmail.com>, semantic versioning starting
  at 0.1.0, and a modern minimum Python version (3.12).
- **Bootstrap on first run.** On invocation, the command ensures the runtime layout is present: the shipped artifacts
  are rendered into the engine's config locations when absent or outdated, a user-modified config is never
  overwritten, one status line is printed on install/update (nothing when up to date), and failures are reported to
  stderr with a nonzero exit. The config base is renamed to the modus-operandi config directory. `edit` re-applies the
  config from the installed package; `uninstall` removes all files the tool created on the machine and directs the
  user to `pip uninstall modus-operandi` for the wheel.
- **Publishing.** A CI workflow publishes on release via OIDC trusted publishing, without API tokens or other
  secrets, and continuous integration (tests, lint, type checks) runs on push and pull requests.

## Alternatives

- **The whole pipeline from the wheel without the config directory** — rejected: the engine reads agents only from
  its user config directory; config and workflow paths are tied to the config base; site-packages is effectively
  read-only.
- **An explicit install step after `pip install`** — rejected by feedback: "pip install — and it just works".
- **Post-install hooks** — rejected: they do not exist for wheels by design (PEP 427); sdist-only tricks are an
  anti-pattern.
- **API tokens instead of OIDC** — rejected: trusted publishing is the modern standard and needs no secrets.
- **Other build backends** — workable alternatives; hatchling is the fallback if the chosen backend misses package
  data files.
- **Keeping `adr`** — rejected by feedback.
- **Migrating the old installation layout** — rejected: the only existing user is the author, who switches to the new
  model.

## Consequences

- Positive: one install command; updates and removal through standard PyPI tooling; a self-contained wheel whose
  bootstrap needs no network and no checkout; OIDC publishing without secrets; pipx and uv tool installs work for
  free; dead weight removed (`adr`, self-update flags, launcher rendering into a bin directory).
- Negative: the first run performs an implicit install (slightly slower and requires writing to the config
  directory, as before); a lightweight version check on every run; the higher minimum Python version cuts off old
  systems (deliberate); a one-off refactoring that moves the artifacts and adjusts the test suite; the specify
  dependency in a shared environment may conflict with other packages (mitigated via pipx/uv tool, documented).

## Acceptance Criteria

- `pip install modus-operandi` gives a working command on any machine.
- The first run bootstraps the runtime layout without a network and never overwrites a user-modified config.
- Updates and removal go through standard PyPI tooling.
- Publishing happens from CI via OIDC trusted publishing without secrets.
- The obsolete standalone pipeline is removed.
- The command exposes `task`, `review`, `edit`, and `uninstall`; `adr` is absent; the config directory is renamed to
  the modus-operandi name.
