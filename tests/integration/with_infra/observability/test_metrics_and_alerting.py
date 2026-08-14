from collections.abc import AsyncIterator, Sequence

import asgi_lifespan
import httpx2
import pytest
from dishka import Provider, Scope
from fastapi import FastAPI

from app.core.common.ports.email_sender import EmailSender
from app.main.config.settings import AlertSettings, AppSettings
from app.main.run import make_app
from tests.integration.with_infra.account.constants import SIGN_UP_ENDPOINT
from tests.integration.with_infra.authentication import authenticate
from tests.integration.with_infra.factories import (
    create_raw_email,
    create_raw_password,
    create_raw_phone_number,
    create_raw_username,
)
from tests.integration.with_infra.spy_email_sender import SpyEmailSender

UNHANDLED_ERROR_ENDPOINT = "/__test_unhandled_error__"
LIFESPAN_MANAGER_STARTUP_TIMEOUT_S = 30


def _counter_value(metrics_text: str, exception_type: str) -> float:
    """
    Reads app_unhandled_exceptions_total{exception_type="..."} from a /metrics
    response, or 0.0 if that label combination hasn't been recorded yet.

    Needed because prometheus_client.Counter registers into the process-wide
    default registry: it's a singleton for the life of the test process, so
    two tests in the same run share the same counts. Real production code
    wants exactly that (one cumulative total per process) - it's only tests
    that need to work around it, by comparing before/after deltas instead of
    absolute values.
    """
    prefix = f'app_unhandled_exceptions_total{{exception_type="{exception_type}"}} '
    for line in metrics_text.splitlines():
        if line.startswith(prefix):
            return float(line.removeprefix(prefix))
    return 0.0


@pytest.fixture
def it_spy_email_sender() -> SpyEmailSender:
    return SpyEmailSender()


@pytest.fixture
def it_di_overrides(it_spy_email_sender: SpyEmailSender) -> Sequence[Provider]:
    provider = Provider()
    provider.provide(lambda: it_spy_email_sender, provides=EmailSender, scope=Scope.APP)
    return (provider,)


@pytest.fixture
def it_fastapi_app(it_di_overrides: Sequence[Provider]) -> FastAPI:
    """
    Overrides the shared it_fastapi_app fixture to enable alerting (off by
    default) with a long cooldown, and adds a probe route that always raises
    -  a stand-in for "some genuine, unanticipated bug", the same shape of
    failure the global exception handler exists to catch.
    """
    app = make_app(
        *it_di_overrides,
        app_settings=AppSettings(DEBUG_MODE=False),
        alert_settings=AlertSettings(
            ENABLED=True,
            TO_EMAIL="oncall@example.com",
            TO_NAME="Test On-call",
            COOLDOWN_S=9999.0,
        ),
    )

    @app.get(UNHANDLED_ERROR_ENDPOINT, include_in_schema=False)
    async def _raise_unhandled_error() -> None:
        raise ValueError("simulated unhandled error")

    return app


@pytest.fixture
async def it_client(it_fastapi_app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    """Overrides the shared it_client fixture.

    ``GlobalExceptionMiddleware`` catches all unhandled exceptions and returns
    a ``JSONResponse`` before they can propagate to the ASGI transport, so
    ``raise_app_exceptions`` can stay at its default (``True``).
    """
    async with (
        asgi_lifespan.LifespanManager(
            it_fastapi_app,
            startup_timeout=LIFESPAN_MANAGER_STARTUP_TIMEOUT_S,
        ),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=it_fastapi_app),
            base_url="http://test",
        ) as client,
    ):
        yield client


async def test_metrics_endpoint_is_exposed_in_prometheus_format(it_client: httpx2.AsyncClient) -> None:
    r = await it_client.get("/metrics")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


async def test_unhandled_exception_returns_generic_500_without_leaking_internals(
    it_client: httpx2.AsyncClient,
) -> None:
    r = await it_client.get(UNHANDLED_ERROR_ENDPOINT)

    assert r.status_code == 500
    assert "Traceback" not in r.text
    assert "ValueError" not in r.text
    assert "simulated unhandled error" not in r.text


async def test_unhandled_exception_increments_the_metric_labeled_by_exception_type(
    it_client: httpx2.AsyncClient,
) -> None:
    before = _counter_value((await it_client.get("/metrics")).text, "ValueError")

    await it_client.get(UNHANDLED_ERROR_ENDPOINT)

    after = _counter_value((await it_client.get("/metrics")).text, "ValueError")
    assert after == before + 1.0


async def test_unhandled_exception_sends_a_critical_error_alert_email(
    it_client: httpx2.AsyncClient,
    it_spy_email_sender: SpyEmailSender,
) -> None:
    await it_client.get(UNHANDLED_ERROR_ENDPOINT)

    assert len(it_spy_email_sender.sent) == 1
    sent = it_spy_email_sender.sent[0]
    assert sent["to_email"] == "oncall@example.com"
    assert "ValueError" in sent["subject"]
    assert UNHANDLED_ERROR_ENDPOINT in sent["subject"]


async def test_unhandled_exception_from_an_anonymous_request_shows_anonymous_in_the_alert(
    it_client: httpx2.AsyncClient,
    it_spy_email_sender: SpyEmailSender,
) -> None:
    """it_client has no session cookie unless a test explicitly logs in."""
    await it_client.get(UNHANDLED_ERROR_ENDPOINT)

    assert "anonymous" in it_spy_email_sender.sent[0]["html_body"]


async def test_unhandled_exception_from_a_logged_in_user_shows_their_identity_in_the_alert(
    it_client: httpx2.AsyncClient,
    it_spy_email_sender: SpyEmailSender,
) -> None:
    username = create_raw_username()
    password = create_raw_password()
    email = create_raw_email()
    phone_number = create_raw_phone_number()
    r = await it_client.post(
        SIGN_UP_ENDPOINT,
        json={"username": username, "email": email, "phone_number": phone_number, "password": password},
    )
    assert r.status_code == 200
    await authenticate(it_client, username, password)

    await it_client.get(UNHANDLED_ERROR_ENDPOINT)

    # Sign-up itself may also send its own (unrelated) welcome email through
    # this same spy, so filter to the alert recipient specifically rather
    # than asserting on the spy's full history.
    alert_emails = [sent for sent in it_spy_email_sender.sent if sent["to_email"] == "oncall@example.com"]
    assert len(alert_emails) == 1
    html_body = alert_emails[0]["html_body"]
    assert username in html_body
    assert email in html_body
    assert phone_number in html_body
    assert "anonymous" not in html_body


async def test_repeated_same_type_errors_are_rate_limited_to_one_alert_email(
    it_client: httpx2.AsyncClient,
    it_spy_email_sender: SpyEmailSender,
) -> None:
    await it_client.get(UNHANDLED_ERROR_ENDPOINT)
    await it_client.get(UNHANDLED_ERROR_ENDPOINT)
    await it_client.get(UNHANDLED_ERROR_ENDPOINT)

    # The fixture's cooldown is 9999s, so only the first of these three sends.
    assert len(it_spy_email_sender.sent) == 1


async def test_business_validation_error_never_triggers_an_alert_or_the_counter(
    it_client: httpx2.AsyncClient,
    it_spy_email_sender: SpyEmailSender,
) -> None:
    before = _counter_value((await it_client.get("/metrics")).text, "ValueError")

    r = await it_client.post(SIGN_UP_ENDPOINT, json={})  # missing required fields -> 422, never a 500

    assert r.status_code < 500
    assert it_spy_email_sender.sent == []

    after = _counter_value((await it_client.get("/metrics")).text, "ValueError")
    assert after == before
