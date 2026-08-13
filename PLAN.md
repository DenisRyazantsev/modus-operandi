# План реализации: spec-kit-llm-client (v2)

План проверен на живых бинарях: opencode 1.18.18, specify-cli 0.16.2 (GitHub Spec Kit, PyPI).
Ключевые факты, подтверждённые экспериментально (не на память):
- `opencode run --session <id> --agent <role> --format json` существует; JSON-поток содержит поле `sessionID` (`ses_...`).
- `specify workflow` поддерживает `run/resume/status/add/list`; `run <локальный файл>` работает вне проекта без `specify init` (state → `.specify/workflows/runs/<id>/`).
- Шаги `shell`, `gate`, `do-while` (+ `max_iterations`, `condition`, `continue_on_error`) работают как задумано; выражения `{{ steps.<id>.output.exit_code }}` доступны.
- `gate` + `verdict_input` + `enum: ["", approve, reject]` + `default: "approve"` авто-проходят гейт без TTY.
- При исчерпании `max_iterations` без PASS run завершается успешно — нужен отдельный fail-шаг (`final-verdict`).
- Пермишн-инструменты opencode 1.18.18 (канонический список): `bash, read, edit, glob, grep, webfetch, task, todowrite, websearch, lsp, skill`.
- Синтакс-проверка воркфлоу: `specify workflow run <file> --json` без обязательного входа → exit 1, stderr `Error: Required input '<name>' not provided.` (схема распарсилась). ВАЖНО: при этом в cwd создаётся `.specify/workflows/` — чистить после проверки.

## 1. Контекст и цель

Продукт — установщик на Python, который на любой машине с установленным OpenCode разворачивает глобальный воркфлоу «planner → executor» поверх движка Spec Kit. Пользователь запускает `install.py`, затем редактирует один конфиг (`config.yml`), после чего в любом проекте команда `specify workflow run ~/.config/spec-kit-llm-client/adr-pipeline.yml -i feature="..."` гоняет полный цикл: ADR → вопросы экзекьютора → ответы планера → имплементация → ревью → фиксы до схождения. Ключевое требование: сессии агентов держатся тёплыми между шагами через `opencode run --session` — экзекьютор не перечитывает проект на каждом шаге.

Проблема: повторяющийся ручной обмен файлами между сильной моделью (планирование/ревью) и дешёвой (имплементация), при котором переключение между клиентами теряет контекст и заставляет экзекьютора заново читать весь проект.

## 2. Границы скоупа

Входит: install.py (Python 3, только stdlib + PyYAML), шаблоны агентов/воркфлоу/клея, config.example.yml, тесты-smoke, README.
**Не входит**: поддержка Cursor; per-project установка (кроме опционального `--register`); MCP-конфиги; PyPI-пакетирование; CI-пайплайны; телеметрия; `serve-start`; авто-замер размера сессии; любые изменения в самом OpenCode или Spec Kit.

## 3. Репозиторий (итоговая структура)

```
spec-kit-llm-client/
├── install.py                  # точка входа (python3 install.py)
├── config.example.yml          # эталон конфига с комментариями
├── templates/
│   ├── planner.md.tpl          # агент-планер (сильная модель)
│   ├── executor.md.tpl         # агент-экзекьютор (дешёвая модель)
│   ├── adr-pipeline.yml.tpl    # воркфлоу для движка spec-kit
│   ├── run-agent.sh.tpl        # клей с резюмом сессий
│   └── gitignore.snippet       # .workflow/, .specify/workflows/
├── tests/
│   └── test_install.py         # smoke-тесты установщика
└── README.md
```

## 4. Что куда ставится (глобально)

```
~/.config/opencode/
├── agent/planner.md            # сгенерировано из шаблона + конфига
├── agent/executor.md
└── scripts/run-agent.sh        # сгенерировано, chmod +x

~/.config/spec-kit-llm-client/
├── config.yml                  # конфиг пользователя (не перезаписывается)
└── adr-pipeline.yml            # воркфлоу (генерируется; канонический источник запуска)
```

Опционально (`install.py --register`, запускается из каталога проекта):
```
~/.specify/workflow-catalogs.yml   # юзер-каталог: URL локального каталога (идемпотентно)
<проект>/.specify/workflows/adr-pipeline/   # результат specify workflow add adr-pipeline
```

Per-project рантайм-состояние (создаётся самим воркфлоу в момент работы, в репозиторий проекта не коммитится):
`.workflow/` (артефакты задачи) и `.specify/workflows/runs/` (состояние движка).

## 5. Формат config.yml (эталон)

```yaml
models:
  planner:
    provider: anthropic            # id провайдера opencode
    model: claude-opus-4-5
  executor:
    provider: <провайдер>
    model: <дешёвая модель>
workflow:
  state_dir: .workflow            # каталог артефактов в проекте
  max_fix_iterations: 5           # потолок цикла ревью-фиксы
  human_gates: true               # false = гейты авто-аппрувятся через verdict_input
  use_serve: false                # true = run-agent.sh подставляет --attach http://localhost:4096
```

Требования к парсеру конфига: stdlib `yaml` не входит в Python 3 — использовать PyYAML; при отсутствии — `pip install --user pyyaml` внутри шага зависимостей. Валидация: обязательные ключи (`models.planner.model`, `models.executor.model`), при пропуске — понятная ошибка с указанием ключа. Комментарии в config.example.yml — на английском.

## 6. Контракт артефактов задачи (обязателен для агентов и клея)

Для задачи с id `<task-id>` в каталоге `<state_dir>/tasks/<task-id>/`:

| Файл | Пишет | Читает | Правило |
|---|---|---|---|
| `adr.md` | planner | executor, planner | создаётся на шаге 1 |
| `questions.md` | executor | planner | **всегда** создаётся; первая строка строго `QUESTIONS: NONE` или `QUESTIONS: PRESENT`, ниже — вопросы (если PRESENT) |
| `answers.md` | planner | executor | пишется **только** при `QUESTIONS: PRESENT`, ответы построчно в том же порядке |
| `review-N.md` (N=1,2..) | planner | executor, planner | **первая строка строго `VERDICT: PASS` или `VERDICT: FIX`**, ниже — замечания |

## 7. Требования к файлам-шаблонам

Все промпты агентов — на английском. Роли формулируют самодостаточные инструкции, не требующие AGENTS.md проекта.

### 7.1 planner.md.tpl
Фронтматтер:
```yaml
description: Planner and reviewer for the adr-pipeline workflow
mode: subagent
model: ${planner_provider}/${planner_model}
temperature: 0.3
permission: bash, read, edit, glob, grep, webfetch
```
Пермишн-список сверяется с живым CLI (`opencode agent create` — канонический формат), при расхождении — исправить в шаблоне. Роль: планировщик и ревьюер; шаг 1 — составить ADR по входному описанию в `adr.md` (формат: контекст, решение, альтернативы, последствия, критерии приёмки); отвечает на `questions.md` в `answers.md` (при `QUESTIONS: NONE` — ничего не писать); на ревью читает `git diff` и `adr.md`, пишет `review-N.md` с первой строкой `VERDICT: PASS|FIX` (следующий номер N после существующих); не пишет код.

### 7.2 executor.md.tpl
Фронтматтер:
```yaml
description: Executor for the adr-pipeline workflow
mode: subagent
model: ${executor_provider}/${executor_model}
temperature: 0.1
permission: bash, read, edit, glob, grep
```
Роль: читает `adr.md` (+`answers.md`, если есть); при неоднозначностях — пишет `questions.md` с первой строкой `QUESTIONS: PRESENT` и СТОП; если всё ясно — пишет `questions.md` с `QUESTIONS: NONE` (всегда!) и реализует по артефактам; на шаге фиксов читает только последний `review-N.md`; **не перечитывает проект, если он уже в контексте сессии**; перед завершением запускает тесты/линт проекта.

### 7.3 run-agent.sh.tpl
Интерфейс строго: `run-agent.sh <role> "<prompt>" [--task <task-id>] [--reset]`. Логика:
1. state-файл: `<state_dir>/sessions.json` (json: `{"planner": "...", "executor": "..."}`), `<state_dir>` из env `SKLC_STATE_DIR`, дефолт `.workflow` (относительно cwd).
2. Если сессии нет или `--reset`: `opencode run --agent <role> --auto --format json "<prompt>"`; выдрать первое поле `sessionID` из JSON-вывода (структура: поток событий, у сообщений есть `sessionID`); сохранить в sessions.json. Если id не извлечён — выйти с кодом 2 и сообщением. При расхождении структуры вывода — фоллбэк по нескольким известным полям (`sessionID`, `sessionId`, `id` в объектах-сообщениях).
3. Иначе: `opencode run --session <id> --agent <role> --auto "<prompt>"`.
4. В stdout печатать последней строкой `SESSION:<id>` — её использует установщик для верификации.
5. `--reset` — удалить запись роли из sessions.json; следующий запуск создаст новую сессию (ручной хендофф при перегрузе окна).
6. `use_serve: true` → добавить `--attach http://localhost:4096` к обоим вариантам вызова. Сервер (`opencode serve`) поднимает пользователь; `serve-start` НЕ в скоупе, README документирует сервер как пререквизит режима.
7. Флаг `--auto` обязателен (headless: воркфлоу-шаги без TTY, пермишн-промпты зависли бы). Дублируется фронтматтером `permission` в агентах как защита для TUI-запусков.
8. Скрипт — POSIX sh (bash), shellcheck-чистый. Аргументы-промпты передаются opencode как единый аргумент (корректное квотирование).

### 7.4 adr-pipeline.yml.tpl
Входы: `feature` (string, required), `task_id` (string, default: дата-время), плюс при `human_gates: false` — `adr_verdict` и `final_verdict` (`enum: ["", approve, reject]`, `default: "approve"`) для авто-прохода гейтов.
Шаги:
1. `write-adr` — shell: `run-agent.sh planner "Write an ADR for: {{ inputs.feature }} to .workflow/tasks/{{ inputs.task_id }}/adr.md" --task {{ inputs.task_id }}`
2. `approve-adr` — gate: «ADR ready — approve?», options approve/reject, `on_reject: abort`; при `human_gates: false` — `verdict_input: adr_verdict`
3. `executor-questions` — shell: `run-agent.sh executor "Read adr.md. If anything is ambiguous, write questions.md (first line QUESTIONS: PRESENT) and stop. Otherwise write questions.md (first line QUESTIONS: NONE)." --task {{ inputs.task_id }}`
4. `planner-answers` — shell: `run-agent.sh planner "Read questions.md. If QUESTIONS: PRESENT, answer each question line-by-line into answers.md. If QUESTIONS: NONE, write nothing." --task {{ inputs.task_id }}`
5. `implement` — shell: `run-agent.sh executor "Implement per adr.md and answers.md (if present). Run the project tests." --task {{ inputs.task_id }}`
6. `review-loop` — `do-while`, `max_iterations: {{ max_fix_iterations }}`, `condition: "{{ steps.verdict.output.exit_code != 0 }}"`, внутри:
   - `review` — shell: `run-agent.sh planner "Review the git diff against adr.md. Write review-N.md (next N) with the first line VERDICT: PASS or VERDICT: FIX." --task {{ inputs.task_id }}`
   - `fix` — shell: `run-agent.sh executor "Read the last review-N.md, fix all findings." --task {{ inputs.task_id }}`
   - `verdict` — shell (обязательно `continue_on_error: true`): `last=$(ls -1 .workflow/tasks/{{ inputs.task_id }}/review-*.md 2>/dev/null | sort -V | tail -1) && head -1 "$last" | grep -q '^VERDICT: PASS'` — проверяется ТОЛЬКО последний по sort -V файл, а не любой PASS; при FIX exit 1 → условие цикла истинно → следующая итерация; при PASS exit 0 → выход из цикла.
7. `final-verdict` — shell, БЕЗ `continue_on_error`: та же команда `last=$(ls -1 ... | sort -V | tail -1) && head -1 "$last" | grep -q '^VERDICT: PASS'`. Ненулевой exit (нет PASS в последнем review / нет review-файлов) валит run — жёсткий fail при исчерпании итераций. Дальше `specify workflow resume` после вмешательства человека.
8. `final-gate` — gate «Review is clean — close?», approve/reject; при `human_gates: false` — `verdict_input: final_verdict` (точка осознанного закрытия, но при авто-аппруве на неё не опираться — защита это шаг 7).

## 8. Требования к install.py

Запуск: `python3 install.py [--update] [--uninstall] [--register] [--home <dir>] [--yes]`.
- `--home` переопределяет базовый каталог (по умолчанию `~`), обязателен для тестов.
- `--register` — опциональная per-project регистрация: запускается из каталога проекта, дописывает URL локального каталога в `~/.specify/workflow-catalogs.yml` (идемпотентно, без поломки чужого YAML) и выполняет `specify workflow add adr-pipeline` (относительно cwd). Дальше в этом проекте воркфлоу доступен по ID: `specify workflow run adr-pipeline`. `--home` и `--register` несовместимы (ошибка).

Порядок шагов:
1. Проверка предпосылок: python3, opencode в PATH, сеть. Ошибки — exit 1 с командой-решением.
2. Зависимости: `uv tool install specify-cli` (fallback: `pipx install specify-cli`; если нет ни uv, ни pipx — `pip install --user`); PyYAML. После — проверка `specify --version`. Пиновать минимальную версию specify-cli (>= 0.16, диспатч opencode `-p` → `run` уже чинили).
3. Каталоги `~/.config/opencode/{agent,scripts}` и `~/.config/spec-kit-llm-client/` (mkdir -p).
4. Конфиг: нет config.yml → копия config.example.yml; есть → не трогать, обновить только example. Режим `--update` дополнительно печатает diff новых опций.
5. Генерация: шаблоны рендерятся подстановкой плейсхолдеров `${...}` из конфига (stdlib `string.Template`), результат в целевые пути; `chmod +x` для run-agent.sh.
6. Регистрация: НЕ выполняется автоматически (см. `--register`).
7. Валидация: (a) `opencode agent list` содержит planner и executor; (b) run-agent.sh исполнимый; (c) воркфлоу: файл существует, YAML парсится (PyYAML), и синтакс-проверка движком: `specify workflow run <abs path> --json` в отдельном temp-каталоге без `--input feature` → ожидается exit 1 и stderr `Required input 'feature' not provided.` (значит схема валидна); после проверки удалить созданный `<temp>/.specify/`.
8. Вывод: инструкция — отредактировать config.yml → в проекте `specify workflow run ~/.config/spec-kit-llm-client/adr-pipeline.yml -i feature="..."`; упомянуть `--register` для по-ID режима.

`--uninstall`: удалить созданные файлы, спросить (или `--yes`) про удаление specify-cli/PyYAML; снять юзер-каталог из `~/.specify/workflow-catalogs.yml` (если был добавлен `--register`).
Все операции идемпотентны; повторный запуск без флагов = безопасный апдейт шаблонов с сохранением конфига пользователя.

## 9. Тесты (tests/test_install.py)

Smoke-тесты на stdlib `unittest`, всё через `--home <tempdir>`:
1. установка на чистый temp-home создаёт все целевые файлы (включая `~/.config/spec-kit-llm-client/adr-pipeline.yml`);
2. повторный запуск не меняет пользовательский config.yml (изменить его → перезапуск → контент сохранён);
3. повторная регистрация `--register` не дублирует запись в workflow-catalogs.yml (мок `specify`/подмена PATH);
4. отсутствие opencode → exit 1 с сообщением (мок PATH);
5. рендер executor.md содержит модель из конфига и пермишн-список;
6. рендер воркфлоу: при `human_gates: false` гейты содержат `verdict_input`, при `true` — нет; есть шаг `final-verdict` без `continue_on_error`; verdict-шаг в цикле использует `sort -V` и `continue_on_error: true`.

## 10. Приёмка (исполнитель обязан выполнить)

- `python3 -m py_compile install.py` и `python3 -m unittest tests/test_install.py` — зелёные;
- `shellcheck run-agent.sh` (если shellcheck есть);
- ручной прогон `python3 install.py --home /tmp/sklc-test` и проверка структуры п.4;
- синтакс-проверка воркфлоу из п.8.7 (temp-каталог, `Required input` на stderr, `.specify` почищен);
- `python3 install.py --home /tmp/sklc-test --register` в temp-проекте: запись в workflow-catalogs.yml одна, повторный запуск не дублирует; `specify workflow run adr-pipeline -i feature="x"` в этом проекте стартует (упав на Required input — уже ОК для `--register`-проверки; при живом opencode — реальный прогон ниже);
- реальный прогон на мелкой задаче (если доступен opencode): `specify workflow run <abs path>`; проверка: в `opencode session list` две сессии на задачу (planner/executor), на ходах фиксов сессия executor продолжается тем же id; `specify workflow resume <run_id>` после обрыва продолжает без перечитывания;
- проверка контракта questions.md: executor всегда пишет файл, первая строка NONE/PRESENT.

## 11. Риски и указания

- CLI opencode меняется: поля JSON-вывода (`sessionID`) проверять на реальном выводе; при расхождении — извлекать id по нескольким известным полям с фоллбэком (п.7.3.2).
- Пермишн-синтаксис фронтматтера: канонический список инструментов сверен на 1.18.18 (`bash, read, edit, glob, grep, webfetch, task, todowrite, websearch, lsp, skill`) — при апгрейде opencode перепроверить через `opencode agent create`.
- specify-cli: пиновать минимальную версию (>= 0.16) в install.py; workflow-схема (do-while, verdict_input, continue_on_error) проверена на 0.16.2.
- Синтакс-проверка воркфлоу создаёт `.specify/workflows/` в cwd даже при фейле на входных — всегда гонять в temp-каталоге и чистить.
- Автокомпакция длинной сессии: фиксировать в README сценарий ручного `--reset executor` + хендофф-файл. Авто-замер размера сессии отложен: `opencode stats` не отдаёт JSON, парсить TUI-вывод хрупко. Knob (`handoff_threshold_tokens`) в конфиге НЕ вводить.
- `use_serve: true` требует поднятого пользователем сервера (`opencode serve`) — README описывает пререквизит; скрипт не стартует и не проверяет сервер.
- Глобальные файлы не должны требовать AGENTS.md проекта: промпты агентов самодостаточны, `permission` прописан в самих агентах.
- `--auto` в run-agent.sh обязателен (headless); его наличие и риски документировать в README.
- Порядок review-файлов — только `sort -V` (`review-10.md` после `review-2.md`); проверка вердикта — по последнему файлу, никогда по «любому PASS».
- Гейты с `verdict_input` + default approve — единственный способ не-TTY авто-прохода; при `human_gates: true` гейты интерактивны и run паузится (это ожидаемо, README описывает resume).
- Исчерпание `max_fix_iterations` без PASS = жёсткий fail через `final-verdict` (exit 1); состояние run позволяет `resume` после вмешательства человека.
- Все сообщения ошибок — на английском (CLI-конвенция), README — на английском, комментарии в конфиге-примере — на английском, промпты агентов — на английском.
