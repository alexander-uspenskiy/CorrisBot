import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "Looper" / "start_loops_sequential.py"


class StartLoopsSequentialTests(unittest.TestCase):
    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _prepare_phase3_config(self, project_root: Path, agent_rel_path: str) -> None:
        self._write_json(
            project_root / "AgentRunner" / "model_registry.json",
            {
                "version": 1,
                "codex": {
                    "default_model": "codex-5.3",
                    "models": ["codex-5.3", "codex-5.3-mini"],
                    "reasoning_effort": ["low", "medium", "high"],
                },
                "kimi": {
                    "default_model": "kimi-k2",
                    "models": ["kimi-k2"],
                },
            },
        )
        agent_dir = project_root / Path(agent_rel_path)
        self._write_json(agent_dir / "agent_runner.json", {"version": 1, "runner": "codex"})
        self._write_json(
            agent_dir / "codex_profile.json",
            {"version": 1, "model": "codex-5.3", "reasoning_effort": "high"},
        )
        self._write_json(agent_dir / "kimi_profile.json", {"version": 1, "model": "kimi-k2"})

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
            self._prepare_phase3_config(project_root, "Orchestrator")
            self._prepare_phase3_config(project_root, "Workers/Worker_001")

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
            self._prepare_phase3_config(project_root, "Orchestrator")

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

    def test_dry_run_accepts_model_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "ProjectC"
            (project_root / "Temp").mkdir(parents=True, exist_ok=True)
            (project_root / "Orchestrator").mkdir(parents=True, exist_ok=True)
            self._prepare_phase3_config(project_root, "Orchestrator")

            code, stdout, stderr = self._run_script(
                [
                    "--project-root",
                    str(project_root),
                    "--dry-run",
                    "--model",
                    "codex-5.3-mini",
                    "Orchestrator",
                ]
            )

            self.assertEqual(0, code, msg=stderr)
            payload = json.loads(stdout.strip())
            self.assertEqual("ok", payload["status"])
            self.assertEqual("Orchestrator", payload["launched"][0]["agent_path"])


if __name__ == "__main__":
    unittest.main()
