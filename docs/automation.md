# Automated test runner: process isolation, interaction and verbose logging

Run `./test-all.sh` from the repository root. It starts **each discovered unittest method in its own new Python process**, waits until that process exits, logs the return code, then waits **one full additional second** before starting the next test. There is no concurrent test execution. It continues after individual test failures so the final report contains all observed failures rather than stopping at the first issue.

In addition, six scripted end-to-end scenarios are launched as individual child processes. These send events to an in-memory mock implementation of Termux:GUI, trigger Python callbacks, verify model changes and log native setter traces. They automate simulated user interaction but **cannot** establish physical Android touch positions or pixels.

## Basic commands

```bash
./test-all.sh
./test-all.sh --list
./test-all.sh --filter '^(scripted|test_regressions\.)'
./test-all.sh --timeout 120
./test-all.sh --log-file /sdcard/Download/termux-kivy-tests.txt
```

The default single text file is written at `logs/test-all-YYYYMMDD-HHMMSS-PID.txt`. Every child output line (stdout and stderr merged), PID, command, start/end timestamp, return code, timeout, assertion, event, layout check, exception and final summary is printed live. All are simultaneously appended to a temporary spooling buffer, which starts in memory and spills to a temporary file at 2 MiB. At the **end** of the test run (including Ctrl+C), the buffer is streamed into an fsynced temporary sibling and atomically renamed into exactly one persistent text log, avoiding a partially written final filename. Very long tests do not have to fit entirely in memory.

The runner reports PASS/FAIL/TIMEOUT per individual test; an unsuccessful test does not hide later test results. On a timeout, the entire child process group is terminated. The final exit code is nonzero if any test fails. `--delay 0` is available for fast CI; this is an opt-out from the requested one-second default.

`--list` discovers cases without starting them. `--filter` accepts a Python regular expression evaluated against each case's identifier.

## Simulated interaction coverage (portable)

- `scripted.counter`: inject three native click events; check callback count, label text and deduplication of outgoing setter calls.
- `scripted.typing`: inject incremental keyboard text and Unicode; verify input state, non-echoing IME updates and programmatic text changes.
- `scripted.selection`: inject spinner string selection, checkbox checked and unchecked events, and toggle state.
- `scripted.layout`: build a two-column grid, inspect each native `setgridlayoutparams(row,col)` command, and dispatch an indexed simulated click.
- `scripted.dynamic`: add and remove a native view, check click routing, and verify old native IDs cannot trigger stale callbacks.
- `scripted.failure`: inject a transient native setter failure and assert dirty-state retention and recovery.

The scripted suite prints synthetic touch targets and logical grid positions with explicit `SIMULATED` labels. It **never** asserts that actual Android pixels have been checked.

## Optional physical Android ADB automation

To test **real** Android screen bounds and input injection, install/configure `adb` with an *authorized* connection to the Android phone (for example Termux wireless debugging paired using Android's Developer Options), and install the Termux:GUI Android plugin and Python binding. Then run from **Termux on the same device**:

```bash
pkg install android-tools
./test-all.sh --device --timeout 180
```

For multiple devices specify `--serial SERIAL`, or point `--adb` at a different executable. The `--device` flag is explicit: an unavailable ADB bridge or incompatible Android UI hierarchy is a **failed** test, not an unreported skip or a fabricated success.

The device test starts a real native Termux:GUI fixture in a separate process, waits for an atomic JSON readiness signal, uses Android's `uiautomator dump` and `wm size` to read view bounds, and verifies the expected vertical ordering and non-overlap of visible controls. It uses `adb shell input tap X Y` to click the actual screen, `adb shell input text Termux42` to type ASCII through Android's input system, and `adb shell input keyevent 4` for Back. The fixture logs each callback into a temporary JSON trace and the driver checks that a counter, checkbox and text input match their expected states. The fixture trace and temporary UI hierarchy files are deleted afterward; their relevant content is copied into the **single** combined text transcript.

Android may reject `uiautomator` in some builds; some keyboards, overlays and layout policies can also differ. In those cases, the test must fail with diagnostics, not claim successful position or interaction testing. If a real Android screen is unavailable, the default mock suite remains useful, but does not prove the GUI actually appears or is positioned correctly.

## Continuous integration

CI runs each unit test file through Python's unittest discovery and also runs the comprehensive test runner with `--delay 0` to verify its process isolation, interaction scenarios, and consolidated logging. The normal interactive default remains one second between exited child processes.

## Security and operational notes

ADB's `input` commands control the **selected authorized device**; do not use `--device` while sensitive screens are open. The fixture requests a GUI Activity, which can bring its window to the foreground. No root privileges are needed when ADB is properly authorized, but Android's permission/security model may prevent local ADB setup on some devices.

The generated combined log can contain typed test strings and UI labels. Avoid sharing logs that include sensitive data from third-party windows (e.g. if the device UI test accidentally captures the wrong foreground screen).


## Reliability stress testing (real Android)

After ADB pairing and a successful single run, measure repeated physical-device reliability:

```bash
./test-all.sh --device --device-repeats 20 \
  --filter '^android\\.' \
  --timeout 180 --delay 1 \
  --log-file logs/android-reliability-20.txt
```

Each iteration is a **fresh, isolated Python process**, never parallel. The transcript lists per-iteration results and aggregates the physical-device success rate, mean, median, p95, minimum and maximum wall-clock durations. One mandatory second separates iterations. An early **ADB preflight** checks for an authorized `adb get-state` device **before** running all the Python tests; a missing connection creates a failed report rather than 51 irrelevant test executions or a false PASS. The stress test is not run by cloud CI because no phone is attached.

## Screenshot verification and display variants

The real-device test always makes in-memory PNG screenshots: before click, after counter redraw, and after checkbox/keyboard input. PNG header and image dimensions are checked, SHA-256 digests logged, and distinct post-interaction output required. When Pillow is available, the counter's **actual screenshot crop** is compared pixel-by-pixel with its pre-click image; a nonzero changed-pixel fraction is required. Without Pillow, this pixel-level assertion is **not claimed**: native UIAutomator text and geometry verification remains active. Install Pillow to enable pixel comparison on the device:

```bash
python -c 'from PIL import Image; print(Image.__version__)'
# If the import fails, install a compatible Pillow build in Termux.
```

To persist the screenshots as PNGs **in addition** to the normal single combined text log:

```bash
./test-all.sh --device --filter '^android\\.' --device-screenshots
```

The PNGs are placed in a timestamped ignored `logs/android-screenshots-*/` directory, not embedded as binary data in the TXT log. They can be inspected manually for visual rendering defects. A screenshot hash change does not prove every pixel is correct, and there is currently no golden-image reference catalog; the status-label crop comparison specifically tests a real redraw.

Opt-in orientation and reduced-resolution tests exercise screen geometry and screenshots:

```bash
./test-all.sh --device --filter '^android\\.' \
  --device-orientation --device-display-matrix --device-screenshots \
  --device-foreground-timeout 6 --timeout 180
```

**Caution:** `--device-orientation` temporarily changes Android's `accelerometer_rotation` and `user_rotation` system settings; `--device-display-matrix` temporarily changes `wm size`. Both restore the original values via `finally` even after an assertion fails. Do not use those flags on a phone involved in important foreground work, and avoid manually interrupting the process by force-killing it before cleanup. Without these flags, the test does not modify system display settings.

## Foreground, lifecycle and failure evidence

Before GUI events, the hardware test now probes `adb shell dumpsys window` for the foreground package `com.termux.gui`. UIAutomator XML is also checked to ensure **all selected targets belong to that exact application**. If the wrong window is focused, the test fails rather than accidentally sending taps to Termux or another app.

On native test failure, it attempts to log the fixture's atomic state trace, process exit status, `dumpsys window`, `dumpsys activity activities`, `pidof`, the last 180 lines of `logcat`, and an in-memory diagnostic screenshot before cleaning up. Successful test runs avoid this expensive diagnostic collection. These logs may include information about other Android applications; **review and redact them before sharing externally**.

Process tests now explicitly close the `subprocess.Popen` output stream after a child exits or times out. The regression suite includes warnings-capture tests to detect unclosed file handles, and verifies fail-fast ADB handling and the 20-iteration case generation.

All device options are additive: the unchanged `./test-all.sh` default still runs offline tests in separate child processes with the required one-second gaps and writes one consolidated TXT report.
