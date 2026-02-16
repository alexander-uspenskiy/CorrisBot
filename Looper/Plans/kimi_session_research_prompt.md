# Задача: Определение workspace_hash и session_id для Kimi CLI

Помоги с исследованием управления сессиями в Kimi CLI.

## Эксперимент 1: Определение workspace_hash

В директории `%USERPROFILE%\.kimi\sessions\` хранятся сессии, организованные по workspace_hash.
У тебя есть доступ к этой директории.

Задача:
1. Перечисли все поддиректории в `%USERPROFILE%\.kimi\sessions\`
2. Для каждого workspace_hash покажи самый свежий session_uuid подкаталог (по дате модификации)
3. Для каждого такого свежего session_uuid, прочитай первые 3 строки `context.jsonl` — там видно, с какой директорией связан workspace

## Эксперимент 2: Определение алгоритма хеширования

Возьми известные directory paths из эксперимента 1 и попробуй определить алгоритм хеширования workspace_hash.
Попробуй:
- `md5(path)` для разных нормализаций path (с/без trailing slash, forward/backward slashes, upper/lower case)
- Если нет совпадения — попробуй `sha256[:32]`
- Если ничего не подходит — посмотри исходный код Kimi CLI (он Python, установлен через pip/uv)

Подсказка: Kimi CLI написан на Python. Поищи файлы `session` в установленном пакете:
```
python -c "import kimi; print(kimi.__file__)"
```
Или поищи в site-packages:
```
pip show kimi-cli
```
и посмотри в Source Code / каталог пакета.

## Эксперимент 3: Получение session_id программно

Попробуй запустить следующую команду и найди, появляется ли session_id где-то:
```
kimi --print --output-format stream-json --yolo -w C:\CorrisBot -c "скажи OK" 2>&1
```
Проверь:
1. Есть ли session_id в stdout (JSON)?
2. Есть ли session_id в stderr?
3. Какой новый UUID-каталог появился в `%USERPROFILE%\.kimi\sessions\` после этого вызова?

## Формат ответа

Запиши результаты в файл `C:\CorrisBot\Looper\Plans\kimi_session_research_report.md`:

```markdown
# Kimi CLI Session Research Report

## Workspace Hash Mapping
| workspace_hash | Directory Path | Algorithm |
|---|---|---|

## Hash Algorithm
(описание алгоритма или "не определён")

## Session ID Detection
### In JSON output
(есть/нет)
### In stderr
(есть/нет)
### Filesystem detection method
(описание метода)
### Source code location (if found)
(путь к файлу в пакете kimi-cli, где определяется хеш)
```
