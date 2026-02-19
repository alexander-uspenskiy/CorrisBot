"""Launch multiple loopers sequentially via StartLoopsInWT.bat.

This helper removes fragile ad-hoc multi-command orchestration for WT startup.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start multiple loopers sequentially using StartLoopsInWT.bat."
    )
    parser.add_argument("--project-root", required=True, help="Project root path.")
    parser.add_argument("agent_paths", nargs="+", help="One or more looper agent paths.")
    parser.add_argument("--runner", choices=["codex", "kimi"], help="Runner override for StartLoopsInWT.bat.")
    parser.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high"],
        help="Per-call Codex reasoning effort override.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to StartLoopsInWT.bat.")
    return parser


def _run_one(start_bat: Path, project_root: Path, agent_path: str, args: argparse.Namespace) -> tuple[int, str, str, list[str]]:
    cmd = ["cmd", "/c", str(start_bat), str(project_root), agent_path]
    if args.runner:
        cmd.extend(["--runner", args.runner])
    if args.reasoning_effort:
        cmd.extend(["--reasoning-effort", args.reasoning_effort])
    if args.dry_run:
        cmd.append("--dry-run")

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr, cmd


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        project_root = Path(args.project_root).expanduser().resolve()
        if not project_root.is_dir():
            raise RuntimeError(f"project root not found: {project_root}")

        # StartLoopsInWT.py uses project Temp/state path for lock files.
        (project_root / "Temp").mkdir(parents=True, exist_ok=True)

        looper_root = Path(__file__).resolve().parent
        start_bat = looper_root / "StartLoopsInWT.bat"
        if not start_bat.exists():
            raise RuntimeError(f"StartLoopsInWT.bat not found: {start_bat}")

        launched: list[dict[str, str | int]] = []
        for idx, agent_path in enumerate(args.agent_paths, start=1):
            code, stdout, stderr, cmd = _run_one(start_bat, project_root, agent_path, args)
            if code != 0:
                raise RuntimeError(
                    "sequential launch failed on step "
                    f"{idx}/{len(args.agent_paths)} for agent '{agent_path}' "
                    f"(exit={code}). stdout={stdout.strip()!r}; stderr={stderr.strip()!r}; cmd={cmd!r}"
                )
            launched.append(
                {
                    "step": idx,
                    "agent_path": agent_path,
                    "exit_code": code,
                }
            )

        print(
            json.dumps(
                {
                    "status": "ok",
                    "project_root": str(project_root),
                    "launched": launched,
                    "dry_run": bool(args.dry_run),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
