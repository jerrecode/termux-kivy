"""Deliberately restricted KV widget-tree parser; never eval arbitrary Python."""
from __future__ import annotations

import ast
from pathlib import Path

from . import core


class KVError(ValueError):
    pass


class _Factory:
    def __init__(self):
        self._registered = {}

    def register(self, name, cls=None):
        if not isinstance(name, str) or not name.isidentifier():
            raise KVError("invalid factory class name")
        if not isinstance(cls, type) or not issubclass(cls, core.Widget):
            raise KVError("factory class must inherit Widget")
        self._registered[name] = cls

    def get(self, name):
        result = self._registered.get(name, getattr(core, name, None))
        if not isinstance(result, type) or not issubclass(result, core.Widget):
            raise KVError(f"unsupported KV widget: {name}")
        return result


Factory = _Factory()


def _reference(node, app, root, current):
    if isinstance(node, ast.Name):
        if node.id == "app":
            return app
        if node.id == "root":
            return root
        if node.id == "self":
            return current
    if isinstance(node, ast.Attribute) and not node.attr.startswith("_"):
        base = _reference(node.value, app, root, current)
        return getattr(base, node.attr)
    raise KVError("only app/root/self and public attribute paths are supported")


def _property(expr, app, root, current):
    try:
        return ast.literal_eval(expr)
    except (ValueError, SyntaxError):
        try:
            return _reference(ast.parse(expr, mode="eval").body, app, root, current)
        except (SyntaxError, AttributeError) as exc:
            raise KVError(f"unsupported property expression: {expr}") from exc


def _call_event(expr, app, root, current):
    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError as exc:
        raise KVError("invalid KV callback") from exc
    if not isinstance(node, ast.Call) or node.keywords or not isinstance(node.func, ast.Attribute):
        raise KVError("callbacks must be a single public method invocation")
    if node.func.attr.startswith("_"):
        raise KVError("private callbacks are forbidden")
    target = _reference(node.func.value, app, root, current)
    if target is None:
        raise KVError("KV app reference only works inside App.run")
    method = getattr(target, node.func.attr)
    if not callable(method):
        raise KVError("callback target is not callable")
    args = []
    for argument in node.args:
        try:
            args.append(ast.literal_eval(argument))
        except (ValueError, SyntaxError):
            args.append(_reference(argument, app, root, current))
    return method(*args)


class _Builder:
    def load_file(self, path, *, encoding="utf-8"):
        return self.load_string(Path(path).read_text(encoding=encoding))

    def load_string(self, source):
        """Supports one widget tree, indented properties, id, and on_press.

        Does not support KV class templates, directives, Python expressions,
        canvas instructions, mutation of arbitrary globals, or multiple roots.
        """
        from .core import App
        app = App.get_running_app()
        stack = []
        root = None
        ids = {}
        handlers = []
        for lineno, raw in enumerate(source.splitlines(), 1):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            if "\t" in raw[:len(raw) - len(raw.lstrip())]:
                raise KVError(f"line {lineno}: tabs forbidden in indentation")
            indent = len(raw) - len(raw.lstrip(" "))
            entry = raw.strip()
            if ":" not in entry:
                raise KVError(f"line {lineno}: missing colon")
            key, value = [part.strip() for part in entry.split(":", 1)]
            if key.startswith(("#:", "<", "@")):
                raise KVError("KV directives and class rules are unsupported")
            if key and key[0].isupper() and not value:
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                node = Factory.get(key)()
                if stack:
                    stack[-1][1].add_widget(node)
                elif root is None:
                    root = node
                else:
                    raise KVError("multiple KV roots")
                stack.append((indent, node))
                continue
            if not stack or indent <= stack[-1][0]:
                raise KVError(f"line {lineno}: property requires deeper indentation")
            node = stack[-1][1]
            if key == "id":
                if not value.isidentifier() or value.startswith("_") or value in ids:
                    raise KVError(f"line {lineno}: invalid or duplicate id")
                ids[value] = node
            elif key.startswith("on_"):
                if key not in ("on_press", "on_release"):
                    raise KVError(f"line {lineno}: unsupported event {key}")
                handlers.append((node, key, value))
            else:
                if not hasattr(type(node), key):
                    raise KVError(f"line {lineno}: unknown property {key}")
                setattr(node, key, _property(value, app, root, node))
        if root is None:
            raise KVError("empty KV tree")
        root.ids.update(ids)
        for node, event, expr in handlers:
            node.bind(**{event: (
                lambda _sender, *_, expr=expr, node=node, root=root:
                _call_event(expr, App.get_running_app(), root, node)
            )})
        return root


Builder = _Builder()
