from pydantic.experimental.missing_sentinel import MISSING

from app.core.common.sentinels import OMITTED
from app.inbound.missing import omit_if_missing

# The web-layer half of the "omitted" sentinel
# (docs/plans/15-upstream-autumn-2026.md, Step 2), ported from the original
# author's Autumn 2026 update. A sentinel is a special, one-of-a-kind marker
# value that stands for a situation rather than for data (here: "this field
# was left out of the request"); pydantic and core each have their own.
# When FastAPI reads a JSON body, a field the client left out can be given
# pydantic's own MISSING sentinel; omit_if_missing()
# turns that into core's OMITTED, so core never imports anything from pydantic.


def test_translates_missing_into_omitted() -> None:
    sut = omit_if_missing

    result = sut(MISSING)

    # "Left out of the request" becomes core's own "left out" marker.
    assert result is OMITTED


def test_does_not_translate_none_into_omitted() -> None:
    sut = omit_if_missing

    result = sut(None)

    # An explicit `null` means "clear it", so it must stay None, never OMITTED.
    assert result is None
