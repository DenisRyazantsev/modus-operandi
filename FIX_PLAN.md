# FIX_PLAN: ревью spec-kit-llm-client (SRP + баги)

Составлено по результатам ревью `install.py`, `tests/test_install.py`, `templates/*`, `config.example.yml`.

Текущее состояние: все 18 тестов проходят (`python3 -m unittest tests.test_install`). Вносимые изменения НЕ должны их ломать; рядом с каждым исправлением — какие тесты добавить.

---

## Часть 1. Баги

### B1. HIGH — `sync-adr` теряет deviation.md и перезаписывает сохранённый ADR при сбое planner-вызова
**Файл:** `templates/adr-pipeline.yml.tpl` (шаг `sync-adr`, строки ~187-212).
**Проблема:** shell-шаг не имеет `set -e` и не проверяет код возврата `${run_agent} planner ...`. Если вызов агента падает (opencode упал, сеть, таймаут), интерпретатор продолжает: python-блок переписывает `architecture/ADR-XXXX-*.md` НЕизменённым adr.md, затем `rm -f deviation.md` — запись о девиации утрачена, ADR остался без Amendments, при этом следов ошибки нет (шаг завершится кодом 0 от `rm`/`echo`).
**Исправление:**
- Добавить `set -euo pipefail` в начало `run:` шага `sync-adr`.
- Либо явно: `if ! "${run_agent}" planner "..."; then echo "error: planner sync failed; keeping deviation.md" >&2; exit 1; fi` и убрать `rm` из общего потока (удалять deviation.md только после успешной синхронизации).
- Заодно проверить: выполняется ли specify-cli shell-шаг через `bash -c` без `-e` (по умолчанию — без). Это подтверждает баг.
**Тесты:** продлить `test_workflow_deviation_sync` — assert, что в шаге `sync-adr` присутствует `set -euo pipefail` (или явная проверка кода возврата) и что `rm -f ... deviation.md` идёт ПОСЛЕ проверки успеха.

### B2. HIGH — непойманные исключения в `main()` дают traceback вместо понятной ошибки
**Файл:** `install.py` (`main`, строка ~497; `run_install`, `load_config`).
**Проблема:** `main()` ловит только `InstallError`. Реальные сценарии падения с traceback:
- кривой `config.yml` → `yaml.YAMLError` (ParserError) из `load_config`;
- нет прав на запись в `~/.config/...` → `OSError` из `mkdir`/`copy2`/`write_text`;
- `KeyError` из `Template.substitute` (если в шаблоне появится незаэкранированный `$name`) и `ValueError`.
**Исправление:** в `main()` добавить обработку `except (OSError, yaml.YAMLError, ValueError, KeyError) as exc: print("error: ...", file=sys.stderr); return 1` (или обернуть `run_install` в один `try` с общим сообщением). `yaml` может быть `None` — обрабатывать аккуратно (до `ensure_pyyaml`).
**Тесты:** `test_malformed_config_reports_error_not_traceback`: записать в config.yml `"models: ["` → rc=1, в stderr есть `error:`, нет `Traceback`.

### B3. MEDIUM — ADR сохраняется в `architecture/` без одобрения, если `adr-loop` исчерпал 3 итерации
**Файл:** `templates/adr-pipeline.yml.tpl` (шаги `adr-loop` / `save-adr`).
**Проблема:** `do-while` c `max_iterations: 3` после исчерпания итераций продолжает выполнение (не abort). Если пользователь 3 раза выбирает `revise`, `save-adr` всё равно выполняется — неодобренный ADR попадает в `architecture/`.
**Исправление:** после `adr-loop` добавить проверку: шаг `if`/`shell`, который смотрит последний результат `steps.adr-gate.output.choice`; если != `approve` — `exit 1` с понятным сообщением (запуск падает, резюмируется) или gate с `on_reject: abort`. До 0.16.2 уточнить: последнее значение choice доступно как `steps.adr-gate.output.choice` (aliasing починен в spec-kit PR #2662, вошёл до 0.16.0 — verify на установленной версии).
**Тесты:** рендер-тест — наличие шага проверки одобрения между `adr-loop` и `save-adr`, со ссылкой на `steps.adr-gate.output.choice`.

### B4. MEDIUM — `ensure_specify`/`ensure_pyyaml`: успешная установка не видна, если `~/.local/bin` нет в PATH
**Файл:** `install.py` (`ensure_specify`, строки ~141-170; аналогично `ensure_pyyaml`).
**Проблема:** `uv tool install` / `pipx install` / `pip install --user` кладут бинарь в `~/.local/bin` (или `~/.local/share/uv/tools/...`). Если каталога нет в PATH текущего процесса, `find_in_path("specify")` вернёт `None`, инсталлятор перейдёт к следующему способу (двойная установка) и в конце выдаст ложное «could not install specify-cli», хотя пакет установлен.
**Исправление:** после каждой попытки установки проверять и явные пути: `Path.home()/".local/bin/specify"`, а не только `shutil.which`. Если найден, но не на PATH — вывести предупреждение «добавьте ~/.local/bin в PATH» и продолжить, используя полный путь.
**Тесты:** мок `find_in_path` → None + мок `run` записывающий факт установки; проверка, что явный путь проверяется (или что предупреждение печатается) — на усмотрение исполнителя, минимально: unit-тест на новую helper-функцию `_specify_candidates()`.

### B5. MEDIUM — у `sync-adr` нет `timeout`, хотя шаг запускает planner-сессию
**Файл:** `templates/adr-pipeline.yml.tpl` (шаг `sync-adr`).
**Проблема:** все агентские шаги имеют `timeout: ${step_timeout}`; `sync-adr` запускает `${run_agent} planner` (минуты работы) БЕЗ timeout. Если у specify-cli есть дефолтный таймаут shell-шагов (verify), вызов может обрываться. Несогласованность в любом случае.
**Исправление:** добавить `timeout: ${step_timeout}` в `sync-adr` (и в `save-adr`, если агентский вызов slug-фикса — он уже имеет timeout, перепроверить).
**Тесты:** продлить `test_workflow_agent_steps_have_timeout` шагом `sync-adr`.

### B6. MEDIUM — slug-санитизация: слово >60 символов или нелатинский slug → жёсткий, непонятный сбой
**Файл:** `templates/adr-pipeline.yml.tpl` (save-adr, строки ~86-95).
**Проблема:** если первое слово длиннее 60 символов — цикл обрывается сразу, `slug` пустой → «error: slug is empty after sanitization». Если slug целиком нелатинский — после `re.sub(r"[^a-z0-9-]", "-", ...)` остаются только `-`, `strip("-")` → пустая строка → та же ошибка без объяснения, что причина в не-English slug.
**Исправление:** (а) обрезать отдельное слово до 60 символов вместо пустого slug; (б) для полностью нелатинского slug выдавать внятную ошибку: «slug must contain ASCII letters (English), e.g. 'slug: prod-validation-splits'».
**Тесты:** unit-тест на функцию санитизации, если она будет вынесена в отдельный скрипт (см. S3); иначе — рендер-тест на текст ошибки.

### B7. MEDIUM — `run-agent.sh`: `--task` без значения завершается кодом 1 без usage
**Файл:** `templates/run-agent.sh.tpl` (строки ~31-37).
**Проблема:** `--task) TASK_ID="$2"; shift 2;;` — при `--task` последним аргументом `shift 2` под `set -e` завершает скрипт кодом 1 без сообщения (проверено: `bash -c 'set -e; set -- a; shift 2'` → exit 1).
**Исправление:** проверять наличие значения: `--task) [ $# -ge 2 ] || usage; TASK_ID="$2"; shift 2;;`.
**Тесты:** shell-тест не добавлять (инфраструктура только unittest/python); допустим рендер-тест на присутствие guard-строки. Достаточно ручной проверки.

### B8. LOW — хрупкая проверка синтаксиса workflow в `validate_install`
**Файл:** `install.py` (строки ~325-335).
**Проблема:** проверка `if result.returncode == 0 or "Required input" not in result.stderr:` завязана на точный текст сообщения specify-cli в stderr. Смена формулировки/регистра (или вывод в stdout) → ложный провал установки.
**Исправление:** искать нечувствительно к регистру в `(result.stderr or "") + "\n" + (result.stdout or "")`; сообщение об ошибке делать информативным. Альтернатива: `specify workflow validate <file>` (если есть в 0.16 — verify) вместо запуска.
**Тесты:** расширить fake `make_run` кейсом с сообщением в stdout.

### B9. LOW — конфликты флагов не валидируются (`--register` молча побеждает `--uninstall`/`--update`)
**Файл:** `install.py` (`run_install`, строки ~437-447).
**Исправление:** в начале `run_install` проверять взаимоисключающие комбинации (`--register` с `--uninstall`/`--update`, `--home` с `--register`) и бросать `InstallError` с пояснением.
**Тесты:** параметризованный тест конфликтных комбинаций → rc=1.

### B10. LOW — misleading сообщение `ensure_config`
**Файл:** `install.py` (строки ~198-202).
**Проблема:** печатается «created config.yml — edit it and rerun install.py», но установка ПРОДОЛЖАЕТСЯ и завершается успешно с дефолтными моделями. Сообщение противоречит поведению.
**Исправление:** переформулировать: «created config.yml with defaults — edit it and rerun to change models» (без «rerun» как обязательства).
**Тесты:** не требуются.

### B11. LOW — `print_instructions` ломается при вызове не через `python3 install.py`
**Файл:** `install.py` (строки ~353-367).
**Проблема:** `Path(sys.argv[0]).name` даёт «python -m unittest» / путь; инструкция `python3 install.py --register` оказывается неверной.
**Исправление:** использовать `REPO_ROOT / "install.py"` (абсолютный путь).
**Тесты:** не требуются (или простой тест содержимого вывода).

### B12. LOW — `do_uninstall` удаляет PyYAML только через pip3 и не чистит пустые каталоги
**Файл:** `install.py` (строки ~392-414).
**Проблема:** PyYAML мог быть поставлен через `uv pip install --system` / `pip --user` — `pip3 uninstall` промахнётся; каталоги `agents/`, `scripts/`, `sklc/` остаются пустыми.
**Исправление:** попробовать несколько uninstall-путей (pip3 --user, python3 -m pip); удалять пустые каталоги через `shutil.rmtree` c `ignore_errors` после удаления файлов (только если каталог пуст — `os.rmdir` в try/except).
**Тесты:** `test_uninstall_removes_files_keeps_config` (rc=0, planner.md/executor.md/run-agent.sh/workflow удалены, config.yml на месте).

### B13. LOW — риск убийства чужого процесса по переиспользованному PID в `run-agent.sh`
**Файл:** `templates/run-agent.sh.tpl` (строки ~54-64).
**Проблема:** stale-PID kill полагается только на `kill -0` — если PID переиспользован другой программой, убьём невиновный процесс.
**Исправление:** перед `kill` сверять имя процесса: `ps -p "$OLD_PID" -o comm=` содержит `opencode` (или `pgrep -f`), иначе только удалять PID-файл.
**Тесты:** ручная проверка; рендер-тест на присутствие `ps -p`/`pgrep` guard.

### B14. LOW — task_id не валидируется в рантайме (инъекция в пути/имена файлов)
**Файлы:** `templates/adr-pipeline.yml.tpl`, `templates/run-agent.sh.tpl`.
**Проблема:** `task_id` интерполируется в пути `.workflow/tasks/<id>/`, `sessions-<id>.json`, `pids/`. Значение `../../x` или с пробелами ломает шаги / пишет вне state_dir. README предупреждает, но защиты нет.
**Исправление:** в `run-agent.sh` валидировать `TASK_ID` regex `^[A-Za-z0-9_-]+$` перед использованием (exit 2 с сообщением). В workflow добавить шаг валидации на старте (shell: `echo "{{ inputs.task_id }}" | grep -qE '^[A-Za-z0-9_-]+$'`).
**Тесты:** рендер-тесты наличия валидации.

### B15. LOW — `network_available` жёстко завязан на pypi.org
**Файл:** `install.py` (строки ~67-72).
**Проблема:** при корпоративном зеркале/заблокированном pypi установка блокируется, хотя pip настроен на зеркало.
**Исправление:** оставить как есть, но в сообщение ошибки добавить подсказку, либо проверять `pip config` (низкий приоритет, можно пропустить).

---

## Часть 2. SRP-нарушения

### S1. HIGH — `install.py` (507 строк) объединяет 7 ответственностей
Текущее разбиение по функциям:
1. Bootstrap окружения: `network_available`, `_pip_works`, `ensure_pyyaml`, `ensure_specify`, `get_specify_version`, `parse_specify_version`.
2. Конфигурация: `build_paths`, `ensure_config`, `load_config`, `validate_config`, `collect_keys`, `print_diff_new_options`.
3. Рендеринг: `render_file`, `render_agents`, `render_run_agent`, `render_workflow`.
4. Верификация: `validate_install` (см. S2).
5. Жизненный цикл: `do_register`, `do_uninstall`, `confirm`.
6. CLI/оркестрация: `parse_args`, `run_install`, `main`.
7. Вывод инструкций: `print_instructions`.

**Целевая структура** (пакет, совместимый с запуском `python3 install.py` — оставить тонкий entry-point):

```
install.py          # entry point: from sklc.cli import main; sys.exit(main())
sklc/
  __init__.py       # InstallError, REPO_ROOT, TEMPLATES_DIR, CONFIG_EXAMPLE
  deps.py           # network_available, _pip_works, ensure_pyyaml, ensure_specify, get_specify_version, parse_specify_version
  config.py         # build_paths, ensure_config, load_config, apply_defaults, validate_config, collect_keys, print_diff_new_options
  render.py         # render_file, render_agents, render_run_agent, render_workflow
  verify.py         # check_files, check_workflow_syntax, check_agents_visible (см. S2)
  actions.py        # do_register, do_uninstall, confirm
  cli.py            # parse_args, run_install, main, print_instructions
```
Правила миграции:
- чисто механический перенос (никаких изменений логики, кроме багов из Части 1);
- тесты продолжают импортировать по старым путям или перейти на `from sklc import ...` — обновить импорт в `tests/test_install.py` (`import install` → `import sklc.cli as install` или моки по новым путям); ВАЖНО: моки в тестах патчат `install.run`, `install.find_in_path` — при переносе либо оставить реэкспорт этих имён в `sklc/__init__.py`, либо обновить тесты (предпочтительно обновить тесты на новые пути).

### S2. MEDIUM — `validate_install` делает три независимые проверки
**Файл:** `install.py` (строки ~317-350).
Проверки: (а) наличие сгенерированных файлов + бит исполняемости; (б) синтаксис workflow через `specify workflow run`; (в) видимость агентов через `opencode agent list`.
**Исправление:** разбить на три функции `check_files`, `check_workflow_syntax`, `check_agents_visible` с отдельными сообщениями об ошибках; `verify_install()` вызывает все три и собирает ошибки (не останавливаться на первой — пользователь увидит все проблемы сразу).
**Тесты:** существующие покрывают happy path; добавить `test_verify_collects_all_errors` (мок: сломаны 2 из 3 проверок → в ошибке обе причины).

### S3. MEDIUM — дублирование логики в шаблоне workflow (DRY)
**Файл:** `templates/adr-pipeline.yml.tpl`.
Дубли:
- regex переписывания заголовка `^#\s*ADR(?:\s*-\s*\d+)?\s*:\s*(.+)$` дважды (save-adr ~строка 109 и sync-adr ~строка 204);
- логика slug (чтение, санитизация, обрезка) реализована только в save-adr, но связанный код sync-adr частично её повторяет;
- сниппет `last=$(ls -1 .../review-*.md | sort -V | tail -1)` дважды (verdict и pass-check).
**Исправление:** вынести Python-логику save/sync ADR в отдельный скрипт `templates/save_adr.py` (устанавливается рядом с run-agent.sh, вызывается из шагов `python3 <scripts>/save_adr.py <task_dir> <adr_dir> <run_agent> [--sync]`). В одном месте: read_slug, sanitize_slug, find_next_number, rewrite_heading. Это же упрощает тестирование (unit-тесты на Python, а не рендер-проверки) и закрывает B6.
**Тесты:** unit-тесты `tests/test_save_adr.py` (sanitize_slug: kebab-case, нелатинский slug, слово >60, дедупликация номера, rewrite_heading). Рендер-тесты workflow обновить на вызов скрипта.

### S4. LOW — `run_install` смешивает preflight-проверки с оркестрацией
**Файл:** `install.py` (строки ~437-469).
**Исправление:** вынести «python3 найден», «opencode найден» в `check_prerequisites()` (в `deps.py`), оставив `run_install` как чистую композицию шагов.
**Тесты:** `test_missing_opencode_fails_with_message` продолжает работать.

### S5. LOW — `load_config` грузит, мутирует и применяет дефолты одновременно
**Файл:** `install.py` (строки ~205-216).
**Исправление:** `load_config` → чистое чтение YAML; `apply_defaults(raw) -> cfg` — отдельная чистая функция; `validate_config(apply_defaults(load_config(path)))`.
**Тесты:** unit-тесты `apply_defaults` (пустой конфиг, отсутствующие секции, переопределение reasoning).

### S6. LOW — двойная реализация извлечения session id в `run-agent.sh`
**Файл:** `templates/run-agent.sh.tpl` (строки ~91-114).
`extract_session_id` (sessionID) + inline sed fallback (sessionId) — два паттерна.
**Исправление:** одна функция с единым regex `sessionId` (без учёта регистра): `sed -n 's/.*"session[iI][dD]":"\([^"]*\)".*/\1/p' | head -1`.
**Тесты:** ручная проверка; рендер-тест на одно вхождение `session[iI][dD]`.

---

## Часть 3. Дополнительные тесты (общие)

- `test_malformed_config_reports_error_not_traceback` (B2).
- `test_uninstall_removes_files_keeps_config` + `test_uninstall_prompts_declined_on_eof` (B12).
- `test_flag_conflicts_rejected` (B9).
- `test_verify_collects_all_errors` (S2).
- `tests/test_save_adr.py` — unit-тесты санитизации slug (S3, B6).
- `tests/test_config_defaults.py` — `apply_defaults` (S5).
- Рендер-тесты: `sync-adr` содержит `set -e` (B1) и `timeout` (B5); проверка одобрения после `adr-loop` (B3); валидация task_id (B14); guard `--task` (B7).
- Обновить `test_install.py`: импорты на новые пути модулей (S1) и моки (`install.run` → `sklc.deps.run` и т.п.).

## Часть 4. Порядок выполнения и критерии приёмки

1. Сначала баги B1–B14 (правки в `install.py` и шаблонах) + их тесты; прогон полного сьюта.
2. Затем рефакторинг S1 (механический перенос в пакет `sklc/`) с обновлением тестов; прогон.
3. S2–S6 поверх новой структуры.
4. Прогнать `python3 -m unittest tests.test_install` + новые тесты; убедиться, что все зелёные.
5. Ручная проверка: `python3 install.py --home /tmp/sklc-test` в чистом каталоге, проверка генерации всех файлов и инструкций; `python3 install.py --uninstall --home /tmp/sklc-test --yes`.
6. Не менять поведение публичного CLI (флаги, exit-коды 0/1, тексты ключевых ошибок, на которые завязаны тесты).

## Замечания, требующие verify (не менять без проверки)

- Таймаут shell-шагов по умолчанию в specify-cli 0.16 — влияет на B5.
- Доступность `steps.<step>.output.*` после do-while на установленной версии specify (fix PR #2662 вошёл до 0.16.0 — убедиться, что установленная версия его содержит) — влияет на B3 и корректность review-loop.
- Формат вывода `opencode agent list` для regex в `check_agents_visible` (B8/S2).
