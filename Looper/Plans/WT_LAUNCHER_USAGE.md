# WT Launcher Usage

## Launch contract (production)
One call launches exactly one agent:

```bat
StartLoopsInWT.bat <project_root> <agent_path>
```

Examples:

```bat
StartLoopsInWT.bat C:\CorrisBot\ProjectFolder_Template Orchestrator
StartLoopsInWT.bat C:\CorrisBot\ProjectFolder_Template Workers\Worker_001
```

Optional:

```bat
StartLoopsInWT.bat C:\CorrisBot\ProjectFolder_Template Workers\Worker_001 --dry-run
```

## Behavior
- Starts one looper per launch request.
- If the same agent is already running, launch is skipped.
- Fills panes sequentially inside a tab up to `max_panes_per_tab`.
- Opens a new tab when current tab is full.
- Uses state file from config (default: `Temp\wt_layout_state.json`).

## Config
Layout config path:
- `C:\CorrisBot\loops.wt.json`

Current keys:
- `window_name_template` (supports `{project}`)
- `tab_name_prefix`
- `max_panes_per_tab`
- `tab_index_offset` (default `1`: keeps project tabs after Gateway/Talker tab in shared window)
- `state_subpath`

Pane layout per tab is fixed to 2x2 when full (equal 25/25/25/25).
If saved state was created with older layout parameters, launcher resets stale state automatically.
