#!/usr/bin/env python3
"""Sequential, process-isolated test harness for termux-kivy.

Each unittest method, scripted interaction scenario, and optional Android E2E
case runs in a separate child process. A one-second cool-down follows every
completed child before the next one starts. Every emitted line is mirrored to
the terminal and a single bounded-memory, temporary spool. The spool is
copied to one final text log after the test run, including on Ctrl+C.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest


ROOT = Path(__file__).resolve().parent
TESTS = ROOT / "tests"
DEFAULT_TIMEOUT = 90.0


@dataclass(frozen=True)
class Case:
    name: str
    command: tuple[str, ...]
    kind: str


class Transcript:
    def __init__(self):
        # Starts as a memory buffer; transparently spills to a temporary file
        # for arbitrarily long test output. No separate persistent files.
        self.buffer = tempfile.SpooledTemporaryFile(
            max_size=2 * 1024 * 1024, mode="w+t",
            encoding="utf-8", newline="\n",
        )
        self.lock = threading.RLock()
        self.lines = 0

    def write(self, message: str, *, source: str = "runner"):
        with self.lock:
            timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
            for text in (message.splitlines() or [""]):
                line = f"[{timestamp}] [{source}] {text}\n"
                self.buffer.write(line)
                self.lines += 1
                print(line, end="", flush=True)

    def save(self, filename: Path):
        """Atomically publish exactly one persistent UTF-8 report at the end."""
        with self.lock:
            filename.parent.mkdir(parents=True, exist_ok=True)
            self.buffer.flush()
            self.buffer.seek(0)
            temporary = None
            try:
                # Keep incomplete reports hidden under a temporary filename.
                # os.replace() makes the final filename visible only after
                # the entire transcript was flushed and fsynced.
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", newline="\n",
                    dir=str(filename.parent), prefix="." + filename.name + ".",
                    suffix=".tmp", delete=False,
                ) as output:
                    temporary = Path(output.name)
                    shutil.copyfileobj(self.buffer, output, length=128 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, filename)
                temporary = None
            finally:
                self.buffer.close()
                if temporary is not None:
                    try:
                        temporary.unlink()
                    except FileNotFoundError:
                        pass
        return filename


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def discover_cases():
    # Import test modules only for *discovery*; each test is executed in its
    # own fresh interpreter process, eliminating cross-test state leakage.
    sys.path.insert(0, str(TESTS))
    try:
        suite = unittest.defaultTestLoader.discover(
            start_dir=str(TESTS), pattern="test_*.py", top_level_dir=str(TESTS)
        )
        names = sorted({case.id() for case in _flatten(suite)})
    finally:
        sys.path.remove(str(TESTS))
    return [
        Case(name, (sys.executable, "-u", "-m", "unittest", "-v", name), "unit")
        for name in names
    ]


def all_cases(include_device=False, adb="adb", serial=None, device_repeats=1,
              device_options=()):
    cases = discover_cases()
    for scenario in ("counter", "typing", "selection", "layout", "dynamic", "failure"):
        cases.append(Case(
            "scripted." + scenario,
            (sys.executable, "-u", str(TESTS / "automation" / "scripted.py"), scenario),
            "simulated",
        ))
    if include_device:
        cmd = [sys.executable, "-u", str(TESTS / "automation" / "android_e2e.py")]
        cmd.extend(["--adb", adb])
        if serial:
            cmd.extend(["--serial", serial])
        cmd.extend(device_options)
        for iteration in range(1, device_repeats + 1):
            name = "android.native-touch-keyboard-layout"
            if device_repeats > 1:
                name += f".run-{iteration:03d}"
            cases.append(Case(name, tuple(cmd), "device"))
    return cases


def _terminate_tree(process, transcript):
    if process.poll() is not None:
        return
    transcript.write(f"Terminating process group PID={process.pid}")
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        transcript.write(f"Escalating to SIGKILL PID={process.pid}")
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        process.wait()


def run_case(case: Case, transcript: Transcript, timeout: float):
    transcript.write("=" * 88)
    transcript.write(f"START [{case.kind}] {case.name}")
    transcript.write(f"COMMAND: {list(case.command)!r}")
    started = time.monotonic()
    environment = dict(os.environ)
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
        str(TESTS), str(ROOT), environment.get("PYTHONPATH", ""),
    )))
    process = None
    reader = None
    result = "FAIL"
    stream_errors = []
    try:
        process = subprocess.Popen(
            case.command, cwd=str(ROOT), env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace",
            text=True, bufsize=1, start_new_session=(os.name == "posix"),
        )
        transcript.write(f"SPAWNED pid={process.pid} timeout={timeout:g}s")
        def drain():
            try:
                for line in process.stdout:
                    transcript.write(line.rstrip("\r\n"), source=f"pid:{process.pid}")
            except (OSError, ValueError) as exc:
                stream_errors.append(exc)
                transcript.write(f"PIPE READ FAILURE: {exc!r}", source="pipe-reader")
            except Exception as exc:
                stream_errors.append(exc)
                transcript.write(traceback.format_exc(), source="pipe-reader")
        reader = threading.Thread(target=drain, daemon=True, name="test-output")
        reader.start()
        try:
            code = process.wait(timeout=timeout)
            result = "PASS" if code == 0 else "FAIL"
            transcript.write(f"EXIT pid={process.pid} code={code}")
        except subprocess.TimeoutExpired:
            result = "TIMEOUT"
            transcript.write(f"TIMEOUT pid={process.pid} after {timeout:g}s")
            _terminate_tree(process, transcript)
    except BaseException as exc:
        transcript.write(f"RUNNER ERROR: {type(exc).__name__}: {exc}")
        transcript.write(traceback.format_exc())
        if process is not None:
            _terminate_tree(process, transcript)
        if isinstance(exc, KeyboardInterrupt):
            raise
    finally:
        if process is not None:
            if process.poll() is None:
                _terminate_tree(process, transcript)
            if reader is not None:
                reader.join(timeout=5)
                if reader.is_alive():
                    transcript.write("WARNING: output reader did not finish after child exit")
                    result = "FAIL"
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError as exc:
                    transcript.write(f"WARNING: closing child output pipe failed: {exc}")
                    result = "FAIL"
            if stream_errors:
                result = "FAIL"
            transcript.write(f"CLEANUP pid={process.pid} "
                             f"returncode={process.returncode} "
                             f"stdout_closed={process.stdout is None or process.stdout.closed}")
    elapsed = time.monotonic() - started
    transcript.write(f"END [{case.kind}] {case.name}: {result}; elapsed={elapsed:.3f}s")
    return result, elapsed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-file", type=Path, help="single final combined .txt log path")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="timeout per child test process (default 90s)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds after process exit before next test (default 1)")
    parser.add_argument("--filter", help="case-name regex; omit to run all")
    parser.add_argument("--device", action="store_true",
                        help="also run real Android ADB input/geometry checks; requires configured adb")
    parser.add_argument("--adb", default="adb", help="ADB executable")
    parser.add_argument("--device-repeats", type=int, default=1,
                        help="run each physical Android test N times sequentially (e.g. 20)")
    parser.add_argument("--device-foreground-timeout", type=float, default=4.0,
                        help="seconds to wait for the Termux:GUI foreground Activity")
    parser.add_argument("--device-screenshots", action="store_true",
                        help="save PNG stage captures alongside the transcript, outside the single text log")
    parser.add_argument("--device-orientation", action="store_true",
                        help="run optional orientation-change validation; restores Android settings")
    parser.add_argument("--device-display-matrix", action="store_true",
                        help="test one temporary override display size; restores previous override")

    parser.add_argument("--serial", help="optional adb -s serial")
    parser.add_argument("--list", action="store_true", help="list cases without executing")
    args = parser.parse_args(argv)
    if not 1 <= args.device_repeats <= 200:
        parser.error("--device-repeats must be 1..200")
    if not 1 <= args.device_foreground_timeout <= 60:
        parser.error("--device-foreground-timeout must be 1..60")
    if not 0 <= args.delay <= 60 or not 1 <= args.timeout <= 3600:
        parser.error("delay must be 0..60 and timeout 1..3600 seconds")
    options = ["--foreground-timeout", str(args.device_foreground_timeout)]
    if args.device_screenshots:
        options.append("--save-screenshots")
    if args.device_orientation:
        options.append("--orientation-check")
    if args.device_display_matrix:
        options.append("--display-matrix")
    cases = all_cases(args.device, args.adb, args.serial,
                      args.device_repeats, options)
    if args.filter is not None:
        try:
            pattern = re.compile(args.filter)
        except re.error as exc:
            parser.error(f"invalid --filter expression: {exc}")
        cases = [c for c in cases if pattern.search(c.name)]
    if args.list:
        for i, case in enumerate(cases, 1):
            print(f"{i:03d} [{case.kind}] {case.name}")
        return 0
    if not cases:
        parser.error("no tests match the requested filter")

    filename = args.log_file or (
        ROOT / "logs" / ("test-all-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                         + "-" + str(os.getpid()) + ".txt")
    )
    transcript = Transcript()
    results = []
    interrupted = False
    preflight_failure = False
    try:
        transcript.write(f"TEST RUN START; python={sys.version.split()[0]}; pid={os.getpid()}")
        transcript.write(f"Root: {ROOT}")
        transcript.write(f"Selected {len(cases)} tests; delay={args.delay:g}s; timeout={args.timeout:g}s")
        transcript.write(f"Device mode={'enabled' if args.device else 'disabled; simulated events only'}")
        if any(case.kind == "device" for case in cases):
            transcript.write("ADB PREFLIGHT: checking physical connection before starting any tests")
            command = [args.adb] + (["-s", args.serial] if args.serial else []) + ["get-state"]
            try:
                checked = subprocess.run(command, capture_output=True, text=True,
                                         timeout=12, check=False)
                transcript.write(f"ADB PREFLIGHT result: rc={checked.returncode}, "
                                 f"stdout={checked.stdout.strip()!r}, "
                                 f"stderr={checked.stderr.strip()!r}")
                if checked.returncode != 0 or checked.stdout.strip() != "device":
                    preflight_failure = True
            except (OSError, subprocess.TimeoutExpired) as exc:
                transcript.write(f"ADB PREFLIGHT ERROR: {exc!r}")
                preflight_failure = True
            if preflight_failure:
                transcript.write("ADB PREFLIGHT FAILED: no authorized device; "
                                 "aborting before the full suite to save time")
                return 1
        for index, case in enumerate(cases, 1):
            transcript.write(f"TEST {index}/{len(cases)}")
            result, duration = run_case(case, transcript, args.timeout)
            results.append((case.name, result, duration))
            if index < len(cases):
                transcript.write(
                    f"POST-EXIT COOLDOWN: waiting {args.delay:g} second(s) before next test"
                )
                time.sleep(args.delay)
                transcript.write("COOLDOWN COMPLETE")
    except KeyboardInterrupt:
        interrupted = True
        transcript.write("INTERRUPTED by user; preserving partial report")
    except BaseException:
        transcript.write("UNHANDLED RUNNER FAILURE:")
        transcript.write(traceback.format_exc())
        interrupted = True
    finally:
        passed = sum(result == "PASS" for _, result, _ in results)
        failed = len(results) - passed
        transcript.write("=" * 88)
        transcript.write(f"RESULTS: {passed} passed / {failed} failed-or-timeout / "
                         f"{len(cases) - len(results)} not started")
        for name, result, duration in results:
            transcript.write(f"  {result:7} {duration:9.3f}s {name}")
        if interrupted:
            transcript.write("FINAL STATUS: INTERRUPTED")
        elif failed:
            transcript.write("FINAL STATUS: FAILED")
        else:
            transcript.write("FINAL STATUS: PASSED")
        device_durations = [duration for name, status, duration in results
                            if name.startswith("android.")]
        device_failures = sum(status != "PASS" for name, status, _ in results
                              if name.startswith("android."))
        if device_durations:
            ordered = sorted(device_durations)
            from statistics import mean, median
            p95 = ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)]
            transcript.write(
                f"ANDROID RELIABILITY: {len(ordered) - device_failures}/"
                f"{len(ordered)} passed ({100 * (len(ordered) - device_failures) / len(ordered):.1f}%); "
                f"mean={mean(ordered):.3f}s median={median(ordered):.3f}s "
                f"p95={p95:.3f}s min={ordered[0]:.3f}s max={ordered[-1]:.3f}s"
            )
        transcript.write(f"Final report: {filename.resolve()}")
        try:
            transcript.save(filename)
            print(f"\nCombined transcript saved: {filename.resolve()}", flush=True)
        except OSError as exc:
            print(f"CRITICAL: could not write final log: {exc}", file=sys.stderr, flush=True)
            raise
    return 130 if interrupted else 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
