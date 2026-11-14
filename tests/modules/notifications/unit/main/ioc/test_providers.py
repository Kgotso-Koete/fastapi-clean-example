from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.exceptions import NoFactoryError

from app.base.core.common.ports.email_sender import EmailSender
from app.modules.notifications.core.common.events.handlers.send_organization_invitation_email import (
    SendOrganizationInvitationEmail,
)
from app.modules.notifications.core.common.events.handlers.send_welcome_email import SendWelcomeEmail
from app.modules.notifications.main.ioc.providers import (
    NotificationsCliProvider,
    NotificationsWebProvider,
    NotificationsWorkerProvider,
)

# Notifications' own providers, one per entrypoint that uses its handlers
# (docs/plans/16-modular-monolith.md, Decision 13: a unit brings its providers
# per entrypoint). Each test builds a tiny real dishka container from one of
# them, so what is checked is what dishka actually builds.


# Stands in for the entrypoint's own EmailSender binding (shared's
# SharedEmailProvider in the real app): Notifications needs an
# EmailSender but never binds one itself.
class FakeEmailSenderProvider(Provider):
    @provide(scope=Scope.APP)
    def provide_email_sender(self) -> EmailSender:
        return AsyncMock()


@pytest.mark.parametrize(
    ("notifications_provider", "handler_types"),
    [
        pytest.param(NotificationsWebProvider, (SendWelcomeEmail, SendOrganizationInvitationEmail), id="web"),
        pytest.param(NotificationsCliProvider, (SendWelcomeEmail,), id="cli"),
        pytest.param(NotificationsWorkerProvider, (SendWelcomeEmail, SendOrganizationInvitationEmail), id="worker"),
    ],
)
async def test_each_entrypoints_provider_builds_its_handlers(
    notifications_provider: type[Provider],
    handler_types: tuple[type[object], ...],
) -> None:
    # Exactly the handlers each entrypoint's container binds today
    # (tests/base/characterisation/main/test_container_bindings.py, BINDINGS),
    # built per request like every other handler.
    container = make_async_container(notifications_provider(), FakeEmailSenderProvider())
    async with container() as request_container:
        for handler_type in handler_types:
            assert isinstance(await request_container.get(handler_type), handler_type)
    await container.close()


async def test_the_cli_provider_has_no_invitation_email() -> None:
    # The CLI has no organization commands, so today's CLI container has no
    # invitation email (test_container_bindings.py, ABSENT); Notifications
    # keeps it that way.
    container = make_async_container(NotificationsCliProvider(), FakeEmailSenderProvider())
    async with container() as request_container:
        with pytest.raises(NoFactoryError):
            await request_container.get(SendOrganizationInvitationEmail)
    await container.close()
