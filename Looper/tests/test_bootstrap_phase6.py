import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CREATE_PROJECT = REPO_ROOT / "Looper" / "CreateProjectStructure.bat"
CREATE_WORKER = REPO_ROOT / "Looper" / "CreateWorkerStructure.bat"


class BootstrapPhase6Tests(unittest.TestCase):
    def _run_cmd(self, cmd: list[str], workdir: Path | None = None) -> tuple[int, str, str]:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(workdir) if workdir else None,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_new_project_and_worker_receive_required_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "ProjectP6"
            env = os.environ.copy()
            env["REPO_ROOT"] = str(REPO_ROOT)
            env["LOOPER_ROOT"] = str(REPO_ROOT / "Looper")
            env["TALKER_ROOT"] = str(REPO_ROOT / "Talker")
            env["TEMPLATE_ROOT"] = str(REPO_ROOT / "ProjectFolder_Template")

            proc_project = subprocess.run(
                ["cmd", "/c", "call", str(CREATE_PROJECT), str(project_root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            self.assertEqual(0, proc_project.returncode, msg=proc_project.stdout + proc_project.stderr)

            workers_root = project_root / "Workers"
            proc_worker = subprocess.run(
                ["cmd", "/c", "call", str(CREATE_WORKER), "Worker_002", "Orc_ProjectP6"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(workers_root),
                env=env,
            )
            self.assertEqual(0, proc_worker.returncode, msg=proc_worker.stdout + proc_worker.stderr)

            required_project_files = [
                project_root / "AgentRunner" / "model_registry.json",
                project_root / "Orchestrator" / "agent_runner.json",
                project_root / "Orchestrator" / "codex_profile.json",
                project_root / "Orchestrator" / "kimi_profile.json",
                project_root / "Orchestrator" / "CR_REPORT_TEMPLATE.md",
            ]
            required_worker_files = [
                project_root / "Workers" / "Worker_002" / "agent_runner.json",
                project_root / "Workers" / "Worker_002" / "codex_profile.json",
                project_root / "Workers" / "Worker_002" / "kimi_profile.json",
            ]
            for path in [*required_project_files, *required_worker_files]:
                self.assertTrue(path.is_file(), msg=f"missing required bootstrap file: {path}")

    def test_talker_runtime_root_has_profile_and_registry(self) -> None:
        required = [
            REPO_ROOT / "Talker" / "AgentRunner" / "model_registry.json",
            REPO_ROOT / "Talker" / "agent_runner.json",
            REPO_ROOT / "Talker" / "codex_profile.json",
            REPO_ROOT / "Talker" / "kimi_profile.json",
        ]
        for path in required:
            self.assertTrue(path.is_file(), msg=f"missing Talker runtime file: {path}")


if __name__ == "__main__":
    unittest.main()
