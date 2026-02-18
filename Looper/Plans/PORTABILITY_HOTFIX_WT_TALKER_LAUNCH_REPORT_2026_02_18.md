# PORTABILITY HOTFIX WT Talker Launch Report

Date: 2026-02-18  
Branch: `chore/portable-paths-2026-02-18`

## 1) Findings-first
### High
- **Fixed:** `Gateways/Telegram/run_gateway.bat:86` had malformed Talker payload quoting in WT split-pane launch: `""%LOOP_BAT%" "%TALKER_ROOT%" ".""`.
- **Impact:** Talker pane command parser fails before loop startup (`The filename, directory name, or volume label syntax is incorrect.` / `Синтаксическая ошибка...`).
- **CR loop evidence:**
  - **CR-1 (before fix):** reproduced parser failure using the exact pre-fix payload form.
  - **Fix applied:** replaced malformed invocation with deterministic `call "%LOOP_BAT%" "%TALKER_ROOT%" "."`.
  - **CR-2 (after fix):** same payload flow executes successfully with quoted path+args.

### Medium
- None.

### Low
- WT GUI pane execution was validated via deterministic command-payload tests + WT shim capture (headless-safe), not by observing an interactive GUI pane in this CI shell session.

## 2) Root cause
The Talker split-pane `cmd /k` payload in `run_gateway.bat` ended with an invalid nested quote sequence (`""%LOOP_BAT%" ... ".""`). CMD interpreted this as broken command tokenization, so the loop BAT was never invoked. Replacing it with `call "%LOOP_BAT%" "%TALKER_ROOT%" "."` preserves portability env variables and provides valid CMD parsing for both `CodexLoop.bat` and `KimiLoop.bat`.

## 3) Checklist
| item | command | expected | actual | status |
|---|---|---|---|---|
| Reproduce failure signature (pre-fix payload form) | `cmd /c C:\Users\Dell\AppData\Local\Temp\corrisbot_hotfix_test\pre_fix_payload.bat` | CMD parser failure | `'""C:\Users\Dell\AppData\Local\Temp\corrisbot_hotfix_test\loop' is not recognized...` | ✅ |
| Post-fix payload works | `cmd /c C:\Users\Dell\AppData\Local\Temp\corrisbot_hotfix_test\post_fix_payload.bat` | Target BAT executes | `LOOP_OK` | ✅ |
| Launcher path from root BAT (`CorrisBot.bat`) | `cmd /c "set LOCALAPPDATA=C:\__no_wt_alias__&& set PATH=C:\Users\Dell\AppData\Local\Temp\corrisbot_hotfix_test;%PATH%&& C:\CorrisBot\CorrisBot.bat"` | Gateway boot path + WT command assembled | `[BOOT] Runner: kimi` and AGENTS assembled successfully | ✅ |
| Runner resolution from `loops.wt.json` = `kimi` | WT shim capture file `wt_args.log` | Talker pane uses `KimiLoop.bat` | contains `call "C:\CorrisBot\Looper\KimiLoop.bat" "C:\CorrisBot\Talker" "."` | ✅ |
| Runner resolution from `loops.wt.json` = `codex` | temporary `runner=codex` + same root launch command | Talker pane uses `CodexLoop.bat` | contains `call "C:\CorrisBot\Looper\CodexLoop.bat" "C:\CorrisBot\Talker" "."` | ✅ |
| Portability regression check | `rg -n -F "C:\\CorrisBot" --hidden --glob "!.git/" --glob "!Looper/Plans/**" --glob "!Gateways/Telegram/Plans/**"` | no hardcoded runtime/source regressions outside excluded plans | no matches (exit code 1) | ✅ |

## 4) Final Go/No-Go
**Go.** Hotfix is deterministic, keeps portability model and env contract (`REPO_ROOT`, `LOOPER_ROOT`, `TALKER_ROOT`, `TEMPLATE_ROOT`), and resolves Talker WT launch quoting regression.
