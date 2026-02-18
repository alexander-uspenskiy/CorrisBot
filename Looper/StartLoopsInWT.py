import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_LAYOUT: dict[str, Any] = {
    "window_name_template": "CorrisBot",
    "tab_name_prefix": "Agents",
    "max_panes_per_tab": 4,
    "tab_index_offset": 1,
    "state_subpath": "Temp\\wt_layout_state.json",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def resolve_project_root(path_text: str) -> Path:
    return Path(path_text).expanduser().resolve()


def get_project_tag(project_root: Path) -> str:
    return project_root.name


def normalize_agent_path(agent_path: str) -> str:
    normalized = agent_path.strip().replace("/", "\\")
    if normalized.startswith(".\\"):
        normalized = normalized[2:]
    return normalized


def resolve_agent_dir(project_root: Path, agent_path: str) -> Path:
    normalized = normalize_agent_path(agent_path)
    candidate = Path(normalized)
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / normalized).resolve()


def normalize_for_match(text: str) -> str:
    return text.lower().replace("/", "\\")


def contains_path_token(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    # Require non-alphanumeric boundaries to avoid partial name matches
    # (for example, Executor_Merge vs Executor_Merger).
    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])")
    return bool(pattern.search(haystack))


def get_powershell_executable() -> str:
    return shutil.which("powershell") or shutil.which("pwsh") or ""


def run_powershell_list(command: str) -> list[str]:
    shell = get_powershell_executable()
    if not shell:
        return []
    try:
        proc = subprocess.run(
            [shell, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]


def get_process_command_lines() -> list[str]:
    shell = get_powershell_executable()
    if not shell:
        return []
    command = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "Get-CimInstance Win32_Process | Select-Object -ExpandProperty CommandLine | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            [shell, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []

    raw = (proc.stdout or "").strip()
    if not raw:
        return []

    try:
        obj = json.loads(raw)
    except Exception:
        return []

    if isinstance(obj, list):
        return [str(x) for x in obj if x]
    if isinstance(obj, str):
        return [obj]
    return []


def test_agent_already_running(
    command_lines: list[str], project_root: Path, agent_path: str, agent_abs_path: Path
) -> bool:
    project_norm = normalize_for_match(str(project_root))
    agent_rel_norm = normalize_for_match(normalize_agent_path(agent_path))
    agent_abs_norm = normalize_for_match(str(agent_abs_path))

    for cmd in command_lines:
        lower = normalize_for_match(cmd)
        if "codex_prompt_fileloop.py" not in lower and "codexloop.bat" not in lower:
            continue
        has_project = contains_path_token(lower, project_norm)
        has_agent_rel = contains_path_token(lower, agent_rel_norm)
        has_agent_abs = contains_path_token(lower, agent_abs_norm)
        if has_project and (has_agent_rel or has_agent_abs):
            return True
    return False


def resolve_wt_candidates() -> list[str]:
    candidates: list[str] = []

    for name in ("wt.exe", "wt"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        fallback = Path(local_app_data) / "Microsoft" / "WindowsApps" / "wt.exe"
        if fallback.exists():
            candidates.append(str(fallback))

    user_profile = os.environ.get("USERPROFILE", "")
    if user_profile:
        fallback = Path(user_profile) / "AppData" / "Local" / "Microsoft" / "WindowsApps" / "wt.exe"
        if fallback.exists():
            candidates.append(str(fallback))

    ps_sources = run_powershell_list(
        "(Get-Command wt -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)"
    )
    candidates.extend(ps_sources)

    appx_locations = run_powershell_list(
        "(Get-AppxPackage -Name Microsoft.WindowsTerminal* -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty InstallLocation)"
    )
    for location in appx_locations:
        candidates.append(str(Path(location) / "wt.exe"))

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def can_invoke_wt_alias() -> bool:
    try:
        probe = subprocess.run(
            ["cmd", "/c", "wt", "-v"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return False
    return probe.returncode == 0


def normalize_tab_index_offset(raw: Any) -> int:
    try:
        value = int(raw)
    except Exception:
        return 1
    return max(0, value)


def format_args_for_display(args: list[str]) -> str:
    parts: list[str] = []
    for arg in args:
        if arg == ";":
            parts.append(";")
        elif any(c.isspace() for c in arg):
            parts.append(f'"{arg}"')
        else:
            parts.append(arg)
    return " ".join(parts)


def get_loop_invocation(loop_bat_path: Path, project_root: Path, agent_path: str) -> str:
    return f'"{loop_bat_path}" "{project_root}" "{agent_path}"'


def escape_for_cmd(text: str) -> str:
    return (
        text.replace("^", "^^")
        .replace("&", "^&")
        .replace("|", "^|")
        .replace("<", "^<")
        .replace(">", "^>")
    )


def get_split_operation_args(pane_index: int, pane_title: str, cmd_line: str) -> list[str]:
    common = [
        "--title",
        pane_title,
        "--suppressApplicationTitle",
        "cmd",
        "/k",
        cmd_line,
    ]
    if pane_index == 1:
        return ["split-pane", "-V", *common]
    if pane_index == 2:
        return ["focus-pane", "-t", "0", ";", "split-pane", "-H", *common]
    if pane_index == 3:
        return ["focus-pane", "-t", "1", ";", "split-pane", "-H", *common]
    return ["split-pane", "-H", *common]


def prepend_window_and_tab_focus(
    window_name: str, split_ops: list[str], tab_index: int | None
) -> list[str]:
    args = ["-w", window_name]
    if tab_index is not None:
        args.extend(["focus-tab", "-t", str(tab_index), ";"])
    args.extend(split_ops)
    return args


def parse_int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {}


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def resolve_state_path(project_root: Path, state_subpath: str) -> Path:
    candidate = Path(state_subpath).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / candidate).resolve()


def normalize_state_slots(raw_slots: Any) -> dict[str, dict[str, int]]:
    if not isinstance(raw_slots, dict):
        return {}
    result: dict[str, dict[str, int]] = {}
    for agent, slot in raw_slots.items():
        if not isinstance(slot, dict):
            continue
        agent_path = normalize_agent_path(str(agent))
        try:
            tab_index = int(slot.get("tab_index", 0))
            pane_index = int(slot.get("pane_index", 0))
        except Exception:
            continue
        if tab_index < 0 or pane_index < 0:
            continue
        result[agent_path] = {"tab_index": tab_index, "pane_index": pane_index}
    return result


def prune_state_slots(
    slots: dict[str, dict[str, int]], project_root: Path, process_lines: list[str]
) -> dict[str, dict[str, int]]:
    pruned: dict[str, dict[str, int]] = {}
    for agent_path, slot in slots.items():
        agent_dir = resolve_agent_dir(project_root, agent_path)
        if not agent_dir.exists():
            continue
        if test_agent_already_running(process_lines, project_root, agent_path, agent_dir):
            pruned[agent_path] = slot
    return pruned


def build_tab_counts(slots: dict[str, dict[str, int]]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for slot in slots.values():
        tab_index = int(slot["tab_index"])
        counts[tab_index] = counts.get(tab_index, 0) + 1
    return counts


def choose_target(tab_counts: dict[int, int], max_panes_per_tab: int) -> tuple[int, int]:
    for tab_index in sorted(tab_counts.keys()):
        pane_count = tab_counts[tab_index]
        if pane_count < max_panes_per_tab:
            return tab_index, pane_count
    next_tab = 0 if not tab_counts else (max(tab_counts.keys()) + 1)
    return next_tab, 0


def run_wt_command(
    wt_args: list[str], wt_candidates: list[str], alias_available: bool
) -> tuple[bool, str]:
    errors: list[str] = []

    for wt_exe in wt_candidates:
        try:
            proc = subprocess.run(
                [wt_exe, *wt_args],
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as exc:
            errors.append(f"{wt_exe}: {exc}")
            continue

        if proc.returncode == 0:
            return True, ""
        stderr = (proc.stderr or proc.stdout or "").strip()
        errors.append(f"{wt_exe}: exit={proc.returncode} {stderr}")

    if alias_available:
        try:
            proc = subprocess.run(
                ["cmd", "/c", "wt", *wt_args],
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if proc.returncode == 0:
                return True, ""
            stderr = (proc.stderr or proc.stdout or "").strip()
            errors.append(f"wt(alias): exit={proc.returncode} {stderr}")
        except OSError as exc:
            errors.append(f"wt(alias): {exc}")

    return False, " | ".join(errors)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch one looper in Windows Terminal with dynamic pane allocation.")
    parser.add_argument("project_root", help="Path to project root directory.")
    parser.add_argument("agent_path", help="Agent path relative to project root (for example, Executors\\Executor_001).")
    parser.add_argument(
        "--config-path",
        default=str(SCRIPT_DIR.parent / "loops.wt.json"),
        help="Path to WT layout config file.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print command without launching WT.")
    parser.add_argument("--runner", default=None, choices=["codex", "kimi"],
                        help="CLI agent backend: codex (default) or kimi.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    project_root = resolve_project_root(args.project_root)
    if not project_root.is_dir():
        raise RuntimeError(f"Project root not found: {project_root}")

    agent_path = normalize_agent_path(args.agent_path)
    agent_dir = resolve_agent_dir(project_root, agent_path)
    if not agent_dir.is_dir():
        raise RuntimeError(f"Agent directory not found: {agent_dir}")

    config_path = Path(args.config_path).expanduser().resolve()
    if not config_path.is_file():
        raise RuntimeError(f"Config file not found: {config_path}")

    config_raw = load_json_file(config_path)
    layout: dict[str, Any] = dict(DEFAULT_LAYOUT)
    for key, value in config_raw.items():
        layout[key] = value

    project_tag = get_project_tag(project_root)
    window_template = str(layout.get("window_name_template", DEFAULT_LAYOUT["window_name_template"]))
    window_name = window_template.format(project=project_tag)
    tab_name_prefix = str(layout.get("tab_name_prefix", DEFAULT_LAYOUT["tab_name_prefix"])).strip() or "Agents"

    try:
        max_panes = int(layout.get("max_panes_per_tab", DEFAULT_LAYOUT["max_panes_per_tab"]))
    except Exception:
        max_panes = int(DEFAULT_LAYOUT["max_panes_per_tab"])
    max_panes = max(1, max_panes)
    tab_index_offset = normalize_tab_index_offset(layout.get("tab_index_offset", 1))

    state_subpath = str(layout.get("state_subpath", DEFAULT_LAYOUT["state_subpath"])).strip()
    if not state_subpath:
        state_subpath = str(DEFAULT_LAYOUT["state_subpath"])
    state_path = resolve_state_path(project_root, state_subpath)

    wt_candidates = resolve_wt_candidates()
    alias_available = can_invoke_wt_alias()
    if not wt_candidates and not alias_available:
        if not args.dry_run:
            raise RuntimeError(
                "Windows Terminal command 'wt' is not available. "
                "Install Windows Terminal or enable the App Execution Alias for wt.exe."
            )
        print("[warning] wt.exe was not found, running in dry-run with command preview only.")

    process_lines = get_process_command_lines()
    if test_agent_already_running(process_lines, project_root, agent_path, agent_dir):
        print(f"[skip] Agent already running: {agent_path}")
        return 0

    state = load_json_file(state_path)
    state_tab_index_offset = parse_int_or_none(state.get("tab_index_offset"))
    reset_due_to_layout = state and state_tab_index_offset != tab_index_offset
    if reset_due_to_layout:
        print("[info] Resetting stale WT layout state (tab_index_offset changed).")
        slots: dict[str, dict[str, int]] = {}
    else:
        slots = normalize_state_slots(state.get("agent_slots"))
    slots = prune_state_slots(slots, project_root, process_lines)

    tab_counts = build_tab_counts(slots)
    tab_index, pane_index = choose_target(tab_counts, max_panes)

    # Determine runner type (codex or kimi)
    # Priority: CLI argument > config file > default
    runner = args.runner or str(config_raw.get("runner", "codex")).lower()
    if runner not in ("codex", "kimi"):
        runner = "codex"
    
    loop_bat_name = "KimiLoop.bat" if runner == "kimi" else "CodexLoop.bat"
    loop_bat_path = (SCRIPT_DIR / loop_bat_name).resolve()
    if not loop_bat_path.is_file():
        raise RuntimeError(f"{loop_bat_name} not found: {loop_bat_path}")

    tab_label = f"{tab_name_prefix}-{tab_index + 1:02d}"
    agent_label = agent_path.replace("\\", "/")
    pane_title = f"{agent_label} [{project_tag}/{tab_label}]"
    loop_cmd = get_loop_invocation(loop_bat_path, project_root, agent_path)
    cmd_line = f"title {escape_for_cmd(pane_title)} && {loop_cmd}"
    absolute_tab_index = tab_index + tab_index_offset

    if pane_index == 0:
        wt_args = [
            "-w",
            window_name,
            "new-tab",
            "--title",
            pane_title,
            "--suppressApplicationTitle",
            "cmd",
            "/k",
            cmd_line,
        ]
    else:
        split_ops = get_split_operation_args(pane_index, pane_title, cmd_line)
        wt_args_primary = prepend_window_and_tab_focus(window_name, split_ops, absolute_tab_index)
        wt_args_active = prepend_window_and_tab_focus(window_name, split_ops, None)
        wt_candidates_by_priority: list[tuple[str, list[str]]] = [("focused+offset", wt_args_primary)]
        wt_candidates_by_priority.append(("active-tab", wt_args_active))
        wt_args = wt_args_primary

    print(f"Project root: {project_root}")
    print(f"Agent path:   {agent_path}")
    print(f"Window name:  {window_name}")
    print(f"Target:       tab={tab_index + 1} (absolute {absolute_tab_index + 1}), pane={pane_index + 1}")
    print(f"State file:   {state_path}")

    if args.dry_run:
        print("[dry-run] wt " + format_args_for_display(wt_args))
        if pane_index > 0:
            for label, candidate in wt_candidates_by_priority[1:]:
                print(f"[dry-run] fallback({label}) wt " + format_args_for_display(candidate))
        return 0

    if pane_index == 0:
        ok, err = run_wt_command(wt_args, wt_candidates, alias_available)
        if not ok:
            raise RuntimeError(f"Failed to start Windows Terminal: {err}")
    else:
        launch_errors: list[str] = []
        launched = False
        for label, candidate in wt_candidates_by_priority:
            ok, err = run_wt_command(candidate, wt_candidates, alias_available)
            if ok:
                launched = True
                if label != "focused+offset":
                    print(f"[warning] Used fallback launch mode: {label}")
                break
            launch_errors.append(f"{label}: {err}")
        if not launched:
            raise RuntimeError("Failed to start Windows Terminal: " + " | ".join(launch_errors))

    slots[agent_path] = {"tab_index": tab_index, "pane_index": pane_index}
    write_json_file(
        state_path,
        {
            "project_root": str(project_root),
            "window_name": window_name,
            "max_panes_per_tab": max_panes,
            "tab_name_prefix": tab_name_prefix,
            "tab_index_offset": tab_index_offset,
            "agent_slots": slots,
            "runner": runner,
            "updated_at": now_iso(),
        },
    )
    print(f"[ok] Launch command sent: {agent_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(130)
