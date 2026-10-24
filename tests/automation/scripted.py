#!/usr/bin/env python3
"""Scripted simulated UI input. This does NOT verify physical screen pixels.

Launch via test-all.py. Every scenario runs as a standalone process and emits
detailed automation actions, native method traces and assertions.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fake_termuxgui as fake
from fake_termuxgui import event
from termux_kivy import (
    App, BoxLayout, Button, CheckBox, GridLayout, Label,
    ProgressBar, Spinner, TextInput, ToggleButton, TermuxBackend,
)


def log(kind, message):
    print(f"[{datetime.now().astimezone().isoformat(timespec='milliseconds')}] "
          f"{kind}: {message}", flush=True)


def require(ok, description, *, expected=None, actual=None):
    log("ASSERT", f"{description}; expected={expected!r}; actual={actual!r}; "
        f"{'PASS' if ok else 'FAIL'}")
    if not ok:
        raise AssertionError(f"{description}: expected {expected!r}; got {actual!r}")


class Demo(App):
    def __init__(self, scenario):
        super().__init__()
        self.scenario = scenario
        self.clicks = 0

    def build(self):
        self.root_layout = BoxLayout(orientation="vertical")
        self.counter = self.root_layout.add_widget(Label(text="Clicks: 0"))
        self.button = self.root_layout.add_widget(Button(text="Tap counter"))
        self.button.bind(on_press=self.increment)
        self.entry = self.root_layout.add_widget(TextInput(text=""))
        self.checkbox = self.root_layout.add_widget(CheckBox(text="Enable"))
        self.toggle = self.root_layout.add_widget(ToggleButton())
        self.spinner = self.root_layout.add_widget(
            Spinner(text="alpha", values=["alpha", "beta", "2026"])
        )
        self.progress = self.root_layout.add_widget(ProgressBar(value=20, max=100))
        log("TREE", f"Built {len(self.root_layout.children)} widgets; "
            "native Activity creation occurs next")
        return self.root_layout

    def increment(self, widget):
        self.clicks += 1
        self.counter.text = f"Clicks: {self.clicks}"
        log("CALLBACK", f"Counter handler invoked by {type(widget).__name__}; clicks={self.clicks}")

    def on_start(self):
        backend = self._backend
        log("ACTIVITY", f"Fake native Activity mounted; "
            f"view_count={len(backend._index)}; mode={self.scenario!r}")
        try:
            getattr(self, "scenario_" + self.scenario)()
            backend.flush()
            log("RESULT", f"SCENARIO PASS: {self.scenario}")
        finally:
            self.trace_calls()
            backend.stop()

    def trace_calls(self):
        for node in self.root.walk():
            native = node._native
            if native is None:
                continue
            log("NATIVE", f"node={type(node).__name__} id={native.id} "
                f"parent={getattr(native.parent, 'id', None)} "
                f"calls={native.calls!r}")

    def tap(self, widget, label, *, center=None):
        """Simulate native View->click dispatch; bounds are NOT real Android pixels."""
        n = widget._native
        require(n is not None and n.id in self._backend._index,
                f"{label} is mounted and indexed",
                expected=True, actual=n is not None and n.id in self._backend._index)
        log("SIMULATED_TOUCH", f"{label}: target View id={n.id}; "
            f"synthetic center={center}; injecting native click event")
        self._backend.handle_event(event("click", n))

    def type_text(self, widget, text):
        log("SIMULATED_KEYBOARD", f"Focusing synthetic EditText id={widget._native.id}; "
            f"typing {text!r} via native text event")
        self._backend.handle_event(event("text", widget._native, text=text))

    def scenario_counter(self):
        self._backend.flush()
        self.tap(self.button, "counter", center=(180, 96))
        self.tap(self.button, "counter", center=(180, 96))
        self.tap(self.button, "counter", center=(180, 96))
        require(self.clicks == 3, "all simulated clicks reach the handler", expected=3, actual=self.clicks)
        require(self.counter.text == "Clicks: 3", "Python label state", expected="Clicks: 3", actual=self.counter.text)
        self._backend.flush()
        writes = [v for n, v in self.counter._native.calls if n == "settext"]
        require(writes == [("Clicks: 3",)], "3 clicks coalesce into 1 native text write",
                expected=[("Clicks: 3",)], actual=writes)

    def scenario_typing(self):
        self._backend.flush()
        for sample in ("H", "He", "Hello", "Hello world 42", "Grüße 世界"):
            self.type_text(self.entry, sample)
            require(self.entry.text == sample, "Unicode text event reaches Python",
                    expected=sample, actual=self.entry.text)
        self._backend.flush()
        echos = [call for call in self.entry._native.calls if call[0] == "settext"]
        require(not echos, "text input does not reset active IME composition",
                expected=[], actual=echos)
        self.entry.text = "programmatic override"
        self._backend.flush()
        require(("settext", ("programmatic override",)) in self.entry._native.calls,
                "programmatic text still propagates to native EditText",
                expected=True, actual=self.entry._native.calls)

    def scenario_selection(self):
        self._backend.flush()
        log("SIMULATED_SELECTION", "Selecting Spinner label '2026' (not integer index 2026)")
        self._backend.handle_event(event("itemselected", self.spinner._native, selected="2026"))
        require(self.spinner.text == "2026", "Spinner resolves text payload",
                expected="2026", actual=self.spinner.text)
        log("SIMULATED_TOUCH", "Native checkbox click checked=True")
        self._backend.handle_event(event("click", self.checkbox._native, set=True))
        log("SIMULATED_TOUCH", "Native toggle click checked=True")
        self._backend.handle_event(event("click", self.toggle._native, set=True))
        require(self.checkbox.active is True, "checkbox has checked state", expected=True, actual=self.checkbox.active)
        require(self.toggle.state == "down", "toggle state synchronized", expected="down", actual=self.toggle.state)
        log("SIMULATED_TOUCH", "Native checkbox/toggle click checked=False")
        self._backend.handle_event(event("click", self.checkbox._native, set=False))
        self._backend.handle_event(event("click", self.toggle._native, set=False))
        require(self.checkbox.active is False and self.toggle.state == "normal",
                "native toggling roundtrip", expected=(False, "normal"),
                actual=(self.checkbox.active, self.toggle.state))

    def scenario_layout(self):
        grid = self.root_layout.add_widget(GridLayout(cols=2))
        cells = [grid.add_widget(Button(text=f"Cell {i}")) for i in range(5)]
        # Dynamic insertion into a freshly mounted GridLayout is deliberately
        # restricted. We inserted all cells before mounting the grid.
        log("LAYOUT", "Mounting fixed 2-column GridLayout with five buttons")
        require(grid._native is not None, "grid was mounted with children",
                expected=True, actual=grid._native is not None)
        for i, widget in enumerate(cells):
            expected = (i // 2, i % 2)
            positions = [args for name, args in widget._native.calls if name == "setgridlayoutparams"]
            require(positions == [expected], f"logical grid cell {i} row/column",
                    expected=[expected], actual=positions)
        # Logical cell mapping is verified; real screen pixel positions are
        # checked ONLY by the --device ADB suite.
        self.tap(cells[3], "grid cell 3", center="logical row=1 col=1")
        log("LAYOUT", "SIMULATED GRID VERIFIED; physical bounds require --device")

    def scenario_dynamic(self):
        new = self.root_layout.add_widget(Button(text="Dynamic button"))
        log("TREE", f"Added button after Activity mount: id={new._native.id}")
        require(new._backend is self._backend, "newly inserted widget is mounted",
                expected=True, actual=new._backend is self._backend)
        presses = []
        new.bind(on_press=lambda _sender: presses.append("pressed"))
        self.tap(new, "dynamic button")
        require(presses == ["pressed"], "dynamic button receives clicks",
                expected=["pressed"], actual=presses)
        native = new._native
        self.root_layout.remove_widget(new)
        require(native.deleted, "native view was removed", expected=True, actual=native.deleted)
        require(new._backend is None, "Python model detached", expected=None, actual=new._backend)
        self._backend.handle_event(event("click", native))
        require(presses == ["pressed"], "stale native events ignored",
                expected=["pressed"], actual=presses)

    def scenario_failure(self):
        self._backend.flush()
        original = self.counter._native.settext
        errors = []

        def flaky(text):
            log("FAULT_INJECTION", f"Failing first native setter for payload={text!r}")
            if not errors:
                errors.append("simulated transient failure")
                raise OSError("simulated temporary native IPC error")
            return original(text)

        self.counter._native.settext = flaky
        self.counter.text = "Recoverable native update"
        try:
            self._backend.flush()
        except OSError as exc:
            log("EXPECTED_ERROR", str(exc))
        else:
            raise AssertionError("Fault injection was not observed")
        require(self.counter in self._backend._dirty,
                "failed property remains pending", expected=True,
                actual=self.counter in self._backend._dirty)
        self._backend.flush()
        require(("settext", ("Recoverable native update",)) in self.counter._native.calls,
                "retry delivers final value", expected=True, actual=self.counter._native.calls)
        log("FAULT_RECOVERY", "Native setter retry was successful")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=(
        "counter", "typing", "selection", "layout", "dynamic", "failure"
    ))
    args = parser.parse_args(argv)
    log("BEGIN", f"Starting isolated scenario {args.scenario}")
    try:
        Demo(args.scenario).run(backend=TermuxBackend(fake, idle_seconds=0))
    except BaseException:
        log("FATAL", traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
