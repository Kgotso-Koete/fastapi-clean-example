from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

import click

from app.core.common.exceptions import BaseError
from app.main.cli.identity_provider import CliIdentityError

P = ParamSpec("P")
R = TypeVar("R")

# Mirrors the HTTP layer's error_map (src/app/inbound/http/errors/rules.py
# and each src/app/inbound/http/users/*.py's own error_map): every one of
# this project's known domain/infrastructure exceptions becomes a stderr
# message + exit(1), instead of a raw traceback. CliIdentityError isn't a
# BaseError (it's CLI-only, defined in main/cli/identity_provider.py rather
# than core/common/exceptions.py), so it's listed alongside it explicitly.
_KNOWN_ERRORS: tuple[type[Exception], ...] = (CliIdentityError, BaseError)


def handle_errors[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Wrap a Click command callback so known exceptions exit(1) with a message instead of a traceback."""

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except _KNOWN_ERRORS as e:
            click.echo(str(e), err=True)
            raise SystemExit(1) from e

    return wrapper
