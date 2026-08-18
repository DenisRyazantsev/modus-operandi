---
slug: ux-ui-improvements
status: accepted
date: 2026-08-18
---

# ADR-0011: UX/UI-улучшения: живые статус-строки, GUI-редактор, упрощение task-pipeline

## Context

Задача `ux-ui-improvements-20260818-0754` собрала семь UX/UI-жалоб пользователя (согласованы в трёх
раундах мотивации, см. `study.md` rev. 3 и `proposal.md`):

1. На motivation-гейте обрезается текст study.md — движок specify 0.16.3 жёстко режет `show_file`
   на 200 строк (`GateStep.MAX_SHOW_FILE_LINES`), а `message` гейта безлимитен и вычисляется через
   шаблоны `{{ ... }}` (`expressions.py`: dot-пути `steps.<id>.output.stdout`; stdout shell-шага
   сохраняется в `step_results[<id>].output.stdout`).
2. feedback.md открывается в nano (в окружении пользователя `EDITOR=/usr/bin/nano`) — нужен
   предустановленный графический редактор в отдельном окне. Целевые платформы: Fedora Workstation
   (дефолтный редактор — GNOME Text Editor, на современных Fedora поставляется как Flatpak
   `org.gnome.TextEditor`; `--wait`-флага нет) и macOS (TextEdit, всегда предустановлен;
   `open -a TextEdit -W` блокирует до закрытия приложения).
3. Гейт согласования proposal дублирует согласование мотивации — его нужно убрать (только гейт;
   research и proposal.md остаются).
4. Логи засоряют размышления модели (`text`-события, обрезаемые до 100 символов). Вместо них —
   живые статус-строки с накопительными токенами. Каждое `step_finish`-событие агент-лога opencode
   уже несёт `part.tokens = {input, output, reasoning, cache: {read, write}}` и `part.cost`.
5. Таблица латенси без процентов и в `HH:MM:SS` — нужны проценты от общего wall-time и формат `Xm`.
6. Не видно прогресса по шагам — нужен индикатор N/M. `state.json` даёт `current_step_index`
   (0-базированный, по верхнеуровневым шагам); общее число шагов — из установленного workflow-файла
   (верхнеуровневый `steps:`; adr-pipeline = 15, task-pipeline = 17, review-pipeline = 5).
7. Лимит раундов уточнения мотивации должен исчезнуть; движок при невалидном `max_iterations`
   ставит фолбэк 10, «бесконечности» нет. Пользователь выбрал `max_iterations: 100`.

Проверено локально по установленному specify-cli 0.16.3 и реальным `.jsonl`-логам opencode.

## Decision

1. **Полный текст study.md на гейте.** Новый скрипт `pipeline_scripts/show-file.sh <state_dir>
   <file>`: печатает файл в stdout, предварительно удаляя управляющие символы (кроме `\t` и `\n`;
   защита от ANSI-инъекции текста модели; скрипт резолвит файл относительно `state_dir`-аргумента,
   регистрируется в `paths.py`/`render.py`/`verify.py` как остальные скрипты шагов). В
   `task-pipeline.yml` первым шагом тела `motivation-loop` добавляется `study-display` (shell):
   `show-file.sh "{{ inputs.state_dir }}" "{{ inputs.state_dir }}/tasks/current/study.md"`. У
   `motivation-gate` удаляется `show_file`, добавляется
   `message: >-` с текстом «The motivation study is ready — clear, or clarify?» и
   `{{ steps.study-display.output.stdout }}`. (Движок алиасирует результат шага внутри итерации
   цикла под базовый id, поэтому на каждом раунде clarify выводится актуальный study.md.)

2. **GUI-редактор для feedback-гейтов.** В `editor.py`/`feedback_editor.py` цепочка для
   feedback-гейтов заменяется на платформенную:
   - macOS (`sys.platform == "darwin"`): `open -a TextEdit -W <file>` — блокирующий запуск;
     после закрытия обёртка, как сейчас, отвечает гейту `continue`;
   - Linux: неблокирующий запуск в отдельном окне по цепочке `flatpak run org.gnome.TextEditor
     <file>` (если `flatpak` есть в PATH и приложение установлено — проверка `flatpak info
     org.gnome.TextEditor`), затем `gnome-text-editor <file>` (если в PATH), затем `gio open
     <file>`/`xdg-open <file>`. Обёртка в этом случае **не** отвечает гейту сама — гейт остаётся
     интерактивным (пользователь закрывает окно и жмёт `continue`); editor-функция возвращает
     признак `waited`/`detached`, автоответ пишется только при `waited`;
   - фолбэк без GUI (ничего не нашлось / нет TTY): терминальная цепочка `$VISUAL → $EDITOR → nano
     → vi` как сейчас, гейт интерактивный.
   `spec-run edit` продолжает использовать терминальную цепочку (`$VISUAL → $EDITOR → nano → vi`) —
   для него это не меняется.

3. **Убрать гейт proposal.** Из `task-pipeline.yml` удаляются: вход `proposal_verdict`, шаги
   `proposal-loop` (целиком: `proposal-gate`, `proposal-revise-branch`, `proposal-revise`,
   `proposal-feedback-clear`) и `proposal-unapproved` (с `proposal-approval-gate`); промпт
   `prompts/task/proposal-revise.md` удаляется (становится неиспользуемым). `research` и
   `write-adr` идут подряд без гейта. Из `config_invocation.py` убирается передача
   `-i proposal_verdict=` для task-pipeline; из `spec_utils/config.py` (дефолты и список валидных
   ключей) и `config.example.yml` удаляются `max_proposal_iterations`; из `_LOOP_ITERATION_KEYS`
   (`spec_utils/render.py`) удаляется пара `"proposal-loop": "max_proposal_iterations"`. Промпт
   `prompts/task/research.md`: убрать фразу «This document is shown to the human for approval».

4. **Живые статус-строки токенов.** В `render_log_event` (`_run_pipeline_common.py`) больше не
   печатаются `text`/`reasoning`-события (и сырые не-JSON строки не печатаются); `tool_use` не
   печатается как и раньше. Новый модуль `live_lines.py` (только stdlib, ANSI) в обёртке:
   - строка формата `[hh:mm:ss] [<role>] [<step>] cache <X> · reasoning <Y> · input <Z> · output
     <W> · price $<P>` — накопительные суммы по роли (и по форку при параллельных ревью-форках),
     пробельные разделители тысяч (`fmt_thousands`), X = `cache.read` (не write), P = сумма
     `part.cost` (2 знака после запятой); `<step>` = `current_step_id` из `state.json` (обёртка
     уже читает его каждый тик; при отсутствии — без шага);
   - одна живая строка на активный процесс (роль/форк); обновление — `\r` + перезапись, при
     необходимости `\x1b[K`; несколько одновременных строк — блок с `\x1b[<n>A`;
   - когда шаг workflow завершается (обёртка печатает маркер `--- step ... (completed)`), живая
     строка этого процесса **фиксируется** — печатается с `\n` и остаётся в терминале как
     история; для следующего шага той же роли открывается новая живая строка (счётчики
     продолжаются);
   - не-TTY/перенаправленный stdout: без ANSI, одна обычная строка на каждое `step_finish`;
   - живые строки подчиняются существующей политике `BufferedEmitter` (во время открытого меню
     гейта буферизуются, после закрытия флашатся).

5. **Таблица латенси.** `latency_table.py`: длительности печатаются новым форматтером
   `fmt_minutes` — целые минуты с суффиксом `m` (обычное округление; ненулевое значение меньше
   30 секунд — `1m`); добавляется колонка процентов — доля длительности каждого стейджа от общего
   wall-time (сумма длительностей всех стейджей), формат `NN.N%` (один знак); для fan-out детали —
   процент каждого чека и `fan-out wall` от того же общего wall-time. `fmt_duration` не меняется:
   `wall time` в блоке `=== run statistics ===` остаётся `HH:MM:SS`.

6. **Прогресс N/M.** Обёртка при старте читает установленный workflow-файл (путь из argv[0],
   который уже передаётся в `build_specify_invocation`) и считает число верхнеуровневых шагов
   (`workflow.steps`) через PyYAML; маркер шага печатается как
   `--- step <id> (completed) [<N>/<M>]`, где N = `current_step_index + 1`; живые строки
   показывают шаг как `[<step> <N>/<M>]`. Нет файла/парса — прогресс опускается без падений.

7. **Безлимитная мотивация.** `motivation-loop` получает литерал `max_iterations: 100`; пара
   `"motivation-loop": "max_motivation_iterations"` удаляется из `_LOOP_ITERATION_KEYS` (чтобы
   `_patch_workflow_numbers` не перезаписал литерал), а `max_motivation_iterations` — из дефолтов
   и валидации `spec_utils/config.py` и из `config.example.yml`.

8. **Тесты и документация.** Обновить: `tests/install/test_task_workflow_structure.py`
   (proposal-шагов нет; `study-display` есть; motivation-gate без `show_file`, с message-шаблоном;
   `motivation-loop.max_iterations == 100` и не зависит от конфига), тесты
   `build_specify_invocation` (нет `proposal_verdict`), `tests/test_config_defaults.py`. Добавить
   юнит-тесты: `show-file.sh` (управляющие символы вычищаются), платформенное разрешение
   редактора и `waited`/`detached`, `fmt_minutes`, проценты латенси (обычные + fan-out), живые
   строки (формат, фиксация, не-TTY), подавление `text`-событий, подсчёт шагов workflow и
   N/M-маркер. Обновить README (новый UX, GUI-редактор, отсутствие proposal-гейта, лимит 100).

## Alternatives

- **Оставить терминальный редактор (как есть).** Отклонено: пользователь хочет GUI-окно;
  `EDITOR=nano` в окружении всё равно перекрывает переменные.
- **Детект закрытия окна на Fedora (поллинг процесса/окна).** Отклонено: хрупко (Flatpak-песочница,
  один процесс на несколько окон); пользователь явно выбрал ручной режим.
- **Сводка вместо полного текста на гейте.** Отклонено: нужен полный текст; message-обход
  безлимитен и проверен по исходникам движка.
- **Библиотека rich/tqdm для живых строк.** Отклонено: лишняя зависимость; достаточно `\r`,
  `\x1b[K`, `\x1b[<n>A`.
- **Убрать `max_iterations` совсем.** Отклонено: движок молча ставит фолбэк 10 — цикл стал бы
  короче, а не длиннее.
- **Проценты без fan-out детали.** Отклонено: фидбек просил проценты и для fan-out детали.

## Consequences

- Плюс: терминал показывает компактный статус (прогресс N/M, накопительные токены и стоимость),
  размышления не засоряют экран, история шагов остаётся; мотивация видна целиком.
- Плюс: одна остановка согласования вместо двух; мотивация уточняется без лимита (до `clear`).
- Плюс: родной GUI-редактор на обеих платформах без новых зависимостей.
- Минус: ANSI-вывод усложняет обёртку (нужна аккуратная деградация для не-TTY); на Fedora
  feedback-гейт полуручной (закрыл окно → сам жмёшь `continue`).
- Минус: proposal.md больше никто не читает до ADR; при плохом ресерче проблемы всплывут на
  реализации/ревью.
- Минус: `max_iterations: 100` — технически не бесконечность (практически недостижимо).

## Acceptance Criteria

1. `show-file.sh` печатает содержимое файла в stdout без управляющих символов (кроме `\t`/`\n`);
   зарегистрирован в `paths.py`/`render.py`/`verify.py` и копируется установщиком.
2. В `task-pipeline.yml`: `study-display` — первый шаг `motivation-loop`; `motivation-gate` без
   `show_file`, с `message`, содержащим `{{ steps.study-display.output.stdout }}`; `proposal-loop`,
   `proposal-unapproved`, `proposal-revise`, вход `proposal_verdict` отсутствуют; `research` идёт
   сразу перед `write-adr`; `motivation-loop.max_iterations == 100` после установки при любом
   конфиге.
3. `prompts/task/proposal-revise.md` удалён; `prompts/task/research.md` не содержит «shown to the
   human for approval».
4. Конфиг: `max_motivation_iterations` и `max_proposal_iterations` отсутствуют в дефолтах,
   валидации и `config.example.yml`; `_LOOP_ITERATION_KEYS` не содержит motivation/proposal-циклов;
   `config_invocation.py` не передаёт `-i proposal_verdict=`.
5. На macOS feedback-гейт открывает TextEdit (`open -a TextEdit -W`), после закрытия обёртка
   отвечает `continue`; на Linux запускает Flatpak/RPM GNOME Text Editor либо `gio open`/`xdg-open`
   без автоответа (гейт интерактивный); при отсутствии GUI — терминальный фолбэк
   `$VISUAL → $EDITOR → nano → vi`. `spec-run edit` по-прежнему использует терминальную цепочку.
6. `render_log_event` не печатает `text`/`reasoning`-события; живая строка формата
   `[hh:mm:ss] [<role>] [<step>] cache X · reasoning Y · input Z · output W · price $P` с
   накопительными суммами из `step_finish` (cache = cache.read, тысячи через пробел), по строке на
   активный процесс; при маркере завершения шага строка фиксируется (`\n`) и для следующего шага
   открывается новая; в не-TTY ANSI не используется.
7. Таблица латенси: длительности в `Xm` (целые минуты), колонка процентов от общего wall-time
   (один знак после запятой), проценты в fan-out детали; `wall time` в `=== run statistics ===`
   остаётся `HH:MM:SS`.
8. Маркеры шагов показывают `[N/M]` (N = `current_step_index + 1`, M = число верхнеуровневых
   шагов установленного workflow-файла); живые строки показывают шаг как `[<step> N/M]`;
   отсутствие workflow-файла деградирует без падения.
9. `python3 -m pytest tests -q`, `ruff check .` и `mypy spec_utils pipeline_scripts` проходят;
   добавлены тесты по п. 8 Decision; тесты `test_task_workflow_structure.py`,
   `test_build_specify_invocation.py`, `test_config_defaults.py` обновлены.
10. README документирует новые UX-изменения (живые строки, прогресс, GUI-редактор, отсутствие
    proposal-гейта, мотивация без лимита).
