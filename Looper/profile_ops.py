"""Deterministic profile operations helper for per-agent runner/model/reasoning.

Phase 5 scope:
- validate profile set
- set runner
- set backend model/reasoning
- enforce ownership/authorization rules
- mandatory lock + atomic replace writes
- append audit log record (ok/error)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_config_resolver import (
    ALLOWED_RUNNERS,
    ResolverError,
    discover_runtime_root,
    normalize_agent_dir,
)


PROFILE_FILE_BY_RUNNER = {
    "codex": "codex_profile.json",
    "kimi": "kimi_profile.json",
}

DEFAULT_LOCK_TIMEOUT = 5.0
LOCK_STALE_SECONDS = 30.0


@dataclass(frozen=True)
class ProfileOpsError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class _MachineCodeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ProfileOpsError("argument_error", message)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_json_dict(path: Path, missing_code: str, invalid_code: str) -> dict[str, Any]:
    if not path.is_file():
        raise ProfileOpsError(missing_code, f"missing file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProfileOpsError(invalid_code, f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProfileOpsError(invalid_code, f"JSON object expected: {path}")
    return payload


def _load_registry(runtime_root: Path) -> dict[str, Any]:
    path = runtime_root / "AgentRunner" / "model_registry.json"
    registry = _load_json_dict(path, "registry_missing", "registry_invalid_json")

    blocks: dict[str, Any] = {}
    for runner in ALLOWED_RUNNERS:
        block = registry.get(runner)
        if not isinstance(block, dict):
            raise ProfileOpsError(
                "registry_backend_invalid",
                f"registry backend block must be object: {runner}",
            )
        models = block.get("models")
        default_model = block.get("default_model")
        if (
            not isinstance(models, list)
            or not models
            or not all(isinstance(item, str) and item for item in models)
        ):
            raise ProfileOpsError(
                "registry_backend_invalid",
                f"registry backend models invalid: {runner}",
            )
        if not isinstance(default_model, str) or default_model not in models:
            raise ProfileOpsError(
                "registry_backend_invalid",
                f"registry backend default_model invalid: {runner}",
            )
        blocks[runner] = {
            "default_model": default_model,
            "models": models,
        }
        if runner == "codex":
            reasoning = block.get("reasoning_effort")
            if (
                not isinstance(reasoning, list)
                or not reasoning
                or not all(isinstance(item, str) and item for item in reasoning)
            ):
                raise ProfileOpsError(
                    "registry_backend_invalid",
                    "registry codex reasoning_effort invalid",
                )
            blocks[runner]["reasoning_effort"] = reasoning
    return blocks


def _classify_agent_kind(agent_dir: Path, runtime_root: Path) -> str:
    try:
        rel = agent_dir.resolve().relative_to(runtime_root.resolve())
    except Exception as exc:
        raise ProfileOpsError("agent_outside_runtime_root", f"{agent_dir} is outside {runtime_root}") from exc

    if rel.parts == ():
        if runtime_root.name.lower() == "talker":
            return "talker"
        return "runtime_root"
    if rel.parts == ("Orchestrator",):
        return "orchestrator"
    if len(rel.parts) == 2 and rel.parts[0] == "Workers":
        return "worker"
    return "other"


def _require_mutation_allowed(actor_role: str, agent_kind: str) -> None:
    if actor_role == "talker":
        if agent_kind in {"talker", "orchestrator"}:
            return
        raise ProfileOpsError(
            "ownership_violation",
            f"Talker is not allowed to mutate agent kind '{agent_kind}'",
        )

    if actor_role == "orchestrator":
        if agent_kind == "worker":
            return
        raise ProfileOpsError(
            "ownership_violation",
            f"Orchestrator is not allowed to mutate agent kind '{agent_kind}'",
        )

    raise ProfileOpsError("ownership_violation", f"unsupported actor role: {actor_role}")


def _acquire_lock(path: Path, timeout_seconds: float) -> tuple[int, Path, str]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + max(0.05, timeout_seconds)

    while True:
        now = time.time()
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            token = str(uuid.uuid4())
            payload = f"token={token}\npid={os.getpid()} acquired_at={now_iso()}\n"
            os.write(fd, payload.encode("utf-8", errors="replace"))
            return fd, lock_path, token
        except FileExistsError:
            try:
                age = now - lock_path.stat().st_mtime
                if age > LOCK_STALE_SECONDS:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue

            if now >= deadline:
                raise ProfileOpsError("lock_timeout", f"timed out waiting for lock: {lock_path}")
            time.sleep(0.05)


def _release_lock(fd: int, lock_path: Path, token: str) -> None:
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        if lock_path.exists():
            current = lock_path.read_text(encoding="utf-8", errors="replace")
            if f"token={token}" in current:
                lock_path.unlink(missing_ok=True)
    except Exception:
        pass


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _replace_with_retry(tmp_path, path)


def _replace_with_retry(tmp_path: Path, target_path: Path, attempts: int = 40, delay_seconds: float = 0.01) -> None:
    last_error: Exception | None = None
    for idx in range(attempts):
        try:
            tmp_path.replace(target_path)
            return
        except PermissionError as exc:
            last_error = exc
            if idx >= attempts - 1:
                break
            time.sleep(delay_seconds)
        except OSError as exc:
            raise ProfileOpsError("write_failed", f"atomic replace failed for {target_path}: {exc}") from exc
    raise ProfileOpsError(
        "write_conflict",
        f"atomic replace conflicted for {target_path}: {last_error}",
    )


def _snapshot_root(agent_dir: Path) -> Path:
    return agent_dir / "AgentRunner" / "last_known_good"


def _snapshot_path(agent_dir: Path, filename: str) -> Path:
    return _snapshot_root(agent_dir) / filename


def _update_last_known_good_snapshot(agent_dir: Path, lock_timeout: float) -> None:
    for filename in ("agent_runner.json", "codex_profile.json", "kimi_profile.json"):
        source_path = agent_dir / filename
        if not source_path.is_file():
            continue
        dest_path = _snapshot_path(agent_dir, filename)
        fd, lock_path, token = _acquire_lock(dest_path, lock_timeout)
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = dest_path.with_suffix(dest_path.suffix + f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
            tmp_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
            _replace_with_retry(tmp_path, dest_path)
        finally:
            _release_lock(fd, lock_path, token)


def _restore_from_snapshot_if_available(agent_dir: Path, lock_timeout: float) -> tuple[bool, list[str]]:
    restored: list[str] = []
    for filename in ("agent_runner.json", "codex_profile.json", "kimi_profile.json"):
        source_path = _snapshot_path(agent_dir, filename)
        if not source_path.is_file():
            return False, []
        dest_path = agent_dir / filename
        fd, lock_path, token = _acquire_lock(dest_path, lock_timeout)
        try:
            tmp_path = dest_path.with_suffix(dest_path.suffix + f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
            tmp_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
            _replace_with_retry(tmp_path, dest_path)
            restored.append(str(dest_path))
        finally:
            _release_lock(fd, lock_path, token)
    return True, restored


def _restore_template_default(agent_dir: Path, runtime_root: Path, lock_timeout: float) -> list[str]:
    kind = _classify_agent_kind(agent_dir, runtime_root)
    repo_root = Path(__file__).resolve().parent.parent

    if kind == "talker":
        template_root = repo_root / "Talker"
    elif kind == "orchestrator":
        template_root = repo_root / "ProjectFolder_Template" / "Orchestrator"
    elif kind == "worker":
        template_root = repo_root / "ProjectFolder_Template" / "Workers" / "Worker_001"
    else:
        raise ProfileOpsError("template_default_not_available", f"template default is not available for kind={kind}")

    restored: list[str] = []
    for filename in ("agent_runner.json", "codex_profile.json", "kimi_profile.json"):
        source_path = template_root / filename
        if not source_path.is_file():
            raise ProfileOpsError("template_default_not_available", f"missing template source: {source_path}")
        dest_path = agent_dir / filename
        fd, lock_path, token = _acquire_lock(dest_path, lock_timeout)
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = dest_path.with_suffix(dest_path.suffix + f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
            tmp_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
            _replace_with_retry(tmp_path, dest_path)
            restored.append(str(dest_path))
        finally:
            _release_lock(fd, lock_path, token)
    return restored


def _append_audit_record(runtime_root: Path, record: dict[str, Any], lock_timeout: float) -> None:
    audit_path = runtime_root / "AgentRunner" / "profile_change_audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    fd, lock_path, token = _acquire_lock(audit_path, lock_timeout)
    try:
        with audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    finally:
        _release_lock(fd, lock_path, token)


def _build_actor_label(actor_role: str, actor_id: str) -> str:
    role_name = "Talker" if actor_role == "talker" else "Orchestrator"
    return f"{role_name}:{actor_id}"


def _load_profile_set(agent_dir: Path, runtime_root: Path) -> dict[str, Any]:
    registry = _load_registry(runtime_root)

    runner_path = agent_dir / "agent_runner.json"
    codex_path = agent_dir / "codex_profile.json"
    kimi_path = agent_dir / "kimi_profile.json"

    runner_profile = _load_json_dict(runner_path, "agent_runner_missing", "agent_runner_invalid_json")
    codex_profile = _load_json_dict(codex_path, "codex_profile_missing", "codex_profile_invalid_json")
    kimi_profile = _load_json_dict(kimi_path, "kimi_profile_missing", "kimi_profile_invalid_json")

    runner_value = runner_profile.get("runner")
    if not isinstance(runner_value, str) or runner_value not in ALLOWED_RUNNERS:
        raise ProfileOpsError("runner_not_allowed", f"unsupported runner: {runner_value!r}")

    codex_model = codex_profile.get("model")
    if not isinstance(codex_model, str) or codex_model not in registry["codex"]["models"]:
        raise ProfileOpsError("model_not_in_registry", f"invalid codex model: {codex_model!r}")
    codex_reasoning = codex_profile.get("reasoning_effort")
    if codex_reasoning is not None:
        if (
            not isinstance(codex_reasoning, str)
            or codex_reasoning not in registry["codex"]["reasoning_effort"]
        ):
            raise ProfileOpsError("reasoning_invalid", f"invalid codex reasoning_effort: {codex_reasoning!r}")

    kimi_model = kimi_profile.get("model")
    if not isinstance(kimi_model, str) or kimi_model not in registry["kimi"]["models"]:
        raise ProfileOpsError("model_not_in_registry", f"invalid kimi model: {kimi_model!r}")

    return {
        "registry": registry,
        "paths": {
            "runner": runner_path,
            "codex": codex_path,
            "kimi": kimi_path,
        },
        "profiles": {
            "runner": runner_profile,
            "codex": codex_profile,
            "kimi": kimi_profile,
        },
    }


def _audit_record(
    *,
    actor_role: str,
    actor_id: str,
    action: str,
    target_file: Path,
    changes: dict[str, Any],
    request_ref: str,
    result: str,
    error_code: str = "",
    error_message: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp": now_iso(),
        "actor": _build_actor_label(actor_role, actor_id),
        "action": action,
        "target_file": str(target_file),
        "changes": changes,
        "request_ref": request_ref,
        "result": result,
    }
    if error_code:
        payload["error_code"] = error_code
    if error_message:
        payload["error_message"] = error_message
    return payload


def validate_profile_set(agent_dir: str | Path) -> dict[str, Any]:
    normalized_agent_dir = normalize_agent_dir(agent_dir)
    runtime_root = discover_runtime_root(normalized_agent_dir)
    data = _load_profile_set(normalized_agent_dir, runtime_root)
    kind = _classify_agent_kind(normalized_agent_dir, runtime_root)
    return {
        "status": "ok",
        "agent_dir": str(normalized_agent_dir),
        "runtime_root": str(runtime_root),
        "agent_kind": kind,
        "effective_runner": data["profiles"]["runner"]["runner"],
    }


def mutate_set_runner(
    *,
    agent_dir: str | Path,
    actor_role: str,
    actor_id: str,
    request_ref: str,
    intent: str,
    new_runner: str,
    lock_timeout: float,
) -> dict[str, Any]:
    if intent != "explicit":
        raise ProfileOpsError("explicit_intent_required", "mutation requires --intent explicit")

    normalized_agent_dir = normalize_agent_dir(agent_dir)
    runtime_root = discover_runtime_root(normalized_agent_dir)
    action = "set_runner"
    target_path = normalized_agent_dir / "agent_runner.json"
    changes: dict[str, Any] = {}

    try:
        data = _load_profile_set(normalized_agent_dir, runtime_root)
        agent_kind = _classify_agent_kind(normalized_agent_dir, runtime_root)
        _require_mutation_allowed(actor_role, agent_kind)

        if new_runner not in ALLOWED_RUNNERS:
            raise ProfileOpsError("runner_not_allowed", f"unsupported runner: {new_runner!r}")

        runner_profile = dict(data["profiles"]["runner"])
        old_runner = runner_profile.get("runner")
        runner_profile["version"] = int(runner_profile.get("version") or 1)
        runner_profile["runner"] = new_runner
        changes = {"runner": {"old": old_runner, "new": new_runner}}
        target_path = data["paths"]["runner"]

        fd, lock_path, token = _acquire_lock(target_path, lock_timeout)
        try:
            _write_json_atomic(target_path, runner_profile)
        finally:
            _release_lock(fd, lock_path, token)

        _load_profile_set(normalized_agent_dir, runtime_root)
        _update_last_known_good_snapshot(normalized_agent_dir, lock_timeout)
        _append_audit_record(
            runtime_root,
            _audit_record(
                actor_role=actor_role,
                actor_id=actor_id,
                action=action,
                target_file=target_path,
                changes=changes,
                request_ref=request_ref,
                result="ok",
            ),
            lock_timeout,
        )
    except ProfileOpsError as exc:
        _append_audit_record(
            runtime_root,
            _audit_record(
                actor_role=actor_role,
                actor_id=actor_id,
                action=action,
                target_file=target_path,
                changes=changes,
                request_ref=request_ref,
                result="error",
                error_code=exc.code,
                error_message=exc.message,
            ),
            lock_timeout,
        )
        raise

    return {
        "status": "ok",
        "action": action,
        "agent_dir": str(normalized_agent_dir),
        "runner": new_runner,
        "target_file": str(target_path),
    }


def mutate_set_backend(
    *,
    agent_dir: str | Path,
    actor_role: str,
    actor_id: str,
    request_ref: str,
    intent: str,
    backend: str,
    model: str | None,
    reasoning_effort: str | None,
    lock_timeout: float,
) -> dict[str, Any]:
    if intent != "explicit":
        raise ProfileOpsError("explicit_intent_required", "mutation requires --intent explicit")
    if model is None and reasoning_effort is None:
        raise ProfileOpsError(
            "mutation_fields_missing",
            "set-backend requires --model and/or --reasoning-effort",
        )
    if backend not in ALLOWED_RUNNERS:
        raise ProfileOpsError("runner_not_allowed", f"unsupported backend: {backend!r}")
    if backend != "codex" and reasoning_effort is not None:
        raise ProfileOpsError(
            "reasoning_incompatible_with_runner",
            "--reasoning-effort is supported only for backend=codex",
        )

    normalized_agent_dir = normalize_agent_dir(agent_dir)
    runtime_root = discover_runtime_root(normalized_agent_dir)
    action = "other"
    changes: dict[str, Any] = {}
    target_path = normalized_agent_dir / PROFILE_FILE_BY_RUNNER[backend]

    try:
        data = _load_profile_set(normalized_agent_dir, runtime_root)
        agent_kind = _classify_agent_kind(normalized_agent_dir, runtime_root)
        _require_mutation_allowed(actor_role, agent_kind)

        profile = dict(data["profiles"][backend])
        target_path = data["paths"][backend]
        registry_backend = data["registry"][backend]

        old_model = profile.get("model")
        old_reasoning = profile.get("reasoning_effort")

        if model is not None:
            if model not in registry_backend["models"]:
                raise ProfileOpsError(
                    "model_not_in_registry",
                    f"model '{model}' is not allowed for backend={backend}",
                )
            profile["model"] = model
            changes["model"] = {"old": old_model, "new": model}

        if backend == "codex" and reasoning_effort is not None:
            allowlist = data["registry"]["codex"]["reasoning_effort"]
            if reasoning_effort not in allowlist:
                raise ProfileOpsError(
                    "reasoning_invalid",
                    f"invalid reasoning_effort '{reasoning_effort}' for backend=codex",
                )
            profile["reasoning_effort"] = reasoning_effort
            changes["reasoning_effort"] = {"old": old_reasoning, "new": reasoning_effort}

        if "version" not in profile or not isinstance(profile["version"], int):
            profile["version"] = 1

        model_changed = "model" in changes and changes["model"]["old"] != changes["model"]["new"]
        reasoning_changed = (
            "reasoning_effort" in changes
            and changes["reasoning_effort"]["old"] != changes["reasoning_effort"]["new"]
        )
        if model_changed and not reasoning_changed:
            action = "set_model"
        elif reasoning_changed and not model_changed:
            action = "set_reasoning"
        elif model_changed or reasoning_changed:
            action = "other"
        else:
            action = "other"

        fd, lock_path, token = _acquire_lock(target_path, lock_timeout)
        try:
            _write_json_atomic(target_path, profile)
        finally:
            _release_lock(fd, lock_path, token)

        _load_profile_set(normalized_agent_dir, runtime_root)
        _update_last_known_good_snapshot(normalized_agent_dir, lock_timeout)
        _append_audit_record(
            runtime_root,
            _audit_record(
                actor_role=actor_role,
                actor_id=actor_id,
                action=action,
                target_file=target_path,
                changes=changes,
                request_ref=request_ref,
                result="ok",
            ),
            lock_timeout,
        )
    except ProfileOpsError as exc:
        _append_audit_record(
            runtime_root,
            _audit_record(
                actor_role=actor_role,
                actor_id=actor_id,
                action=action,
                target_file=target_path,
                changes=changes,
                request_ref=request_ref,
                result="error",
                error_code=exc.code,
                error_message=exc.message,
            ),
            lock_timeout,
        )
        raise

    return {
        "status": "ok",
        "action": action,
        "agent_dir": str(normalized_agent_dir),
        "backend": backend,
        "target_file": str(target_path),
    }


def self_heal_profiles(
    *,
    agent_dir: str | Path,
    actor_role: str,
    actor_id: str,
    request_ref: str,
    intent: str,
    lock_timeout: float,
) -> dict[str, Any]:
    if intent != "explicit":
        raise ProfileOpsError("explicit_intent_required", "self-heal requires --intent explicit")

    normalized_agent_dir = normalize_agent_dir(agent_dir)
    runtime_root = discover_runtime_root(normalized_agent_dir)
    _require_mutation_allowed(actor_role, _classify_agent_kind(normalized_agent_dir, runtime_root))

    action = "self_heal_restore"
    target_path = normalized_agent_dir / "agent_runner.json"
    changes: dict[str, Any] = {}

    try:
        restore_source = ""
        restored_files: list[str] = []
        restored, restored_files = _restore_from_snapshot_if_available(normalized_agent_dir, lock_timeout)
        if restored:
            restore_source = "last_known_good"
        else:
            restored_files = _restore_template_default(normalized_agent_dir, runtime_root, lock_timeout)
            restore_source = "template_default"

        _load_profile_set(normalized_agent_dir, runtime_root)
        _update_last_known_good_snapshot(normalized_agent_dir, lock_timeout)

        changes = {
            "restore_source": restore_source,
            "restored_files": restored_files,
        }
        _append_audit_record(
            runtime_root,
            _audit_record(
                actor_role=actor_role,
                actor_id=actor_id,
                action=action,
                target_file=target_path,
                changes=changes,
                request_ref=request_ref,
                result="ok",
            ),
            lock_timeout,
        )
        return {
            "status": "ok",
            "action": action,
            "agent_dir": str(normalized_agent_dir),
            "restore_source": restore_source,
            "restored_files": restored_files,
        }
    except ProfileOpsError as exc:
        _append_audit_record(
            runtime_root,
            _audit_record(
                actor_role=actor_role,
                actor_id=actor_id,
                action=action,
                target_file=target_path,
                changes=changes,
                request_ref=request_ref,
                result="error",
                error_code=exc.code,
                error_message=exc.message,
            ),
            lock_timeout,
        )
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = _MachineCodeArgumentParser(
        description="Deterministic helper for profile validate/mutation operations."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--agent-dir", required=True, help="Agent directory path.")

    common_mutation = argparse.ArgumentParser(add_help=False)
    common_mutation.add_argument("--agent-dir", required=True, help="Agent directory path.")
    common_mutation.add_argument(
        "--actor-role",
        required=True,
        choices=["talker", "orchestrator"],
        help="Actor role for ownership checks.",
    )
    common_mutation.add_argument("--actor-id", required=True, help="Actor sender ID.")
    common_mutation.add_argument("--request-ref", required=True, help="Explicit request reference marker.")
    common_mutation.add_argument(
        "--intent",
        required=True,
        help="Explicit mutation intent marker; must be 'explicit'.",
    )
    common_mutation.add_argument(
        "--lock-timeout",
        type=float,
        default=DEFAULT_LOCK_TIMEOUT,
        help="Lock timeout in seconds.",
    )

    set_runner = subparsers.add_parser("set-runner", parents=[common_mutation])
    set_runner.add_argument("--runner", required=True, choices=["codex", "kimi"])

    set_backend = subparsers.add_parser("set-backend", parents=[common_mutation])
    set_backend.add_argument("--backend", required=True, choices=["codex", "kimi"])
    set_backend.add_argument("--model", help="New model for target backend.")
    set_backend.add_argument(
        "--reasoning-effort",
        help="New reasoning_effort for codex backend.",
    )

    subparsers.add_parser("self-heal", parents=[common_mutation])

    return parser


def main() -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args()
        if args.command == "validate":
            payload = validate_profile_set(args.agent_dir)
        elif args.command == "set-runner":
            payload = mutate_set_runner(
                agent_dir=args.agent_dir,
                actor_role=args.actor_role,
                actor_id=args.actor_id,
                request_ref=args.request_ref,
                intent=args.intent,
                new_runner=args.runner,
                lock_timeout=args.lock_timeout,
            )
        elif args.command == "set-backend":
            payload = mutate_set_backend(
                agent_dir=args.agent_dir,
                actor_role=args.actor_role,
                actor_id=args.actor_id,
                request_ref=args.request_ref,
                intent=args.intent,
                backend=args.backend,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                lock_timeout=args.lock_timeout,
            )
        elif args.command == "self-heal":
            payload = self_heal_profiles(
                agent_dir=args.agent_dir,
                actor_role=args.actor_role,
                actor_id=args.actor_id,
                request_ref=args.request_ref,
                intent=args.intent,
                lock_timeout=args.lock_timeout,
            )
        else:
            raise ProfileOpsError("unsupported_command", f"unsupported command: {args.command}")
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except ResolverError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    except ProfileOpsError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    except Exception:
        print("internal_error", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
