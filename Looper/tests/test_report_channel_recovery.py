import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOOPER_ROOT = REPO_ROOT / "Looper"
SCRIPT_PATH = LOOPER_ROOT / "send_reply_to_report.py"

class TestReportChannelRecovery(unittest.TestCase):
    def _run_script(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr

    def setUp(self):
        sys.path.insert(0, str(LOOPER_ROOT))
        self.original_trace_relay = os.environ.get("TRACE_RELAY_ENABLED")
        
    def tearDown(self):
        if str(LOOPER_ROOT) in sys.path:
            sys.path.remove(str(LOOPER_ROOT))
        if self.original_trace_relay is None:
            os.environ.pop("TRACE_RELAY_ENABLED", None)
        else:
            os.environ["TRACE_RELAY_ENABLED"] = self.original_trace_relay

    def test_relay_logic_trace_relay_disabled_suppresses_trace(self) -> None:
        from codex_prompt_fileloop import LoopRunner
        from agent_runners import CodexRunner
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            inbox_root = temp_root / "Inbox"
            worker_dir = temp_root / "Worker"
            worker_dir.mkdir(parents=True)
            runner = CodexRunner(codex_bin="mock", sandbox_mode="read-only", approval_policy="never")
            loop_runner = LoopRunner(worker_dir, inbox_root, runner, is_talker_context=True)
            
            os.environ["TRACE_RELAY_ENABLED"] = "false"
            
            relay_content = (
                "Message-Meta:\n"
                "- MessageClass: trace\n" # <--- should be suppressed
                "- ReportType: status\n"
                "- ReportID: t_001\n"
                "- RouteSessionID: RS_TEST\n"
                "- ProjectTag: PT_TEST\n\n"
                "trace log data"
            )
            
            loop_runner.handle_relay_delivery("UserSenderXYZ", relay_content, "UserSenderXYZ")
            
            # Since TRACE_RELAY_ENABLED is false, it should NOT deliver
            target_inbox = inbox_root / "UserSenderXYZ"
            if target_inbox.exists():
                self.assertEqual(len(list(target_inbox.iterdir())), 0, "Trace should be suppressed when TRACE_RELAY_ENABLED is false")

    def test_relay_logic_trace_relay_always_relays_report(self) -> None:
        from codex_prompt_fileloop import LoopRunner
        from agent_runners import CodexRunner
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            inbox_root = temp_root / "Inbox"
            worker_dir = temp_root / "Worker"
            worker_dir.mkdir(parents=True)
            runner = CodexRunner(codex_bin="mock", sandbox_mode="read-only", approval_policy="never")
            loop_runner = LoopRunner(worker_dir, inbox_root, runner, is_talker_context=True)
            
            os.environ["TRACE_RELAY_ENABLED"] = "false"
            
            relay_content = (
                "Message-Meta:\n"
                "- MessageClass: report\n" # <--- MUST BYPASS
                "- ReportType: phase_gate\n"
                "- ReportID: rep_001\n"
                "- RouteSessionID: RS_TEST\n"
                "- ProjectTag: PT_TEST\n\n"
                "mandatory report data"
            )
            
            loop_runner.handle_relay_delivery("UserSenderXYZ", relay_content, "UserSenderXYZ")
            
            target_inbox = inbox_root / "UserSenderXYZ"
            self.assertTrue(target_inbox.exists())
            files = list(target_inbox.iterdir())
            self.assertEqual(len(files), 1, "Report MUST be relayed even if TRACE_RELAY_ENABLED is false")
            self.assertIn("mandatory report data", files[0].read_text(encoding="utf-8"))

    def test_relay_duplicate_report_guard(self) -> None:
        from codex_prompt_fileloop import LoopRunner
        from agent_runners import CodexRunner
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            inbox_root = temp_root / "Inbox"
            worker_dir = temp_root / "Worker"
            worker_dir.mkdir(parents=True)
            runner = CodexRunner(codex_bin="mock", sandbox_mode="read-only", approval_policy="never")
            loop_runner = LoopRunner(worker_dir, inbox_root, runner, is_talker_context=True)
            
            relay_content = (
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_dupe\n" # <--- duplicate test
                "- RouteSessionID: RS_TEST\n"
                "- ProjectTag: PT_TEST\n\n"
                "data"
            )
            
            loop_runner.handle_relay_delivery("UserSenderXYZ", relay_content, "UserSenderXYZ")
            # Should be delivered immediately
            target_inbox = inbox_root / "UserSenderXYZ"
            files1 = list(target_inbox.iterdir())
            self.assertEqual(len(files1), 1)
            
            # Second attempt with same ID should be suppressed completely
            loop_runner.handle_relay_delivery("UserSenderXYZ", relay_content, "UserSenderXYZ")
            files2 = list(target_inbox.iterdir())
            self.assertEqual(len(files2), 1) # Still 1

    def test_relay_invalid_message_meta_is_blocked(self) -> None:
        from codex_prompt_fileloop import LoopRunner
        from agent_runners import CodexRunner

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            inbox_root = temp_root / "Inbox"
            worker_dir = temp_root / "Worker"
            worker_dir.mkdir(parents=True)
            runner = CodexRunner(codex_bin="mock", sandbox_mode="read-only", approval_policy="never")
            loop_runner = LoopRunner(worker_dir, inbox_root, runner, is_talker_context=True)

            relay_content = (
                "Message-Meta:\n"
                "- MessageClass: trace\n"
                "- ReportType: BAD_TYPE\n"
                "- ReportID: bad_meta_001\n"
                "- RouteSessionID: RS_TEST\n"
                "- ProjectTag: PT_TEST\n\n"
                "data"
            )

            loop_runner.handle_relay_delivery("UserSenderXYZ", relay_content, "UserSenderXYZ")

            target_inbox = inbox_root / "UserSenderXYZ"
            if target_inbox.exists():
                self.assertEqual(len(list(target_inbox.iterdir())), 0)

    def test_send_reply_idempotency_audit_append(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            app_root = temp_root / "_RUN_CorrisBot"
            talker_root = app_root / "Talker"
            agents_root = temp_root / "Project_A"
            edit_root = temp_root / "EditRepo"
            talker_root.mkdir(parents=True, exist_ok=True)
            agents_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            
            # The audit log path is now explicitly passed via --audit-file
            audit_file = talker_root / "Temp" / "report_delivery_audit.jsonl"
            
            inbox = talker_root / "Prompts" / "Inbox" / "Orc_ProjectX"
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            prompt_file.write_text(
                "\n".join(
                    [
                        "Route-Meta:",
                        "- RouteSessionID: RS_X",
                        "- ProjectTag: ProjectX",
                        "",
                        "Routing-Contract:",
                        "- Version: 1",
                        f"- RouteSessionID: RS_X",
                        f"- AppRoot: {app_root.resolve()}",
                        f"- AgentsRoot: {agents_root.resolve()}",
                        f"- EditRoot: {edit_root.resolve()}",
                        "- ProjectTag: ProjectX",
                        "- OrchestratorSenderID: Orc_ProjectX",
                        "- CreatedAtUTC: 2026-02-20T12:00:00Z",
                        "",
                        "Reply-To:",
                        f"- InboxPath: {inbox}",
                        "- SenderID: Orc_ProjectX",
                        "- FilePattern: Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md",
                        "",
                        "Task payload here",
                    ]
                ),
                encoding="utf-8",
            )
            report_file.write_text(
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_test_audit_888\n"
                "- RouteSessionID: RS_X\n"
                "- ProjectTag: ProjectX\n\n"
                "delivery payload", 
                encoding="utf-8"
            )

            # Execution 1
            proc1 = subprocess.run(
                [
                    sys.executable, str(SCRIPT_PATH), 
                    "--incoming-prompt", str(prompt_file), 
                    "--report-file", str(report_file),
                    "--audit-file", str(audit_file),
                ],
                capture_output=True, text=True, encoding="utf-8"
            )
            self.assertEqual(0, proc1.returncode, proc1.stderr)
            out1 = json.loads(proc1.stdout.strip())
            self.assertNotEqual("<idempotent_skip>", out1["delivered_file"])
            
            # Verify Audit logs
            self.assertTrue(audit_file.exists())
            audit_lines = audit_file.read_text("utf-8").splitlines()
            self.assertEqual(len(audit_lines), 1)
            record1 = json.loads(audit_lines[0])
            self.assertEqual(record1["report_id"], "rep_test_audit_888")
            self.assertEqual(record1["result"], "ok")
            
            # Execution 2 (Idempotency skip)
            proc2 = subprocess.run(
                [
                    sys.executable, str(SCRIPT_PATH), 
                    "--incoming-prompt", str(prompt_file), 
                    "--report-file", str(report_file),
                    "--audit-file", str(audit_file),
                ],
                capture_output=True, text=True, encoding="utf-8"
            )
            self.assertEqual(0, proc2.returncode)
            out2 = json.loads(proc2.stdout.strip())
            self.assertEqual("<idempotent_skip>", out2["delivered_file"])
            
            # Ensure no new prompt was created
            files_in_inbox = list(inbox.iterdir())
            self.assertEqual(len(files_in_inbox), 1) # Only the first one

if __name__ == "__main__":
    unittest.main()
