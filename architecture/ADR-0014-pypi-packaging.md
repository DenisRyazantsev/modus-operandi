---
slug: pypi-packaging
status: accepted
date: 2026-08-19
---

# ADR-0014: Публикация spec-run через PyPI с bootstrap-установкой

## Context

Сейчас инструмент распространяется как git-репозиторий: пользователь клонирует проект и запускает `python3 install.py`, который копирует артефакты из дерева исходников (`pipeline_scripts/`, `prompts/`, `spec_utils/workflows/`, `config.example.yml`, `victory.wav`) в `~/.config/opencode/` и `~/.config/spec-kit-llm-client/` и ставит лаунчер `~/.local/bin/spec-run`. Источники резолвятся через `REPO_ROOT` из `spec_utils/__init__.py` — это работает только в checkout. `pyproject.toml` не имеет `[build-system]` и `[project.scripts]`, `requires-python = ">=3.14"`.

Пользователь хочет: на любой машине `pip install spec-run` — и `spec-run` сразу работает из командной строки, как сегодня после `install.py`. По фидбеку: обновление — через PyPI (`--update`/`--apply` не нужны); удаление — `pip uninstall` + явная команда полной очистки машины; standalone-пайплайн `adr` удаляется (остаются `task` и `review`); лицензия MIT, автор Denis Riazantsev <metacodeine@gmail.com>, semver, публикация из GitHub Actions через OIDC trusted publishing; репозиторий `git@github.com:DenisRyazantsev/spec-run.git`; конфиг-каталог переименовывается в `~/.config/spec-run`.

Исследование: wheel не поддерживает post-install хуки by design (PEP 427) — принятый паттерн «инициализация при первом запуске»; PyPA рекомендует данные пакета хранить внутри пакета и читать через `importlib.resources`; trusted publishing — современный стандарт публикации из CI без секретов. Имена `spec-run` и `spec-kit-llm-client` на PyPI свободны.

## Decision

### 1. Структура пакета и метаданные

- Переименовать проект в **`spec-run`**. Перейти на src-layout: Python-код `spec_utils/` → `src/spec_run/` (корневые модули пакета), `pipeline_scripts/` → `src/spec_run/pipeline_scripts/` (подпакет).
- Артефакты — package data внутри пакета: `src/spec_run/data/pipeline_scripts/`, `data/prompts/`, `data/workflows/` (yml), `data/config.example.yml`, `data/victory.wav`. Читать их через `importlib.resources.files("spec_run")`. `REPO_ROOT`/`PIPELINE_SCRIPTS_DIR`/`CONFIG_EXAMPLE` из `spec_utils/__init__.py` удалить.
- `src/spec_run/__init__.py` определяет `__version__ = "0.1.0"`; `pyproject.toml` содержит `version = "0.1.0"`; при релизе версия бампается в обоих местах.
- `pyproject.toml`:
  - `[build-system]`: `requires = ["uv_build >= 0.12.1, <0.13.0"]`, `build-backend = "uv_build"`.
  - `[project]`: `name = "spec-run"`, `requires-python = ">=3.12"`, `license = "MIT"` (+ файл `LICENSE` с текстом MIT), `authors = [{name = "Denis Riazantsev", email = "metacodeine@gmail.com"}]`, `readme = "README.md"`, classifiers, `[project.urls] repository = "https://github.com/DenisRyazantsev/spec-run"`.
  - `dependencies = ["specify-cli>=0.16", "pyyaml"]` (specify приходит с pip в тот же bin-каталог, что и `spec-run`; `deps.ensure_specify`/`ensure_pyyaml`/`uninstall_specify`/`uninstall_pyyaml` удаляются, `deps.py` упрощается).
  - `[project.scripts] spec-run = "spec_run.cli:main"`.
  - ruff `target-version = "py312"`, mypy `python_version = "3.12"`; `uv.lock` перегенерировать.

### 2. Лаунчер и подкоманды

- `src/spec_run/cli.py` — порт `pipeline_scripts/spec_run.py` (console-script entry point). Подкоманды: `task`, `review`, `edit`, `uninstall`. Удалить подкоманду `adr`, `ADR_WORKFLOW`, `_build_adr_command`; USAGE обновить. Флаг `--backend cursor|opencode` сохранить.
- Разрешение путей в рантайме из `XDG_CONFIG_HOME`/`~/.config` и `os.execv` установленного `run-pipeline.py` сохранить без изменений.
- Модули `edit_command.py`, `editor.py`, пакет `exceptions/` становятся обычными модулями пакета (`src/spec_run/`), импортируемыми cli; рендер их копий в `~/.local/bin` упраздняется (`render_spec_run`, `paths["spec_run"]`, `paths["exceptions_dir"]`, `paths["launcher_editor"]` удаляются).
- `install.py` в корне остаётся тонкой dev-обёрткой для разработки/тестов: вызывает инсталлер пакета с флагами `--home`/`--yes`/`--uninstall` (флаги `--update`/`--apply` удаляются).

### 3. Bootstrap при первом запуске

- `spec_run.cli.main` для подкоманд `task`/`review`/`edit` (но не `uninstall` и не `--help`) в начале вызывает `ensure_installed()`:
  - читает `~/.config/spec-run/install-version.txt`; если файла нет или версия != `__version__` — применяет рендер из ресурсов пакета: агенты `planner.md`/`executor.md` → `~/.config/opencode/agent/`; pipeline-скрипты → `~/.config/opencode/scripts/`; `task-pipeline.yml`, `review-pipeline.yml`, `prompts/`, `config.example.yml` → `~/.config/spec-run/`; `config.yml` создаётся копированием примера **только если отсутствует** (существующий конфиг пользователя никогда не перезаписывается); `victory.wav` → `~/.config/opencode/scripts/`; записывает `install-version.txt` с `__version__`.
  - печатает одну статус-строку: `spec-run: installed to ~/.config/spec-run` (или `spec-run: updated to <version>`); при актуальной установке — ничего не печатает.
  - при ошибке — сообщение в stderr и выход с кодом 1.
- На bootstrap проверяются предпосылки как в текущем `verify.check_prerequisites` (backend-CLI: `opencode` или `cursor-agent` в PATH в зависимости от `backend:` в конфиге).
- Конфиг-база переименовывается: `~/.config/spec-run` вместо `~/.config/spec-kit-llm-client` (`paths.py` и все упоминания, включая тесты).

### 4. edit и uninstall

- `edit`: пере-применение конфига вызовом apply **из пакета** (import), без `install-path.txt` (`paths["install_path"]` и его запись/чтение удаляются).
- `uninstall` (подкоманда): удаляет `~/.config/spec-run`, файлы `planner.md`/`executor.md` из `~/.config/opencode/agent/`, spec-run-принадлежащие файлы из `~/.config/opencode/scripts/` (список из `paths.py`), устаревшие `~/.local/bin/spec-run` и `~/.local/bin/editor.py`; печатает подсказку выполнить `pip uninstall spec-run` для удаления wheel. Уважает `XDG_CONFIG_HOME` (для тестов).

### 5. Удаление adr

- Удалить: `spec_utils/workflows/adr-pipeline.yml` (в `data/workflows/` не копировать), `render_workflow`, `paths["workflow"]`, проверки adr-pipeline в `verify.py`, маппинг `adr` в лаунчере, тесты и примеры `adr` в README/USAGE. `prompts/adr/*` сохраняются (используются task-пайплайном).

### 6. CI/CD

- `.github/workflows/ci.yml`: на push/PR — pytest, `ruff check`, `mypy`.
- `.github/workflows/publish.yml` (**имя файла фиксируется**, указывается в PyPI trusted publisher): триггер `release: types: [published]`; джоба `build`: `actions/checkout`, `astral-sh/setup-uv`, `uv build`, `actions/upload-artifact` (dist); джоба `publish`: `needs: build`, `environment: pypi`, `permissions: id-token: write`, `actions/download-artifact` (dist), `pypa/gh-action-pypi-publish@release/v1` без креденшелов (trusted publishing).
- Внешние шаги автора (в ADR только фиксируются): `git remote add origin git@github.com:DenisRyazantsev/spec-run.git` + push; создание pending trusted publisher на PyPI (проект `spec-run`, owner `DenisRyazantsev`, repo `spec-run`, workflow `publish.yml`, environment `pypi`); репетиция первого релиза на TestPyPI; тег `v0.1.0`.

### 7. Тесты и документация

- Адаптировать существующие тесты: новые пути (`~/.config/spec-run`), флоу `install.py --home` продолжает работать.
- Новый e2e-тест (или тестовый скрипт): `uv build` → `pip install` wheel во временное окружение → запуск entry point с `XDG_CONFIG_HOME` во временный каталог → проверка структуры `~/.config/spec-run` и `~/.config/opencode/...`, наличие `install-version.txt`, не-перезапись пользовательского `config.yml` при повторном apply; плюс проверка, что wheel содержит `src/spec_run/data/**`.
- README переписать под новый флоу (`pip install spec-run`; подкоманды; требования: opencode или cursor-agent; заметка про `pipx install spec-run` / `uv tool install spec-run`).
- Добавить `LICENSE` (MIT).

## Alternatives

- **Пайплайн целиком из wheel без `~/.config`** — отклонено: opencode читает агентов только из `~/.config/opencode`, конфиг и workflow-пути завязаны на config-base, site-packages фактически read-only.
- **Явный шаг `spec-run install` после pip install** — отклонено фидбеком: «pip install — и сразу работает».
- **Post-install hook** (setup.py install / sdist-only) — не существует для wheel by design (PEP 427); sdist-only-трюк — антипаттерн.
- **API-token вместо OIDC** — отклонено: trusted publishing — современный стандарт, без секретов.
- **hatchling/setuptools/flit вместо uv_build** — рабочие альтернативы; hatchling — запасной вариант (включает non-.py файлы пакета по умолчанию), если uv_build пропустит data-файлы.
- **Оставить `adr`** — отклонено фидбеком.
- **Миграция старой установки `~/.config/spec-kit-llm-client`** — отклонено: единственный существующий пользователь — автор, просто переходит на новую модель.

## Consequences

- Положительно: одна команда установки; обновления и удаление стандартными средствами PyPI; самодостаточный wheel (bootstrap не требует сети и не зависит от checkout); OIDC-публикация без секретов; `uvx`/`pipx` работают бесплатно; удалён мёртвый груз (`adr`, `--update`/`--apply`, `install-path.txt`, specify-каскады, рендер лаунчера в `~/.local/bin`).
- Отрицательно: первый запуск делает неявную установку (чуть медленнее, требует записи в `~/.config` — как и раньше при `install.py`); лёгкая проверка маркера на каждом запуске; `requires-python >=3.12` отсекает старые системы (осознанно); разовый рефакторинг (перенос ~45 артефактов, замена `REPO_ROOT`, правка тестов); specify-cli в общем окружении может конфликтовать с другими пакетами (решение — pipx/uv tool, задокументировать).

## Acceptance Criteria

1. `uv build` собирает wheel; wheel содержит `src/spec_run/data/pipeline_scripts/`, `data/prompts/`, `data/workflows/`, `data/config.example.yml`, `data/victory.wav` (проверяется тестом/скриптом).
2. `pyproject.toml`: `[build-system]` (uv_build), `name = "spec-run"`, `version = "0.1.0"`, `requires-python = ">=3.12"`, `license = "MIT"`, `authors` (Denis Riazantsev, metacodeine@gmail.com), `dependencies = ["specify-cli>=0.16", "pyyaml"]`, `[project.scripts] spec-run = "spec_run.cli:main"`; файлы `LICENSE` и обновлённый `README.md` существуют; ruff/mypy на 3.12; `uv.lock` перегенерирован.
3. Установка собранного wheel (`pip install` во временное окружение) даёт команду `spec-run`; первый запуск `spec-run review` (или `task`/`edit`) с чистым `XDG_CONFIG_HOME` создаёт `~/.config/spec-run/{config.yml, config.example.yml, task-pipeline.yml, review-pipeline.yml, prompts/, install-version.txt}` и `~/.config/opencode/{agent/planner.md, agent/executor.md, scripts/...}` со структурой, как у текущего `install.py --home`; печатается одна статус-строка установки.
4. Повторный запуск без смены версии ничего не печатает и не перезаписывает; изменённый пользователем `config.yml` сохраняется и при bootstrap после смены версии пакета (проверяется тестом).
5. `spec-run` имеет подкоманды `task`, `review`, `edit`, `uninstall`; `adr` отсутствует; `spec-run --help` печатает usage без `adr` и завершается кодом 0.
6. `spec-run edit` открывает конфиг и пере-применяет его через код пакета; файла `install-path.txt` в установке нет.
7. `spec-run uninstall` (с `XDG_CONFIG_HOME`) удаляет `~/.config/spec-run`, `planner.md`/`executor.md` из `~/.config/opencode/agent/`, spec-run-файлы из `~/.config/opencode/scripts/` и печатает подсказку про `pip uninstall spec-run`.
8. `adr-pipeline.yml` удалён из исходников; `prompts/adr/*` сохранены; примеры `adr` убраны из README/USAGE.
9. `install.py --home` из checkout продолжает работать (dev-флоу); флагов `--update`/`--apply` нет; существующие тесты адаптированы и проходят: `pytest tests -q`, `ruff check .`, `mypy spec_run`.
10. Существуют `.github/workflows/ci.yml` (pytest/ruff/mypy) и `.github/workflows/publish.yml` (триггер `release: published`; джобы build → publish; `environment: pypi`; `permissions: id-token: write` только в publish; `pypa/gh-action-pypi-publish@release/v1` без креденшелов).

## Amendments

### Amend 1: AC 9 — команда `mypy spec_run` заменена конфигурацией `[tool.mypy]`

Записанное отклонение (`deviation.md`): литеральная команда `mypy spec_run` из AC 9 невыполнима при src-layout, который предписывает сам ADR — mypy трактует голый аргумент как путь к файлу, а не модуль (`Cannot read file 'spec_run'`), и конфигурация, заставляющая голое имя модуля работать как аргумент, невозможна.

Что сделано вместо: эквивалентная строгая проверка через `[tool.mypy]` в `pyproject.toml` — `files = ["install.py", "src/spec_run", <7 standalone-скриптов: save_adr, check_review, check_implementation, check_questions, task_utils, adr_utils, agent_call>]` (та же строгость, что до рефакторинга), `explicit_package_bases = true`, `mypy_path = ["src", "src/spec_run/data/pipeline_scripts"]` (standalone-скрипты вне пакета резолвят sibling-импорты как в рантайме), `exclude` для остального `src/spec_run/data` (негативный lookahead сохраняет перечисленные скрипты в проверке). CI (`ci.yml`) запускает `uv run mypy` без аргументов (использует `files` из конфига); README-секция для разработчиков документирует `uv run mypy`.

Почему принято: намерение AC 9 (строгий mypy над пакетом и проверяемыми pipeline-скриптами, проходящий в CI) выполнено; изменение чисто конфигурационное, покрытие типов не ослаблено.

