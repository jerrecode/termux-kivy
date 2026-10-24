# Source reference analysis: tgk and tgk-tools

Source observation date: 2026-10-24. These are the *reference* projects, **not** submodules or dependencies of termux-kivy.

- https://github.com/jerrecode/tgk — observed main commit `0b5b66586d2d721a9d1ef73f8e726bf1477e2b45`, 94 blobs in the main recursive tree, approximately 48 branch names returned by the GitHub branch API at observation.
- https://github.com/jerrecode/tgk-tools — observed main tree `dcd6bf6d2c55f4e4d36e7791b65abca168d2186c`, 83 blobs, approximately 46 branch names returned.
- https://github.com/jerrecode/termux-kivy — empty repository at the start of this exercise; this implementation was initialized there.

This analysis examines repository structure, representative core source and API entrypoints, CI/packaging metadata, and selected branch relationships. **It is not a verified line-by-line review of every test, every historical commit, or every alternate branch implementation.** The branch inventory is not an instruction to merge old source branches into the new clean-room project.

## tgk components and techniques

### API, compatibility and parsing

`tgk/__init__.py` exports an extensive surface lazily through module attribute access. Widgets and functions are loaded on demand, reducing baseline import overhead.

`tgk/compat/importer.py` defines a PEP-451 meta-path finder and loader for selected `kivy.*` modules, mapping them to TGK constructs. It explicitly enumerates supported classes and throws on unsupported modules. This minimizes source changes for programs inside its declared subset, but it changes global module resolution. The new implementation keeps this facility strictly opt-in, and provides a separate explicit `termux_kivy` API by default.

`tgk/kv.py` parses a subset of indentation-based KV syntax, tracking class rules, ids, properties and event handlers. It uses Python AST-based restrictions rather than a general-purpose `eval`. Some Kivy language features are deliberately unavailable. The new KV builder starts from an even narrower, explicit language contract.

### Widget model and Android lifecycle

`tgk/widgets.py` is the operational center. `EventDispatcher` observes assignments and invokes property callbacks; `Widget` owns a tree and a native view reference. `TermuxBackend` maps Widget subclasses to native Termux:GUI classes, applies dimensions, themes, text styles and Android-specific layout rules, installs event handlers, and operates an Activity event loop. View IDs index events instead of requiring a full scan in the normal case. Timer callbacks are bounded in a heap scheduler.

It uses iterative preorder mounting with postorder completion to avoid recursive construction issues and to finish screen/tab arrangements only after descendants exist. It guards TextInput updates to avoid redundant text reflection and potential Android IME/caret disruption. Pixel-slider and canvas drawing resources have explicit cleanup routines.

A limitation in the main source observed was that inserting or removing a Widget once native rendering has begun raises NotImplementedError; this design simplifies lifecycle invariants but blocks dynamic UI composition. The new project permits direct incremental operations on compatible Android layouts and explicitly excludes live changes to pre-sized native grids.

### Drawing and visual subsystems

`tgk/canvas.py` wraps a native shared-buffer rasterizer through ctypes. `tgk/native/tgk_canvas.c` provides bounded pixel drawing operations and touch mapping. This is valuable for slider controls or custom surfaces where native Android widgets cannot express the desired visuals. Its graphics responsibilities differ from ordinary native text/button controls. A fresh design should allocate shared buffers only on demand and measure resize, blit and refresh overhead rather than route all UI through rasterization.

`tgk/theme.py`, `tgk/typography.py`, `tgk/style_tokens.py`, `tgk/icons.py`, `tgk/icon_builder.py` and `tgk/semantic_icons.py` separate visual primitives, tokens, icon recipes, asset generation and raster/vector representations. `advanced.py` adds screens, tabs, popups, rich HTML views and an infinite canvas. The architecture achieves broad feature coverage, but it also has many conditional render paths and cross-subsystem interactions. The new MVP deliberately does not port that complexity before an independently testable lifecycle and IPC layer exists.

### Configuration, screen geometry, I/O

`tgk/config.py` handles versioned persistent defaults, validation, caching, preset lookup and atomic locking/writes. File-system safety and inter-process concurrency are substantial responsibilities of a configuration service, not properties of native GUI rendering. `tgk/adaptive.py` and `tgk/sizing.py` resolve screen metrics, touch targets, breakpoint layouts, spans and dimensions; these should be layered on top of a correct native Activity viewport contract. `tgk/io_pipeline.py` implements bounded transfer, hashing, media probing and download controls; these belong to application/tooling utilities, not the low-level widget adapter.

### Release and operations

`install.sh`, `install_assets.py` and `install_hook.py` install Python/native components and assets; `pyproject.toml` packages the TGK API. GitHub Actions cover testing and asset generation. Using an interpreter import hook or auto-activation may help source compatibility but increases environment-level surprise and blast radius; termux-kivy installs no such behavior by default.

## tgk-tools components and techniques

The `tgk_tools/cli.py` command parser is a shell-oriented front-end with Android dialogs, choices, file browsers, progress display, image/canvas operations, themes, gallery and configuration commands. It collects many command flags and validates bounds before calling GUI code.

`mobile_ui.py` and `advanced_ui.py` expose layout previews and mobile interaction scenarios; `config_cli.py` handles persisted profiles; `preset_catalog.py` discovers configuration/style assets; `pipeline_cli.py` exposes bounded file/media operation results in JSON; `mobile_actions.py` implements reusable actions. `bench.py` and CLI tests cover selected performance and behavior. Release scripts create/check offline bundles; `install.sh` is the shell distribution path.

The tools are a consumer and operational showcase of TGK, **not** a necessary dependency for rendering a Kivy-like Widget tree. In the redesign, the framework ships a single small example and places optional CLI products in independent packages to preserve modularity.

## Difficult engineering questions and their solutions

| Challenge | Existing project approach | Fresh approach / reason |
|---|---|---|
| Termux Python and Android GUI separation | termuxgui connection and native bridge | Keep bridge behind one backend and mock it |
| Kivy imports without full Kivy runtime | selective PEP-451 hooks | Explicit opt-in alias layer; reject unsupported modules |
| Reactivity | assignment observation and callbacks | Descriptor-based change notification, backed by dirty sets |
| Native events | ID map plus fallback | Strict indexed ID dispatch for documented event schema |
| TextInput/IME | skip echo when source is native input | Track last native event text and never send it back |
| Nontrivial layout | responsive native configuration & style rules | Basic deterministic native layouts first, richer sizing later |
| Persistent settings | versioned/locked config and presets | Keep configuration independent of core runtime |
| Styled/custom visuals | HTML views, icons, C rasterizer | Defer until lifecycle + renderer capabilities measured |
| Excessive Python UI calls | caching, bounded event loop | Deduplicated dirty updates, explicit per-tick work budgets |
| Feature surface complexity | broad framework and CLI shell tools | Smaller composable kernel, strict capability matrix |

## Selected branch relationship observations

At the observation point the TGK `integration/all-branches-20261023` branch was behind main, and the reviewed `fix/native-cleanup-failures-20261024` branch was **one commit ahead** of main. The latter changed `tgk/widgets.py`, `tests/test_backend_cleanup.py`, and `docs/android-validation.md`; it should be reviewed in the original repository before being assumed integrated. In tgk-tools, the `integration/all-branches-20261023` and `fix/icon-cli-styling-release-20261024` branches were behind main. These comparisons are snapshots, not an exhaustive merge analysis of every branch.

## Evaluation and remaining work

The independent implementation has a smaller maintainable core, but **no defensible claim of being faster or more feature-complete than TGK yet**. A production comparison needs matching devices and workloads, Android instrumentation, IPC call counts, latency distributions, startup time, idle CPU/memory, package size, keyboard behavior, rotation and cleanup stress. Expanding the compatibility layer without such tests risks creating unsupported behavior disguised as a supported Kivy API.
