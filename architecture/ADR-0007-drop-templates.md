---
slug: drop-templates
status: accepted
date: 2026-08-15
---

# Drop `templates/`: Apply the Config via Ordinary Arguments Instead of Insertion

## Context

Installed artifacts — the agents, both workflows, the shell wrappers, the pipeline wrapper, and the modus-operandi launcher — were generated from template files via placeholder substitution, while other files in the same directory were plain scripts that were only copied, not rendered. The directory was thus a mixture of two mechanisms. This was painful in practice: every literal `$` in shell scripts and YAML (bash variables, command substitutions, dollars in messages) had to be escaped, otherwise substitution failed; the curly braces used by the engine's own templating could not be distinguished from the substitution placeholders; substitution errors surfaced only at render time, not in the source; and tests had to manually render template files while other scripts were imported from the directory directly. The goal was to remove this whole layer and write plain code, delivering the config via ordinary arguments rather than by inserting values into file text at install time. During implementation it was also learned that embedding the numeric iteration limit into the pass-check warning text was itself the kind of value-into-text substitution being prohibited, so the number was dropped from the human-readable warning while the limit itself continued to be written and enforced as data.

## Decision

Remove the template system and the placeholder-substitution mechanism entirely: no template files, no placeholders, and no escaping remain. The config is applied via ordinary arguments and environment variables (such as `MO_STATE_DIR`): installed scripts are plain code that receive their settings (state and artifact locations, attach behavior, workflow paths, their own locations) at execution time rather than having them baked in at install. Values that physically must live in a file — the model and reasoning settings in the agent frontmatter — are written by plain code as data (structure to text), without any text-substitution machinery and without escaping. Runtime scripts move out of the templates directory into a regular source directory and remain ordinary importable modules; the installer still copies them together so their mutual imports keep working. Observable runtime behavior does not change: the install layout and the pipeline's visible behavior (warm sessions, task-id resolution, review loops, gates) stay the same — only *how* settings are delivered changes, not *what* the pipeline does.

## Alternatives

- **Keep the current setup** — rejected: the escaping pain and the mixed render-vs-copy mechanism remain.
- **Switch to another templater (e.g. Jinja2)** — rejected: adds an external dependency, keeps the template-to-file layer, and only changes the placeholder syntax, creating a conflict with the curly braces of the engine's own templating.
- **Apply the config via ordinary arguments** — chosen: the only option that removes the insertion machinery itself, leaves one language in the project, and makes runtime scripts honest importable modules.

## Consequences

- One language across the project; escaping, value-into-text insertion, and their related errors disappear.
- Scripts receive config as ordinary arguments/environment and are imported and tested as normal modules; build errors become visible directly in the code.
- A large mechanical refactor touching the installer, the rendering logic, the workflows, and the tests.
- Settings must be carefully forwarded through the pipeline via inputs and environment variables, otherwise steps lose their state and artifact locations.

## Acceptance Criteria

- Installation, update, and uninstall produce the same artifacts as before.
- All config values are delivered at runtime via arguments/environment and are honored.
- Observable pipeline behavior is unchanged.
