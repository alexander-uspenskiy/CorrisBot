"""Shared parsing and validation helpers for fail-closed routing contract."""

from __future__ import annotations

import re
from pathlib import Path


SUPPORTED_FILE_PATTERN = "Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md"
PLACEHOLDER_RE = re.compile(r"^<[^>]+>$")
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
BLOCK_ITEM_RE = re.compile(r"^-\s*([A-Za-z0-9_-]+)\s*:\s*(.*)$")


def _scan_markdown_block(prompt_text: str, header: str) -> dict[str, str]:
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
        if stripped != header:
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
            m = BLOCK_ITEM_RE.match(s)
            if m is None:
                if fields:
                    break
                continue
            fields[m.group(1)] = m.group(2).strip()
        if fields:
            return fields
    return {}


def remove_markdown_block(prompt_text: str, header: str) -> str:
    """Removes a markdown block by exact header. Returns modified text or original if not found."""
    lines = prompt_text.splitlines(keepends=True)
    in_code_fence = False
    
    start_idx = -1
    end_idx = -1

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if stripped.startswith(">"):
            continue
        if stripped != header:
            continue

        has_items = False
        target_end_idx = idx + 1
        for tail_idx in range(idx + 1, len(lines)):
            s = lines[tail_idx].strip()
            if not s:
                target_end_idx = tail_idx + 1
                if has_items:
                    break
                continue
            if s.startswith("```") or s.startswith(">"):
                target_end_idx = tail_idx
                break
            m = BLOCK_ITEM_RE.match(s)
            if m is None:
                target_end_idx = tail_idx
                if has_items:
                    break
                continue
            has_items = True
            target_end_idx = tail_idx + 1

        if has_items:
            start_idx = idx
            end_idx = target_end_idx
            break

    if start_idx == -1:
        return prompt_text

    return "".join(lines[:start_idx] + lines[end_idx:])


def extract_reply_to_fields(prompt_text: str) -> dict[str, str]:
    fields = _scan_markdown_block(prompt_text, "Reply-To:")
    inbox = fields.get("InboxPath", "").strip()
    if not inbox:
        raise RuntimeError("valid Reply-To block not found in incoming prompt")
    if PLACEHOLDER_RE.fullmatch(inbox):
        raise RuntimeError(f"Reply-To.InboxPath is placeholder and cannot be used: {inbox}")
    if not Path(inbox).expanduser().is_absolute():
        raise RuntimeError(f"Reply-To.InboxPath must be absolute path: {inbox!r}")
    return fields


def extract_message_meta_fields(prompt_text: str) -> dict[str, str]:
    fields = _scan_markdown_block(prompt_text, "Message-Meta:")
    if not fields:
        raise RuntimeError("Message-Meta block not found in payload")
    
    required = ["MessageClass", "ReportType", "ReportID", "RouteSessionID", "ProjectTag"]
    missing = [key for key in required if not fields.get(key, "").strip()]
    if missing:
        raise RuntimeError(f"Message-Meta missing required fields: {', '.join(missing)}")
    
    msg_class = fields["MessageClass"].strip()
    if msg_class not in ("report", "trace"):
        raise RuntimeError(f"invalid Message-Meta.MessageClass: {msg_class}")
        
    report_type = fields["ReportType"].strip()
    valid_types = ("phase_gate", "phase_accept", "final_summary", "question", "status")
    if report_type not in valid_types:
        raise RuntimeError(f"invalid Message-Meta.ReportType: {report_type}")
        
    ensure_safe_token("Message-Meta.ReportID", fields["ReportID"])
    ensure_safe_token("Message-Meta.RouteSessionID", fields["RouteSessionID"])
    
    return {key: fields[key].strip() for key in required}


def _extract_top_level_field_values(prompt_text: str, field_name: str) -> list[str]:
    """Collect top-level `Field: value` or `- Field: value` entries.

    Ignores code fences and quoted markdown to avoid matching examples.
    """
    values: list[str] = []
    in_code_fence = False
    field_lower = field_name.lower()

    for raw_line in prompt_text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence or line.startswith(">"):
            continue

        if line.startswith("-"):
            payload = line[1:].strip()
        else:
            payload = line

        if ":" not in payload:
            continue

        key, value = payload.split(":", 1)
        if key.strip().lower() != field_lower:
            continue

        normalized_value = value.strip()
        if normalized_value:
            values.append(normalized_value)
    return values


def _extract_single_top_level_field(prompt_text: str, field_name: str) -> str | None:
    values = _extract_top_level_field_values(prompt_text, field_name)
    if not values:
        return None

    unique_normalized = {item.strip().upper() for item in values}
    if len(unique_normalized) > 1:
        raise RuntimeError(
            f"phase_accept contract has conflicting {field_name} values: {', '.join(values)}"
        )
    return values[0].strip()


def validate_phase_accept_contract(report_text: str) -> dict[str, str]:
    """Validate semantic gate contract for phase_accept reports.

    Contract:
    - Verdict: ACCEPT | REWORK
    - Decision: GO | NO-GO
    - Canonical mapping:
      ACCEPT => GO
      REWORK => NO-GO
    - Mapping (optional): if present, must match canonical pair.
    """
    verdict_raw = _extract_single_top_level_field(report_text, "Verdict")
    decision_raw = _extract_single_top_level_field(report_text, "Decision")
    mapping_raw = _extract_single_top_level_field(report_text, "Mapping")

    if not verdict_raw or not decision_raw:
        raise RuntimeError(
            "phase_accept contract missing required fields: Verdict and Decision are mandatory"
        )

    verdict = verdict_raw.upper()
    decision = decision_raw.upper()
    if verdict not in ("ACCEPT", "REWORK"):
        raise RuntimeError(f"phase_accept contract invalid Verdict: {verdict_raw}")
    if decision not in ("GO", "NO-GO"):
        raise RuntimeError(f"phase_accept contract invalid Decision: {decision_raw}")

    expected_decision = "GO" if verdict == "ACCEPT" else "NO-GO"
    if decision != expected_decision:
        raise RuntimeError(
            "phase_accept contract mismatch: "
            f"Verdict={verdict} requires Decision={expected_decision}, got {decision}"
        )

    if mapping_raw is not None:
        mapping = mapping_raw.upper().replace(" ", "")
        expected_mapping = f"{verdict}=>{expected_decision}"
        if mapping != expected_mapping:
            raise RuntimeError(
                "phase_accept contract mapping mismatch: "
                f"expected {expected_mapping}, got {mapping_raw}"
            )

    return {
        "Verdict": verdict,
        "Decision": decision,
        "Mapping": (mapping_raw or "").strip(),
    }


def validate_semantic_report_contract(report_text: str, msg_meta: dict[str, str]) -> None:
    """Apply report-type-specific semantic checks."""
    if msg_meta.get("MessageClass") != "report":
        return

    report_type = msg_meta.get("ReportType", "")
    if report_type == "phase_accept":
        validate_phase_accept_contract(report_text)


def extract_route_meta_fields(prompt_text: str) -> dict[str, str]:
    fields = _scan_markdown_block(prompt_text, "Route-Meta:")
    session_id = fields.get("RouteSessionID", "").strip()
    project_tag = fields.get("ProjectTag", "").strip()
    if not session_id or not project_tag:
        raise RuntimeError("Route-Meta block is missing required fields: RouteSessionID/ProjectTag")
    if PLACEHOLDER_RE.fullmatch(session_id) or PLACEHOLDER_RE.fullmatch(project_tag):
        raise RuntimeError("Route-Meta contains placeholder values")
    ensure_safe_token("Route-Meta.RouteSessionID", session_id)
    return {"RouteSessionID": session_id, "ProjectTag": project_tag}


def extract_routing_contract_fields(prompt_text: str) -> dict[str, str]:
    fields = _scan_markdown_block(prompt_text, "Routing-Contract:")
    return _validate_routing_contract_fields(fields)


def try_extract_routing_contract_fields(prompt_text: str) -> dict[str, str] | None:
    fields = _scan_markdown_block(prompt_text, "Routing-Contract:")
    if not fields:
        return None
    return _validate_routing_contract_fields(fields)


def _validate_routing_contract_fields(fields: dict[str, str]) -> dict[str, str]:
    required = [
        "Version",
        "RouteSessionID",
        "AppRoot",
        "AgentsRoot",
        "ProjectTag",
        "OrchestratorSenderID",
        "CreatedAtUTC",
    ]
    missing = [key for key in required if not fields.get(key, "").strip()]
    if missing:
        raise RuntimeError(f"Routing-Contract missing required fields: {', '.join(missing)}")
    for key in required:
        value = fields[key].strip()
        if PLACEHOLDER_RE.fullmatch(value):
            raise RuntimeError(f"Routing-Contract field {key} is placeholder")
    if fields["Version"].strip() != "1":
        raise RuntimeError(f"unsupported Routing-Contract.Version: {fields['Version']!r}")
    ensure_safe_token("Routing-Contract.RouteSessionID", fields["RouteSessionID"])
    return {key: fields[key].strip() for key in required}


def ensure_safe_token(label: str, raw_value: str) -> str:
    normalized = raw_value.strip()
    if not normalized:
        raise RuntimeError(f"{label} is empty")
    if PLACEHOLDER_RE.fullmatch(normalized):
        raise RuntimeError(f"{label} is placeholder")
    if SAFE_TOKEN_RE.fullmatch(normalized) is None:
        raise RuntimeError(f"{label} has unsupported format: {raw_value!r}")
    return normalized


def ensure_abs_path(label: str, raw_path: str) -> Path:
    expanded = Path(raw_path).expanduser()
    if not expanded.is_absolute():
        raise RuntimeError(f"{label} must be absolute path: {raw_path!r}")
    return expanded.resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def ensure_path_in_root(path: Path, root: Path, label: str) -> None:
    if not _is_relative_to(path, root):
        raise RuntimeError(f"{label} is outside allowed root: {path} (allowed root: {root})")


def ensure_reply_to_in_scope(reply_to_inbox: Path, contract: dict[str, str]) -> None:
    app_root = ensure_abs_path("Routing-Contract.AppRoot", contract["AppRoot"])
    agents_root = ensure_abs_path("Routing-Contract.AgentsRoot", contract["AgentsRoot"])

    allowed_roots = [
        (app_root / "Talker" / "Prompts" / "Inbox").resolve(),
        (agents_root / "Orchestrator" / "Prompts" / "Inbox").resolve(),
    ]
    if not any(_is_relative_to(reply_to_inbox, root) for root in allowed_roots):
        roots_text = ", ".join(str(root) for root in allowed_roots)
        raise RuntimeError(
            "Reply-To.InboxPath is out of allowed scope for current Routing-Contract: "
            f"{reply_to_inbox}; allowed roots: {roots_text}"
        )


def ensure_route_meta_matches_contract(route_meta: dict[str, str], contract: dict[str, str]) -> None:
    if route_meta["RouteSessionID"] != contract["RouteSessionID"]:
        raise RuntimeError(
            "Route-Meta.RouteSessionID does not match Routing-Contract.RouteSessionID: "
            f"{route_meta['RouteSessionID']} vs {contract['RouteSessionID']}"
        )
    if route_meta["ProjectTag"] != contract["ProjectTag"]:
        raise RuntimeError(
            "Route-Meta.ProjectTag does not match Routing-Contract.ProjectTag: "
            f"{route_meta['ProjectTag']} vs {contract['ProjectTag']}"
        )
