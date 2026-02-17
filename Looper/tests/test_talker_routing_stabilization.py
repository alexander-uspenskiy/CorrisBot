import json
import tempfile
import unittest
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Looper"))

from codex_prompt_fileloop import LoopRunner  # noqa: E402


class FakeRunner:
    runner_name = "codex"
    supports_filesystem_session_detection = False

    @staticmethod
    def extract_agent_messages(file_lines: list[str]) -> list[str]:
        messages: list[str] = []
        for line in file_lines:
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if payload.get("type") == "agent_message" and isinstance(payload.get("text"), str):
                messages.append(payload["text"])
        return messages


class TestLoopRunner(LoopRunner):
    def __init__(self, executor_dir: Path, inbox_root: Path, agent_message_text: str = "") -> None:
        self.console_messages: list[tuple[str, str]] = []
        self.agent_message_text = agent_message_text
        self.captured_prompts: list[str] = []
        super().__init__(
            executor_dir=executor_dir,
            inbox_root=inbox_root,
            runner=FakeRunner(),
            is_talker_context=True,
        )

    def write_console_line(self, text: str, color: str = "gray") -> None:
        self.console_messages.append((text, color))

    def run_agent(self, prompt_text: str, thread_id: str | None, result_path: Path) -> tuple[list[str], int, str]:
        self.captured_prompts.append(prompt_text)
        if self.agent_message_text:
            with result_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "agent_message", "text": self.agent_message_text}) + "\n")
        return [], 0, "session-test"


def write_prompt(inbox_root: Path, sender_id: str, marker: str, text: str) -> None:
    sender_dir = inbox_root / sender_id
    sender_dir.mkdir(parents=True, exist_ok=True)
    (sender_dir / f"Prompt_{marker}.md").write_text(text, encoding="utf-8")


def list_relay_files(inbox_root: Path, sender_id: str) -> list[Path]:
    sender_dir = inbox_root / sender_id
    if not sender_dir.exists():
        return []
    return sorted(sender_dir.glob("Prompt_*_relay_Result.md"))


class TalkerRoutingStabilizationTests(unittest.TestCase):
    def create_runner(self, temp_root: Path, agent_message_text: str = "") -> TestLoopRunner:
        executor_dir = temp_root / "Talker"
        inbox_root = executor_dir / "Prompts" / "Inbox"
        inbox_root.mkdir(parents=True, exist_ok=True)
        return TestLoopRunner(
            executor_dir=executor_dir,
            inbox_root=inbox_root,
            agent_message_text=agent_message_text,
        )

    def test_unit_unset_user_sender_id_blocks_relay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = self.create_runner(Path(temp_dir))
            runner.handle_relay_delivery("tg_corriscant", "hello", user_sender_id="")

            self.assertEqual([], list_relay_files(runner.inbox_root, "tg_corriscant"))
            self.assertTrue(
                any("protocol error: user_sender_id is unset" in text for text, _ in runner.console_messages)
            )

    def test_unit_target_mismatch_blocks_relay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = self.create_runner(Path(temp_dir))
            runner.handle_relay_delivery("tg_user", "hello", user_sender_id="tg_corriscant")

            self.assertEqual([], list_relay_files(runner.inbox_root, "tg_user"))
            self.assertTrue(
                any("protocol error: target mismatch" in text for text, _ in runner.console_messages)
            )

    def test_unit_valid_target_creates_folder_and_delivers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = self.create_runner(Path(temp_dir))
            target = "tg_corriscant"
            target_dir = runner.inbox_root / target
            self.assertFalse(target_dir.exists())

            runner.handle_relay_delivery(target, "relay payload", user_sender_id=target)

            relay_files = list_relay_files(runner.inbox_root, target)
            self.assertEqual(1, len(relay_files))
            self.assertTrue(target_dir.exists())
            self.assertIn("relay payload", relay_files[0].read_text(encoding="utf-8"))

    def test_unit_reset_signal_clears_routing_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = self.create_runner(Path(temp_dir))
            runner.write_routing_state("tg_corriscant", "operator_command")
            (runner.inbox_root / "reset_signal.json").write_text("{}", encoding="utf-8")

            write_prompt(
                runner.inbox_root,
                sender_id="tg_corriscant",
                marker="2026_02_17_00_00_00_000",
                text="/looper stop",
            )
            runner.run_forever()

            user_sender_id, _, updated_by = runner.read_routing_state()
            self.assertEqual("", user_sender_id)
            self.assertEqual("reset", updated_by)

    def test_unit_routing_control_commands_set_show_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = self.create_runner(Path(temp_dir))

            write_prompt(
                runner.inbox_root,
                sender_id="tg_corriscant",
                marker="2026_02_17_00_00_00_000",
                text="/routing set-user tg_corriscant",
            )
            write_prompt(
                runner.inbox_root,
                sender_id="tg_corriscant",
                marker="2026_02_17_00_00_01_000",
                text="/routing show",
            )
            write_prompt(
                runner.inbox_root,
                sender_id="tg_corriscant",
                marker="2026_02_17_00_00_02_000",
                text="/routing clear",
            )
            write_prompt(
                runner.inbox_root,
                sender_id="tg_corriscant",
                marker="2026_02_17_00_00_03_000",
                text="/looper stop",
            )

            runner.run_forever()

            user_sender_id, _, updated_by = runner.read_routing_state()
            self.assertEqual("", user_sender_id)
            self.assertEqual("operator_command", updated_by)
            self.assertEqual([], runner.captured_prompts)

    def test_unit_non_talker_prompt_has_no_talker_routing_instructions(self) -> None:
        prompt_text = LoopRunner.build_loop_prompt(
            user_prompt="hello",
            sender_id="Executor_001",
            user_sender_id="",
            is_talker_context=False,
        )
        self.assertNotIn("Fixed User Sender ID", prompt_text)
        self.assertNotIn("Talker relay contract", prompt_text)

    def test_e2e_user_prompt_is_processed_by_talker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = self.create_runner(Path(temp_dir), agent_message_text="No relay")
            runner.write_routing_state("tg_corriscant", "operator_command")

            write_prompt(
                runner.inbox_root,
                sender_id="tg_corriscant",
                marker="2026_02_17_00_00_00_000",
                text="Передай задачу оркестратору",
            )
            write_prompt(
                runner.inbox_root,
                sender_id="tg_corriscant",
                marker="2026_02_17_00_00_01_000",
                text="/looper stop",
            )

            runner.run_forever()

            self.assertTrue(runner.captured_prompts)
            self.assertIn("Sender ID: tg_corriscant", runner.captured_prompts[0])

    def test_e2e_orchestrator_relay_delivers_only_to_fixed_user_sender_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            relay_text = (
                "---\n"
                "type: relay\n"
                "target: tg_corriscant\n"
                "from: Orc_Project\n"
                "---\n"
                "[Orc_Project]: done"
            )
            runner = self.create_runner(Path(temp_dir), agent_message_text=relay_text)
            runner.write_routing_state("tg_corriscant", "operator_command")

            write_prompt(
                runner.inbox_root,
                sender_id="Orc_Project",
                marker="2026_02_17_00_00_00_000",
                text="status?",
            )
            write_prompt(
                runner.inbox_root,
                sender_id="tg_corriscant",
                marker="2026_02_17_00_00_01_000",
                text="/looper stop",
            )

            runner.run_forever()

            self.assertEqual(1, len(list_relay_files(runner.inbox_root, "tg_corriscant")))
            self.assertEqual([], list_relay_files(runner.inbox_root, "tg_user"))

    def test_negative_e2e_wrong_target_is_not_delivered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            relay_text = (
                "---\n"
                "type: relay\n"
                "target: tg_user\n"
                "from: Orc_Project\n"
                "---\n"
                "[Orc_Project]: done"
            )
            runner = self.create_runner(Path(temp_dir), agent_message_text=relay_text)
            runner.write_routing_state("tg_corriscant", "operator_command")

            write_prompt(
                runner.inbox_root,
                sender_id="Orc_Project",
                marker="2026_02_17_00_00_00_000",
                text="status?",
            )
            write_prompt(
                runner.inbox_root,
                sender_id="tg_corriscant",
                marker="2026_02_17_00_00_01_000",
                text="/looper stop",
            )

            runner.run_forever()

            self.assertEqual([], list_relay_files(runner.inbox_root, "tg_corriscant"))
            self.assertEqual([], list_relay_files(runner.inbox_root, "tg_user"))
            self.assertTrue(
                any("protocol error: target mismatch" in text for text, _ in runner.console_messages)
            )


if __name__ == "__main__":
    unittest.main()
