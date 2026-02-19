"""Deliver a report to upstream looper using Reply-To block from incoming prompt.

This helper replaces ad-hoc shell snippets for Reply-To routing:
extract -> ensure/create inbox -> create prompt via create_prompt_file.py ->
verify file exists -> retry once on failure.
"""

from __future__ import annotations

import argparse
import codecs
import json
import re
import subprocess
import sys
from pathlib import Path


SUPPORTED_FILE_PATTERN = "Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md"
PROMPT_FILENAME_RE = re.compile(r"^Prompt_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_\d{3}(?:_[A-Za-z0-9]+)?\.md$")
PLACEHOLDER_RE = re.compile(r"^<[^>]+>$")
REPLY_ITEM_RE = re.compile(r"^-\s*([A-Za-z0-9_-]+)\s*:\s*(.*)$")


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


def _extract_reply_to_fields(prompt_text: str) -> dict[str, str]:
    lines = prompt_text.splitlines()
    in_code_fence = False

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if stripped.startswith(">"):
            continue
        if stripped != "Reply-To:":
            continue

        fields: dict[str, str] = {}
        for tail in lines[idx + 1 :]:
            s = tail.strip()
            if not s:
                if fields:
                    break
                continue
            if s.startswith("```") or s.startswith(">"):
                break
            m = REPLY_ITEM_RE.match(s)
            if not m:
                if fields:
                    break
                continue
            fields[m.group(1)] = m.group(2).strip()

        inbox = fields.get("InboxPath", "").strip()
        if inbox:
            if PLACEHOLDER_RE.fullmatch(inbox):
                raise RuntimeError(f"Reply-To.InboxPath is placeholder and cannot be used: {inbox}")
            return fields

    raise RuntimeError("valid Reply-To block not found in incoming prompt")


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Deliver report via Reply-To block from incoming prompt: "
            "extract route, ensure inbox, create Prompt_*.md, verify delivery."
        )
    )
    parser.add_argument("--incoming-prompt", required=True, help="Path to incoming prompt file containing Reply-To block.")
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
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        incoming_prompt = Path(args.incoming_prompt).expanduser().resolve()
        if not incoming_prompt.exists():
            raise FileNotFoundError(f"incoming prompt file not found: {incoming_prompt}")
        prompt_text = _read_text_file(incoming_prompt)
        fields = _extract_reply_to_fields(prompt_text)

        file_pattern = fields.get("FilePattern", "").strip()
        if file_pattern and file_pattern != SUPPORTED_FILE_PATTERN:
            raise RuntimeError(f"unsupported FilePattern: {file_pattern}")

        inbox = Path(fields["InboxPath"]).expanduser().resolve()
        inbox.mkdir(parents=True, exist_ok=True)
        report_file = _materialize_report_file(args)

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

        if delivered_file is None:
            raise RuntimeError(f"delivery failed after {total_attempts} attempt(s): {last_error}")

        result = {
            "status": "ok",
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
