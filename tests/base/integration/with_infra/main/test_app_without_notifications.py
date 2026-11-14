"""
The feature-delete test (docs/plans/16-modular-monolith.md, user story 4 and finding 5):
the web app built with no modules registered -- Notifications removed -- still starts and
still signs a user up, and sends no welcome email, now or later. Zero import violations
don't prove a module can be removed (Shopify's lesson); running the app without it does.
"""

from collections.abc import Sequence

import httpx2
import pytest
from dishka import Provider, Scope
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.base.core.common.entities.user import User
from app.base.core.common.ports.email_sender import EmailSender
from app.base.main.modules import Unit
from app.base.outbound.persistence_sqla.mappings.outbox_message import event_outbox_table
from app.base.outbound.persistence_sqla.mappings.user import users_table
from app.shared.main import module as shared
from tests.base.integration.with_infra.account.constants import SIGN_UP_ENDPOINT
from tests.base.integration.with_infra.factories import (
    create_raw_email,
    create_raw_password,
    create_raw_phone_number,
    create_raw_username,
)
from tests.base.integration.with_infra.spy_email_sender import SpyEmailSender


@pytest.fixture
def it_units() -> Sequence[Unit]:
    # No modules registered, only shared, which base needs: today, that is the app
    # with Notifications removed.
    return (shared,)


@pytest.fixture
def it_spy_email_sender() -> SpyEmailSender:
    return SpyEmailSender()


@pytest.fixture
def it_di_overrides(it_spy_email_sender: SpyEmailSender) -> Sequence[Provider]:
    # shared binds EmailSender (base's error alerting needs one); the spy replaces it, and records
    # anything sent, so the test can prove nothing was.
    provider = Provider()
    provider.provide(lambda: it_spy_email_sender, provides=EmailSender, scope=Scope.APP)
    return (provider,)


async def test_signs_up_and_sends_no_email(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_spy_email_sender: SpyEmailSender,
) -> None:
    username = create_raw_username()
    payload = {
        "username": username,
        "email": create_raw_email(),
        "phone_number": create_raw_phone_number(),
        "password": create_raw_password(),
    }

    r = await it_client.post(SIGN_UP_ENDPOINT, json=payload)

    # The app started (it_client ran its lifespan) and sign-up succeeded, user stored.
    assert r.status_code == 200
    user = await it_session.scalar(select(User).where(users_table.c.username == username))
    assert isinstance(user, User)
    # Nothing subscribes to UserRegisteredEvent, so the dispatcher stages no outbox
    # row (no email later) and runs no handler (no email now).
    assert await it_session.scalar(select(func.count()).select_from(event_outbox_table)) == 0
    assert len(it_spy_email_sender.sent) == 0
