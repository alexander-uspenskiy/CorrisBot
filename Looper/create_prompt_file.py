"""Create inter-looper prompt files with guaranteed timestamp format.

Usage examples:
  PowerShell:
    py "$env:LOOPER_ROOT\\create_prompt_file.py" create --inbox "Prompts\\Inbox\\Talker" --from-file "Temp\\report.md"
  cmd:
    py "%LOOPER_ROOT%\\create_prompt_file.py" create --inbox "Prompts\\Inbox\\Talker" --text "/looper stop"
"""

from __future__ import annotations

import argparse
import codecs
import sys
import uuid
import re
from datetime import datetime
from pathlib import Path


PROMPT_MARKER_RE = re.compile(
    r"^(?P<year>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})_"
    r"(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})_"
    r"(?P<millis>\d{3})(?:_(?P<suffix>[A-Za-z0-9]+))?$"
)
SUFFIX_RE = re.compile(r"^[A-Za-z0-9]+$")


def _make_base_marker() -> str:
    now = datetime.now()
    millis = int(now.microsecond / 1000)
    return now.strftime("%Y_%m_%d_%H_%M_%S_") + f"{millis:03d}"


def _validate_suffix(raw: str | None) -> str:
    if raw is None:
        return ""
    suffix = raw.strip()
    if not suffix:
        return ""
    if not SUFFIX_RE.fullmatch(suffix):
        raise ValueError("suffix must match [A-Za-z0-9]+")
    return suffix


def _allocate_prompt_path(inbox: Path, suffix: str) -> Path:
    base = _make_base_marker()

    for attempt in range(0, 1000):
        if suffix:
            suffix_part = suffix if attempt == 0 else f"{suffix}t{attempt:03d}"
            marker = f"{base}_{suffix_part}"
        else:
            marker = base if attempt == 0 else f"{base}_t{attempt:03d}"
        if PROMPT_MARKER_RE.fullmatch(marker) is None:
            continue

        prompt_path = inbox / f"Prompt_{marker}.md"
        result_path = inbox / f"Prompt_{marker}_Result.md"
        if not prompt_path.exists() and not result_path.exists():
            return prompt_path

    raise RuntimeError(f"could not allocate unique prompt marker in {inbox}")


def _read_text_from_file(src: Path) -> str:
    raw = src.read_bytes()
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig")
    if raw.startswith(codecs.BOM_UTF32_LE) or raw.startswith(codecs.BOM_UTF32_BE):
        return raw.decode("utf-32")
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        return raw.decode("utf-16")
    return raw.decode("utf-8")


def _read_content(args: argparse.Namespace) -> str:
    if args.from_file:
        src = Path(args.from_file).expanduser().resolve()
        if not src.exists():
            raise FileNotFoundError(f"source file not found: {src}")
        return _read_text_from_file(src)

    if args.text is not None:
        return args.text

    if args.stdin:
        return sys.stdin.read()

    raise RuntimeError("one of --from-file, --text, or --stdin is required")


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".tmp_{uuid.uuid4().hex}.part"
    try:
        tmp.write_text(content, encoding="utf-8", newline="\n")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _cmd_create(args: argparse.Namespace) -> int:
    try:
        inbox = Path(args.inbox).expanduser().resolve()
        suffix = _validate_suffix(args.suffix)
        content = _read_content(args)
        prompt_path = _allocate_prompt_path(inbox, suffix)
        _write_atomic(prompt_path, content)
        if not prompt_path.exists():
            raise RuntimeError(f"write verification failed: {prompt_path}")
        print(str(prompt_path))
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md file in a target inbox."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Create a prompt file with generated timestamp marker.")
    create.add_argument("--inbox", required=True, help="Target inbox folder path.")
    create.add_argument("--suffix", help="Optional marker suffix (alnum only).")
    group = create.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-file", help="Read prompt content from UTF text file (UTF-8 default, BOM-aware).")
    group.add_argument("--text", help="Prompt content passed as CLI text.")
    group.add_argument("--stdin", action="store_true", help="Read prompt content from stdin.")
    create.set_defaults(func=_cmd_create)

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
