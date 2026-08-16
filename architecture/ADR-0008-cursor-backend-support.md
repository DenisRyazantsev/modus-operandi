---
slug: cursor-backend-support
status: accepted
date: 2026-08-16
---

# Поддержка Cursor как второго backend'а для planner → executor пайплайна

## Context

Проект стабильно работает на opencode: две тёплые сессии (planner на сильной LLM, executor на дешёвой) ведутся
через `opencode run --session <id> --agent <role> --auto --format json`, а роли задаются файлами
`~/.config/opencode/agent/{planner,executor}.md` (frontmatter с provider/model/reasoning + тело системного промпта).
Сессионный слой — `pipeline_scripts/run-agent.sh` — хранит session id в `<state_dir>/sessions-<task_id>.json` и резюмит
сессию между шагами, чтобы executor не перечитывал проект заново.

Нужно добавить тот же сценарий для Cursor: горячие 2 сессии (planner + executor), одна сильная LLM, одна дешёвая.
Изучение официальной документации Cursor CLI (`cursor.com/docs/cli`) и обсуждений показало:

* CLI называется `cursor-agent` (устанавливается как бинарник `agent` на PATH); есть non-interactive режим
  `-p/--print` с `--output-format json|text|stream-json`.
* Модель задаётся per-invocation флагом `--model <slug>` — то есть разница «planner vs executor» ложится на
  `--model`, а не на отдельные agent-файлы (в Cursor нет аналога `--agent`).
* Сессии возобновляются через `--resume <chatId>` (`--continue` = `--resume=-1`), а `agent create-chat` создаёт
  пустой чат и печатает его id — готовый способ «завести» тёплую сессию.
* Headless-автоодобрение достигается флагами `--force` (a.k.a. `--yolo`) + `--trust` (аналог `--auto` у opencode).
* **Критично:** у cursor-agent нет флага `--session-id`. Id сессии «чеканит» сам CLI и отдаёт его в поле
  `session_id` JSON-вывода (или через `agent create-chat`). Передача *придуманного* id в `--resume` **не** даёт
  ошибки — cursor молча открывает свежий чат, т.е. тихо теряется контекст (подтверждено в
  nexu-io/open-design#4790). Поэтому id надо всегда брать от самого Cursor, никогда не синтезировать.
* Отдельного флага для системного промпта или «reasoning effort» в CLI нет: роль можно задать только текстом в
  самом промпте, а high-effort-варианты модели кодируются самим slug'ом.

## Decision

Ввести выбор инструмента-исполнителя (backend) на уровне пайплайна и продублировать opencode-логику для Cursor
через тот же сессионный слой `run-agent.sh`. Структура моделей — **две модели на роли, ровно как в opencode**
(planner и executor настраиваются независимо). Конкретно:

1. **Конфиг: отдельные секции под каждый backend, две модели в каждой.** Вместо общей `models:` в `config.yml`
   заводятся две секции, а верхнеуровневый ключ `backend` выбирает активную (`opencode` по умолчанию):

   ```yaml
   backend: opencode        # активный backend; per-run override: spec-run --backend cursor

   opencode:                # прежняя секция models (переименована; legacy models: принимается как opencode)
     models:
       planner:
         provider: opencode-go
         model: deepseek-v4-pro
         reasoning: max
       executor:
         provider: opencode-go
         model: deepseek-v4-flash
         reasoning: max

   cursor:
     models:
       planner:
         model: <planner-slug>    # сильная модель (планирование/ревью)
       executor:
         model: <executor-slug>   # дешёвая модель (реализация)

   workflow: ...
   ```

   Валидация: `backend` ∈ {opencode, cursor}; для `cursor` обязательны оба `models.planner.model` и
   `models.executor.model` (симметрично opencode, где обязательны provider/model/reasoning). Легаси-верхнеуровневая
   `models:` при загрузке сворачивается в `opencode.models`, чтобы существующие конфиги не ломались. Для MVP, пока на
   бесплатном тарифе Cursor доступна одна модель Composer, в обеих строках указывается один и тот же slug — это
   значение конфига, а не ограничение структуры: логика всегда работает с двумя независимыми слотами.

2. **CLI-флаг `--backend`.** `spec-run --backend cursor adr "bla-bla"` (глобальный флаг перед подкомандой)
   переопределяет `backend` из конфига на один прогон. Обёртка `run_pipeline.py` вычисляет эффективный backend
   (CLI-флаг > конфиг > `opencode`) и экспортирует его в окружение шагов (`SKLC_BACKEND` + модели выбранного
   backend'а для ролей) — тем же механизмом, что уже используется для `SKLC_ATTACH_FLAG`/`SKLC_STATE_DIR`. Workflow
   при этом не меняется: шаги наследуют окружение, `run-agent.sh` читает `SKLC_BACKEND`.

3. **Диспетчеризация вызова (run-agent.sh).** `run-agent.sh` ветвится по `SKLC_BACKEND`:
   * opencode (без изменений): `opencode run --session <id>|--agent <role> --auto [--attach …] --format json "<prompt>"`.
   * cursor: `cursor-agent -p --output-format json --force --trust --workspace <cwd> --model <role-model>
     [--resume <chatId>] "<prompt>"`, где `<role-model>` — `cursor.models.<role>.model` (у каждой роли своя).
   Первым запуском, когда сохранённого chat id нет, сначала выполняется `agent create-chat`, затем промпт запускается
   уже с `--resume <id>`.

4. **Тёплые сессии.** Переиспользуется тот же файл `<state_dir>/sessions-<task_id>.json` и те же helpers
   `read_session`/`save_session` (ключ по роли), только в нём теперь хранится cursor chat id. Id всегда берётся от
   Cursor: из вывода `agent create-chat` (первично) или из поля `session_id` JSON-результата (запасной путь). Никогда
   не генерировать id самим. `--reset` удаляет сохранённый id — следующая роль снова минтит чат через
   `agent create-chat`.

5. **Роль (system prompt) — один раз на старте сессии.** Так как `--agent` и флага системного промпта у Cursor нет,
   тело роли (те же `PLANNER_BODY`/`EXECUTOR_BODY`, что сейчас пишутся в agent-файлы opencode) предваряет промпт
   **только первого сообщения** сессии (когда чат только что создан). На повторных `--resume`-вызовах отправляется
   голый промпт: сессия горячая, и LLM уже помнит свою роль — повторять её в каждом сообщении не нужно. Тела ролей
   записываются инсталлером в файлы (один источник истины), которые `run-agent.sh` читает и подставляет один раз.

6. **Одноразовый name-task.sh.** При cursor генерация слага идёт через
   `cursor-agent -p --output-format text --force --trust --model <cursor.models.executor.model> "<slug-prompt>"` —
   текстовый вывод содержит только финальный ответ, парсинг JSON-стрима не нужен.

7. **Очистка зависших процессов.** Логика kill stale-процесса в `run-agent.sh` (проверка `ps -o comm=`) проверяет имя
   процесса, соответствующее backend'у (`opencode` либо `cursor-agent`/`agent`).

8. **Инсталлер/проверка.** `check_prerequisites()` проверяет `cursor-agent` (или `agent`) на PATH, когда
   `backend: cursor` (opencode при этом не обязателен и наоборот). Скрипты `save_adr.py`, `check_review.py`,
   `agent_call.py` менять не нужно — они ходят через `run-agent.sh`, а dispatch лежит внутри него.

## Alternatives

* **Роли через Cursor Rules / AGENTS.md вместо inline-префикса на первом сообщении.** Отклонено: правила с
  `alwaysApply: true` грузятся в каждый запрос и загрязнили бы интерактивные сессии пользователя; inline-префикс
  изолирован на backend, работает в любом проекте без правки `.cursor/`, а однократная отправка делает его дешёвым.
* **Отдельный скрипт `run-agent-cursor.sh` вместо ветки в run-agent.sh.** Отклонено: привело бы к дублированию логики
  сессий/pid/logs и потребовало бы менять `agent_call.py` и все шаги пайплайна; ветка backend'а — одна точка правки.
* **`--continue` вместо именованных сессий.** Отклонено: `--continue` резюмит «последнюю» сессию глобально и не
  различает роли/задачи; нужны ровно две тёплые сессии, по одной на роль, адресуемые явно по chat id.
* **Свой id сессии для `--resume`.** Отклонено: Cursor игнорирует чужие id и молча теряет контекст (см. Context).
* **Общая секция `models:` с флагом backend (вместо отдельных `opencode:`/`cursor:`).** Отклонено: у opencode и cursor
  разные наборы настроек (provider/reasoning против одного slug'а), общая секция порождает «мёртвые» поля и путаницу.
* **Одна общая модель cursor на обе роли (без отдельных planner/executor).** Отклонено: структура должна быть
  симметрична opencode — две независимые модели, чтобы на платных планах planner и executor можно было развести на
  сильную/дешёвую без переделки конфига и логики.
* **Backend только через конфиг, без CLI-флага.** Отклонено: удобно выбирать backend на один прогон без правки
  конфига (`spec-run --backend cursor …`); конфиг остаётся значением по умолчанию.
* **Поддержать Claude Code вместо/вместе с Cursor.** Отклонено: задача сформулирована именно под Cursor; его CLI
  покрывает нужный сценарий (headless + resume + per-model), отдельный backend можно добавить позже тем же приёмом.

## Consequences

* Положительно: та же архитектура «две тёплые сессии, сильная + дешёвая LLM» работает на Cursor без переписывания
  пайплайна — `save_adr.py`, `check_review.py`, `agent_call.py` и workflow-шаги остаются без изменений.
* Положительно: один источник истины ролей (`PLANNER_BODY`/`EXECUTOR_BODY`) для обоих backend'ов; роль отправляется
  один раз, поэтому входные токены на повторных вызовах не раздуваются.
* Положительно: id сессии всегда «родной» для Cursor — исключён тихий сброс контекста.
* Положительно: отдельные секции конфига и две модели на роли симметричны opencode — миграция и дальнейшее развитие
  (например, развод моделей на платном тарифе) не требуют менять структуру.
* Отрицательно: `cursor-agent` находится в beta, флаги могут меняться между релизами (как и
  `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX` в своё время — см. ADR-0006).
* Отрицательно: для Cursor нужны активная подписка/логин (или `CURSOR_API_KEY`/`--api-key` для CI); модель задаётся
  slug'ом, имена моделей у Cursor и opencode не совпадают — конфиг под каждый backend свой.
* Отрицательно: на бесплатном тарифе единственная модель Composer ставится в оба слота — экономии «сильная + дешёвая»
  в MVP нет (планирование и реализация идут на одной модели), но структура это допускает.

## Acceptance Criteria

* `config.yml` принимает отдельные секции `opencode.models.{planner,executor}` и `cursor.models.{planner,executor}`,
  а верхнеуровневый `backend` ∈ {opencode, cursor} выбирает активную; прочие значения `backend` отклоняются
  валидацией с понятной ошибкой. Легаси-`models:` при загрузке трактуется как `opencode.models` (существующие
  конфиги работают).
* Для `cursor` обязательны оба слота `models.planner.model` и `models.executor.model`; их отсутствие отклоняется
  валидацией (симметрично обязательным полям opencode).
* `spec-run --backend cursor adr "..."` переопределяет backend на один прогон; без флага используется `backend` из
  конфига (по умолчанию `opencode`).
* При `backend: cursor` `run-agent.sh <role> "<prompt>"` вызывает `cursor-agent` (не `opencode run`) с флагами
  `-p --output-format json --force --trust --model <role-model>`, где planner берёт `cursor.models.planner.model`,
  executor — `cursor.models.executor.model`.
* Роль (тело системного промпта) предваряет промпт **только первого** сообщения сессии; на повторных
  `--resume`-вызовах отправляется голый промпт.
* Первый вызов роли минтит chat через `agent create-chat` и сохраняет id в `<state_dir>/sessions-<task_id>.json` под
  ключом роли; повторный вызов резюмит через `--resume <сохранённый id>`.
* Session id, передаваемый в `--resume`, всегда получен от Cursor (вывод `agent create-chat` или поле `session_id`
  JSON-результата); синтезированных id в коде нет.
* `--reset` удаляет сохранённый chat id, и следующая роль создаёт новый чат.
* `name-task.sh` при cursor использует `-p --output-format text` и возвращает слаг.
* Скрипты на базе `agent_call.py` (`save_adr.py` и др.) работают при `backend: cursor` без изменений.
* Очистка stale-процесса проверяет имя процесса по backend'у (`opencode` vs `cursor-agent`/`agent`).
* `check_prerequisites()` требует `cursor-agent` (или `agent`) на PATH при `backend: cursor` и не требует opencode в
  этом режиме.
* Дефолт `backend: opencode` сохраняет текущее поведение без регрессий (существующие тесты проходят).
* Добавлены тесты: разбор `--backend`, выбор секции конфига, валидация двух cursor-моделей, dispatch команды по
  backend'у, однократная отправка роли, сохранение/резюм chat id, `--reset`, выбор модели по роли.
