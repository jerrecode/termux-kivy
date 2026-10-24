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
