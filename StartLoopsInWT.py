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
    "window_name_template": "CorrisBot-{project}",
    "tab_name_prefix": "Agents",
    "max_panes_per_tab": 4,
    "split_sequence": ["-H", "-V", "-H"],
    "state_subpath": "Temp\\wt_layout_state.json",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def resolve_dot_corrisbot_root(path_text: str) -> Path:
    full = Path(path_text).expanduser().resolve()
    dot = full / ".CorrisBot"
    if dot.is_dir():
        return dot
    return full


def get_project_tag(project_root: Path) -> str:
    leaf = project_root.name
    if leaf.lower() == ".corrisbot":
        return project_root.parent.name
    return leaf


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
        if project_norm in lower and (agent_rel_norm in lower or agent_abs_norm in lower):
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


def parse_split_sequence(raw: Any) -> list[str]:
    values: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            text = str(item).strip().upper()
            if text in {"-H", "H", "HORIZONTAL"}:
                values.append("-H")
            elif text in {"-V", "V", "VERTICAL"}:
                values.append("-V")
    if not values:
        return ["-H", "-V", "-H"]
    return values


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
    parser.add_argument("project_root", help="Path to .CorrisBot root or parent project directory.")
    parser.add_argument("agent_path", help="Agent path relative to project root (for example, Executors\\Executor_001).")
    parser.add_argument(
        "--config-path",
        default=str(SCRIPT_DIR / "Plans" / "loops.wt.json"),
        help="Path to WT layout config file.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print command without launching WT.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    project_root = resolve_dot_corrisbot_root(args.project_root)
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
    split_sequence = parse_split_sequence(layout.get("split_sequence"))

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
    slots = normalize_state_slots(state.get("agent_slots"))
    slots = prune_state_slots(slots, project_root, process_lines)

    tab_counts = build_tab_counts(slots)
    tab_index, pane_index = choose_target(tab_counts, max_panes)

    loop_bat_path = (SCRIPT_DIR / "CodexLoop.bat").resolve()
    if not loop_bat_path.is_file():
        raise RuntimeError(f"CodexLoop.bat not found: {loop_bat_path}")

    tab_label = f"{tab_name_prefix}-{tab_index + 1:02d}"
    agent_label = agent_path.replace("\\", "/")
    pane_title = f"{agent_label} [{project_tag}/{tab_label}]"
    loop_cmd = get_loop_invocation(loop_bat_path, project_root, agent_path)

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
            loop_cmd,
        ]
    else:
        orientation = split_sequence[(pane_index - 1) % len(split_sequence)]
        wt_args = [
            "-w",
            window_name,
            "focus-tab",
            "-t",
            str(tab_index),
            ";",
            "split-pane",
            orientation,
            "--title",
            pane_title,
            "--suppressApplicationTitle",
            "cmd",
            "/k",
            loop_cmd,
        ]

    print(f"Project root: {project_root}")
    print(f"Agent path:   {agent_path}")
    print(f"Window name:  {window_name}")
    print(f"Target:       tab={tab_index + 1}, pane={pane_index + 1}")
    print(f"State file:   {state_path}")

    if args.dry_run:
        print("[dry-run] wt " + format_args_for_display(wt_args))
        return 0

    ok, err = run_wt_command(wt_args, wt_candidates, alias_available)
    if not ok:
        raise RuntimeError(f"Failed to start Windows Terminal: {err}")

    slots[agent_path] = {"tab_index": tab_index, "pane_index": pane_index}
    write_json_file(
        state_path,
        {
            "project_root": str(project_root),
            "window_name": window_name,
            "max_panes_per_tab": max_panes,
            "tab_name_prefix": tab_name_prefix,
            "agent_slots": slots,
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
