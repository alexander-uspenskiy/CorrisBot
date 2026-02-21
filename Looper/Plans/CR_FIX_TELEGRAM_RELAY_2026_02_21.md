# CR Report

## Scope
- Task/Plan: Восстановление передачи сообщений (cross-agent relay) от Оркестратора пользователю в Telegram.
- Reviewed commit/diff: Изменение возвращаемого значения для неизвестных `sender_id` в `tg_codex_gateway.py`.
- Reviewed files:
  - `C:\CorrisBot\Gateways\Telegram\tg_codex_gateway.py:646`

## Findings
1. [SEVERITY: MEDIUM] Блокировка доставки внутренних отчетов (silent drop).
   - Location: `C:\CorrisBot\Gateways\Telegram\tg_codex_gateway.py:646`
   - Problem: Функция `_get_sender_chat()` возвращала `None` для отправителей (таких как `Orc_CorrisBot_TestProject_10`), не зарегистрированных явно через webhook-контекст Telegram. Из-за этого Gateway не мог сопоставить сообщения из папки входящих с конкретным пользователем и отбрасывал их, не доставляя в чат.
   - Impact/Risk: Приводит к тому, что все асинхронные отчеты от Orchestrator и других Workers, обрабатываемые Talker'ом и сохраняемые в `Inbox`, оставались "невидимыми" для владельца системы. Нарушалась observability рабочего процесса.
   - Required fix: Так как бот спроектирован для одного владельца (`ALLOWED_CHAT_ID_INT`), логично делать fallback на этот ID для системных/внутренних агентов. Изменение уже применено.

## Checks Performed
- Выполнен регрессионный прогон всего тестового набора Looper (`py -m unittest discover -s C:\CorrisBot\Looper\tests`) — 84 теста без сбоев прошли за 45 сек.
- Инспекция кода `tg_codex_gateway.py`: проверка того, что использование `ALLOWED_CHAT_ID_INT` как дефолтного значения в `_get_sender_chat` не нарушает безопасность: входящие запросы всё так же фильтруются через `_is_allowed()`, а рассылка системных уведомлений в авторизованный чат безопасна.

## Not Verified
- Интеграционный тест через "живой" API Telegram-бота не выполнялся, опирались только на поведенческий анализ дампа стейта рассылок Gateway.

## Risk Assessment
- Overall risk: LOW
- Release gate recommendation: ALLOW

## Acceptance Recommendation
- Status: ACCEPT
- Blocking items: Отсутствуют.
