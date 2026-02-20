"""Shared resolver/validator for per-agent runner/model/reasoning config.

Phase 2 scope:
- Path normalization
- Runtime-root discovery
- Profile/registry loading
- Validation with deterministic error codes
- Effective config resolution with source labels
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_RUNNERS = ("codex", "kimi")
PROFILE_FILE_BY_RUNNER = {
    "codex": "codex_profile.json",
    "kimi": "kimi_profile.json",
}
PROFILE_KNOWN_FIELDS = {
    "codex": {"version", "model", "reasoning_effort"},
    "kimi": {"version", "model"},
}
RUNNER_PROFILE_KNOWN_FIELDS = {"version", "runner"}
SOURCE_CLI = "cli"
SOURCE_PROFILE = "profile"
SOURCE_BACKEND_DEFAULT = "backend-default"


# Phase 0 capability freeze.
BACKEND_CAPABILITIES = {
    "codex": {"supports_runtime_model_override": True},
    "kimi": {"supports_runtime_model_override": True},
}


@dataclass(frozen=True)
class ResolverError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def _load_json_object(path: Path, missing_code: str, invalid_code: str) -> dict[str, Any]:
    if not path.is_file():
        raise ResolverError(missing_code, f"missing file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ResolverError(invalid_code, f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ResolverError(invalid_code, f"JSON object expected: {path}")
    return payload


def normalize_agent_dir(agent_dir: str | Path) -> Path:
    candidate = Path(agent_dir).expanduser()
    if candidate.is_absolute():
        normalized = candidate.resolve()
    else:
        normalized = (Path.cwd() / candidate).resolve()
    if not normalized.is_dir():
        raise ResolverError("agent_dir_not_found", f"agent directory not found: {normalized}")
    return normalized


def discover_runtime_root(agent_dir: Path) -> Path:
    current = agent_dir.resolve()
    while True:
        if (current / "AgentRunner" / "model_registry.json").is_file():
            return current
        if (current / ".git").exists():
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise ResolverError("runtime_root_not_found", f"model_registry.json not found for {agent_dir}")


def _validate_registry(registry: dict[str, Any], path: Path) -> dict[str, dict[str, Any]]:
    validated: dict[str, dict[str, Any]] = {}
    for runner in ALLOWED_RUNNERS:
        block = registry.get(runner)
        if not isinstance(block, dict):
            raise ResolverError(
                "registry_backend_invalid",
                f"registry backend block must be object: {runner} ({path})",
            )
        models = block.get("models")
        default_model = block.get("default_model")
        if (
            not isinstance(models, list)
            or not models
            or not all(isinstance(item, str) and item for item in models)
        ):
            raise ResolverError(
                "registry_backend_invalid",
                f"registry backend models invalid: {runner} ({path})",
            )
        if not isinstance(default_model, str) or default_model not in models:
            raise ResolverError(
                "registry_backend_invalid",
                f"registry backend default_model invalid: {runner} ({path})",
            )
        validated_block = {
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
                raise ResolverError(
                    "registry_backend_invalid",
                    f"registry codex reasoning_effort invalid: {path}",
                )
            validated_block["reasoning_effort"] = reasoning
        validated[runner] = validated_block
    return validated


def _collect_unknown_fields(
    payload: dict[str, Any],
    known_fields: set[str],
    file_path: Path,
) -> list[str]:
    unknown = sorted(key for key in payload.keys() if key not in known_fields)
    warnings: list[str] = []
    for key in unknown:
        warnings.append(f"unknown_field_ignored:{file_path}:{key}")
    return warnings


def resolve_agent_config(
    *,
    agent_dir: str | Path,
    cli_runner: str | None = None,
    cli_model: str | None = None,
    cli_reasoning_effort: str | None = None,
) -> dict[str, Any]:
    normalized_agent_dir = normalize_agent_dir(agent_dir)
    runtime_root = discover_runtime_root(normalized_agent_dir)

    registry_path = runtime_root / "AgentRunner" / "model_registry.json"
    registry_raw = _load_json_object(
        registry_path,
        missing_code="registry_missing",
        invalid_code="registry_invalid_json",
    )
    registry = _validate_registry(registry_raw, registry_path)

    runner_path = normalized_agent_dir / "agent_runner.json"
    runner_profile = _load_json_object(
        runner_path,
        missing_code="agent_runner_missing",
        invalid_code="agent_runner_invalid_json",
    )
    warnings = _collect_unknown_fields(runner_profile, RUNNER_PROFILE_KNOWN_FIELDS, runner_path)

    runner_from_profile = runner_profile.get("runner")
    if runner_from_profile is not None and not isinstance(runner_from_profile, str):
        raise ResolverError("runner_not_allowed", f"runner must be string: {runner_path}")

    effective_runner = cli_runner if cli_runner is not None else runner_from_profile
    source_runner = SOURCE_CLI if cli_runner is not None else SOURCE_PROFILE
    if not isinstance(effective_runner, str) or effective_runner not in ALLOWED_RUNNERS:
        raise ResolverError("runner_not_allowed", f"unsupported runner: {effective_runner!r}")

    profiles: dict[str, dict[str, Any]] = {}
    profile_paths: dict[str, Path] = {}
    for backend in ALLOWED_RUNNERS:
        profile_path = normalized_agent_dir / PROFILE_FILE_BY_RUNNER[backend]
        profile_paths[backend] = profile_path
        if not profile_path.exists():
            if backend == effective_runner:
                raise ResolverError("active_profile_missing", f"missing active profile: {profile_path}")
            continue
        try:
            profile_raw = _load_json_object(
                profile_path,
                missing_code="active_profile_missing",
                invalid_code=(
                    "active_profile_invalid_json"
                    if backend == effective_runner
                    else "inactive_profile_invalid_json"
                ),
            )
        except ResolverError:
            if backend == effective_runner:
                raise
            warnings.append(f"inactive_profile_invalid_ignored:{profile_path}")
            continue
        profiles[backend] = profile_raw
        warnings.extend(_collect_unknown_fields(profile_raw, PROFILE_KNOWN_FIELDS[backend], profile_path))

    active_profile = profiles.get(effective_runner)
    if active_profile is None:
        raise ResolverError(
            "active_profile_missing",
            f"active profile must exist for runner={effective_runner}: {profile_paths[effective_runner]}",
        )

    backend_registry = registry[effective_runner]
    supports_override = bool(BACKEND_CAPABILITIES[effective_runner]["supports_runtime_model_override"])

    model_value = cli_model if cli_model is not None else active_profile.get("model")
    model_source = SOURCE_CLI if cli_model is not None else SOURCE_PROFILE
    if not isinstance(model_value, str) or not model_value:
        raise ResolverError(
            "model_missing",
            f"model is required for active profile: {profile_paths[effective_runner]}",
        )
    if model_value not in backend_registry["models"]:
        raise ResolverError(
            "model_not_in_registry",
            f"model '{model_value}' is not allowed for runner={effective_runner}",
        )

    if not supports_override:
        default_model = backend_registry["default_model"]
        if cli_model is not None and model_value != default_model:
            raise ResolverError(
                "model_override_not_supported",
                f"CLI model override is not supported for runner={effective_runner}",
            )
        if model_value != default_model:
            raise ResolverError(
                "model_must_equal_backend_default",
                f"runner={effective_runner} requires default model '{default_model}'",
            )

    reasoning_value = ""
    reasoning_source = SOURCE_BACKEND_DEFAULT
    if cli_reasoning_effort is not None and effective_runner != "codex":
        raise ResolverError(
            "reasoning_incompatible_with_runner",
            f"--reasoning-effort is only supported for runner=codex (got {effective_runner})",
        )

    if effective_runner == "codex":
        if cli_reasoning_effort is not None:
            reasoning_value = cli_reasoning_effort
            reasoning_source = SOURCE_CLI
        else:
            profile_reasoning = active_profile.get("reasoning_effort")
            if profile_reasoning is not None:
                reasoning_value = profile_reasoning
                reasoning_source = SOURCE_PROFILE

        if reasoning_value != "":
            allowlist = backend_registry["reasoning_effort"]
            if not isinstance(reasoning_value, str) or reasoning_value not in allowlist:
                raise ResolverError(
                    "reasoning_invalid",
                    f"invalid reasoning_effort '{reasoning_value}' for runner=codex",
                )

    result = {
        "agent_dir": str(normalized_agent_dir),
        "runtime_root": str(runtime_root),
        "effective": {
            "runner": effective_runner,
            "model": model_value,
            "reasoning": reasoning_value,
        },
        "source": {
            "runner": source_runner,
            "model": model_source,
            "reasoning": reasoning_source,
        },
        "capability": {
            "supports_runtime_model_override": supports_override,
        },
        "warnings": warnings,
        "paths": {
            "runner_profile": str(runner_path),
            "active_backend_profile": str(profile_paths[effective_runner]),
            "registry": str(registry_path),
        },
    }
    return result
