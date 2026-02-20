import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LOOPER_ROOT = REPO_ROOT / "Looper"
SCRIPT_PATH = LOOPER_ROOT / "resolve_agent_config.py"
sys.path.insert(0, str(LOOPER_ROOT))

from agent_config_resolver import ResolverError, resolve_agent_config  # noqa: E402


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


def _prepare_agent_tree(tmp: Path) -> tuple[Path, Path]:
    runtime_root = tmp / "ProjectA"
    _write_json(runtime_root / "AgentRunner" / "model_registry.json", _default_registry())

    agent_dir = runtime_root / "Workers" / "Worker_001"
    _write_json(agent_dir / "agent_runner.json", {"version": 1, "runner": "codex"})
    _write_json(
        agent_dir / "codex_profile.json",
        {"version": 1, "model": "codex-5.3", "reasoning_effort": "high"},
    )
    _write_json(agent_dir / "kimi_profile.json", {"version": 1, "model": "kimi-k2"})
    return runtime_root, agent_dir


class AgentConfigResolverTests(unittest.TestCase):
    def _run_bridge(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_resolve_success_from_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root, agent_dir = _prepare_agent_tree(Path(temp_dir))
            payload = resolve_agent_config(agent_dir=agent_dir)

            self.assertEqual(str(runtime_root.resolve()), payload["runtime_root"])
            self.assertEqual("codex", payload["effective"]["runner"])
            self.assertEqual("codex-5.3", payload["effective"]["model"])
            self.assertEqual("high", payload["effective"]["reasoning"])
            self.assertEqual("profile", payload["source"]["runner"])
            self.assertEqual("profile", payload["source"]["model"])
            self.assertEqual("profile", payload["source"]["reasoning"])
            self.assertTrue(payload["capability"]["supports_runtime_model_override"])

    def test_resolve_success_cli_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, agent_dir = _prepare_agent_tree(Path(temp_dir))
            payload = resolve_agent_config(
                agent_dir=agent_dir,
                cli_runner="kimi",
                cli_model="kimi-k2",
            )

            self.assertEqual("kimi", payload["effective"]["runner"])
            self.assertEqual("kimi-k2", payload["effective"]["model"])
            self.assertEqual("", payload["effective"]["reasoning"])
            self.assertEqual("cli", payload["source"]["runner"])
            self.assertEqual("cli", payload["source"]["model"])
            self.assertEqual("backend-default", payload["source"]["reasoning"])

    def test_runtime_root_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent_dir = Path(temp_dir) / "Workers" / "Worker_001"
            _write_json(agent_dir / "agent_runner.json", {"version": 1, "runner": "codex"})
            _write_json(agent_dir / "codex_profile.json", {"version": 1, "model": "codex-5.3"})
            _write_json(agent_dir / "kimi_profile.json", {"version": 1, "model": "kimi-k2"})

            with self.assertRaises(ResolverError) as ctx:
                resolve_agent_config(agent_dir=agent_dir)
            self.assertEqual("runtime_root_not_found", ctx.exception.code)

    def test_model_not_in_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, agent_dir = _prepare_agent_tree(Path(temp_dir))
            with self.assertRaises(ResolverError) as ctx:
                resolve_agent_config(agent_dir=agent_dir, cli_model="codex-unknown")
            self.assertEqual("model_not_in_registry", ctx.exception.code)

    def test_inactive_profile_invalid_json_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, agent_dir = _prepare_agent_tree(Path(temp_dir))
            (agent_dir / "kimi_profile.json").write_text("{invalid", encoding="utf-8")
            payload = resolve_agent_config(agent_dir=agent_dir)
            self.assertEqual("codex", payload["effective"]["runner"])
            self.assertTrue(
                any(msg.startswith("inactive_profile_invalid_ignored:") for msg in payload["warnings"])
            )

    def test_bridge_bat_env_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, agent_dir = _prepare_agent_tree(Path(temp_dir))
            code, stdout, stderr = self._run_bridge(
                ["--agent-dir", str(agent_dir), "--format", "bat_env"]
            )

            self.assertEqual(0, code, msg=stderr)
            lines = [line.strip() for line in stdout.splitlines() if line.strip()]
            self.assertIn('set "RUNNER=codex"', lines)
            self.assertIn('set "MODEL=codex-5.3"', lines)
            self.assertIn('set "REASONING_EFFORT=high"', lines)
            self.assertIn('set "SOURCE_RUNNER=profile"', lines)
            self.assertIn('set "SOURCE_MODEL=profile"', lines)
            self.assertIn('set "SOURCE_REASONING=profile"', lines)

    def test_bridge_fail_fast_active_profile_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, agent_dir = _prepare_agent_tree(Path(temp_dir))
            (agent_dir / "codex_profile.json").unlink()
            code, _, stderr = self._run_bridge(
                ["--agent-dir", str(agent_dir), "--format", "bat_env"]
            )
            self.assertEqual(2, code)
            self.assertEqual("active_profile_missing", stderr.strip())

    def test_bridge_fail_fast_reasoning_incompatible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, agent_dir = _prepare_agent_tree(Path(temp_dir))
            code, _, stderr = self._run_bridge(
                [
                    "--agent-dir",
                    str(agent_dir),
                    "--format",
                    "bat_env",
                    "--runner",
                    "kimi",
                    "--reasoning-effort",
                    "high",
                ]
            )
            self.assertEqual(2, code)
            self.assertEqual("reasoning_incompatible_with_runner", stderr.strip())

    def test_bridge_argument_error_is_machine_code(self) -> None:
        code, _, stderr = self._run_bridge([])
        self.assertEqual(2, code)
        self.assertEqual("argument_error", stderr.strip())


if __name__ == "__main__":
    unittest.main()
