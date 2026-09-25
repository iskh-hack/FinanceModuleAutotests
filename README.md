# Функциональные автотесты Finance Module

Тесты проверяют интеграцию Core Backend, Debezium, Finance Module и BLNK на dev.
База Finance Module используется только для фиксированных `SELECT`-проверок.

## Happy path

```text
Core Backend создаёт реальные тестовые Order, OrderProduct и payment rows
→ Debezium публикует source event
→ штатный consumer Core Backend публикует payments.order.paid
→ Finance Module выполняет CREDIT
→ тест дожидается CREDITED и проверяет snapshot
→ QA setup переводит тот же тестовый Core-заказ в DELIVERED
→ Debezium и штатный handler публикуют orders.order.completed
→ Finance Module выполняет SPLIT
→ тест дожидается SPLIT_COMPLETED и проверяет BLNK-транзакции
```

Для подготовки MBANK-заказа используется реальный клиентский HTTP-флоу Market
(`src/finance_autotests/market_checkout.py`): логин → корзина → самовывоз →
`order/prepare` → эмуляция колбэка MBank через служебный вебхук-токен (тот же
механизм, которым провайдер подтверждает оплату в проде). Это не требует kubectl.

Остальные методы оплаты (MBANK Pay, Payler, MPlus, Adal) пока создаются через
штатную developer-команду Core Backend `trigger_finmodule_debezium_flows` (kubectl
exec в Core Backend pod). Она создаёт настоящие тестовые заказы, поэтому после
обработки они доступны на странице «Заказы» в интерфейсе Finance Module.
Прямые `INSERT`, `UPDATE`, `DELETE`, `SET` и другие команды к БД из автотестов не
выполняются.

Перевод MBANK-заказа в `DELIVERED` (второй шаг happy path) делает та же
`MarketCheckoutFactory` реальным dispatcher-эндпоинтом
`PATCH /api/crm/dispatcher/v2/orders/{id}/` с `{"status": "DELIVERED"}` — тем же
API, которым в проде пользуется диспетчер, когда завершает заказ вручную. Для
входа нужна роль Dispatcher на тестовом клиенте (`FM_TEST_CLIENT_PHONE`). Для
остальных методов оплаты завершение по-прежнему идёт через kubectl-команду
(`CoreBackendScenarioFactory.complete()`).

## Тестовый профиль dev

- merchant: `741d63b1-f37e-48c3-b2bb-523ef03faf32`;
- shop: `273`;
- все созданные заказы и товары имеют признак `is_test=True`;
- существующие пользователи и магазин переиспользуются.

Пользователь выбирается явно через FM_TEST_CLIENT_PHONE=996500122279; магазин проверяется по FM_TEST_MERCHANT_ID.

QA-обёртка вызывает только выбранный метод developer builder. Поэтому одиночный
smoke создаёт один нужный заказ, а не полный пакет из девяти сценариев. Поддержаны
MBANK, MBANK Pay, Payler, MPlus и Adal.

На dev 2026-09-09 Payler setup заблокирован рассинхронизацией developer builder и
схемы БД: обязательный `order_paylertransaction.payment_source` не заполняется.
Остальные сценарии создаются независимо и не блокируются этой ошибкой.

## Подготовка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
```

Секреты и DSN хранятся только локально. Файл .env автоматически не загружается:
передайте его значения как переменные окружения процесса/CI. Перед запуском укажите актуальный Core
Backend pod в `FM_MAIN_BACKEND_RESOURCE`.

Побочные эффекты разрешаются только двумя явными флагами:

```powershell
$env:FM_ALLOW_SIDE_EFFECTS = "true"
$env:FM_CONFIRM_DOWNSTREAM_ISOLATED = "true"
```

Для MBANK-флоу через Market API дополнительно нужны `FM_MARKET_DEV_LOGIN_TOKEN`
(dev-bypass токен для входа без пароля, `settings.DEVELOPMENT_TOKEN` на Core Backend)
и `FM_MBANK_WEBHOOK_TOKEN` (служебный токен MBank-вебхука на dev) — оба без значения
по умолчанию, проверяются при старте.

## Запуск

Один MBANK happy path:

```powershell
python scripts/run_dev_payments.py --payment MBANK
pytest tests/functional/payments/test_payment_mbank.py -v -s
```

Все поддержанные оплаты:

```powershell
python scripts/run_dev_payments.py --payment ALL
pytest -m functional -v -s
```

`--run-id` можно передать вручную для диагностики. Без него каждый запуск получает
уникальный маркер.

`scripts/run_dev_payments.py` создаёт заказ только через kubectl (для всех методов,
включая MBANK) и требует рабочего доступа к кластеру.
`pytest tests/functional/payments/test_payment_mbank.py` полностью не зависит от
kubectl: и создание заказа, и перевод в `DELIVERED` идут через реальный HTTP Market
API.

## Границы и защита

MBANK сверяет суммы проводок со snapshot и их общий итог; выбор правильного тарифа и состояние BLNK отдельно ещё не проверяются.
Первый запуск — только MBANK, вручную, без параллельности и автоматических повторов. Флаги не доказывают изоляцию внешних интеграций.


- setup переиспользует developer builder `trigger_finmodule_debezium_flows` и
  запускает только выбранный flow через Django management shell;
- после setup заказ хранится в Core Backend как `is_paid=True`, `INITIALIZED`;
- события оплаты и завершения создаются реальным Debezium/consumer flow;
- переход в `DELIVERED` выполняется только после подтверждённого `CREDITED` и
  только для созданного тестом `is_test=True` заказа выбранного магазина;
- Kafka key обязан совпадать с `payload.order_id`;
- ошибки `FAILED` завершают тест с содержимым `last_error`;
- пароли и DSN не выводятся в отчёт;
- автоматического удаления созданных заказов нет: продуктового safe cleanup API пока нет.

## Только функциональные тесты

Репозиторий содержит только функциональные тесты. Юнит-тесты продуктовой логики
Finance Module, BLNK и Core Backend ведут разработчики в своих репозиториях;
юнит-тесты на вспомогательный код этого репозитория не пишутся — его поломку
выявляют сами функциональные тесты.
