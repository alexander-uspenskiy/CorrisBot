# Stage 1 Gate A Report (runtime portability migration)

## 1) Stage 1 commit SHA
`d5527d5fa96f2ff4d88106bee7676d5b300e4ca0`

## 2) CR findings-first report

### High
None.

### Medium
Resolved during CR loop before commit:
- `Looper/CodexLoop.bat:28` and `Looper/KimiLoop.bat:27` were adjusted so explicit CLI project root wins over env override (`CLI > env > default`).

### Low
None.

Open questions/assumptions: none.

## 3) Checklist

| item | command | expected | actual | status |
|---|---|---|---|---|
| 1 | `rg -n -F "C:\\CorrisBot" Looper/CreateProjectStructure.bat Looper/CreateWorkerStructure.bat Looper/CodexLoop.bat Looper/KimiLoop.bat Gateways/Telegram/run_gateway.bat Gateways/Telegram/tg_codex_gateway.py` | No runtime hardcoded matches in Stage 1 scope | No output, exit code `1` (no matches) | PASS |
| 2 | `cmd /c "call Looper\CreateProjectStructure.bat"`; `cmd /c "call Looper\CreateWorkerStructure.bat"`; `cmd /c "echo.|call Looper\CodexLoop.bat"`; `cmd /c "echo.|call Looper\KimiLoop.bat"`; `cmd /c "set TALKER_ROOT=C:\__NOT_FOUND__&& echo.|call Gateways\Telegram\run_gateway.bat"` | Dry-run/usage checks work | Usage printed for structure scripts; loop scripts printed usage + `[PATHS]`; gateway printed computed `[PATHS]` and expected missing-root error | PASS |
| 3 | `cmd /c "set REPO_ROOT=D:\PortableRepo&& set LOOPER_ROOT=D:\PortableRepo\Looper&& set TEMPLATE_ROOT=D:\PortableRepo\ProjectFolder_Template&& echo.|call Looper\CodexLoop.bat"`; `cmd /c "set REPO_ROOT=D:\PortableRepo&& set LOOPER_ROOT=D:\PortableRepo\Looper&& set TALKER_ROOT=D:\PortableRepo\Talker&& set TEMPLATE_ROOT=D:\PortableRepo\ProjectFolder_Template&& set WORKDIR=D:\PortableRepo\Gateways\Telegram&& echo.|call Gateways\Telegram\run_gateway.bat"` | Computed roots are printed and not locked to legacy fixed path | Outputs showed `D:\PortableRepo...` in `[PATHS]` | PASS |
| 4 | PowerShell probe with temp `py.cmd` shim + `cmd /c "set PATH=<stub>;%PATH%&& echo.|call Looper\CodexLoop.bat c:\CorrisBot ."` | `LOOPER_ROOT` is visible in child process env | Shim output: `PY_STUB_LOOPER_ROOT:C:\CorrisBot\Looper` | PASS |

## 4) Anti-Hack gate answers

1. Единая архитектурная модель путей или набор частных обходов?  
Единая модель: все launcher-скрипты Stage 1 вычисляют root от `%~dp0`/`__file__` + допускают env override.

2. Не добавлены ли fallback/эвристики, которые тихо возвращают в `C:\CorrisBot`?  
Нет. Runtime hardcoded `C:\CorrisBot` удален из Stage 1 scope.

3. Решение воспроизводимо в новой папке без ручных правок?  
Да. Проверено через override-прогоны на `D:\PortableRepo`.

4. Не зависит ли решение от "магического" cwd/окружения, которое не гарантируется launcher-ом?  
Нет критичной зависимости. Корни вычисляются от расположения скриптов и явно экспортируются в окружение.

## 5) Handoff note for Gate A

Recommendation: **Go**.  
Stage 1 выполнен в полном заявленном scope, CR loop закрыт (`CR -> fix -> CR`), mandatory checklist пройден.
