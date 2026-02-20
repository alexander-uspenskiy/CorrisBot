"""Deliver Orchestrator -> Worker task with deterministic fail-closed routing."""

from __future__ import annotations

import argparse
import codecs
import json
import re
import subprocess
import sys
from pathlib import Path

from route_contract_utils import (
    SUPPORTED_FILE_PATTERN,
    ensure_abs_path,
    ensure_path_in_root,
    ensure_safe_token,
)


PROMPT_FILENAME_RE = re.compile(r"^Prompt_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_\d{3}(?:_[A-Za-z0-9]+)?\.md$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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


def _require_safe_id(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise RuntimeError(f"{name} is empty")
    if SAFE_ID_RE.fullmatch(normalized) is None:
        raise RuntimeError(f"{name} must match [A-Za-z0-9_-]+, got: {value!r}")
    return normalized


def _require_path_segment(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise RuntimeError(f"{name} is empty")
    if normalized in {".", ".."}:
        raise RuntimeError(f"{name} cannot be dot-segment: {value!r}")
    if "/" in normalized or "\\" in normalized:
        raise RuntimeError(f"{name} cannot contain path separators: {value!r}")
    if ":" in normalized:
        raise RuntimeError(f"{name} cannot contain drive separator ':': {value!r}")
    return normalized


def _load_routing_contract(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = [
        "Version",
        "RouteSessionID",
        "AppRoot",
        "AgentsRoot",
        "EditRoot",
        "ProjectTag",
        "OrchestratorSenderID",
        "CreatedAtUTC",
    ]
    missing = [key for key in required if not str(payload.get(key, "")).strip()]
    if missing:
        raise RuntimeError(f"routing contract missing required fields: {', '.join(missing)}")
    contract = {key: str(payload[key]).strip() for key in required}
    if contract["Version"] != "1":
        raise RuntimeError(f"unsupported Routing-Contract.Version: {contract['Version']!r}")
    ensure_safe_token("Routing-Contract.RouteSessionID", contract["RouteSessionID"])
    return contract


def _materialize_task_source(args: argparse.Namespace, worker_id: str) -> Path:
    if args.task_file:
        source = Path(args.task_file).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"task file not found: {source}")
        return source

    if args.text is not None:
        task_text = args.text
    else:
        task_text = sys.stdin.read()

    if args.local_task_file:
        source = Path(args.local_task_file).expanduser().resolve()
    else:
        source = (Path.cwd() / "Temp" / f"worker_task_{worker_id}.md").resolve()
    _write_text(source, task_text)
    return source


def _build_task_payload(
    *,
    task_text: str,
    contract: dict[str, str],
    reply_to_inbox: Path,
    reply_to_sender_id: str,
) -> str:
    chunks = [
        "Route-Meta:",
        f"- RouteSessionID: {contract['RouteSessionID']}",
        f"- ProjectTag: {contract['ProjectTag']}",
        "",
        "Routing-Contract:",
        f"- Version: {contract['Version']}",
        f"- RouteSessionID: {contract['RouteSessionID']}",
        f"- AppRoot: {contract['AppRoot']}",
        f"- AgentsRoot: {contract['AgentsRoot']}",
        f"- EditRoot: {contract['EditRoot']}",
        f"- ProjectTag: {contract['ProjectTag']}",
        f"- OrchestratorSenderID: {contract['OrchestratorSenderID']}",
        f"- CreatedAtUTC: {contract['CreatedAtUTC']}",
        "",
        "Reply-To:",
        f"- InboxPath: {reply_to_inbox}",
        f"- SenderID: {reply_to_sender_id}",
        f"- FilePattern: {SUPPORTED_FILE_PATTERN}",
        "",
        task_text,
    ]
    return "\n".join(chunks)


def _run_create_prompt(looper_root: Path, inbox: Path, task_file: Path, suffix: str | None) -> Path:
    cmd = [
        sys.executable,
        str(looper_root / "create_prompt_file.py"),
        "create",
        "--inbox",
        str(inbox),
        "--from-file",
        str(task_file),
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
            "Deterministic Orchestrator->Worker transport helper: "
            "resolve worker inbox from Routing-Contract, inject Route-Meta/Reply-To, deliver Prompt_*.md."
        )
    )
    parser.add_argument("--routing-contract-file", required=True, help="Path to pinned routing_contract.json.")
    parser.add_argument("--worker-id", required=True, help="Worker folder name (for example: Worker_001).")
    parser.add_argument(
        "--reply-to-folder",
        help="Folder under Orchestrator\\Prompts\\Inbox for worker reports (default: <worker-id>).",
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--task-file", help="Path to local task markdown file.")
    input_group.add_argument("--text", help="Inline task text.")
    input_group.add_argument("--stdin", action="store_true", help="Read task text from stdin.")
    parser.add_argument(
        "--local-task-file",
        help="Output file for task text when using --text/--stdin (default: ./Temp/worker_task_<worker>.md).",
    )
    parser.add_argument(
        "--local-envelope-file",
        help="Output file for generated task envelope (default: ./Temp/worker_task_envelope_<worker>.md).",
    )
    parser.add_argument("--suffix", help="Optional create_prompt_file.py marker suffix.")
    parser.add_argument("--retry", type=int, default=1, help="Additional retry attempts after first send (default: 1).")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        routing_contract_file = Path(args.routing_contract_file).expanduser().resolve()
        if not routing_contract_file.exists():
            raise FileNotFoundError(f"routing contract file not found: {routing_contract_file}")
        contract = _load_routing_contract(routing_contract_file)

        agents_root = ensure_abs_path("Routing-Contract.AgentsRoot", contract["AgentsRoot"])
        if not agents_root.exists():
            raise FileNotFoundError(f"agents root not found: {agents_root}")

        worker_id = _require_safe_id("worker-id", args.worker_id)
        sender_id = _require_path_segment("sender-id", contract["OrchestratorSenderID"])
        reply_to_folder = _require_safe_id("reply-to-folder", args.reply_to_folder or worker_id)

        worker_root = (agents_root / "Workers" / worker_id).resolve()
        if not worker_root.exists():
            raise RuntimeError(f"worker root not found in agents root: {worker_root}")

        worker_inbox = (worker_root / "Prompts" / "Inbox" / sender_id).resolve()
        reply_to_inbox = (agents_root / "Orchestrator" / "Prompts" / "Inbox" / reply_to_folder).resolve()
        ensure_path_in_root(worker_inbox, agents_root, "worker inbox")
        ensure_path_in_root(reply_to_inbox, agents_root, "reply-to inbox")

        task_source = _materialize_task_source(args, worker_id)
        task_text = _read_text_file(task_source)
        payload_text = _build_task_payload(
            task_text=task_text,
            contract=contract,
            reply_to_inbox=reply_to_inbox,
            reply_to_sender_id=sender_id,
        )

        if args.local_envelope_file:
            envelope_file = Path(args.local_envelope_file).expanduser().resolve()
        else:
            envelope_file = (Path.cwd() / "Temp" / f"worker_task_envelope_{worker_id}.md").resolve()
        _write_text(envelope_file, payload_text)

        worker_inbox.mkdir(parents=True, exist_ok=True)
        reply_to_inbox.mkdir(parents=True, exist_ok=True)

        looper_root = Path(__file__).resolve().parent
        delivered_file: Path | None = None
        last_error: Exception | None = None
        total_attempts = max(1, int(args.retry) + 1)

        for attempt in range(1, total_attempts + 1):
            try:
                candidate = _run_create_prompt(looper_root, worker_inbox, envelope_file, args.suffix)
                if not candidate.exists():
                    raise RuntimeError(f"delivery verification failed: file not found after create: {candidate}")
                if candidate.parent.resolve() != worker_inbox:
                    raise RuntimeError(
                        "delivery verification failed: prompt created in unexpected inbox: "
                        f"{candidate.parent} (expected {worker_inbox})"
                    )
                if PROMPT_FILENAME_RE.fullmatch(candidate.name) is None:
                    raise RuntimeError(f"delivery verification failed: invalid prompt filename: {candidate.name}")
                delivered_file = candidate
                break
            except Exception as exc:  # pragma: no cover - integration behavior
                last_error = exc

        if delivered_file is None:
            raise RuntimeError(f"delivery failed after {total_attempts} attempt(s): {last_error}")

        result = {
            "status": "ok",
            "route_session_id": contract["RouteSessionID"],
            "project_tag": contract["ProjectTag"],
            "worker_id": worker_id,
            "worker_inbox": str(worker_inbox),
            "reply_to_inbox": str(reply_to_inbox),
            "task_source": str(task_source),
            "envelope_file": str(envelope_file),
            "delivered_file": str(delivered_file),
            "attempts_used": attempt,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
