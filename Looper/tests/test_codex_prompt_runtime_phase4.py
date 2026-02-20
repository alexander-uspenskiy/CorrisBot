import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Looper"))

from codex_prompt_fileloop import LoopRunner  # noqa: E402
from agent_runners import CodexRunner  # noqa: E402


class FakeRuntimeRunner:
    def __init__(self, runner_name: str, model: str | None = None, reasoning_effort: str | None = None) -> None:
        self.runner_name = runner_name
        self.model = model
        self.reasoning_effort = reasoning_effort


class InspectLoopRunner(LoopRunner):
    def __init__(self, worker_dir: Path, inbox_root: Path, runner: FakeRuntimeRunner, pinned: bool) -> None:
        self.console_messages: list[tuple[str, str]] = []
        super().__init__(
            worker_dir=worker_dir,
            inbox_root=inbox_root,
            runner=runner,  # type: ignore[arg-type]
            cli_reasoning_effort_pinned=pinned,
        )

    def write_console_line(self, text: str, color: str = "gray") -> None:
        self.console_messages.append((text, color))


class CodexPromptRuntimePhase4Tests(unittest.TestCase):
    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _prepare_runtime_root(self, project_root: Path, agent_dir: Path) -> None:
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
        self._write_json(agent_dir / "agent_runner.json", {"version": 1, "runner": "codex"})
        self._write_json(
            agent_dir / "codex_profile.json",
            {"version": 1, "model": "codex-5.3", "reasoning_effort": "low"},
        )
        self._write_json(agent_dir / "kimi_profile.json", {"version": 1, "model": "kimi-k2"})

    def test_codex_reasoning_hot_reload_and_model_stays_launch_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "Project"
            agent_dir = project_root / "Workers" / "Worker_001"
            inbox_root = agent_dir / "Prompts" / "Inbox"
            inbox_root.mkdir(parents=True, exist_ok=True)
            self._prepare_runtime_root(project_root, agent_dir)

            runner = FakeRuntimeRunner(runner_name="codex", model="codex-5.3-mini")
            loop = InspectLoopRunner(worker_dir=agent_dir, inbox_root=inbox_root, runner=runner, pinned=False)

            loop.refresh_runtime_apply_rules()
            self.assertEqual("low", runner.reasoning_effort)
            self.assertEqual("codex-5.3-mini", runner.model)

            self._write_json(
                agent_dir / "codex_profile.json",
                {"version": 1, "model": "codex-5.3", "reasoning_effort": "high"},
            )
            loop.refresh_runtime_apply_rules()

            self.assertEqual("high", runner.reasoning_effort)
            self.assertEqual("codex-5.3-mini", runner.model)
            self.assertTrue(any("updated to 'high'" in text for text, _ in loop.console_messages))

    def test_cli_reasoning_is_pinned_for_process_lifetime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "Project"
            agent_dir = project_root / "Workers" / "Worker_001"
            inbox_root = agent_dir / "Prompts" / "Inbox"
            inbox_root.mkdir(parents=True, exist_ok=True)
            self._prepare_runtime_root(project_root, agent_dir)

            runner = FakeRuntimeRunner(runner_name="codex", model="codex-5.3", reasoning_effort="medium")
            loop = InspectLoopRunner(worker_dir=agent_dir, inbox_root=inbox_root, runner=runner, pinned=True)

            loop.refresh_runtime_apply_rules()
            self.assertEqual("medium", runner.reasoning_effort)

            self._write_json(
                agent_dir / "codex_profile.json",
                {"version": 1, "model": "codex-5.3", "reasoning_effort": "low"},
            )
            loop.refresh_runtime_apply_rules()

            self.assertEqual("medium", runner.reasoning_effort)
            pinned_warnings = [
                text for text, _ in loop.console_messages if "CLI --reasoning-effort is pinned for this process" in text
            ]
            self.assertEqual(1, len(pinned_warnings))

    def test_runner_change_logs_warning_and_no_hot_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "Project"
            agent_dir = project_root / "Workers" / "Worker_001"
            inbox_root = agent_dir / "Prompts" / "Inbox"
            inbox_root.mkdir(parents=True, exist_ok=True)
            self._prepare_runtime_root(project_root, agent_dir)

            runner = FakeRuntimeRunner(runner_name="codex", model="codex-5.3")
            loop = InspectLoopRunner(worker_dir=agent_dir, inbox_root=inbox_root, runner=runner, pinned=False)

            loop.refresh_runtime_apply_rules()
            self._write_json(agent_dir / "agent_runner.json", {"version": 1, "runner": "kimi"})
            loop.refresh_runtime_apply_rules()
            loop.refresh_runtime_apply_rules()

            self.assertEqual("codex", runner.runner_name)
            warnings = [text for text, _ in loop.console_messages if "runner change applies next launch" in text]
            self.assertEqual(1, len(warnings))

    def test_codex_runner_build_command_keeps_model_override(self) -> None:
        runner = CodexRunner(
            codex_bin="codex",
            dangerously_bypass_sandbox=False,
            model="codex-5.3-mini",
            reasoning_effort="high",
        )
        cmd, stdin_text = runner.build_command(
            prompt_text="hello",
            session_id=None,
            work_dir=Path("C:/CorrisBot"),
        )

        self.assertEqual("hello", stdin_text)
        self.assertIn("-m", cmd)
        model_index = cmd.index("-m")
        self.assertEqual("codex-5.3-mini", cmd[model_index + 1])


if __name__ == "__main__":
    unittest.main()
