import logging

import pytest

from app.inbound.http.errors.callbacks import log_info

# log_info() is called for every error a route maps to a status code (400,
# 404, 409, 503, ...). Step 3 of docs/plans/15-upstream-autumn-2026.md makes
# it also name the error's underlying cause, so a 503 says which database
# failure caused it. Only the cause's TYPE is logged, never its message
# (decided by the human maintainer, 2026-10-08): a database error's message
# carries SQL parameters and Postgres DETAIL lines, which can hold an email,
# a phone number or a password hash, and OWASP's Logging Cheat Sheet says not
# to log those (https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html#data-to-exclude).

_LOGGER = "app.inbound.http.errors.callbacks"

# Stands in for personal data inside a cause's message.
_SECRET = "peter.parker@dailybugle.com"


def test_logs_the_error_alone_when_it_has_no_cause(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)

    log_info(ValueError("boom"))

    # Unchanged behaviour: the error's type and message.
    assert [r.getMessage() for r in caplog.records] == ["Handled exception: ValueError — boom"]


def test_names_the_cause_by_type_but_never_logs_its_message(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    err = ValueError("Flush failed.")
    # What `raise ValueError(...) from KeyError(...)` sets.
    err.__cause__ = KeyError(_SECRET)

    log_info(err)

    [message] = [r.getMessage() for r in caplog.records]
    assert message == "Handled exception: ValueError — Flush failed.; caused by: KeyError"
    assert _SECRET not in message
