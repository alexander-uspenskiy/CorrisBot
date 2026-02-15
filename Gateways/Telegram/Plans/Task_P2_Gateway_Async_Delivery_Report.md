# Отчет по задаче P2: Gateway Async Delivery

Дата: 2026-02-15
Файл задачи: `Gateways/Telegram/Plans/Task_P2_Gateway_Async_Delivery_Prompt.md`

## 1) Что изменено архитектурно
- Gateway переведен с модели `request/response` (ожидание одного `Prompt_*_Result.md`) на двухфазную модель:
  - `submit`: быстро принять запрос пользователя и положить prompt в inbox Talker.
  - `deliver`: фоновый worker читает result-потоки и доставляет события в Telegram.
- Добавлен persistent delivery-state (`gateway_delivery_state.json`) для offset/event dedup между рестартами.
- Добавлены `epoch` и marker-floor механизмы для безопасного reset, чтобы старая сессия не "доезжала" после `/reset*`.

## 2) Ключевые изменения в коде
Основной файл:
- `Gateways/Telegram/tg_codex_gateway.py`

Что сделано:
- Введен background delivery worker (`_delivery_worker_loop`) и lifecycle start/stop в `post_init/post_shutdown`.
- Введено инкрементальное чтение result-файлов (`_process_result_file_incremental`) с сохранением offset/completed.
- Введена дедупликация событий через `delivered_event_keys` для message/file событий.
- Добавлена сериализация отправки в Telegram через `_DELIVERY_SEND_LOCK`.
- Усилены reset-пути (`/reset_session`, `/reset_all`):
  - lock order и state epoch bump;
  - чистка delivery-state;
  - fail-fast при невозможности сохранить state.
- Усилен submit-путь:
  - перед созданием prompt теперь обязательно сохраняется delivery-state;
  - при ошибке записи prompt выполняется rollback orphan-state записи.

## 3) Почему не ломает безопасность и reset-модель
- Сохраняются проверки `ALLOWED_CHAT_ID` и существующие Telegram-команды.
- Сохраняется sanitize sender/file path.
- Сохраняются scope-guards reset-операций (сброс только в ожидаемом `Talker/Prompts/Inbox`).
- После `/reset*` старая сессия отсекается через `epoch` и marker-floors (по согласованной семантике: reset = новая сессия).

## 4) Результаты CR и фиксов
Проведено несколько циклов CR с правками.

Исправлено:
- Гонка между reset и отправкой в Telegram: введен send-lock + epoch checks в delivery send path.
- Риск rehydrate/доезда после reset: reset теперь обновляет state атомарно относительно epoch и marker-floors.
- Риск "Accepted" при несохраненном delivery-state: submit теперь fail-fast, если `_save_delivery_state()` неуспешен.
- Риск orphan state при фейле prompt-write: добавлен rollback state entry.

Принятые риски (по согласованию):
- В спорных кейсах приоритет отдан политике "лучше возможный дубль, чем недоставка".
- Ошибочные/битые file events не считаются блокером (допустимы диагностические ошибки доставки).
- Логирование с текущей детализацией признано достаточным для отладки post-factum.

## 5) Прогоны и проверки
Локально выполнено:
- `py -3 -m py_compile Gateways/Telegram/tg_codex_gateway.py` (успешно).

Не выполнено в рамках этой сессии:
- Полный e2e прогон с реальными Telegram + Talker + Orchestrator по всем сценариям из prompt.

## 6) Остаточные риски / что можно сделать отдельно
- Редкий edge-case marker-floor сравнения (`<` vs `<=`) оставлен как non-blocking по приоритету.
- В rollback-ветке submit сохранение state сделано в best-effort режиме.
- Рекомендуемый следующий шаг: отдельный e2e smoke-раннер на сценарии submit/interruption/restart/file-delivery.
