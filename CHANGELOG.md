# Changelog

## 0.1.2 — 2026-10-24

### Full automated test pipeline

- Add executable `./test-all.sh` and Python test runner: every discovered unittest method executes in its own child process, with a one-second pause after each process exits and before the next starts.
- Mirror all combined stdout/stderr, assertions, actions, errors, exit codes, timestamps, timeouts and duration to a live terminal and to one temporary spooled transcript. Atomically publish **one final UTF-8 text log** after the full run, including partial results on keyboard interruption.
- Add six scripted native-event interaction cases for button taps, Unicode keyboard input, checked-state controls, Spinner selection, layout cells, dynamic view lifetime and transient IPC failures.
- Add an optional `--device` ADB test that launches a real Termux:GUI fixture, extracts UIAutomator screen geometry, injects touch and keyboard input, verifies actual callbacks, and checks control ordering/overlaps. Device mode explicitly fails when ADB cannot run rather than pretending that simulated tests verified native pixels.
- Include fail-closed ADB/XML parser tests, runner timeout, nonzero exit and cooldown regression tests.
- Extend GitHub Actions with the process-isolated suite (zero cooldown exclusively in CI) and upload its single combined log as an artifact.

Validation: Python 3.10–3.13 CI successful; 45 unit tests and 51 child test runs completed on CI, all passed. **No physical Android device was available in CI for real touch/layout validation.**

## 0.1.1 — 2026-10-24

### Native protocol corrections

- Translate Termux:GUI Spinner item-selection events using the selected string (including numeric-looking strings), rather than assuming the event carries an integer index.
- Stop claiming custom caption support for native ToggleButton; reject unsupported text explicitly without leaking a native view.
- Make fake Termux:GUI setters strict enough to detect nonexistent native methods.
- Assign explicit native row/column placement to GridLayout children.

### State, lifecycle and reliability

- Reconcile Spinner selection when its values change, including in-place Observable ListProperty changes.
- Preserve pending dirty properties on setter failure so callers can retry.
- Keep widget hierarchy intact if native removal raises synchronously.
- Clean partially constructed native subtrees without duplicate delete calls.
- Run Activity cleanup while the Termux:GUI connection is still open; clean up Python ownership after failures, including Activity construction failure.
- Permit background workers to request stop by posting to the owning Activity thread.
- Make invalid mounted structural/state property changes fail before mutating application state.

### Performance

- Cache known initial native View state, skipping redundant visibility, clickability and value setter IPC.
- Maintain last-sent state and send one property update for multiple changes before a flush.
- Avoid a full dirty-state dictionary snapshot on every flush iteration.
- Compact stale cancelled timers when the heap becomes sparse.
- Keep timer, event and worker-callback processing bounded per iteration.

### Testing and diagnostics

- Add deterministic regressions for native event payloads, partial mount failures, native deletion errors, thread affinity, timer compaction, Kivy-style observable lists and property coalescing.
- Check the editable installation, syntax and unit tests on Python 3.10, 3.11, 3.12 and 3.13.
- Build and install the regular Python wheel and run the diagnostic CLI outside the checkout.
- Report Python binding package version and, on an available plugin connection, its version response.

### Known limitations

This is a Kivy-inspired native Termux:GUI widget subset, **not** a complete Kivy/OpenGL runtime. No real Android device validation or paired TGK performance benchmarks have been performed in this environment. See issue #1 and the capability matrix for remaining device checks. No numeric speedup claim is made from mock tests.
