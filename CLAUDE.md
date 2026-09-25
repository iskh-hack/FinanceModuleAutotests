# Finance Module Autotests — правила для Claude Code

Этот файл — обязательный вход для Claude Code в этом репозитории. Прочитай его
перед серьёзной задачей и в начале каждой новой сессии.

## Роль

Этот репозиторий — моя рабочая среда для написания и поддержки функциональных
QA-автотестов Finance Module. В экосистеме проекта есть второй агент — Codex
(`C:\QA\QAKnowledgeAgent`), который ведёт QA-базу знаний (Obsidian Vault) и
отвечает на вопросы "что требовалось / что подтверждено QA". Я отвечаю за код:
автотесты, вспомогательные скрипты, диагностику через БД/YouTrack при написании
тестов. Изменение Vault, YouTrack и Change Set-процессов Codex — не моя область;
я могу читать оттуда контекст, но не веду там записи.

## Локальные репозитории проекта

Полный реестр с ветками и инвентаризацией коммитов:
[`C:\QA\QAKnowledgeAgent\docs\REPOSITORIES.md`](file:///C:/QA/QAKnowledgeAgent/docs/REPOSITORIES.md)
(источник правды — сверяй перед анализом, таблица ниже может отстать).

| ID | Локальный путь | Роль | Авторитетность |
|---|---|---|---|
| `market-monorepo` | `C:\QA\Repositories\MarketMonorepo` | текущий Finance Module runtime, gRPC proto, BLNK fork, Global Admin | текущий operational source |
| `fm-mono` | `C:\QA\Repositories\FinanceModule\Mono` | будущий standalone Finance Module (Go) | целевой канон после миграции, может отставать |
| `fm-api` | `C:\QA\Repositories\FinanceModule\Api` | standalone Kafka/event контракты | источник контрактов, не полной реализации |
| `fm-blnk` | `C:\QA\Repositories\FinanceModule\Blnk` | ledger BLNK (mirror) | источник internal ledger-логики |
| `main-backend` | `C:\QA\Repositories\MainBackend` | marketplace backend | источник upstream order/payment flow |
| `fm-autotests` | этот репозиторий | QA-автотесты | код, который я пишу и поддерживаю |

Правила работы с ними:

- `C:\QA\Repositories\*` — **read-only по умолчанию**. Изменять, `git pull`,
  коммитить в них можно только по явному запросу пользователя в моменте.
  Пользователь сам периодически стягивает их с рабочего GitLab — код обычно
  актуален, но не гарантированно; при сомнении в актуальности сверяйся с
  реестром выше или спрашивай.
- Локальная ветка/имя каталога сама по себе не доказывает, что этот код
  реально развёрнут на стенде — при анализе конкретного поведения стенда
  сверяй image tag/commit, а не полагайся на branch name.
- `MainBackend` и `MarketMonorepo` уже содержат собственные `AGENTS.md`/`CLAUDE.md`
  — читай их перед серьёзным анализом реализации в этих репозиториях.
- Этот репозиторий (`fm-autotests`) — единственный, который я меняю свободно
  в рамках задач по автотестам.

## Контракт функциональных автотестов

Полный контракт: [`C:\QA\QAKnowledgeAgent\docs\FUNCTIONAL_AUTOTESTING.md`](file:///C:/QA/QAKnowledgeAgent/docs/FUNCTIONAL_AUTOTESTING.md).
Ключевое:

- Тест = штатное действие клиента/соседнего сервиса → ожидание асинхронной
  обработки → проверка наблюдаемого результата. Шаг, существующий только ради
  обхода продукта, недопустим.
- **Запрещено**: `INSERT`/`UPDATE`/`DELETE` бизнес-данных, ручное создание
  snapshot/job/проводок, обход авторизации/RBAC/валидации, вызов внутренних
  функций вместо штатного интерфейса, правка настроек БД/Kafka/K8s ради
  прохождения теста, смешение независимых flow в одном тесте.
  БД — средство наблюдения (`SELECT`), не средство подготовки результата.
- Тестовый код без хардкода URL/токенов/DSN/namespace/test ID — всё через env,
  проверяется при старте (см. `tests/conftest.py`).
- Один файл/класс = один понятный flow (`payment_mbank`, `refund_mbank`, ...).
- **Только функциональные тесты.** Юнит-тесты не пишем — ни на продуктовую
  логику (её покрывают разработчики в `MarketMonorepo`, `FinanceModule\Mono`,
  `Blnk`, `MainBackend`), ни на вспомогательный код этого репозитория (его
  поломку выявляют сами функциональные тесты). Каталога `tests/unit` нет.

## Текущее состояние репозитория (сверяй перед серьёзными изменениями)

Тесты работают на **реальных заказах**: MBANK создаётся через клиентский HTTP-флоу
Market (`market_checkout.py`), остальные методы оплаты — штатным developer builder
`trigger_finmodule_debezium_flows` через Core Backend (`core_backend.py`).
Общий happy path — `flow.py`, тесты — `tests/functional/*`. Синтетические
Kafka-события (`events.py`/`kafka_client.py`) удалены.

## MCP: `qa-knowledge-agent`

В проекте есть локальный read-only MCP-сервер (`C:\QA\QAKnowledgeAgent\server.py`),
изначально настроенный для Codex. Он даёт мне такие же гарантированные
guardrails без дублирования инфраструктуры:

- `check_database_connections`, `query_database(database, sql, parameters, max_rows)`
  — read-only `SELECT`/`WITH` к `finance_module`, `core_backend`, `blnk`; сервер
  на своём уровне запрещает запись, блокировки и произвольные функции,
  маскирует чувствительные колонки. Используй для сверки контрактов и данных
  при написании тестов — не для подготовки результата теста.
- `check_youtrack_connection`, `search_youtrack_issues`, `get_youtrack_issue`
  — read-only YouTrack в рамках project allowlist. Источник требований и
  договорённостей при написании/уточнении тестов.
- На этом же сервере есть Vault-инструменты (`read_file`, `query_vault`,
  `preview_change_set`, `apply_change_set`, `prepare_feature_bundle`,
  `start_test_session` и т.д.) — это область Codex. Читать Vault для контекста
  можно, но **не веду там записи** без отдельного явного запроса пользователя.

Регистрация сервера — задача с системными последствиями (правка глобального
`~/.claude.json`), поэтому выполняется только с явным подтверждением
пользователя, не автоматически в фоне.
