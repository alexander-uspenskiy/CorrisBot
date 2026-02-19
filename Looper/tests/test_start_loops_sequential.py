import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "Looper" / "start_loops_sequential.py"


class StartLoopsSequentialTests(unittest.TestCase):
    def _run_script(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_e2e_dry_run_starts_multiple_agents_sequentially(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "ProjectA"
            (project_root / "Temp").mkdir(parents=True, exist_ok=True)
            (project_root / "Orchestrator").mkdir(parents=True, exist_ok=True)
            (project_root / "Workers" / "Worker_001").mkdir(parents=True, exist_ok=True)

            code, stdout, stderr = self._run_script(
                [
                    "--project-root",
                    str(project_root),
                    "--dry-run",
                    "Orchestrator",
                    "Workers\\Worker_001",
                ]
            )

            self.assertEqual(0, code, msg=stderr)
            payload = json.loads(stdout.strip())
            self.assertEqual("ok", payload["status"])
            self.assertEqual(2, len(payload["launched"]))
            self.assertEqual("Orchestrator", payload["launched"][0]["agent_path"])
            self.assertEqual("Workers\\Worker_001", payload["launched"][1]["agent_path"])

    def test_negative_missing_agent_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "ProjectB"
            (project_root / "Temp").mkdir(parents=True, exist_ok=True)
            (project_root / "Orchestrator").mkdir(parents=True, exist_ok=True)

            code, _, stderr = self._run_script(
                [
                    "--project-root",
                    str(project_root),
                    "--dry-run",
                    "Orchestrator",
                    "Workers\\Missing_999",
                ]
            )

            self.assertEqual(2, code)
            self.assertIn("sequential launch failed", stderr)


if __name__ == "__main__":
    unittest.main()
