# REVIEW_2: повторная проверка SRP + баги (после round 1)

Дата: 14 Aug 2026. Состояние: 56 тестов зелёные, `ruff` clean, `mypy --strict` clean.
Реальный прогон `python3 install.py --home /tmp/...` прошёл против specify-cli 0.16.3.

## Часть 0. Статус плана round 1 (FIX_PLAN.md)

| Пункт | Статус |
|---|---|
| B1 sync-adr `set -euo pipefail` + вынос в save_adr.py | ✔ |
| B2 обработка исключений в `main()` (yaml/OSError/KeyError) | ✔ |
| B3 gate одобрения после `adr-loop` (`adr-unapproved`/`adr-approval-gate`) | ✔ — семантика проверена по исходникам spec-kit: `choice in ("reject","abort")` + `on_reject: abort` → aborted; валидация gate принимает option "abort". Работает как задумано |
| B4 поиск specify в ~/.local/bin после установки | ✔ (плюс warning) |
| B5 `timeout` у sync-adr | ✔ |
| B6 slug-санитизация (ASCII-check, обрезка слова >60) | ✔ (unit-тесты) |
| B7 guard `--task` без значения | ✔ |
| B8 проверка синтаксиса: регистронезависимо, stdout+stderr | ✔ |
| B9 конфликты флагов | ✔ |
| B10–B14 (сообщения, REPO_ROOT, uninstall, ps-guard, валидация task_id) | ✔ |
| B15 pypi.org | пропущен по договорённости |
| S1 пакет `spec_utils/` + тонкий `install.py` | ✔ |
| S2 `verify` разбит на 3 проверки + агрегатор | ✔ (см. N1 — исключение ломает агрегацию) |
| S3 вынос save/sync в `save_adr.py` | ✔ (сниппет verdict остался ×4, см. R1) |
| S4 `check_prerequisites()` | ✔ |
| S5 `load_config` / `apply_defaults` разделены | ✔ |
| S6 единый regex `session[iI][dD]` | ✔ |

Aliasing условий циклов (spec-kit PR #2662) — установленная 0.16.3 содержит фикс, действий не требуется.

---

## Часть 1. Новые баги (round 2)

### N1. MEDIUM — `verify.check_workflow_syntax` роняет `FileNotFoundError` и ломает агрегацию ошибок
**Файл:** `spec_utils/verify.py:25-42`.
**Проблема:** шаг вызывает голый `["specify", ...]` через `deps.run`. Если specify не на PATH (сценарий, который сам `ensure_specify` допускает: «installed at ... but not on PATH» → warning → установка продолжается), `subprocess.run` бросает `FileNotFoundError`. Проверено: `check_workflow_syntax` → `FileNotFoundError [Errno 2] 'specify'`. В `main()` оно ловится общим `except OSError` и пользователь видит «error: [Errno 2] No such file or directory: 'specify'» — непонятно и противоречит warning'у выше. Внутри `verify_install` исключение вылетает ДО `check_agents_visible`, т.е. нарушает контракт «собрать все ошибки».
**Исправление:** в `check_workflow_syntax` сначала `path = deps.find_in_path("specify")`; если нет — вернуть `[f"'specify' not found on PATH (installed at {binary}? add it to PATH and rerun)"]` как обычную ошибку (путь можно взять из `deps.latest_specify_version()`), не бросая исключения. Использовать найденный путь в `deps.run`.
**Тесты:** `test_verify_workflow_syntax_specify_off_path` — мок `find_in_path("specify") -> None`, проверка, что возвращается ошибка-строка, а не исключение; и что `verify_install` собирает её вместе с остальными.

### N2. MEDIUM — коллизия slug между РАЗНЫМИ задачами: чужой ADR переиспользуется и затем перезаписывается
**Файл:** `templates/save_adr.py`, `cmd_save` (строки ~131-149).
**Проблема (подтверждено прогоном):** дедупликация `existing = sorted(adr_dir.glob(f"ADR-*-{slug}.md"))` не различает «повторный запуск той же задачи» и «другая задача с тем же slug». Демо: задача t2 со slug «prod-validation-splits» — `cmd_save` печатает «adr already saved», НЕ пишет свой ADR в `architecture/`, а `adr-saved.txt` указывает на файл задачи t1. При последующем `sync` (девиация в t2) файл t1 будет перезаписан контентом t2 — молчаливая потеря чужого ADR.
**Исправление:** в `cmd_save` сначала проверять СОБСТВЕННЫЙ `adr-saved.txt` задачи: если он есть и целевой файл существует — повторный запуск (reuse). Если собственной записи нет, а glob нашёл совпадение — это коллизия: выдать понятную ошибку (предложить сменить slug или удалить чужой файл), НЕ переиспользуя чужой файл. (Дубликаты при полном сбросе .workflow — приемлемая цена.)
**Тесты:** `test_same_slug_different_task_is_collision_not_reuse` — две задачи с одинаковым slug → вторая падает с ошибкой коллизии (или получает новый номер — по решению исполнителя, но НИКОГДА не молчаливый reuse); `test_rerun_same_task_reuses_own_file`.

### N3. LOW — `--update` не печатает новые опции: diff сравнивается с конфигом ПОСЛЕ дефолтов
**Файл:** `spec_utils/cli.py:56-60`, `spec_utils/config.py:121-127`.
**Проблема (подтверждено прогоном):** `cfg = apply_defaults(load_config(...))` заполняет ВСЕ ключи дефолтами, поэтому `collect_keys(example) - collect_keys(cfg)` пуст даже когда в config.yml пользователя отсутствует свежая опция (например `workflow.max_srp_iterations`). Фича «--update prints newly available config options» фактически мертва. (Проблема унаследована из монолита, но теперь её пора закрыть.)
**Исправление:** сравнивать с СЫРЫМ конфигом: `raw = config.load_config(paths["config"])`, затем `cfg = apply_defaults(raw)`; `print_diff_new_options(paths["config"], raw)`.
**Тесты:** `test_update_reports_new_options` — записать config.yml без `max_srp_iterations`, `--update` → в stdout «new options available» и `workflow.max_srp_iterations`.

### N4. LOW — `save_adr._ask_planner_for_slug`: `shell=True` без кавычек вокруг пути run-agent.sh
**Файл:** `templates/save_adr.py:94-106`.
**Проблема:** `cmd = run_agent + " planner " + shlex.quote(prompt) + ...` — если в `$HOME` пробел (путь до run-agent.sh с пробелами), команда ломается.
**Исправление:** `subprocess.run([run_agent, "planner", prompt, "--task", task_id], check=True)` (list-форма, без shell).
**Тесты:** не критично; unit-тест `_ask_planner_for_slug` с моком `subprocess.run`, путь с пробелом.

### N5. LOW — асимметрия циклов: в `review-loop` шаг `fix` выполняется безусловно, включая итерацию с PASS
**Файл:** `templates/adr-pipeline.yml.tpl` (review-loop, строки ~175-209).
**Проблема:** порядок review → fix → verdict: когда review выдал PASS, fix всё равно запускает executor-сессию (no-op: «fix all findings» при отсутствии findings) — лишний LLM-вызов на каждый прогон. В новом `srp-loop` fix условен (`srp-fix-branch` после verdict). 
**Исправление (опционально):** привести review-loop к схеме srp-loop: review → verdict → `if steps.verdict.output.exit_code != 0` → fix.
**Тесты:** рендер-тест порядка внутри review-loop; существующие тесты порядок внутри цикла не проверяют, риск низкий.

---

## Часть 2. SRP — остаточные замечания (round 2)

Общий вердикт: целевая структура достигнута — 6 модулей с одной ответственностью, тонкий entry point, верификация разбита, логика ADR вынесена в отдельный скрипт с unit-тестами. Замечания ниже — полировка, не рефакторинг.

- **R1 (DRY, LOW).** Сниппет `last=$(ls -1 ... | sort -V | tail -1) && head -1 "$last" | grep -q '^...PASS'` повторён 4 раза (srp-verdict, verdict, srp-pass-check, pass-check). Предложение: маленький helper-скрипт `check-review.sh <dir> <glob> <pattern>` (или команда `check` в save_adr.py) и вызов из 4 шагов. Снизит расхождение логики и размер шаблона.
- **R2 (LOW).** `actions.py` дёргает приватный `deps._pip_works`. Либо переименовать в публичный `pip_works`, либо реэкспортировать. Механика.
- **R3 (LOW, по желанию).** `cli.main()` различает `yaml.YAMLError` через `isinstance` на `Any`-модуле с guard «yaml может быть None». Работает и задокументировано, но читается тяжело. Альтернатива: ловить `yaml.YAMLError` в `config.load_config` и поднимать `InstallError` — тогда `main()` останется плоским.
- **R4 (инфо).** `deps.py` (~230 строк) — самый крупный модуль, но одна зона ответственности (bootstrap окружения); дробление не требуется.

## Часть 3. Что НЕ является проблемой (проверено в этом раунде)

- `adr-approval-gate` с `options: [approve, abort]` и `on_reject: abort` — валидно по GateStep (spec-kit): «abort» входит в reject_choices; выбор abort → `output.aborted` → halt. Оставляем.
- Условия do-while читают актуальные output'ы итераций — фикс PR #2662 есть в 0.16.3 (MIN_SPECIFY_VERSION=0.16 покрывает).
- `save_adr.py` вызывается как `python3 <path>` — exec-бит не нужен (копируется без chmod — корректно).
- `human_gates: false` + `adr_verdict` default "approve" — gate авто-аппрувится, `adr-unapproved` не достигается. ОК.
- `validate-task-id` и guard в run-agent.sh совпадают по regex. ОК.

## Часть 4. Порядок работ для исполнителя

1. N1 (verify.py: resolve specify + ошибка-строка) + тест.
2. N2 (save_adr.py: коллизия slug) + 2 теста.
3. N3 (cli.py/config.py: --update по сырому конфигу) + тест.
4. N4 (save_adr.py: list-форма subprocess) + тест.
5. N5 и R1–R3 — опциональная полировка, отдельным коммитом.
6. Прогон: `python3 -m unittest discover -s tests`, `.venv/bin/ruff check .`, `.venv/bin/mypy`, ручной `install.py --home /tmp/x` и `--update`.
