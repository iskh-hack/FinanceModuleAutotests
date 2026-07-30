# Автотесты Finance Module

Внешние QA-тесты проверяют развёрнутый Finance Module от входного события до
состояния в БД. Первый вертикальный сценарий:

```text
pytest → Kafka order.paid → Finance Module → payment_jobs + snapshot
```

Тесты не создают заказ в Marketplace. Они эмулируют upstream-систему и
публикуют валидное событие `order.paid` в настоящий тестовый Kafka topic.

## Безопасность

Публикация события запускает реальные процессы выбранного стенда. Внешние тесты
по умолчанию пропускаются и требуют явного разрешения:

```text
FM_ALLOW_SIDE_EFFECTS=true
```

Использовать можно только QA/test окружение и специально заведённые тестовые
merchant/account/balance. Реальные клиентские данные не используются.

Файл `.env` игнорируется Git. Секреты нельзя добавлять в исходный код,
`.env.example`, fixtures или логи CI.

## Установка

```powershell
cd C:\QA\FinanceModuleAutotests
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Скопировать пример конфигурации:

```powershell
Copy-Item .env.example .env
```

Переменные из `.env` нужно загрузить в окружение перед запуском. В GitLab CI
они должны храниться как masked/protected variables.

## Быстрая проверка каркаса

Эти тесты не обращаются к стенду:

```powershell
pytest tests/unit -v
```

## Запуск внешнего smoke

После заполнения переменных окружения:

```powershell
$env:FM_ALLOW_SIDE_EFFECTS = "true"
pytest tests/smoke -v
```

Первый тест:

1. создаёт уникальные `order_id`, `payment_id` и `order_item_id`;
2. публикует `order.paid` в `payments.order.paid`;
3. ждёт появления `payment_jobs`;
4. проверяет связь job с заказом и сумму;
5. проверяет сохранение snapshot и товара.

## Текущая граница

На первом этапе тест подтверждает ingestion события. Он не утверждает, что
credit, split и внешние банковские операции завершились успешно. Эти проверки
добавляются отдельными слоями после подготовки тестовых accounts и mock
внешних систем.

