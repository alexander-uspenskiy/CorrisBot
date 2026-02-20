"""Resolver bridge CLI for batch launchers.

Contract:
- resolve_agent_config.py --agent-dir <path> --format bat_env
- stdout: CMD-ready lines: set "KEY=VALUE"
- failure: non-zero exit code + single-line machine-readable error code on stderr
"""

from __future__ import annotations

import argparse
import re
import sys

from agent_config_resolver import ResolverError, resolve_agent_config


SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9._-]*$")


class _MachineCodeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ResolverError("argument_error", message)


def _to_cmd_safe(value: str) -> str:
    if SAFE_VALUE_RE.fullmatch(value):
        return value
    return f"hex_{value.encode('utf-8').hex()}"


def _emit_bat_env(payload: dict[str, object]) -> str:
    effective = payload["effective"]
    source = payload["source"]

    mapping = [
        ("RUNNER", str(effective["runner"])),
        ("MODEL", str(effective["model"])),
        ("REASONING_EFFORT", str(effective["reasoning"])),
        ("SOURCE_RUNNER", str(source["runner"])),
        ("SOURCE_MODEL", str(source["model"])),
        ("SOURCE_REASONING", str(source["reasoning"])),
    ]
    return "\n".join(f'set "{key}={_to_cmd_safe(value)}"' for key, value in mapping)


def _build_parser() -> argparse.ArgumentParser:
    parser = _MachineCodeArgumentParser(description="Resolve per-agent effective config for batch consumers.")
    parser.add_argument("--agent-dir", required=True, help="Agent directory path.")
    parser.add_argument("--format", default="bat_env", help="Output format (supported: bat_env).")
    parser.add_argument("--runner", help="Optional CLI runner override.")
    parser.add_argument("--model", help="Optional CLI model override.")
    parser.add_argument("--reasoning-effort", help="Optional CLI reasoning override.")
    return parser


def main() -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args()
        if args.format != "bat_env":
            raise ResolverError("unsupported_format", f"unsupported format: {args.format}")

        resolved = resolve_agent_config(
            agent_dir=args.agent_dir,
            cli_runner=args.runner,
            cli_model=args.model,
            cli_reasoning_effort=args.reasoning_effort,
        )
        print(_emit_bat_env(resolved))
        return 0
    except ResolverError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    except Exception:
        print("internal_error", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
