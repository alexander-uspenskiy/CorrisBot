import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "Looper" / "StartLoopsInWT.py"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_registry() -> dict:
    return {
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
    }


class LauncherIntegrationPhase6Tests(unittest.TestCase):
    def _run_script(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _prepare_project(self, root: Path, agent_rel: str, runner: str, model: str, reasoning: str | None = None) -> tuple[Path, Path]:
        project_root = root / "ProjectA"
        (project_root / "Temp").mkdir(parents=True, exist_ok=True)
        _write_json(project_root / "AgentRunner" / "model_registry.json", _default_registry())
        agent_dir = project_root / Path(agent_rel)
        _write_json(agent_dir / "agent_runner.json", {"version": 1, "runner": runner})
        codex_payload = {"version": 1, "model": "codex-5.3"}
        if reasoning is not None:
            codex_payload["reasoning_effort"] = reasoning
        _write_json(agent_dir / "codex_profile.json", codex_payload)
        _write_json(agent_dir / "kimi_profile.json", {"version": 1, "model": "kimi-k2"})
        _write_json(
            root / "loops.wt.json",
            {
                "runner": "codex",
                "window_name_template": "CorrisBot",
                "max_panes_per_tab": 4,
            },
        )
        return project_root, root / "loops.wt.json"

    def test_dry_run_uses_profile_runner_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            project_root, config_path = self._prepare_project(
                temp_root,
                agent_rel="Orchestrator",
                runner="kimi",
                model="kimi-k2",
            )

            code, stdout, stderr = self._run_script(
                [
                    str(project_root),
                    "Orchestrator",
                    "--config-path",
                    str(config_path),
                    "--dry-run",
                ]
            )
            self.assertEqual(0, code, msg=stderr)
            self.assertIn("Resolved:     runner=kimi (source=profile)", stdout)
            self.assertIn("KimiLoop.bat", stdout)

    def test_cli_runner_override_precedence_in_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            project_root, config_path = self._prepare_project(
                temp_root,
                agent_rel="Workers/Worker_001",
                runner="codex",
                model="codex-5.3",
                reasoning="high",
            )

            code, stdout, stderr = self._run_script(
                [
                    str(project_root),
                    "Workers\\Worker_001",
                    "--config-path",
                    str(config_path),
                    "--runner",
                    "kimi",
                    "--model",
                    "kimi-k2",
                    "--dry-run",
                ]
            )
            self.assertEqual(0, code, msg=stderr)
            self.assertIn("Resolved:     runner=kimi (source=cli)", stdout)
            self.assertIn("KimiLoop.bat", stdout)

    def test_no_global_loops_wt_runner_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            project_root, config_path = self._prepare_project(
                temp_root,
                agent_rel="Orchestrator",
                runner="kimi",
                model="kimi-k2",
            )
            # Keep misleading legacy field; resolver must still use per-agent profile.
            _write_json(config_path, {"runner": "codex", "window_name_template": "CorrisBot"})

            code, stdout, stderr = self._run_script(
                [
                    str(project_root),
                    "Orchestrator",
                    "--config-path",
                    str(config_path),
                    "--dry-run",
                ]
            )
            self.assertEqual(0, code, msg=stderr)
            self.assertIn("Resolved:     runner=kimi (source=profile)", stdout)
            self.assertNotIn("Resolved:     runner=codex", stdout)


if __name__ == "__main__":
    unittest.main()
