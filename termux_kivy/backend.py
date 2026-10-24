"""Android Termux:GUI transport for the pure-Python widget model.

View operations are deliberately constrained to documented termuxgui methods.
All native calls happen on the owning UI thread. No global import hooks.
"""
from __future__ import annotations

import math
from pathlib import Path
from queue import Empty, Full, Queue
import threading
import time

from .core import (
    BoxLayout, Button, CheckBox, Clock, FloatLayout, GridLayout,
    Image, Label, ProgressBar, ScrollView, Spinner, Switch, TextInput, ToggleButton, Widget,
)


class UnsupportedOperation(RuntimeError):
    """A Kivy-like operation that native Android views cannot implement safely."""


class TermuxBackend:
    def __init__(self, tg=None, *, window_mode="normal", idle_seconds=0.016):
        if window_mode not in ("normal", "dialog", "overlay"):
            raise ValueError("unknown Activity window mode")
        if type(idle_seconds) not in (int, float) or not 0 <= idle_seconds <= 0.1:
            raise ValueError("idle_seconds must be in [0, 0.1]")
        if tg is None:
            try:
                import termuxgui as tg
            except ImportError as exc:
                raise RuntimeError(
                    "Install the Termux:GUI Android plugin and run: pip install termuxgui"
                ) from exc
        self.tg = tg
        self.window_mode = window_mode
        self.idle_seconds = idle_seconds
        self.connection = None
        self.activity = None
        self.root = None
        self._owner = None
        self._stopping = False
        self._index = {}
        self._state = {}
        self._dirty = {}
        self._tasks = Queue(maxsize=4096)
        self.stats = {"created": 0, "deleted": 0, "updated": 0, "events": 0}

    def _check_thread(self):
        if self._owner is not None and threading.get_ident() != self._owner:
            raise RuntimeError("Native UI mutations must run on the Activity thread; use post()")

    def post(self, callback, *args, **kwargs):
        """Thread-safe, bounded ingress for worker results. Never calls Android directly."""
        if not callable(callback):
            raise TypeError("callback must be callable")
        try:
            self._tasks.put_nowait((callback, args, kwargs))
        except Full as exc:
            raise RuntimeError("UI callback queue is full") from exc

    def _drain_tasks(self, budget=64):
        for _ in range(budget):
            try:
                fn, args, kwargs = self._tasks.get_nowait()
            except Empty:
                break
            fn(*args, **kwargs)

    def assert_can_insert(self, parent):
        self._check_thread()
        if isinstance(parent, GridLayout):
            raise UnsupportedOperation(
                "live GridLayout structural edits require a new native grid; "
                "construct the complete grid before mounting"
            )
        if isinstance(parent, ScrollView) and len(parent.children) > 0:
            raise UnsupportedOperation("ScrollView accepts one child")

    def _create(self, node, parent):
        tg, a = self.tg, self.activity
        if isinstance(node, BoxLayout):
            native = tg.LinearLayout(a, parent, vertical=node.orientation == "vertical")
        elif isinstance(node, GridLayout):
            cols = int(node.cols)
            if cols != node.cols or cols < 1:
                raise ValueError("GridLayout.cols must be positive integer")
            native = tg.GridLayout(a, max(1, math.ceil(len(node.children) / cols)), cols, parent)
        elif isinstance(node, ScrollView):
            if len(node.children) > 1:
                raise ValueError("ScrollView has more than one child")
            native = tg.NestedScrollView(a, parent)
        elif isinstance(node, FloatLayout) or type(node) is Widget:
            native = tg.FrameLayout(a, parent)
        elif isinstance(node, TextInput):
            inputtype = "textPassword" if node.password else (
                "textMultiLine" if node.multiline else "text"
            )
            native = tg.EditText(
                a, node.text, parent, singleline=not node.multiline, inputtype=inputtype
            )
            native.sendtextevent(True)
        elif isinstance(node, ToggleButton):
            native = tg.ToggleButton(a, parent, checked=node.state == 'down')
            if node.text:
                raise UnsupportedOperation(
                    "Termux:GUI ToggleButton cannot display custom text; "
                    "use a separate Label beside the toggle"
                )
            native.sendclickevent(True)
        elif isinstance(node, Button):
            native = tg.Button(a, node.text, parent)
            native.sendclickevent(True)
        elif isinstance(node, Switch):
            native = tg.Switch(a, node.text, parent, checked=node.active)
            native.sendclickevent(True)
        elif isinstance(node, CheckBox):
            native = tg.Checkbox(a, node.text, parent, checked=node.active)
            native.sendclickevent(True)
        elif isinstance(node, Spinner):
            native = tg.Spinner(a, parent)
            native.setlist([str(x) for x in node.values])
            if node.text in node.values:
                native.selectitem(node.values.index(node.text))
        elif isinstance(node, Image):
            native = tg.ImageView(a, parent)
            if node.source:
                native.setimage(self._read_image(node.source))
        elif isinstance(node, Label):
            native = tg.TextView(a, node.text, parent)
        elif isinstance(node, ProgressBar):
            native = tg.ProgressBar(a, parent)
        else:
            raise UnsupportedOperation(
                f"No native Termux:GUI mapping for {type(node).__name__}"
            )
        return native

    def mount(self, root, parent=None):
        self._check_thread()
        if self.activity is None:
            raise RuntimeError("Activity not opened")
        if root._backend is not None:
            raise ValueError("widget is already mounted")
        # Pre-order, parent-first, without recursion or repeated list scans.
        added = []
        try:
            pending = [(root, parent, None)]
            while pending:
                node, p, child_position = pending.pop()
                native = self._create(node, p)
                node._native = native
                node._backend = self
                native_id = getattr(native, "id", None)
                if native_id is not None:
                    if native_id in self._index:
                        raise RuntimeError(f"duplicate native View ID: {native_id}")
                    self._index[native_id] = node
                self._state[node] = {}
                added.append(node)
                self.stats["created"] += 1
                self._initial_style(node)
                if isinstance(node.parent, GridLayout):
                    cols = int(node.parent.cols)
                    native.setgridlayoutparams(child_position // cols, child_position % cols)
                for index in range(len(node.children) - 1, -1, -1):
                    pending.append((node.children[index], native, index))
        except BaseException:
            # Deleting the subtree root removes Android descendants too.
            # Avoid duplicate deleteView calls on already removed children.
            for descendant in reversed(added[1:]):
                self._detach(descendant, delete=False)
            if added:
                self._detach(added[0], delete=True)
            raise

    def _initial_style(self, node):
        n = node._native
        parent = node.parent
        # The activity root and FrameLayout pages must fill available space.
        if parent is None or isinstance(parent, FloatLayout):
            n.setwidth("MATCH_PARENT" if node.width is None else self._dimension(node.width))
            n.setheight("MATCH_PARENT" if node.height is None else self._dimension(node.height))
        else:
            if node.width is not None:
                n.setwidth(self._dimension(node.width))
            elif isinstance(parent, ScrollView):
                n.setwidth("MATCH_PARENT")
            elif isinstance(parent, BoxLayout):
                if parent.orientation == "vertical":
                    n.setwidth("MATCH_PARENT")
                else:
                    n.setwidth(0)
                    n.setlinearlayoutparams(1)
            if node.height is not None:
                n.setheight(self._dimension(node.height))
            elif isinstance(parent, BoxLayout) and parent.orientation == "vertical":
                if isinstance(node, ScrollView):
                    n.setheight(0)
                    n.setlinearlayoutparams(1)
                elif isinstance(node, (Button, TextInput, CheckBox, Switch, Spinner)):
                    n.setheight(48)
        for name in ("visible", "disabled", "background_color", "font_size",
                     "active", "value", "max", "state"):
            if hasattr(type(node), name):
                self.invalidate(node, name)

    @staticmethod
    def _read_image(source):
        path = Path(source)
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            raise ValueError("Image requires a PNG or JPEG file")
        if not path.is_file() or path.stat().st_size > 8_000_000:
            raise ValueError("Image does not exist or exceeds the 8MB limit")
        return path.read_bytes()

    @staticmethod
    def _dimension(value):
        if isinstance(value, str) and value in ("MATCH_PARENT", "WRAP_CONTENT"):
            return value
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("view dimensions must be nonnegative dp or a layout constant")
        return int(math.ceil(value))

    def _detach(self, node, *, delete=True):
        native = node._native
        native_id = getattr(native, "id", None) if native is not None else None
        if native_id is not None:
            self._index.pop(native_id, None)
        self._state.pop(node, None)
        self._dirty.pop(node, None)
        node._native = None
        node._backend = None
        if native is not None and delete:
            native.delete()
            self.stats["deleted"] += 1

    def unmount(self, root):
        self._check_thread()
        # The native View.delete removes its descendant views too.
        nodes = list(root.walk())
        if not nodes or nodes[0]._backend is not self:
            return
        for node in reversed(nodes[1:]):
            self._detach(node, delete=False)
        self._detach(root, delete=True)

    def invalidate(self, node, name):
        self._check_thread()
        if node._backend is not self:
            return
        self._dirty.setdefault(node, set()).add(name)

    def _update(self, node, name):
        n = node._native
        if n is None:
            return
        # Structural changes need re-mounting. Never silently claim support.
        if name in ("orientation", "cols", "multiline", "password"):
            raise UnsupportedOperation(f"live mutation of {name} requires re-mount")
        state = self._state[node]
        if name in ("text", "font_size") and isinstance(node, (Label, TextInput)) and not isinstance(node, (Spinner, ToggleButton)):
            value = node.text if name == "text" else (
                int(round(node.font_size)) if isinstance(node, Label) else None
            )
            if value is None:
                return
            key = name
            fn = n.settext if name == "text" else n.settextsize
        elif name == "visible":
            key, value, fn = name, (2 if node.visible else 0), n.setvisibility
        elif name == "background_color":
            if node.background_color is None:
                return
            if type(node.background_color) is not int or not 0 <= node.background_color <= 0xFFFFFFFF:
                raise ValueError("background_color must be a 32-bit ARGB integer")
            key, value, fn = name, node.background_color, n.setbackgroundcolor
        elif name in ("width", "height"):
            value = getattr(node, name)
            if value is None:
                return
            key, value = name, self._dimension(value)
            fn = n.setwidth if name == "width" else n.setheight
        elif name == "source" and isinstance(node, Image):
            if not node.source:
                return
            key, value, fn = name, node.source, lambda _source: n.setimage(self._read_image(_source))
        elif name == "values" and isinstance(node, Spinner):
            key, value, fn = name, tuple(node.values), lambda values: n.setlist(list(map(str, values)))
        elif name == "text" and isinstance(node, Spinner):
            if node.text not in node.values:
                return
            key, value, fn = "selected", node.values.index(node.text), n.selectitem
        elif name == "text" and isinstance(node, ToggleButton):
            if node.text:
                raise UnsupportedOperation(
                    "Termux:GUI ToggleButton cannot display custom text"
                )
            return
        elif name == "state" and isinstance(node, ToggleButton):
            if node.state not in ("normal", "down"):
                raise ValueError("toggle state must be normal or down")
            key, value, fn = "checked", node.state == "down", n.setchecked
        elif name == "active" and isinstance(node, CheckBox):
            key, value, fn = name, node.active, n.setchecked
        elif name in ("value", "max") and isinstance(node, ProgressBar):
            if node.max <= 0:
                raise ValueError("ProgressBar.max must be positive")
            key, value, fn = "progress", max(0, min(100, round(node.value * 100 / node.max))), n.setprogress
        elif name == "disabled":
            # setclickable is supported, but not a complete Android disabled style.
            key, value, fn = "clickable", not node.disabled, n.setclickable
        else:
            return
        if state.get(key) == value:
            return
        fn(value)
        state[key] = value
        self.stats["updated"] += 1

    def flush(self, budget=2048):
        self._check_thread()
        if type(budget) is not int or budget <= 0:
            raise ValueError("flush budget must be positive")
        processed = 0
        # Iterate only the allotted nodes; avoid snapshotting the whole dictionary.
        # Re-queue failed and remaining fields so a transient IPC failure does
        # not silently discard the last requested state.
        while self._dirty and processed < budget:
            node, fields = next(iter(self._dirty.items()))
            self._dirty.pop(node)
            ordered = sorted(fields)
            for index, field in enumerate(ordered):
                try:
                    self._update(node, field)
                except BaseException:
                    self._dirty.setdefault(node, set()).update(ordered[index:])
                    raise
            processed += 1
        return processed

    def _is(self, event, name):
        actual = getattr(event, "type", None)
        enum = getattr(getattr(self.tg, "Event", None), name, name)
        return actual == name or actual == enum

    def handle_event(self, event):
        self._check_thread()
        self.stats["events"] += 1
        if self._is(event, "destroy"):
            if event.value.get("finishing", False):
                self._stopping = True
            return
        if self._is(event, "back"):
            self.stop()
            return
        native_id = event.value.get("id")
        node = self._index.get(native_id) if isinstance(native_id, (int, str)) else None
        if node is None:
            return
        if self._is(event, "text") and isinstance(node, TextInput):
            value = event.value.get("text")
            if value is None:
                value = node._native.gettext()
            value = str(value)
            # The IME is the source of truth while editing; avoid re-setting
            # EditText and destroying cursor position / composing text.
            self._state[node]["text"] = value
            node.text = value
        elif self._is(event, "itemselected") and isinstance(node, Spinner):
            # The real Python binding emits the selected *string*, not an
            # index. Numeric-looking strings are still strings (e.g. "2026").
            selection = event.value.get("selected")
            if type(selection) is int:
                index = selection if 0 <= selection < len(node.values) else None
            else:
                try:
                    index = [str(value) for value in node.values].index(selection)
                except ValueError:
                    index = None
            if index is not None:
                self._state[node]["selected"] = index
                node.text = str(node.values[index])
        elif self._is(event, "click"):
            if node.disabled:
                return
            if isinstance(node, CheckBox) and "set" in event.value:
                self._state[node]["active"] = bool(event.value["set"])
                node.active = bool(event.value["set"])
            if isinstance(node, ToggleButton) and "set" in event.value:
                self._state[node]["checked"] = bool(event.value["set"])
                node.state = "down" if event.value["set"] else "normal"
            if isinstance(node, Button):
                node.dispatch("on_press")
                node.dispatch("on_release")

    def _close(self):
        try:
            if self.root is not None and self.root._backend is self:
                if self._stopping:
                    # The Activity is already finishing. Avoid extra IPC to
                    # delete views that Android is disposing automatically.
                    for node in self.root.walk():
                        node._backend = None
                        node._native = None
                else:
                    self.unmount(self.root)
        finally:
            # Always clear Python ownership, even if a native delete fails.
            if self.root is not None:
                for node in self.root.walk():
                    node._backend = None
                    node._native = None
            self._dirty.clear()
            self._index.clear()
            self._state.clear()
            self.root = None
            self.connection = None
            self.activity = None
            self._owner = None
            # Drop callbacks queued for the old Activity, not the next one.
            while True:
                try:
                    self._tasks.get_nowait()
                except Empty:
                    break

    def stop(self):
        # A worker may request stop, but only the UI thread can use Android.
        if self._owner is not None and threading.get_ident() != self._owner:
            self.post(self.stop)
            return
        if self._stopping:
            return
        self._stopping = True
        if self.activity is not None:
            self.activity.finish()

    def run(self, root, on_start=None):
        self._owner = threading.get_ident()
        self._stopping = False
        self.root = root
        try:
            with self.tg.Connection() as connection:
                self.connection = connection
                opts = {"intercept": True}
                if self.window_mode != "normal":
                    opts[self.window_mode] = True
                self.activity = self.tg.Activity(connection, **opts)
                self.mount(root)
                if on_start is not None:
                    on_start()
                while not self._stopping:
                    processed = 0
                    for _ in range(128):
                        event = connection.checkevent()
                        if event is None:
                            break
                        processed += 1
                        self.handle_event(event)
                        if self._stopping:
                            break
                    if self._stopping:
                        break
                    self._drain_tasks()
                    Clock.tick()
                    self.flush()
                    if processed == 0 and not self._stopping:
                        time.sleep(min(self.idle_seconds, Clock.until_next(self.idle_seconds)))
        finally:
            closing_activity = self.activity
            try:
                self._close()
            finally:
                if closing_activity is not None and not self._stopping:
                    closing_activity.finish()
