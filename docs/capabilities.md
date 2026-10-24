# Exact compatibility and capability contract (0.1.0)

The public import `termux_kivy` exposes basic Kivy-style names. A program must explicitly use this API or activate the optional import shim before importing `kivy`.

| Kivy-style feature | Status | Native implementation / limitation |
|---|---|---|
| App.build/run/stop and on_start/on_stop | Implemented | One Termux:GUI Activity; synchronous UI loop |
| Widget parenting / add/remove / walk | Implemented | Dynamic native add/remove except live GridLayout |
| EventDispatcher.bind/unbind/dispatch | Partial | Public property and simple control events; no Kivy gesture subsystem |
| String/Numeric/Boolean/Object/ListProperty | Partial | Values and simple change notification; in-place ListProperty mutations do not dispatch |
| BoxLayout | Partial | Native LinearLayout, horizontal/vertical; no full Kivy size_hint/pos_hint |
| GridLayout | Partial | Native Android grid with fixed rows at mount |
| FloatLayout | Partial | Native FrameLayout; no arbitrary Kivy coordinate placement |
| ScrollView | Partial | Native NestedScrollView, exactly one child |
| Label / Button | Implemented subset | Native TextView / Button; basic text/font size |
| TextInput | Implemented subset | Native EditText and text-event bridge; IME text echo avoided |
| CheckBox / Switch | Implemented subset | Native controls and checked-state updates |
| ProgressBar | Implemented subset | Android 0–100 integer normalized from value/max |
| Clock.schedule_once/interval | Implemented subset | Monotonic heap; no animation subsystem or frame timeline compatibility |
| KV Builder.load_string/load_file | Restricted | Literal values, simple attr references, id and callback method calls |
| Kivy import aliases | Opt-in partial | Only selected modules; no automatic site or interpreter hijack |
| Themes | Minimal | Explicit per-widget ARGB background integer; no design-system presets |
| Image | Implemented subset | PNG/JPEG local file (max 8MB) to native ImageView |
| Spinner | Implemented subset | Native Spinner with values, selected index and text synchronization |
| ToggleButton | Implemented subset | Native ToggleButton and state synchronization |
| Slider | Planned | Requires shared-buffer drawing and touch mapping |
| Canvas / InstructionGroup / Shader / OpenGL | Not supported | Requires separate rendering and input backend |
| Kivy Window, gesture recognizers, multitouch | Not supported | Requires native input mappings and geometry |
| Async file/media/pipeline tools | Out of scope | Separate from UI runtime; use standard Python or third-party libraries |
| Synchronous Activity dismissal and overlay | Partial | Available via backend options; overlay needs Android permission |

Native Layout parameters use Android density-independent pixels. Unlike a Kivy canvas, a native view does not share a universal user-defined 2D coordinate plane. Some native calls are unsupported on particular plugin versions: these are surfaced explicitly, never simulated as successful behavior.

## What the project does not promise

It cannot run any arbitrary unmodified Kivy project. It does not embed the `kivy` wheel, does not implement all Kivy modules, and does not claim pixel-identical output, fonts, exact spacing, colors, keyboard behavior or animation semantics. Compatibility is a practical, progressively extendable API surface rather than a binary or graphical clone.

The Android plugin is a distinct installation and may require foreground or overlay permissions. On desktop the project can test pure-Python logic but cannot create a real Android Activity.

## Security characteristics

The KV parser uses Python AST only to validate and resolve a tiny expression subset. It does not call `eval`, `exec` or import arbitrary modules from KV content. This is **not a general-purpose sandbox**: calling explicitly allowed application methods can have side effects; KV content and registered classes should still originate from trusted applications. The backend does not execute shell commands or download external resources.

No direct import hook is installed by default. The optional `compat.activate()` is process-wide and should not be mixed with an already-running actual Kivy installation.
