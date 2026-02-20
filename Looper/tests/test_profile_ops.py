import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "Looper" / "profile_ops.py"


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


def _write_agent_profiles(agent_dir: Path) -> None:
    _write_json(agent_dir / "agent_runner.json", {"version": 1, "runner": "codex"})
    _write_json(
        agent_dir / "codex_profile.json",
        {"version": 1, "model": "codex-5.3", "reasoning_effort": "medium"},
    )
    _write_json(agent_dir / "kimi_profile.json", {"version": 1, "model": "kimi-k2"})


class ProfileOpsTests(unittest.TestCase):
    def _run_script(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _prepare_project_tree(self, temp_root: Path) -> tuple[Path, Path, Path]:
        project_root = temp_root / "ProjectA"
        _write_json(project_root / "AgentRunner" / "model_registry.json", _default_registry())

        orchestrator_dir = project_root / "Orchestrator"
        worker_dir = project_root / "Workers" / "Worker_001"
        _write_agent_profiles(orchestrator_dir)
        _write_agent_profiles(worker_dir)
        return project_root, orchestrator_dir, worker_dir

    def _read_audit_lines(self, runtime_root: Path) -> list[dict]:
        audit_path = runtime_root / "AgentRunner" / "profile_change_audit.jsonl"
        if not audit_path.exists():
            return []
        lines = [line.strip() for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [json.loads(line) for line in lines]

    def test_valid_mutation_appends_ok_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root, _, worker_dir = self._prepare_project_tree(Path(temp_dir))

            code, stdout, stderr = self._run_script(
                [
                    "set-backend",
                    "--agent-dir",
                    str(worker_dir),
                    "--actor-role",
                    "orchestrator",
                    "--actor-id",
                    "Orc_ProjectA",
                    "--request-ref",
                    "REQ-001",
                    "--intent",
                    "explicit",
                    "--backend",
                    "codex",
                    "--model",
                    "codex-5.3-mini",
                ]
            )

            self.assertEqual(0, code, msg=stderr)
            payload = json.loads(stdout.strip())
            self.assertEqual("ok", payload["status"])
            self.assertEqual("set_model", payload["action"])

            codex_profile = json.loads((worker_dir / "codex_profile.json").read_text(encoding="utf-8"))
            self.assertEqual("codex-5.3-mini", codex_profile["model"])

            audit_lines = self._read_audit_lines(project_root)
            self.assertEqual(1, len(audit_lines))
            self.assertEqual("ok", audit_lines[0]["result"])
            self.assertEqual("set_model", audit_lines[0]["action"])

    def test_rejected_mutation_appends_error_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root, _, worker_dir = self._prepare_project_tree(Path(temp_dir))

            code, _, stderr = self._run_script(
                [
                    "set-backend",
                    "--agent-dir",
                    str(worker_dir),
                    "--actor-role",
                    "orchestrator",
                    "--actor-id",
                    "Orc_ProjectA",
                    "--request-ref",
                    "REQ-002",
                    "--intent",
                    "explicit",
                    "--backend",
                    "codex",
                    "--model",
                    "codex-unknown",
                ]
            )

            self.assertEqual(2, code)
            self.assertEqual("model_not_in_registry", stderr.strip())

            audit_lines = self._read_audit_lines(project_root)
            self.assertEqual(1, len(audit_lines))
            self.assertEqual("error", audit_lines[0]["result"])
            self.assertEqual("model_not_in_registry", audit_lines[0]["error_code"])

    def test_lock_contention_returns_error_and_no_partial_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root, _, worker_dir = self._prepare_project_tree(Path(temp_dir))
            codex_path = worker_dir / "codex_profile.json"
            before_text = codex_path.read_text(encoding="utf-8")
            lock_path = codex_path.with_suffix(codex_path.suffix + ".lock")
            lock_path.write_text("token=foreign\n", encoding="utf-8")

            code, _, stderr = self._run_script(
                [
                    "set-backend",
                    "--agent-dir",
                    str(worker_dir),
                    "--actor-role",
                    "orchestrator",
                    "--actor-id",
                    "Orc_ProjectA",
                    "--request-ref",
                    "REQ-003",
                    "--intent",
                    "explicit",
                    "--backend",
                    "codex",
                    "--model",
                    "codex-5.3-mini",
                    "--lock-timeout",
                    "0.2",
                ]
            )

            self.assertEqual(2, code)
            self.assertEqual("lock_timeout", stderr.strip())
            after_text = codex_path.read_text(encoding="utf-8")
            self.assertEqual(before_text, after_text)
            json.loads(after_text)

            audit_lines = self._read_audit_lines(project_root)
            self.assertEqual(1, len(audit_lines))
            self.assertEqual("error", audit_lines[0]["result"])
            self.assertEqual("lock_timeout", audit_lines[0]["error_code"])

    def test_ownership_violation_is_blocked_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root, orchestrator_dir, _ = self._prepare_project_tree(Path(temp_dir))

            code, _, stderr = self._run_script(
                [
                    "set-runner",
                    "--agent-dir",
                    str(orchestrator_dir),
                    "--actor-role",
                    "orchestrator",
                    "--actor-id",
                    "Orc_ProjectA",
                    "--request-ref",
                    "REQ-004",
                    "--intent",
                    "explicit",
                    "--runner",
                    "kimi",
                ]
            )

            self.assertEqual(2, code)
            self.assertEqual("ownership_violation", stderr.strip())

            audit_lines = self._read_audit_lines(project_root)
            self.assertEqual(1, len(audit_lines))
            self.assertEqual("error", audit_lines[0]["result"])
            self.assertEqual("ownership_violation", audit_lines[0]["error_code"])


if __name__ == "__main__":
    unittest.main()
