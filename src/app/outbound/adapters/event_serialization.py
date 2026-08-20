import importlib
from typing import Any, cast


def dotted_path(cls: type) -> str:
    """
    Builds a string identifying a class by its import path, e.g.
    "app.core.common.events.user_registered:UserRegisteredEvent". This is
    what actually crosses the wire in a Celery message -- HybridEventDispatcher
    sends this string (never the class object itself, which isn't JSON-safe
    and would require the producer to import worker-only code), and the
    worker's task uses import_from_dotted_path() to resolve it back to a
    real class before using it.
    """
    return f"{cls.__module__}:{cls.__qualname__}"


def import_from_dotted_path(path: str) -> type[Any]:
    """Inverse of dotted_path() -- imports and returns the class it names."""
    module_path, _, qualname = path.partition(":")
    obj: Any = importlib.import_module(module_path)
    # qualname can contain dots for nested classes (e.g. "Outer.Inner"), so
    # walk each segment with getattr rather than assuming a single name.
    for attr in qualname.split("."):
        obj = getattr(obj, attr)
    # getattr()'s result is statically `Any` -- cast() tells mypy we know
    # it's actually a class, matching the declared return type.
    return cast(type[Any], obj)
