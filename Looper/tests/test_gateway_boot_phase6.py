import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "Gateways" / "Telegram" / "run_gateway.bat"


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


class GatewayBootPhase6Tests(unittest.TestCase):
    def _run_gateway(self, env: dict[str, str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            ["cmd", "/c", "call", str(SCRIPT_PATH), "--dry-run"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_gateway_dry_run_resolves_talker_via_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            talker_root = temp_root / "TalkerRuntime"
            _write_json(talker_root / "AgentRunner" / "model_registry.json", _default_registry())
            _write_json(talker_root / "agent_runner.json", {"version": 1, "runner": "kimi"})
            _write_json(talker_root / "codex_profile.json", {"version": 1, "model": "codex-5.3"})
            _write_json(talker_root / "kimi_profile.json", {"version": 1, "model": "kimi-k2"})
            (talker_root / "AGENTS_TEMPLATE.md").write_text("# Talker template\n", encoding="utf-8")

            env = os.environ.copy()
            env["REPO_ROOT"] = str(REPO_ROOT)
            env["LOOPER_ROOT"] = str(REPO_ROOT / "Looper")
            env["TALKER_ROOT"] = str(talker_root)
            env["TEMPLATE_ROOT"] = str(REPO_ROOT / "ProjectFolder_Template")
            env["WORKDIR"] = str(REPO_ROOT / "Gateways" / "Telegram")
            env["TEMP"] = str(temp_root)

            code, stdout, stderr = self._run_gateway(env)
            self.assertEqual(0, code, msg=stderr)
            self.assertIn("[BOOT] Effective runner: kimi (source=profile)", stdout)
            self.assertIn("[BOOT] Effective model: kimi-k2 (source=profile)", stdout)
            self.assertIn("KimiLoop.bat", stdout)
            self.assertIn("[dry-run] Talker cmd:", stdout)


if __name__ == "__main__":
    unittest.main()
