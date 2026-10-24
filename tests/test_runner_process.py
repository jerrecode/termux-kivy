"""Process-runner failure, timeout, transcript and one-second default tests."""
from __future__ import annotations

import importlib.util
import gc
import warnings
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "test-all.py"
SPEC = importlib.util.spec_from_file_location("termux_kivy_test_all_script", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class RunnerIsolationTests(unittest.TestCase):
    def test_nonzero_exit_is_recorded_and_not_hidden(self):
        transcript = runner.Transcript()
        case = runner.Case(
            "negative-test",
            (sys.executable, "-u", "-c",
             "import sys; print('stdout marker', flush=True); "
             "print('stderr marker', file=sys.stderr, flush=True); sys.exit(7)"),
            "unit",
        )
        with tempfile.TemporaryDirectory() as directory:
            result, elapsed = runner.run_case(case, transcript, timeout=5)
            output = Path(directory) / "report.txt"
            transcript.write("FINAL STATUS: FAILED")
            transcript.save(output)
            report = output.read_text(encoding="utf-8")
        self.assertEqual(result, "FAIL")
        self.assertIn("stdout marker", report)
        self.assertIn("stderr marker", report)
        self.assertIn("EXIT pid=", report)
        self.assertIn("code=7", report)
        self.assertGreaterEqual(elapsed, 0)

    def test_timeout_kills_child_and_writes_report(self):
        transcript = runner.Transcript()
        case = runner.Case(
            "timeout-test",
            (sys.executable, "-u", "-c",
             "import time; print('before sleep', flush=True); time.sleep(20)"),
            "unit",
        )
        with tempfile.TemporaryDirectory() as directory:
            result, elapsed = runner.run_case(case, transcript, timeout=1)
            output = Path(directory) / "report.txt"
            transcript.save(output)
            report = output.read_text(encoding="utf-8")
        self.assertEqual(result, "TIMEOUT")
        self.assertIn("before sleep", report)
        self.assertIn("TIMEOUT pid=", report)
        self.assertIn("Terminating process group PID=", report)
        self.assertLess(elapsed, 5)

    def test_one_second_gap_is_the_real_default(self):
        with tempfile.TemporaryDirectory() as directory:
            logpath = Path(directory) / "one-second-gap.txt"
            command = [
                sys.executable, str(SCRIPT), "--timeout", "25",
                "--filter", r"^scripted\.(counter|selection)$",
                "--log-file", str(logpath),
            ]
            started = time.monotonic()
            result = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True,
                timeout=30,
            )
            elapsed = time.monotonic() - started
            self.assertEqual(result.returncode, 0, result.stdout[-6000:] + result.stderr)
            content = logpath.read_text(encoding="utf-8")
        self.assertIn("Selected 2 tests; delay=1s", content)
        self.assertEqual(content.count("POST-EXIT COOLDOWN: waiting 1 second(s)"), 1)
        self.assertIn("COOLDOWN COMPLETE", content)
        self.assertIn("FINAL STATUS: PASSED", content)
        self.assertGreaterEqual(elapsed, 1.0)

    def test_children_do_not_leave_unclosed_pipe_warnings(self):
        class SilentTranscript:
            def write(self, *args, **kwargs):
                pass
        cases = [
            runner.Case("success", (sys.executable, "-c", "print('ok')"), "unit"),
            runner.Case("expected-failure", (sys.executable, "-c", "import sys; sys.exit(9)"), "unit"),
            runner.Case("timeout", (sys.executable, "-c", "import time; time.sleep(10)"), "unit"),
        ]
        with warnings.catch_warnings(record=True) as found:
            warnings.simplefilter("always", ResourceWarning)
            outputs = [runner.run_case(case, SilentTranscript(), timeout=.3)
                       for case in cases]
            gc.collect()
        self.assertEqual([x[0] for x in outputs], ["PASS", "FAIL", "TIMEOUT"])
        leaked = [str(w.message) for w in found
                  if issubclass(w.category, ResourceWarning) and
                  "unclosed file" in str(w.message)]
        self.assertEqual(leaked, [], leaked)

    def test_repetition_builds_distinct_cases_not_parallel_threads(self):
        cases = runner.all_cases(include_device=True, device_repeats=20,
                                 device_options=("--foreground-timeout", "6"))
        physical = [c for c in cases if c.kind == "device"]
        self.assertEqual(len(physical), 20)
        self.assertTrue(physical[0].name.endswith(".run-001"))
        self.assertTrue(physical[-1].name.endswith(".run-020"))
        self.assertEqual(physical[0].command, physical[-1].command)

    def test_device_preflight_rejects_missing_adb_without_running_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            logfile = Path(directory) / "preflight.txt"
            result = subprocess.run([
                sys.executable, str(SCRIPT), "--device", "--filter",
                "^android\\.", "--adb", str(Path(directory) / "no-such-adb"),
                "--log-file", str(logfile), "--delay", "0"
            ], cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            text = logfile.read_text(encoding="utf-8")
            self.assertIn("ADB PREFLIGHT FAILED", text)
            self.assertIn("FINAL STATUS: FAILED", text)
            self.assertNotIn("SPAWNED pid=", text)

    def test_shell_entrypoint_has_execute_bit(self):
        if os.name == "posix":
            self.assertTrue(os.access(ROOT / "test-all.sh", os.X_OK))


if __name__ == "__main__":
    unittest.main()
