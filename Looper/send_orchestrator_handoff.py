r"""Create and deliver Talker -> Orchestrator handoff prompt in one deterministic step.

Usage examples:
  PowerShell (first prompt in project session):
    py "$env:LOOPER_ROOT\send_orchestrator_handoff.py" `
      --project-root "C:\Temp\MyProject" `
      --talker-root "$env:TALKER_ROOT" `
      --user-message-file "C:\Temp\user_message.md" `
      --include-reply-to

  cmd (subsequent prompt in same session):
    py "%LOOPER_ROOT%\send_orchestrator_handoff.py" ^
      --project-root "C:\Temp\MyProject" ^
      --talker-root "%TALKER_ROOT%" ^
      --user-message-file "C:\Temp\user_message.md" ^
      --omit-reply-to
"""

from __future__ import annotations

import argparse
import codecs
import json
import os
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_SCOPE = (
    "use this Reply-To for all further reports/questions in this project session "
    "until Talker sends updated Reply-To"
)
PROMPT_FILENAME_RE = re.compile(r"^Prompt_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_\d{3}(?:_[A-Za-z0-9]+)?\.md$")


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig")
    if raw.startswith(codecs.BOM_UTF32_LE) or raw.startswith(codecs.BOM_UTF32_BE):
        return raw.decode("utf-32")
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        return raw.decode("utf-16")
    return raw.decode("utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _derive_project_tag(project_root: Path) -> str:
    return project_root.name


def _build_handoff_content(
    *,
    user_message: str,
    include_reply_to: bool,
    reply_to_inbox: Path,
    sender_id: str,
    scope: str,
) -> str:
    chunks: list[str] = []
    if include_reply_to:
        chunks.extend(
            [
                "Reply-To:",
                f"- InboxPath: {reply_to_inbox}",
                f"- SenderID: {sender_id}",
                "- FilePattern: Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md",
                f"- Scope: {scope}",
                "",
            ]
        )

    chunks.append("---BEGIN USER MESSAGE (VERBATIM)---")
    chunks.append(user_message)
    if user_message and not user_message.endswith("\n"):
        chunks.append("")
    chunks.append("---END USER MESSAGE (VERBATIM)---")
    return "\n".join(chunks)


def _run_create_prompt(
    *,
    looper_root: Path,
    inbox: Path,
    handoff_file: Path,
    suffix: str | None,
) -> Path:
    cmd = [
        sys.executable,
        str(looper_root / "create_prompt_file.py"),
        "create",
        "--inbox",
        str(inbox),
        "--from-file",
        str(handoff_file),
    ]
    if suffix:
        cmd.extend(["--suffix", suffix])

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(
            "create_prompt_file.py failed: "
            f"exit={proc.returncode}; stdout={proc.stdout.strip()!r}; stderr={proc.stderr.strip()!r}"
        )

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("create_prompt_file.py produced empty stdout")

    candidates: list[Path] = []
    for line in lines:
        candidate = Path(line).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if PROMPT_FILENAME_RE.fullmatch(candidate.name):
            candidates.append(candidate)
    if not candidates:
        raise RuntimeError(f"create_prompt_file.py returned no Prompt_*.md path in stdout: {proc.stdout!r}")

    return candidates[-1]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create Talker->Orchestrator handoff markdown (with optional Reply-To block), "
            "deliver it via create_prompt_file.py, and verify resulting Prompt_*.md."
        )
    )
    parser.add_argument("--project-root", required=True, help="Project workspace root path.")
    parser.add_argument(
        "--talker-root",
        help="Talker root path. If omitted, uses TALKER_ROOT env var.",
    )
    parser.add_argument(
        "--user-message-file",
        required=True,
        help="Path to file containing user text to be forwarded verbatim.",
    )
    parser.add_argument(
        "--project-tag",
        help="Optional project tag; default is terminal folder name of project root.",
    )
    parser.add_argument(
        "--sender-id",
        help="Optional sender id for Reply-To; default is Orc_<ProjectTag>.",
    )
    parser.add_argument(
        "--local-handoff-file",
        help="Optional output path for generated handoff markdown.",
    )
    parser.add_argument(
        "--suffix",
        help="Optional create_prompt_file.py marker suffix (alnum only).",
    )
    parser.add_argument(
        "--scope",
        default=DEFAULT_SCOPE,
        help="Reply-To scope text used only when Reply-To block is included.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--include-reply-to",
        action="store_true",
        help="Include Reply-To block (recommended for first prompt in project session).",
    )
    mode.add_argument(
        "--omit-reply-to",
        action="store_true",
        help="Do not include Reply-To block (recommended when route already fixed for the session).",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        project_root = Path(args.project_root).expanduser().resolve()
        if not project_root.exists():
            raise FileNotFoundError(f"project root not found: {project_root}")

        talker_root_arg = args.talker_root or os.environ.get("TALKER_ROOT", "")
        if not talker_root_arg.strip():
            raise RuntimeError("talker root is required: pass --talker-root or set TALKER_ROOT env var")
        talker_root = Path(talker_root_arg).expanduser().resolve()
        if not talker_root.exists():
            raise FileNotFoundError(f"talker root not found: {talker_root}")

        looper_root = Path(__file__).resolve().parent
        create_prompt_script = looper_root / "create_prompt_file.py"
        if not create_prompt_script.exists():
            raise FileNotFoundError(f"missing helper script: {create_prompt_script}")

        user_message_file = Path(args.user_message_file).expanduser().resolve()
        if not user_message_file.exists():
            raise FileNotFoundError(f"user message file not found: {user_message_file}")
        user_message = _read_text_file(user_message_file)

        project_tag = (args.project_tag or _derive_project_tag(project_root)).strip()
        if not project_tag:
            raise RuntimeError("derived/explicit project tag is empty")
        sender_id = (args.sender_id or f"Orc_{project_tag}").strip()
        if not sender_id:
            raise RuntimeError("sender id is empty")

        include_reply_to = not args.omit_reply_to
        reply_to_inbox = (talker_root / "Prompts" / "Inbox" / sender_id).resolve()
        orchestrator_inbox = (project_root / "Orchestrator" / "Prompts" / "Inbox" / "Talker").resolve()
        orchestrator_inbox.mkdir(parents=True, exist_ok=True)
        if include_reply_to:
            reply_to_inbox.mkdir(parents=True, exist_ok=True)

        if args.local_handoff_file:
            local_handoff_file = Path(args.local_handoff_file).expanduser().resolve()
        else:
            local_handoff_file = (talker_root / "Temp" / f"handoff_to_orchestrator_{project_tag}.md").resolve()

        handoff_content = _build_handoff_content(
            user_message=user_message,
            include_reply_to=include_reply_to,
            reply_to_inbox=reply_to_inbox,
            sender_id=sender_id,
            scope=args.scope,
        )
        _write_text(local_handoff_file, handoff_content)

        delivered_file = _run_create_prompt(
            looper_root=looper_root,
            inbox=orchestrator_inbox,
            handoff_file=local_handoff_file,
            suffix=args.suffix,
        )
        if not delivered_file.exists():
            raise RuntimeError(f"delivered prompt file not found after create: {delivered_file}")
        if delivered_file.parent.resolve() != orchestrator_inbox:
            raise RuntimeError(
                "delivered prompt file was created in unexpected inbox: "
                f"{delivered_file.parent} (expected {orchestrator_inbox})"
            )
        if PROMPT_FILENAME_RE.fullmatch(delivered_file.name) is None:
            raise RuntimeError(f"unexpected prompt filename format: {delivered_file.name}")

        result = {
            "status": "ok",
            "project_root": str(project_root),
            "orchestrator_inbox": str(orchestrator_inbox),
            "local_handoff_file": str(local_handoff_file),
            "delivered_file": str(delivered_file),
            "reply_to_included": include_reply_to,
            "reply_to_inbox": str(reply_to_inbox) if include_reply_to else "",
            "sender_id": sender_id,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
