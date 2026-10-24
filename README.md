# termux-kivy

A **clean-room, native-Android, Kivy-inspired** Python UI runtime for Termux:GUI.

This is a new implementation, not a copy of `tgk` or `tgk-tools`, and **not the full Kivy graphics engine**. It targets familiar Python widget trees, reactive properties, application lifecycle, and native Termux:GUI views. Compatibility is explicit and capability-limited rather than pretending to implement OpenGL canvas instructions.

## Status

Early functional implementation. Desktop/mock integration tests run without Android; the actual Android Termux:GUI path requires device testing. See [Architecture](docs/architecture.md) and [Capabilities](docs/capabilities.md).

## Quick start on Android

1. Install Termux and the matching **Termux:GUI** Android plugin from compatible sources.
2. In Termux run `pkg install python git`.
3. Clone this repository, then execute `./install-termux.sh`.
4. Run `termux-kivy doctor --connect` to verify the plugin connection.
5. Run `termux-kivy demo` (or `python examples/counter.py`).

The Python bindings are provided by the independent `termuxgui` project. No root privileges and no Kivy/SDL/OpenGL runtime are needed for native controls.

## Use existing Kivy-style imports where supported

```python
from termux_kivy.compat import activate
activate()  # before any import of kivy.*
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
```

Only a small documented subset is available. Unsupported Kivy classes and rendering
instructions are not silently fabricated. See [Capabilities](docs/capabilities.md).

Run `termux-kivy doctor --json` on a desktop or phone to inspect Python dependencies
without connecting to the plugin; use `--connect` for a real Termux:GUI handshake.

## Maintenance

See [CHANGELOG.md](CHANGELOG.md) for 0.1.1 native protocol fixes, lifecycle hardening, property observation, and performance improvements.

## Design priorities

- Lazy import of the Android adapter; pure-Python core importable on desktop.
- O(1) native ID -> widget event dispatch.
- Incremental add/remove of views when the native container permits it, with recoverable deletion failure semantics.
- Coalesced, deduplicated property updates; in-place ListProperty observation.
- Exception-safe lifecycle cleanup and an event loop with bounded timer callbacks and cancelled-timer compaction.
- Truthful compatibility layer: no global `sitecustomize` takeover or silent import hook.
- Optional, limited KV parsing without arbitrary Python evaluation.
- Explicit and testable Termux:GUI protocol boundaries.

License: MIT.
