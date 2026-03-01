r"""Create and deliver Talker -> Orchestrator handoff prompt in one deterministic step.

This helper enforces fail-closed route identity:
- embeds Route-Meta in every handoff;
- embeds Routing-Contract (v1) for session consistency;
- optionally embeds Reply-To for Orchestrator -> Talker channel.
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from route_contract_utils import (
    SUPPORTED_FILE_PATTERN,
    ensure_abs_path,
    ensure_path_in_root,
    ensure_safe_token,
)

from project_registry import (
    derive_talker_root,
    derive_app_root,
    lookup_project,
    update_project,
    generate_session_id,
)

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


def _write_json(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _contract_filename(route_session_id: str) -> str:
    session_hash = hashlib.sha256(route_session_id.encode("utf-8")).hexdigest()[:12]
    return f"routing_contract_{session_hash}.json"


def _build_handoff_content(
    *,
    user_message: str,
    include_reply_to: bool,
    reply_to_inbox: Path,
    sender_id: str,
    scope: str,
    route_session_id: str,
    project_tag: str,
    routing_contract: dict[str, str],
) -> str:
    chunks: list[str] = [
        "Route-Meta:",
        f"- RouteSessionID: {route_session_id}",
        f"- ProjectTag: {project_tag}",
        "",
        "Routing-Contract:",
        f"- Version: {routing_contract['Version']}",
        f"- RouteSessionID: {routing_contract['RouteSessionID']}",
        f"- AppRoot: {routing_contract['AppRoot']}",
        f"- AgentsRoot: {routing_contract['AgentsRoot']}",
        f"- ProjectTag: {routing_contract['ProjectTag']}",
        f"- OrchestratorSenderID: {routing_contract['OrchestratorSenderID']}",
        f"- CreatedAtUTC: {routing_contract['CreatedAtUTC']}",
        "",
    ]

    if include_reply_to:
        chunks.extend(
            [
                "Reply-To:",
                f"- InboxPath: {reply_to_inbox}",
                f"- SenderID: {sender_id}",
                f"- FilePattern: {SUPPORTED_FILE_PATTERN}",
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
            "Create Talker->Orchestrator handoff markdown with Route-Meta/Routing-Contract "
            "(and optional Reply-To), deliver it and verify resulting Prompt_*.md."
        )
    )
    # Mandatory
    parser.add_argument("--project-tag", required=True, help="Project tag (key in registry).")
    parser.add_argument(
        "--user-message-file",
        required=True,
        help="Path to file containing user text to be forwarded verbatim.",
    )

    # Optional
    parser.add_argument("--new-session", action="store_true", help="Force generate new route_session_id.")
    reply_mode = parser.add_mutually_exclusive_group()
    reply_mode.add_argument(
        "--include-reply-to",
        action="store_true",
        help="Include Reply-To block (recommended for first prompt in project session).",
    )
    reply_mode.add_argument(
        "--omit-reply-to",
        action="store_true",
        help="Do not include Reply-To block (when route already fixed for the session).",
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
    parser.add_argument(
        "--created-at-utc",
        help="Optional contract timestamp; default current UTC ISO-8601.",
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
        "--routing-contract-file",
        help="Optional output path for persisted Routing-Contract JSON.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        talker_root = derive_talker_root()
        app_root = derive_app_root()
        
        project = lookup_project(talker_root, args.project_tag)
        
        project_root = ensure_abs_path("project-root", project["project_root"])
        if not project_root.exists():
            raise FileNotFoundError(f"project root found in registry does not exist: {project_root}")
        
        agents_root = project_root
        
        if args.new_session:
            route_session_id = generate_session_id(args.project_tag)
            update_project(talker_root, args.project_tag, route_session_id=route_session_id)
        else:
            route_session_id = project.get("route_session_id", "")
            if not route_session_id:
                route_session_id = generate_session_id(args.project_tag)
                update_project(talker_root, args.project_tag, route_session_id=route_session_id)
        
        ensure_safe_token("route-session-id", route_session_id)
        
        expected_talker_root = (app_root / "Talker").resolve()
        if talker_root != expected_talker_root:
            raise RuntimeError(
                f"talker-root mismatch: expected {expected_talker_root} from app-root, got {talker_root}"
            )
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

        project_tag = args.project_tag
        sender_id = (args.sender_id or f"Orc_{project_tag}").strip()
        if not sender_id:
            raise RuntimeError("sender id is empty")

        created_at_utc = (args.created_at_utc or datetime.now(timezone.utc).isoformat()).strip()
        if not created_at_utc:
            raise RuntimeError("created-at-utc is empty")

        include_reply_to = not args.omit_reply_to
        reply_to_inbox = (talker_root / "Prompts" / "Inbox" / sender_id).resolve()
        orchestrator_inbox = (agents_root / "Orchestrator" / "Prompts" / "Inbox" / "Talker").resolve()
        ensure_path_in_root(orchestrator_inbox, agents_root, "orchestrator inbox")
        ensure_path_in_root(reply_to_inbox, talker_root, "reply-to inbox")
        
        orchestrator_inbox.mkdir(parents=True, exist_ok=True)
        if include_reply_to:
            reply_to_inbox.mkdir(parents=True, exist_ok=True)

        routing_contract = {
            "Version": "1",
            "RouteSessionID": route_session_id,
            "AppRoot": str(app_root),
            "AgentsRoot": str(agents_root),
            "ProjectTag": project_tag,
            "OrchestratorSenderID": sender_id,
            "CreatedAtUTC": created_at_utc,
        }

        if args.routing_contract_file:
            routing_contract_file = Path(args.routing_contract_file).expanduser().resolve()
        else:
            routing_contract_file = (talker_root / "Temp" / _contract_filename(route_session_id)).resolve()
        _write_json(routing_contract_file, routing_contract)

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
            route_session_id=route_session_id,
            project_tag=project_tag,
            routing_contract=routing_contract,
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
            "route_session_id": route_session_id,
            "project_tag": project_tag,
            "project_root": str(agents_root),
            "app_root": str(app_root),
            "talker_root": str(talker_root),
            "orchestrator_inbox": str(orchestrator_inbox),
            "local_handoff_file": str(local_handoff_file),
            "routing_contract_file": str(routing_contract_file),
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
