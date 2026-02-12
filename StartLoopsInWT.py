import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


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


def get_process_command_lines() -> list[str]:
    shell = shutil.which("powershell") or shutil.which("pwsh")
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
        is_loop = "codex_prompt_fileloop.py" in lower or "codexloop.bat" in lower
        if not is_loop:
            continue
        if project_norm in lower and (agent_rel_norm in lower or agent_abs_norm in lower):
            return True
    return False


def resolve_wt_executable() -> str:
    found = shutil.which("wt.exe") or shutil.which("wt")
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        fallback = Path(local_app_data) / "Microsoft" / "WindowsApps" / "wt.exe"
        if fallback.is_file():
            return str(fallback.resolve())
    return ""


def convert_to_pane_spec(raw_pane: Any) -> tuple[str, str]:
    if isinstance(raw_pane, str):
        return raw_pane, ""
    if isinstance(raw_pane, dict):
        agent_path = str(raw_pane.get("agent_path", "")).strip()
        if not agent_path:
            raise ValueError("Pane object must contain non-empty 'agent_path'.")
        title = str(raw_pane.get("title", "")).strip()
        return agent_path, title
    raise ValueError("Pane entry must be a string or object.")


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


def build_tab_arguments(
    tab_node: dict[str, Any],
    project_root: Path,
    project_tag: str,
    loop_bat_path: Path,
    process_lines: list[str],
    planned_launch_keys: set[tuple[str, str]],
) -> list[str]:
    tab_name = str(tab_node.get("name", "")).strip() or "UnnamedTab"
    pane_nodes = tab_node.get("panes", [])
    if not isinstance(pane_nodes, list) or not pane_nodes:
        print(f"[skip] Tab '{tab_name}' has no panes.")
        return []

    launchable: list[tuple[str, str]] = []
    project_norm = normalize_for_match(str(project_root))

    for pane_node in pane_nodes:
        agent_path_raw, pane_title_raw = convert_to_pane_spec(pane_node)
        agent_path = normalize_agent_path(agent_path_raw)
        agent_dir = resolve_agent_dir(project_root, agent_path)

        if not agent_dir.is_dir():
            print(f"[skip] Agent path not found: {agent_dir}")
            continue

        key = (project_norm, normalize_for_match(agent_path))
        if key in planned_launch_keys:
            print(f"[skip] Agent already planned: {agent_path}")
            continue

        if test_agent_already_running(process_lines, project_root, agent_path, agent_dir):
            print(f"[skip] Agent already running: {agent_path}")
            continue

        pane_title = pane_title_raw or f"[{project_tag}] {tab_name} | {agent_path.replace(chr(92), '/')}"
        launchable.append((agent_path, pane_title))
        planned_launch_keys.add(key)

    if not launchable:
        print(f"[skip] Tab '{tab_name}' has nothing to launch.")
        return []

    tab_args: list[str] = []
    split_index = 0
    for idx, (agent_path, pane_title) in enumerate(launchable):
        loop_cmd = get_loop_invocation(loop_bat_path, project_root, agent_path)
        if idx == 0:
            tab_args.extend(["new-tab", "--title", pane_title, "cmd", "/k", loop_cmd])
            continue
        split_index += 1
        orientation = "-H" if split_index % 2 == 1 else "-V"
        tab_args.extend([";", "split-pane", orientation, "--title", pane_title, "cmd", "/k", loop_cmd])
    return tab_args


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch multiple looper consoles in Windows Terminal.")
    parser.add_argument(
        "--config-path",
        default=str(SCRIPT_DIR / "Plans" / "loops.wt.json"),
        help="Path to loops.wt.json config.",
    )
    parser.add_argument(
        "--project-root-override",
        help="Optional override for project root (.CorrisBot path or parent project path).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print wt commands without launching.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    wt_exe = resolve_wt_executable()
    if not wt_exe:
        if args.dry_run:
            print("[warning] wt.exe was not found, running in dry-run with command preview only.")
            wt_exe = "wt.exe"
        else:
            raise RuntimeError("Windows Terminal command 'wt.exe' not found in PATH.")

    config_path = Path(args.config_path).expanduser().resolve()
    if not config_path.is_file():
        raise RuntimeError(f"Config file not found: {config_path}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    config_project_root = str(config.get("project_root", "")).strip()
    override_project_root = str(args.project_root_override or "").strip()
    if not config_project_root and not override_project_root:
        raise RuntimeError("Config must contain non-empty 'project_root' or pass --project-root-override.")

    effective_root = override_project_root or config_project_root
    project_root = resolve_dot_corrisbot_root(effective_root)
    if not project_root.is_dir():
        raise RuntimeError(f"Project root not found: {project_root}")

    project_tag = get_project_tag(project_root)
    loop_bat_path = (SCRIPT_DIR / "CodexLoop.bat").resolve()
    if not loop_bat_path.is_file():
        raise RuntimeError(f"CodexLoop.bat not found: {loop_bat_path}")

    windows = config.get("windows", [])
    if not isinstance(windows, list) or not windows:
        raise RuntimeError("Config must contain non-empty 'windows' array.")

    print(f"Project root: {project_root}")
    print(f"Project tag:  {project_tag}")
    print(f"Config file:  {config_path}")

    process_lines = get_process_command_lines()
    planned_launch_keys: set[tuple[str, str]] = set()

    for window in windows:
        if not isinstance(window, dict):
            continue
        window_name = str(window.get("name", "")).strip() or "CorrisBot"
        tabs = window.get("tabs", [])
        if not isinstance(tabs, list) or not tabs:
            print(f"[skip] Window '{window_name}' has no tabs.")
            continue

        window_args: list[str] = ["-w", window_name]
        has_commands = False

        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            tab_args = build_tab_arguments(
                tab_node=tab,
                project_root=project_root,
                project_tag=project_tag,
                loop_bat_path=loop_bat_path,
                process_lines=process_lines,
                planned_launch_keys=planned_launch_keys,
            )
            if not tab_args:
                continue
            if has_commands:
                window_args.append(";")
            window_args.extend(tab_args)
            has_commands = True

        if not has_commands:
            print(f"[skip] Window '{window_name}' has no new agents to launch.")
            continue

        if args.dry_run:
            print("[dry-run] wt " + format_args_for_display(window_args))
        else:
            subprocess.Popen([wt_exe, *window_args], cwd=str(SCRIPT_DIR))
            print(f"[ok] Launch command sent to WT window: {window_name}")
            time.sleep(0.15)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(130)
