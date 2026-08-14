from typing import Any

from starlette.requests import Request

from app.inbound.http.errors.alerting import AlertCooldown, RequestUserContext, build_error_alert_email

ANONYMOUS = RequestUserContext(status="anonymous")
UNKNOWN = RequestUserContext(status="unknown")


class _FakeClock:
    """Deterministic, manually-advanced stand-in for time.monotonic."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _make_request(
    *,
    method: str = "GET",
    path: str = "/v1/users",
    client_host: str | None = "127.0.0.1",
) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "headers": [],
    }
    if client_host is not None:
        scope["client"] = (client_host, 12345)
    return Request(scope)


def test_cooldown_allows_first_alert_for_a_new_exception_type() -> None:
    sut = AlertCooldown(cooldown_s=60.0, clock=_FakeClock())

    assert sut.should_send("ValueError") is True


def test_cooldown_suppresses_repeat_alert_within_window() -> None:
    clock = _FakeClock()
    sut = AlertCooldown(cooldown_s=60.0, clock=clock)
    assert sut.should_send("ValueError") is True

    clock.advance(30.0)

    assert sut.should_send("ValueError") is False


def test_cooldown_allows_alert_again_after_window_elapses() -> None:
    clock = _FakeClock()
    sut = AlertCooldown(cooldown_s=60.0, clock=clock)
    assert sut.should_send("ValueError") is True

    clock.advance(60.0)

    assert sut.should_send("ValueError") is True


def test_cooldown_tracks_each_exception_type_independently() -> None:
    clock = _FakeClock()
    sut = AlertCooldown(cooldown_s=60.0, clock=clock)
    assert sut.should_send("ValueError") is True

    # A different exception type is unaffected by ValueError's cooldown.
    assert sut.should_send("KeyError") is True


def test_build_error_alert_email_includes_exception_type_and_path() -> None:
    request = _make_request(method="POST", path="/v1/users")

    subject, html_body = build_error_alert_email(ValueError("boom"), request, ANONYMOUS)

    assert "ValueError" in subject
    assert "POST" in subject
    assert "/v1/users" in subject
    assert "ValueError" in html_body
    assert "boom" in html_body
    assert "/v1/users" in html_body


def test_build_error_alert_email_escapes_untrusted_content() -> None:
    request = _make_request(path="/v1/<script>alert(1)</script>")

    _subject, html_body = build_error_alert_email(ValueError("<b>bold</b>"), request, ANONYMOUS)

    assert "<script>" not in html_body
    assert "<b>bold</b>" not in html_body


def test_build_error_alert_email_handles_missing_client() -> None:
    request = _make_request(client_host=None)

    _subject, html_body = build_error_alert_email(RuntimeError("x"), request, ANONYMOUS)

    assert "unknown" in html_body


def test_build_error_alert_email_shows_anonymous_status() -> None:
    request = _make_request()

    _subject, html_body = build_error_alert_email(ValueError("x"), request, ANONYMOUS)

    assert "anonymous" in html_body


def test_build_error_alert_email_shows_unknown_status_when_session_unresolvable() -> None:
    request = _make_request()

    _subject, html_body = build_error_alert_email(ValueError("x"), request, UNKNOWN)

    assert "unknown" in html_body


def test_build_error_alert_email_shows_full_identity_when_authenticated() -> None:
    request = _make_request()
    user_context = RequestUserContext(
        status="authenticated",
        user_id="11111111-1111-1111-1111-111111111111",
        username="kgotso",
        email="kgotso@example.com",
        phone_number="27831234567",
    )

    _subject, html_body = build_error_alert_email(ValueError("x"), request, user_context)

    assert "kgotso" in html_body
    assert "11111111-1111-1111-1111-111111111111" in html_body
    assert "kgotso@example.com" in html_body
    assert "27831234567" in html_body


def test_build_error_alert_email_escapes_untrusted_identity_fields() -> None:
    request = _make_request()
    user_context = RequestUserContext(
        status="authenticated",
        user_id="1",
        username="<script>alert(1)</script>",
        email="a@b.com",
        phone_number="27831234567",
    )

    _subject, html_body = build_error_alert_email(ValueError("x"), request, user_context)

    assert "<script>" not in html_body


def test_request_user_context_as_log_fields_omits_unset_pii_for_anonymous() -> None:
    fields = ANONYMOUS.as_log_fields()

    assert fields == {"user_status": "anonymous"}


def test_request_user_context_as_log_fields_includes_pii_when_authenticated() -> None:
    user_context = RequestUserContext(
        status="authenticated",
        user_id="1",
        username="kgotso",
        email="kgotso@example.com",
        phone_number="27831234567",
    )

    fields = user_context.as_log_fields()

    assert fields == {
        "user_status": "authenticated",
        "user_id": "1",
        "username": "kgotso",
        "user_email": "kgotso@example.com",
        "user_phone_number": "27831234567",
    }
