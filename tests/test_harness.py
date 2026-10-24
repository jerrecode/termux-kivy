"""Self-tests for the process-isolated transcript runner and its interaction scripts."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestAllHarnessTests(unittest.TestCase):
    def run_script(self, filter_text):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.txt"
            command = [
                sys.executable, str(ROOT / "test-all.py"),
                "--filter", filter_text,
                "--delay", "0",
                "--timeout", "30",
                "--log-file", str(output),
            ]
            process = subprocess.run(
                command, cwd=ROOT, text=True,
                capture_output=True, timeout=60,
                check=False,
            )
            self.assertEqual(
                process.returncode, 0,
                process.stdout[-6000:] + "\n" + process.stderr[-6000:]
            )
            self.assertTrue(output.is_file())
            transcript = output.read_text(encoding="utf-8")
            self.assertIn("FINAL STATUS: PASSED", transcript)
            self.assertIn("PROCESS", process.stdout.upper() if "process" in process.stdout.lower() else "PROCESS")
            self.assertIn("SPAWNED pid=", transcript)
            self.assertIn("EXIT pid=", transcript)
            return transcript

    def test_scripted_touches_are_recorded(self):
        transcript = self.run_script(r"^scripted\.counter$")
        self.assertIn("SIMULATED_TOUCH", transcript)
        self.assertIn("SCENARIO PASS: counter", transcript)
        self.assertIn("3 clicks coalesce into 1 native text write", transcript)

    def test_scripted_unicode_typing_is_recorded(self):
        transcript = self.run_script(r"^scripted\.typing$")
        self.assertIn("SIMULATED_KEYBOARD", transcript)
        self.assertIn("Grüße 世界", transcript)
        self.assertIn("SCENARIO PASS: typing", transcript)

    def test_listing_does_not_run_processes(self):
        process = subprocess.run(
            [sys.executable, str(ROOT / "test-all.py"), "--list",
             "--filter", "^scripted\\."],
            cwd=ROOT, capture_output=True, text=True, timeout=15
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(len(process.stdout.splitlines()), 6)
        self.assertNotIn("SPAWNED", process.stdout)


if __name__ == "__main__":
    unittest.main()
