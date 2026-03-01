"""Deliver a report via Reply-To with fail-closed route identity checks."""

from __future__ import annotations

import argparse
import codecs
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from route_contract_utils import (
    SUPPORTED_FILE_PATTERN,
    ensure_abs_path,
    ensure_reply_to_in_scope,
    ensure_route_meta_matches_contract,
    ensure_safe_token,
    extract_reply_to_fields,
    extract_route_meta_fields,
    try_extract_routing_contract_fields,
    extract_message_meta_fields,
    _is_relative_to,
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


def _load_routing_contract_file(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = [
        "Version",
        "RouteSessionID",
        "AppRoot",
        "AgentsRoot",
        "ProjectTag",
        "OrchestratorSenderID",
        "CreatedAtUTC",
    ]
    missing = [key for key in required if not str(payload.get(key, "")).strip()]
    if missing:
        raise RuntimeError(f"routing contract file missing required fields: {', '.join(missing)}")
    contract = {key: str(payload[key]).strip() for key in required}
    if contract["Version"] != "1":
        raise RuntimeError(f"unsupported Routing-Contract.Version in file: {contract['Version']!r}")
    ensure_safe_token("Routing-Contract.RouteSessionID", contract["RouteSessionID"])
    return contract


def _materialize_report_file(args: argparse.Namespace) -> Path:
    if args.report_file:
        report_path = Path(args.report_file).expanduser().resolve()
        if not report_path.exists():
            raise FileNotFoundError(f"report file not found: {report_path}")
        return report_path

    if args.text is not None:
        report_text = args.text
    else:
        report_text = sys.stdin.read()

    if args.local_report_file:
        target = Path(args.local_report_file).expanduser().resolve()
    else:
        target = (Path.cwd() / "Temp" / "reply_to_report.md").resolve()
    _write_text(target, report_text)
    return target


def _run_create_prompt(looper_root: Path, inbox: Path, report_file: Path, suffix: str | None) -> Path:
    cmd = [
        sys.executable,
        str(looper_root / "create_prompt_file.py"),
        "create",
        "--inbox",
        str(inbox),
        "--from-file",
        str(report_file),
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


def _check_audit_for_success(audit_file: Path, report_id: str, route_session_id: str, project_tag: str, inbox_path: str) -> bool:
    if not audit_file.exists():
        return False
    try:
        for line in audit_file.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            try:
                record = json.loads(line)
                if (record.get("report_id") == report_id and
                    record.get("route_session_id") == route_session_id and
                    record.get("project_tag") == project_tag and
                    record.get("inbox_path") == inbox_path and
                    record.get("result") == "ok"):
                    return True
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    return False


def _append_audit(audit_file: Path, record: dict) -> None:
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    with audit_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _validate_audit_file_scope(audit_file: Path, contract: dict[str, str]) -> None:
    r"""Validate that audit file path is within allowed scope for current sender.
    
    Allowed scopes:
    1. Talker scope: AppRoot\Talker\Temp\...
    2. Orchestrator scope: AgentsRoot\Orchestrator\Temp\...
    3. Worker scope: AgentsRoot\Workers\<WorkerId>\Temp\...
    """
    app_root = ensure_abs_path("Routing-Contract.AppRoot", contract["AppRoot"])
    agents_root = ensure_abs_path("Routing-Contract.AgentsRoot", contract["AgentsRoot"])
    
    talker_temp = (app_root / "Talker" / "Temp").resolve()
    orchestrator_temp = (agents_root / "Orchestrator" / "Temp").resolve()
    workers_root = (agents_root / "Workers").resolve()
    audit_resolved = audit_file.resolve()

    if _is_relative_to(audit_resolved, talker_temp):
        return

    if _is_relative_to(audit_resolved, orchestrator_temp):
        return

    if _is_relative_to(audit_resolved, workers_root):
        # Strict Worker policy: AgentsRoot\Workers\<WorkerId>\Temp\...
        rel_to_workers = audit_resolved.relative_to(workers_root)
        parts = rel_to_workers.parts
        if len(parts) >= 3 and parts[1] == "Temp":
            return

    raise RuntimeError(
        f"report_audit_path_missing_or_invalid: audit file is outside allowed scope: {audit_file}; "
        f"allowed roots: {talker_temp}, {orchestrator_temp}, {workers_root}\\<WorkerId>\\Temp"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Deliver report via Reply-To block from incoming prompt with fail-closed "
            "Route-Meta/Routing-Contract validation."
        )
    )
    parser.add_argument("--incoming-prompt", required=True, help="Path to incoming prompt file containing Reply-To block.")
    parser.add_argument(
        "--routing-contract-file",
        help="Optional pinned routing_contract.json path (required if incoming prompt does not carry Routing-Contract).",
    )
    parser.add_argument("--expected-route-session-id", help="Optional explicit expected RouteSessionID.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--report-file", help="Path to local report file.")
    input_group.add_argument("--text", help="Inline report text.")
    input_group.add_argument("--stdin", action="store_true", help="Read report text from stdin.")
    parser.add_argument(
        "--local-report-file",
        help="Target file for report text when using --text/--stdin (default: ./Temp/reply_to_report.md).",
    )
    parser.add_argument("--suffix", help="Optional create_prompt_file.py marker suffix.")
    parser.add_argument("--retry", type=int, default=1, help="Additional retry attempts after first send (default: 1).")
    parser.add_argument(
        "--audit-file",
        required=True,
        help="Absolute path to report_delivery_audit.jsonl (required). Must be within allowed scope.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        incoming_prompt = Path(args.incoming_prompt).expanduser().resolve()
        if not incoming_prompt.exists():
            raise FileNotFoundError(f"incoming prompt file not found: {incoming_prompt}")
        prompt_text = _read_text_file(incoming_prompt)

        route_meta = extract_route_meta_fields(prompt_text)

        contract_from_prompt = try_extract_routing_contract_fields(prompt_text)
        contract_from_file: dict[str, str] | None = None
        if args.routing_contract_file:
            contract_path = Path(args.routing_contract_file).expanduser().resolve()
            if not contract_path.exists():
                raise FileNotFoundError(f"routing contract file not found: {contract_path}")
            contract_from_file = _load_routing_contract_file(contract_path)

        contract = contract_from_prompt or contract_from_file
        if contract is None:
            raise RuntimeError("routing_contract_missing: no Routing-Contract in prompt and no --routing-contract-file")

        if contract_from_prompt and contract_from_file:
            for key in [
                "RouteSessionID",
                "AppRoot",
                "AgentsRoot",
                "ProjectTag",
                "OrchestratorSenderID",
            ]:
                if contract_from_prompt[key] != contract_from_file[key]:
                    raise RuntimeError(
                        "routing_contract_mismatch: prompt contract and file contract differ on "
                        f"{key}: {contract_from_prompt[key]!r} vs {contract_from_file[key]!r}"
                    )

        ensure_route_meta_matches_contract(route_meta, contract)

        if args.expected_route_session_id:
            expected_session = args.expected_route_session_id.strip()
            if not expected_session:
                raise RuntimeError("expected-route-session-id is empty")
            if expected_session != contract["RouteSessionID"]:
                raise RuntimeError(
                    "routing_session_mismatch: expected-route-session-id does not match contract RouteSessionID"
                )

        fields = extract_reply_to_fields(prompt_text)
        file_pattern = fields.get("FilePattern", "").strip()
        if file_pattern and file_pattern != SUPPORTED_FILE_PATTERN:
            raise RuntimeError(f"unsupported FilePattern: {file_pattern}")

        inbox = ensure_abs_path("Reply-To.InboxPath", fields["InboxPath"])
        ensure_reply_to_in_scope(inbox, contract)
        inbox.mkdir(parents=True, exist_ok=True)
        report_file = _materialize_report_file(args)

        report_text = _read_text_file(report_file)
        msg_meta = extract_message_meta_fields(report_text)
        
        if msg_meta["RouteSessionID"] != contract["RouteSessionID"]:
             raise RuntimeError(f"Message-Meta.RouteSessionID does not match contract: {msg_meta['RouteSessionID']} vs {contract['RouteSessionID']}")
        if msg_meta["ProjectTag"] != contract["ProjectTag"]:
             raise RuntimeError(f"Message-Meta.ProjectTag does not match contract: {msg_meta['ProjectTag']} vs {contract['ProjectTag']}")

        # Validate audit-file argument (required, absolute, in-scope)
        if not args.audit_file:
            raise RuntimeError("report_audit_path_missing_or_invalid: --audit-file is required")
        
        audit_file = Path(args.audit_file).expanduser()
        if not audit_file.is_absolute():
            raise RuntimeError(f"report_audit_path_missing_or_invalid: --audit-file must be absolute path: {args.audit_file!r}")
        
        audit_file = audit_file.resolve()
        _validate_audit_file_scope(audit_file, contract)

        if _check_audit_for_success(audit_file, msg_meta["ReportID"], contract["RouteSessionID"], contract["ProjectTag"], str(inbox)):
            result = {
                "status": "ok",
                "route_session_id": contract["RouteSessionID"],
                "project_tag": contract["ProjectTag"],
                "inbox_path": str(inbox),
                "sender_id": fields.get("SenderID", "").strip(),
                "file_pattern": file_pattern or SUPPORTED_FILE_PATTERN,
                "report_file": str(report_file),
                "delivered_file": "<idempotent_skip>",
                "attempts_used": 0,
            }
            print(json.dumps(result, ensure_ascii=False))
            return 0

        looper_root = Path(__file__).resolve().parent
        delivered_file: Path | None = None
        last_error: Exception | None = None
        total_attempts = max(1, int(args.retry) + 1)

        for attempt in range(1, total_attempts + 1):
            try:
                candidate = _run_create_prompt(looper_root, inbox, report_file, args.suffix)
                if not candidate.exists():
                    raise RuntimeError(f"delivery verification failed: file not found after create: {candidate}")
                if candidate.parent.resolve() != inbox:
                    raise RuntimeError(
                        "delivery verification failed: prompt created in unexpected inbox: "
                        f"{candidate.parent} (expected {inbox})"
                    )
                if PROMPT_FILENAME_RE.fullmatch(candidate.name) is None:
                    raise RuntimeError(f"delivery verification failed: invalid prompt filename: {candidate.name}")
                delivered_file = candidate
                break
            except Exception as exc:  # pragma: no cover - exercised in integration tests
                last_error = exc

        audit_record = {
            "report_id": msg_meta["ReportID"],
            "route_session_id": contract["RouteSessionID"],
            "project_tag": contract["ProjectTag"],
            "inbox_path": str(inbox),
            "message_class": msg_meta["MessageClass"],
            "report_type": msg_meta["ReportType"],
            "delivered_file": str(delivered_file) if delivered_file else None,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "result": "ok" if delivered_file else "failed",
            "error": str(last_error) if last_error else None
        }
        _append_audit(audit_file, audit_record)

        if delivered_file is None:
            raise RuntimeError(f"delivery failed after {total_attempts} attempt(s): {last_error}")

        result = {
            "status": "ok",
            "route_session_id": contract["RouteSessionID"],
            "project_tag": contract["ProjectTag"],
            "inbox_path": str(inbox),
            "sender_id": fields.get("SenderID", "").strip(),
            "file_pattern": file_pattern or SUPPORTED_FILE_PATTERN,
            "report_file": str(report_file),
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
