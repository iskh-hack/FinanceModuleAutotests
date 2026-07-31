# Автотесты Finance Module

Проект проверяет основной финансовый поток на развёрнутом QA-окружении:

```text
pytest
  → реальный тестовый Order и Transaction в Main Backend
  → Debezium
  → штатный producer Main Backend
  → Kafka payments.order.paid
  → Finance Module
  → payment_job и snapshot в БД
```

Тесты не собирают `order.paid` вручную. Контракт события, `order_id`,
`order_item_id` и idempotency key формирует Main Backend.

## Безопасность

Создание оплаченного заказа запускает реальные процессы выбранного стенда:
credit в Blnk, начисление MBonus и последующий split. Внешний smoke запускается
только при двух явных разрешениях:

```text
FM_ALLOW_SIDE_EFFECTS=true
FM_CONFIRM_DOWNSTREAM_ISOLATED=true
```

Второй флаг можно включать только после подтверждения, что тестовый магазин,
балансы Blnk и MBonus изолированы от реальных денег и клиентов.

Файл `.env` игнорируется Git. Секреты нельзя сохранять в исходниках,
fixtures, `.env.example` или логах CI.

## Как создаётся заказ

MVP использует существующий в Main Backend builder
`_FinmoduleDebeziumFlowBuilder` и запускает только flow `mbank-native`.
Builder создаёт:

- тестовый Order с `is_test=True`;
- тестовый Product и OrderProduct;
- настоящую Transaction;
- переход Transaction в финальный статус.

После изменения таблицы штатный Debezium-handler Main Backend публикует
`order.paid`. Использование приватного builder — временное решение. Позже
в Main Backend следует добавить публичную management-команду с параметрами
`--flow mbank-native` и `--client-phone`.

## Установка

```powershell
cd C:\QA\FinanceModuleAutotests
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
```

## Unit-тесты

Unit-тесты не обращаются к кластеру и не создают финансовые операции:

```powershell
pytest tests/unit -v
```

## Внешний smoke

Перед запуском требуется:

- доступ `kubectl` к namespace Main Backend;
- read-only DSN Finance Module;
- специально выделенный тестовый магазин;
- активный тестовый клиент типа `customer`;
- подтверждённая изоляция Blnk и MBonus.

После заполнения `.env`:

```powershell
$env:FM_ALLOW_SIDE_EFFECTS = "true"
$env:FM_CONFIRM_DOWNSTREAM_ISOLATED = "true"
pytest tests/smoke -v
```

Smoke создаёт один реальный MBANK-заказ и проверяет:

- соответствие `payment_job` настоящему Order;
- соответствие payment ID алгоритму producer Main Backend;
- сохранение snapshot;
- реальные OrderProduct, Product, Category, Shop и Merchant ID.

## Текущие ограничения

- Тест нельзя запускать на обычном магазине.
- Тест пока не выполняет автоматический rollback финансовых операций.
- Проверка credit, split и возврата будет добавлена после подготовки
  изолированных downstream-сервисов и тестовых балансов.
