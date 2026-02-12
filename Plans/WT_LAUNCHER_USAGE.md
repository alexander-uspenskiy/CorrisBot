# WT Launcher Usage

## Quick start
Run from `C:\CorrisBot\Looper`:

```bat
StartLoopsInWT.bat
```

This uses `Plans\loops.wt.json`.

Under the hood, `StartLoopsInWT.bat` calls:
- `StartLoopsInWT.py`

## Optional arguments
```bat
StartLoopsInWT.bat [config_path] [project_root_override] [--dry-run]
```

Examples:

```bat
StartLoopsInWT.bat C:\CorrisBot\Looper\Plans\loops.wt.json
StartLoopsInWT.bat C:\CorrisBot\Looper\Plans\loops.wt.json C:\CorrisBot\ProjectFolder_Template\.CorrisBot
StartLoopsInWT.bat C:\CorrisBot\Looper\Plans\loops.wt.json C:\CorrisBot\ProjectFolder_Template\.CorrisBot --dry-run
```

## Notes
- Launcher skips missing agent directories.
- Launcher skips agents that are already running (anti-duplicate check).
- Launcher sends fire-and-forget `wt` commands and does not wait for loop completion.
- WT launcher is Python-only (`StartLoopsInWT.py`) with a `.bat` wrapper.
