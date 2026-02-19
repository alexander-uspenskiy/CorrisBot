# Full CR (Round 2): Migration Plan (Per-Agent Runner/Model/Reasoning)

### Review Summary
Второй проход ревью подтверждает, что все 4 "must-fix" замечания из предыдущей итерации были успешно интегрированы в план:

1. **`last_known_good` conflict:** Путь изменен на безопасный `<AgentDirectory>/AgentRunner/last_known_good/` (п. 4.7 и 9.6). Гонка между агентами устранена.
2. **`.bat` integration:** Добавлен контракт `Resolver -> Batch Bridge` (п. 4.8) через `resolve_agent_config.py --format bat_env`, что полностью снимает риск парсинга JSON средствами Windows Batch и хрупкости Gateway boot.
3. **Precedence vs Hot-Reload:** Добавлен п. 4.6.4, четко фиксирующий, что CLI `--reasoning-effort` "пинит" значение на время жизни процесса, игнорируя hot-reload с выводом warning'а. Противоречие устранено.
4. **`<RuntimeRoot>` discovery:** Введен п. 4.0 с единым детерминированным алгоритмом поиска от `AgentDirectory` вверх по дереву до `model_registry.json`.
5. **Тесты:** В фазе 6 добавлены проверки на `read/write race`, `snapshot isolation` и `path-resolution`.

### Minor Findings / Observations (Round 2)
Критических блоков и потенциальных регрессий не обнаружено. План выглядит монолитно и готов к передаче Оркестратору.
Единственное микро-наблюдение: в п. 4.8 (Batch Bridge Contract) указано: `prints one KEY=VALUE per line`. Рекомендуется, чтобы скрипт моста сразу отдавал переменные окружения в формате, пригодном для батника (например, без кавычек или экранируя спецсимволы, если они появятся), но для текущего скоупа ключей (`codex`, `kimi`, `high`, `low`) проблем с кодировкой в CMD не предвидится.

### Final Verdict
`Ready for execution`

Документ готов стать руководством к действию (Phase 0 -> Phase 7) для Оркестратора и Worker-агентов. Отличная работа!
