import argparse
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Looper"))

import create_prompt_file  # noqa: E402


class CreatePromptFileEncodingTests(unittest.TestCase):
    def test_unit_create_accepts_utf16_bom_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            inbox = temp_root / "Inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            source = temp_root / "orchestrator_ready.md"
            source_text = "# Orchestrator Ready\n\nПривет из UTF-16 файла"
            source.write_text(source_text, encoding="utf-16")

            args = argparse.Namespace(
                inbox=str(inbox),
                suffix=None,
                from_file=str(source),
                text=None,
                stdin=False,
            )
            exit_code = create_prompt_file._cmd_create(args)

            self.assertEqual(0, exit_code)
            created = sorted(inbox.glob("Prompt_*.md"))
            self.assertEqual(1, len(created))
            self.assertEqual(source_text, created[0].read_text(encoding="utf-8"))

    def test_unit_create_keeps_utf8_strict_without_bom(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            inbox = temp_root / "Inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            source = temp_root / "legacy_ansi.md"
            source.write_bytes("Привет".encode("cp1251"))

            args = argparse.Namespace(
                inbox=str(inbox),
                suffix=None,
                from_file=str(source),
                text=None,
                stdin=False,
            )
            exit_code = create_prompt_file._cmd_create(args)

            self.assertEqual(2, exit_code)
            self.assertEqual([], sorted(inbox.glob("Prompt_*.md")))


if __name__ == "__main__":
    unittest.main()
