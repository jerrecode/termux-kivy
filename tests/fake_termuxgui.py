"""Deterministic event-driven stand-in for the documented Termux:GUI binding."""
from collections import deque
from types import SimpleNamespace


class _View:
    _next = 1
    def __init__(self, activity, parent=None, **kwargs):
        self.activity, self.parent = activity, parent
        self.id = _View._next
        _View._next += 1
        self.calls = []
        self.deleted = False
        self.kwargs = dict(kwargs, parent_id=getattr(parent, 'id', None))
        activity.views[self.id] = self

    def __getattr__(self, name):
        if name.startswith(("set", "send")) or name in ("selectitem", "refresh", "delete"):
            def record(*args):
                self.calls.append((name, args))
            return record
        raise AttributeError(name)

    def delete(self):
        self.deleted = True
        self.calls.append(("delete", ()))


class LinearLayout(_View):
    pass
class GridLayout(_View):
    def __init__(self, activity, rows, cols, parent=None):
        super().__init__(activity, parent, rows=rows, cols=cols)
class NestedScrollView(_View):
    pass
class FrameLayout(_View):
    pass
class Button(_View):
    def __init__(self, activity, text, parent=None):
        super().__init__(activity, parent, text=text)
class TextView(Button):
    pass
class EditText(_View):
    def __init__(self, activity, text, parent=None, **kwargs):
        super().__init__(activity, parent, text=text, **kwargs)
        self.text = text
    def gettext(self):
        return self.text
class Checkbox(Button):
    def __init__(self, activity, text, parent=None, checked=False):
        super().__init__(activity, text, parent)
        self.kwargs["checked"] = checked
class Switch(Checkbox):
    pass
class ProgressBar(_View):
    pass
class Spinner(_View):
    pass
class ToggleButton(_View):
    pass
class ImageView(_View):
    pass


class Connection:
    def __init__(self):
        self.queue = deque()
        self.closed = False
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        self.closed = True
    def checkevent(self):
        return self.queue.popleft() if self.queue else None


class Activity:
    def __init__(self, connection, **kwargs):
        self.connection = connection
        self.views = {}
        self.options = kwargs
        self.finished = False
    def finish(self):
        self.finished = True


class Event:
    click = "click"
    text = "text"
    back = "back"
    destroy = "destroy"


def event(name, native, **data):
    return SimpleNamespace(type=name, value={"id": native.id, **data})
