from pydantic.experimental.missing_sentinel import MISSING

from app.core.common.sentinels import OMITTED, Omitted

# Ported unchanged from the original author's "Autumn 2026 Updates & Fixes"
# (docs/plans/15-upstream-autumn-2026.md, Step 2); only these comments are
# added.
#
# A sentinel is a special, one-of-a-kind marker value that stands for a
# situation rather than for data, recognised by identity (`is`), so it can
# never be mistaken for something a user sent. Here the situation is "this
# field was left out of the request", which a PATCH must treat differently
# from a field sent as `null` (clear it) or with a value (change it); see
# app.core.common.sentinels for the full three-state picture.
#
# There are two such sentinels, one per layer. Pydantic, which reads the JSON
# body, has its own: MISSING. Core has OMITTED. This function is the bridge:
# a PATCH request schema gives a left-out field MISSING, and this turns it
# into OMITTED before the value reaches a command, so core never depends on
# pydantic. It lives in inbound because only the web layer is allowed to know
# about pydantic.


def omit_if_missing[T](value: T) -> T | Omitted:
    # `None` (an explicit JSON null, meaning "clear it") is not MISSING, so it
    # passes through unchanged, as does any real value.
    return OMITTED if value is MISSING else value
