"""Assemble a flat AGENTS.md from a template with Read: links.

Usage:
    py assemble_agents.py <template_path> <output_path>

Recursively resolves every ``Read: `<path>` `` directive found in the
template (and in referenced files) and writes a single flat file that
contains all content inline.  The ``Read:`` line itself is replaced by
the referenced file's content.

Exit codes:
    0  success
    1  usage error
    2  referenced file not found
    3  circular reference detected
"""

import sys
import re
from pathlib import Path

_READ_RE = re.compile(r"^\s*(?:-\s*)?Read:\s*`([^`]+)`\s*$")
_CRITICAL_HEADING_RE = re.compile(r"^\s*#{1,6}\s*CRITICAL\s*$", flags=re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")


def resolve(template: Path, seen: set[Path] | None = None) -> list[str]:
    """Return list of lines with all Read: directives resolved."""
    if seen is None:
        seen = set()

    resolved = template.resolve()
    if resolved in seen:
        print(f"[ERROR] Circular reference detected: {template}", file=sys.stderr)
        sys.exit(3)
    seen.add(resolved)

    if not template.exists():
        print(f"[ERROR] File not found: {template}", file=sys.stderr)
        sys.exit(2)

    lines: list[str] = []
    for raw in template.read_text(encoding="utf-8").splitlines(keepends=True):
        m = _READ_RE.match(raw.rstrip("\r\n"))
        if m:
            ref_path = Path(m.group(1))
            if not ref_path.exists():
                print(
                    f"[ERROR] Referenced file not found: {ref_path}  "
                    f"(from {template})",
                    file=sys.stderr,
                )
                sys.exit(2)
            lines.extend(resolve(ref_path, seen))
        else:
            lines.append(raw)

    seen.discard(resolved)
    return lines


def dedup_headings(lines: list[str]) -> list[str]:
    """Remove consecutive duplicate markdown headings."""
    result: list[str] = []
    prev_stripped: str | None = None
    for line in lines:
        stripped = line.rstrip("\r\n")
        # A markdown heading starts with one or more '#'
        if stripped.lstrip().startswith("#") and stripped == prev_stripped:
            continue  # skip duplicate
        result.append(line)
        # Only track non-blank lines for comparison
        if stripped.strip():
            prev_stripped = stripped
    return result


def strip_critical_sections(lines: list[str]) -> list[str]:
    """Remove template-only sections titled exactly 'CRITICAL'.

    Important:
    - We intentionally remove only heading text that is exactly `CRITICAL`
      (case-insensitive), e.g. `## CRITICAL`.
    - If such section is preceded by a `<!-- TEMPLATE-ONLY ... -->` comment
      block, remove that comment block too.
    - Do NOT remove normal operational sections such as
      `## Critical Rules (Mandatory)` from resolved role files.
    """
    def _pop_trailing_template_comment(buffer: list[str]) -> None:
        """Remove the last HTML comment block only when it is TEMPLATE-ONLY."""
        if not buffer:
            return

        end = len(buffer) - 1
        while end >= 0 and not buffer[end].strip():
            end -= 1
        if end < 0 or "-->" not in buffer[end]:
            return

        start = end
        while start >= 0 and "<!--" not in buffer[start]:
            start -= 1
        if start < 0:
            return

        block_text = "".join(buffer[start : end + 1]).upper()
        if "TEMPLATE-ONLY" not in block_text:
            return

        del buffer[start : end + 1]

    result: list[str] = []
    skipping = False

    for line in lines:
        stripped = line.rstrip("\r\n")

        if skipping:
            if _HEADING_RE.match(stripped):
                skipping = False
            else:
                continue

        if _CRITICAL_HEADING_RE.match(stripped):
            _pop_trailing_template_comment(result)
            skipping = True
            continue

        result.append(line)

    return result


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: py assemble_agents.py <template_path> <output_path>")
        sys.exit(1)

    template_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    assembled = resolve(template_path)
    assembled = strip_critical_sections(assembled)
    assembled = dedup_headings(assembled)
    output_path.write_text("".join(assembled), encoding="utf-8")
    print(f"[OK] Assembled {output_path}  ({len(assembled)} lines)")


if __name__ == "__main__":
    main()
