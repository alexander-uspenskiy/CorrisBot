# Handoff: Portable Hotfix for Talker WT Launch Failure

Date: 2026-02-18  
Repo: `C:\CorrisBot`  
Branch: `chore/portable-paths-2026-02-18`

## 1) Incident summary
After portability migration, first launch from root (`CorrisBot.bat`) starts Windows Terminal and gateway pane works, but Talker pane fails immediately with:

`Синтаксическая ошибка в имени файла, имени папки или метке тома.`

Observed gateway boot (healthy):
- Repo/Looper/Talker roots are `C:\CorrisBot\...`
- delivery worker starts

Observed Talker pane:
- only syntax error in `cmd`, no looper startup

## 2) Repro path
1. Run `C:\CorrisBot\CorrisBot.bat`
2. WT opens 2 panes:
   - gateway pane works
   - Talker pane fails with syntax error

## 3) Primary suspect
`Gateways/Telegram/run_gateway.bat:86` has a very long WT command string with nested quoting:
- split-pane talker command currently contains `^&^& ""%LOOP_BAT%" "%TALKER_ROOT%" ".""`
- likely malformed quoting/escaping for `cmd /k` payload in Talker pane.

## 4) Constraints
1. Keep portability model (no return to hardcoded `C:\CorrisBot`).
2. Keep runtime env contract: `REPO_ROOT`, `LOOPER_ROOT`, `TALKER_ROOT`, `TEMPLATE_ROOT`.
3. Deterministic fix only.
4. Mandatory CR loop: `CR -> fix -> CR`.
5. No destructive git/file commands.

## 5) Minimal scope to inspect
- `Gateways/Telegram/run_gateway.bat` (primary)
- optionally `Looper/StartLoopsInWT.bat`, `Looper/CodexLoop.bat`, `Looper/KimiLoop.bat` (if needed for consistency)

## 6) Done criteria
1. `CorrisBot.bat` starts both panes without syntax errors.
2. Talker pane reaches normal looper startup (watching inbox).
3. Works with runner selected from `loops.wt.json` (`codex` and `kimi` path handling remains valid).
4. `rg -n -F "C:\\CorrisBot"` outside excluded plans remains clean.
5. Provide concise test evidence and gate-style report.

## 7) Required report artifact
Create:
- `Looper/Plans/PORTABILITY_HOTFIX_WT_TALKER_LAUNCH_REPORT_2026_02_18.md`

Include:
1. Findings-first (High -> Medium -> Low).
2. Root cause explanation.
3. Commands + actual outputs summary.
4. Final Go/No-Go for launch health.

## 8) Suggested commit message
- `portable(hotfix): fix WT Talker pane launch command quoting`

