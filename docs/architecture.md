# Architecture and redesign rationale

## Scope and non-goals

Termux:GUI bridges a Python process running inside Termux and an Android plugin process. Native Android views live in the plugin. The Python layer is responsible for application state, view creation, events, and updates across process boundaries. It does **not** execute Kivy's SDL window provider, OpenGL canvas, graphics instructions, or arbitrary Kivy extension modules. Full Kivy application equivalence is impossible without porting Kivy's rendering/input stack or implementing a compatible compositor; this project is intentionally a compatible *subset*.

Design principle: **keep the Python model pleasant and familiar; delegate what the plugin already implements to Android; communicate only the necessary changes.** Native rendering avoids serializing entire screens into shared-memory bitmaps for simple controls, though every IPC operation has a cost.

The previous TGK codebase provides a useful functional reference. This project is an independent implementation with deliberately smaller, more explicit layers, not a mechanical rewrite or claimed performance improvement based on unmeasured numbers.

## Data and control flow

```text
User App.build() or restricted KV builder
                  |
              Widget tree
                  |
        Properties and event bindings
                  |
       Dirty property sets (coalesced)
                  |
         Backend.flush() / mount()
                  |
       termuxgui Python bindings
                  |
         IPC to Termux:GUI plugin
                  |
        Native Android View tree

Android event -> Connection.checkevent() -> ID index -> Widget dispatch
                                    `-> property mutation -> dirty set
Background producer -> Backend.post() -> bounded queue -> UI thread
Timers -> monotonic heap -> bounded callback budget -> UI thread
```

The first flow is construction and updates, the second returns native interaction to Python. The queue separates background work from unsafe calls into the plugin. Timer callbacks and input callbacks share a single logical UI thread.

## Layer boundaries

**Core (`termux_kivy/core.py`):** pure-Python descriptors, binding and dispatch, parent/child ownership, tree cycle protection, familiar basic control classes, monotonic scheduler and App lifecycle. It can import on Linux without Android, Java, Kivy, C compilers, or SDL. Mutable descriptor defaults are per-instance. Values that have not changed do not emit events.

**Backend (`termux_kivy/backend.py`):** the sole owner of native Activity, Connection, View IDs, native method calls and view lifecycle. Termux bindings are imported lazily. It constructs the tree iteratively, dispatches by ID in constant expected time, deduplicates dirty properties, and transfers updates at a bounded number of widgets per iteration.

**KV parser (`termux_kivy/kv.py`):** supports a conservative indentation-based widget tree and a small AST grammar. It does not execute arbitrary expressions. Class templates, arbitrary style properties, canvas instructions and dynamic KV expression dependencies are excluded intentionally until they can be implemented without misleading behavior.

**Explicit compatibility (`termux_kivy/compat.py`):** optional import aliases of known supported Kivy modules, enabled *only* by calling `activate()` before a `kivy` import. The default installation never modifies global interpreter startup, sitecustomize or sys.meta_path. The shim never claims it is actual Kivy.

**Tests:** a fake Termux:GUI module reproduces the relevant documented constructors, event envelopes and setters. Tests cover ownership, dirty updates, dispatch and lifecycle without a phone. These mocks cannot validate an Android OEM's IME, Activity transitions, plugin IPC latency, rotation, GPU buffer behavior, or platform UI rendering.

## Performance work and complexity

1. **Native views rather than pixel rasterization for ordinary controls:** Android takes responsibility for layout, drawing and most input semantics. This avoids a Python graphics loop for labels and buttons, but inter-process communication still contributes latency.
2. **Incremental view mutation:** insertion and deletion of children under compatible parents touch only the affected native subtree. `GridLayout` is explicitly frozen after mounting because its row count is declared when the native grid is created; silently modifying its content could produce invalid layout.
3. **Dirty-state reconciliation:** multiple assignments to the same property before a flush produce at most one outbound setter call for that property. The backend also caches both initial known native values and the last sent value, avoiding repeat IPC for identical values. Pending changes survive synchronous setter failures. It is a property invalidation algorithm, **not** a native transactional batch protocol; the underlying setter calls remain individual IPC messages.
4. **Native IDs indexed into a dict:** events do not scan all widgets. Average lookup is O(1), memory O(N).
5. **Iterative tree traversal:** view creation and removal avoid recursion-depth failure for deep trees. Insertion and mount work O(size of inserted subtree).
6. **Bounded timers and ingress:** 64 timer callbacks per loop by default; worker updates enter a bounded FIFO. Long-running callbacks still block the UI and must be moved to workers. Cancelled timers are compacted when the retained queue becomes sparse.
7. **Thread confinement:** synchronous widget property mutations on a mounted tree are checked before assignment. Workers should schedule a callback using `backend.post()`.
8. **Lazy external dependencies:** the Android binding is loaded only when a real backend is constructed. This minimizes start cost and supports desktop testing.

There are no published speedups yet: all percentage or FPS comparisons with TGK would require paired measurements on the same Android device and OS version, equal widget trees, comparable events, warmup, energy/memory profiling and IPC counts.

## Lifecycle invariants

Every mounted model node has one native view, a backend owner, and (if exposed by the binding) one indexed native ID. No node can have two model parents. Removing a node clears indexed IDs, transient state and queued dirty properties. An Activity ends on explicit stop or a finishing destroy event. A configuration-change destroy event marked not-finishing is not treated as a permanent exit. The backend cleans up native resources on exit and App resets its timers.

## Evolvable roadmap

**Phase A (current):** native common controls, reactive fields, explicit subset import compatibility, restricted KV, tests and CI.

**Phase B:** Android manual acceptance suite; additional media/selection controls, rich typography, keyboard focus/validation, larger layouts, orientation/sizing and accessibility checks; robust restart/resume path; detailed installer diagnostics.

**Phase C:** specialized surfaces for truly custom drawing using documented shared buffers; dirty rectangles and optional native vector primitives where available; image caching with memory pressure accounting; pointer capture and gesture translation; virtualized lists for very large data sets.

**Phase D:** broader Kivy semantics where measurable and implementable, including dynamic KV dependencies, optional third-party widget adapters, richer canvas compatibility, expanded events and module-level compatibility. An OpenGL equivalent cannot be achieved merely by aliasing Python imports.

## Device validation protocol

On Android install a compatible Termux build and Termux:GUI plugin, ensure `termuxgui` Python binding imports and establishes a connection, then run both example programs. Verify typing with multi-codepoint Unicode, IME composition, repeated clicks, checkbox toggles, screen rotation, Android back navigation, background/foreground lifecycle, overlay permission rejection, many-widget performance and cleanup. Record Android version, plugin version, CPU, cold/warm startup, UI latency p50/p95, RSS, peak memory, CPU, wakeups and errors. Compare under identical conditions with the TGK version under evaluation; do not infer a performance ratio from desktop mocks.
