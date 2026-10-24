"""Minimal, dependency-free, reactive Kivy-shaped model.

No SDL, OpenGL, private Kivy imports, sitecustomize, or Android dependencies.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
import heapq
import itertools
import math
import time
from typing import Callable


class Property:
    """A per-instance observable descriptor; mutable defaults are copied."""

    def __init__(self, default=None, validator=None):
        self.default = default
        self.validator = validator

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return instance.__dict__.setdefault(self.name, deepcopy(self.default))

    def __set__(self, instance, value):
        if self.validator is not None and not self.validator(value):
            raise ValueError(f"invalid value for {self.name}: {value!r}")
        old = self.__get__(instance)
        if old == value:
            return
        before = getattr(instance, '_before_change', None)
        if before is not None:
            before(self.name, value)
        instance.__dict__[self.name] = value
        instance._changed(self.name, value)


class StringProperty(Property):
    def __init__(self, default=""):
        super().__init__(default, lambda value: isinstance(value, str))


class NumericProperty(Property):
    def __init__(self, default=0):
        super().__init__(default, lambda value: type(value) in (int, float) and math.isfinite(value))


class BooleanProperty(Property):
    def __init__(self, default=False):
        super().__init__(default, lambda value: type(value) is bool)


class ObjectProperty(Property):
    pass


class ListProperty(Property):
    def __init__(self, default=None):
        super().__init__([] if default is None else default, lambda v: isinstance(v, list))


class EventDispatcher:
    def __init__(self, **properties):
        self._bindings = defaultdict(list)
        for name, value in properties.items():
            if not hasattr(type(self), name):
                raise TypeError(f"unsupported property {type(self).__name__}.{name}")
            setattr(self, name, value)

    def bind(self, **callbacks):
        for name, callback in callbacks.items():
            if not callable(callback):
                raise TypeError(f"{name} requires a callable")
            self._bindings[name].append(callback)
        return self

    def unbind(self, **callbacks):
        for name, callback in callbacks.items():
            try:
                self._bindings[name].remove(callback)
            except ValueError:
                pass

    def _changed(self, name, value):
        for callback in tuple(self._bindings.get(name, ())):
            callback(self, value)
        handler = getattr(self, "on_" + name, None)
        if callable(handler):
            handler(self, value)

    def dispatch(self, event, *args):
        handler = getattr(self, event, None)
        if callable(handler):
            handler(*args)
        for callback in tuple(self._bindings.get(event, ())):
            callback(self, *args)


class Widget(EventDispatcher):
    text = StringProperty("")
    visible = BooleanProperty(True)
    disabled = BooleanProperty(False)
    width = ObjectProperty(None)
    height = ObjectProperty(None)
    background_color = ObjectProperty(None)

    def __init__(self, **kwargs):
        self.parent = None
        self.children = []
        self.ids = {}
        self._backend = None
        self._native = None
        super().__init__(**kwargs)

    def _before_change(self, name, value):
        if self._backend is not None:
            self._backend._check_thread()

    def _changed(self, name, value):
        super()._changed(name, value)
        if self._backend is not None:
            self._backend.invalidate(self, name)

    def add_widget(self, widget):
        if not isinstance(widget, Widget):
            raise TypeError("child must be Widget")
        if widget.parent is not None:
            raise ValueError("child already has a parent")
        ancestor = self
        while ancestor is not None:
            if ancestor is widget:
                raise ValueError("widget cycles are forbidden")
            ancestor = ancestor.parent
        if self._backend is not None:
            self._backend.assert_can_insert(self)
        self.children.append(widget)
        widget.parent = self
        if self._backend is not None:
            try:
                self._backend.mount(widget, self._native)
            except BaseException:
                self.children.pop()
                widget.parent = None
                raise
        return widget

    def remove_widget(self, widget):
        if widget not in self.children:
            raise ValueError("not a direct child")
        if self._backend is not None:
            self._backend.assert_can_insert(self)
            self._backend.unmount(widget)
        self.children.remove(widget)
        widget.parent = None

    def walk(self):
        pending = [self]
        while pending:
            node = pending.pop()
            yield node
            pending.extend(reversed(node.children))


class BoxLayout(Widget):
    orientation = StringProperty("horizontal")

    def __init__(self, orientation="horizontal", **kwargs):
        if orientation not in ("vertical", "horizontal"):
            raise ValueError("orientation must be vertical or horizontal")
        super().__init__(orientation=orientation, **kwargs)


class GridLayout(Widget):
    cols = NumericProperty(1)

    def __init__(self, cols=1, **kwargs):
        if type(cols) is not int or cols < 1:
            raise ValueError("cols must be positive integer")
        super().__init__(cols=cols, **kwargs)


class FloatLayout(Widget):
    pass


class ScrollView(Widget):
    def add_widget(self, widget):
        if self.children:
            raise ValueError("ScrollView accepts one child")
        return super().add_widget(widget)


class Label(Widget):
    font_size = NumericProperty(16)

    def __init__(self, text="", **kwargs):
        super().__init__(text=text, **kwargs)


class Button(Label):
    def on_press(self):
        pass

    def on_release(self):
        pass


class TextInput(Widget):
    multiline = BooleanProperty(False)
    password = BooleanProperty(False)

    def __init__(self, text="", multiline=False, password=False, **kwargs):
        super().__init__(text=text, multiline=multiline, password=password, **kwargs)


class CheckBox(Widget):
    active = BooleanProperty(False)

    def __init__(self, active=False, text="", **kwargs):
        super().__init__(active=active, text=text, **kwargs)


class Switch(CheckBox):
    pass


class ToggleButton(Button):
    state = StringProperty("normal")

    def __init__(self, text="", state="normal", **kwargs):
        if state not in ("normal", "down"):
            raise ValueError("toggle state must be normal or down")
        super().__init__(text=text, state=state, **kwargs)


class Spinner(Label):
    values = ListProperty()

    def __init__(self, text="", values=None, **kwargs):
        super().__init__(text=text, values=list(values or ()), **kwargs)


class Image(Widget):
    source = StringProperty("")

    def __init__(self, source="", **kwargs):
        super().__init__(source=source, **kwargs)


class ProgressBar(Widget):
    value = NumericProperty(0)
    max = NumericProperty(100)

    def __init__(self, value=0, max=100, **kwargs):
        if max <= 0:
            raise ValueError("max must be positive")
        super().__init__(value=value, max=max, **kwargs)


class _ClockEvent:
    def __init__(self, owner, number):
        self.owner, self.number = owner, number

    def cancel(self):
        self.owner._active.discard(self.number)


class _Clock:
    """Monotonic heap timer queue with a per-iteration callback budget."""
    def __init__(self):
        self._queue = []
        self._active = set()
        self._counter = itertools.count()

    def _schedule(self, callback, delay, repeat):
        if not callable(callback) or type(delay) not in (int, float) or not math.isfinite(delay):
            raise ValueError("callback and finite delay required")
        if delay < 0 or (repeat and delay == 0):
            raise ValueError("invalid timer interval")
        number = next(self._counter)
        self._active.add(number)
        heapq.heappush(self._queue, (time.monotonic() + delay, number, callback, delay if repeat else None))
        return _ClockEvent(self, number)

    def schedule_once(self, callback, timeout=0):
        return self._schedule(callback, timeout, False)

    def schedule_interval(self, callback, interval):
        return self._schedule(callback, interval, True)

    def tick(self, budget=64):
        if type(budget) is not int or budget < 1:
            raise ValueError("budget must be a positive integer")
        processed = 0
        # A newly scheduled zero-delay callback cannot monopolize the loop.
        while self._queue and processed < budget:
            when, number, callback, repeat = self._queue[0]
            now = time.monotonic()
            if when > now:
                break
            heapq.heappop(self._queue)
            processed += 1
            if number not in self._active:
                continue
            try:
                keep = callback(max(0, now - when))
            except BaseException:
                self._active.discard(number)
                raise
            if repeat is not None and keep is not False and number in self._active:
                heapq.heappush(self._queue, (time.monotonic() + repeat, number, callback, repeat))
            else:
                self._active.discard(number)
        return processed

    def until_next(self, default=0.016):
        if not self._queue:
            return default
        return max(0.0, min(default, self._queue[0][0] - time.monotonic()))

    def reset(self):
        self._queue.clear()
        self._active.clear()


Clock = _Clock()


class App(EventDispatcher):
    _running = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.root = None
        self._backend = None

    @classmethod
    def get_running_app(cls):
        return App._running

    def build(self):
        raise NotImplementedError("override build() to return a Widget")

    def on_start(self):
        pass

    def on_stop(self):
        pass

    def run(self, *, backend=None):
        if App._running is not None:
            raise RuntimeError("only one App can run")
        App._running = self
        try:
            self.root = self.build()
            if not isinstance(self.root, Widget):
                raise TypeError("build() must return a Widget")
            if backend is None:
                from .backend import TermuxBackend
                backend = TermuxBackend()
            self._backend = backend
            backend.run(self.root, self.on_start)
        finally:
            try:
                self.on_stop()
            finally:
                Clock.reset()
                App._running = None
                self._backend = None

    def stop(self):
        if self._backend is not None:
            self._backend.stop()
