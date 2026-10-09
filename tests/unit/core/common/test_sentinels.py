from app.core.common.sentinels import OMITTED, apply_when_present

# The "omitted" sentinel (docs/plans/15-upstream-autumn-2026.md, Step 2),
# ported from the original author's Autumn 2026 update. A sentinel is a
# special, one-of-a-kind marker value that stands for a situation rather than
# for data, recognised by identity (`is`); `None` is Python's best-known one.
# A PATCH request needs three states per field, not two:
# - OMITTED: the field was left out, so leave the stored value alone;
# - None: the field was sent as null, so clear it;
# - a value: the field was sent, so validate it and store it.
# apply_when_present() runs a converter (typically a value object's
# constructor) only on a real value, passing the other two states through
# untouched, so a request field can become a domain value in one call.


def test_passes_omitted_through() -> None:
    sut = apply_when_present

    result = sut(str.upper, OMITTED)

    # "Left out" must stay "left out": the converter never sees it.
    assert result is OMITTED


def test_passes_none_through() -> None:
    sut = apply_when_present

    result = sut(str.upper, None)

    # "Sent as null" must stay null, so the caller can clear the field.
    assert result is None


def test_applies_func_when_value_is_present() -> None:
    sut = apply_when_present

    result = sut(str.upper, "value")

    # A real value is converted.
    assert result == "VALUE"
