"""
Notifications' dishka providers, one per entrypoint that runs its handlers
(docs/plans/16-modular-monolith.md, Decision 13: a unit brings its own
providers per entrypoint). Each is named after the entrypoint it serves, like
base's CliProvider and WorkerProvider, and binds only the handlers that
entrypoint needs.

None of them binds EmailSender, which every handler here needs: shared binds
it (src/app/shared/main/ioc/providers.py), at each entrypoint that sends email.
"""

from dishka import Provider, Scope, provide

from app.modules.notifications.core.common.events.handlers.send_organization_invitation_email import (
    SendOrganizationInvitationEmail,
)
from app.modules.notifications.core.common.events.handlers.send_welcome_email import SendWelcomeEmail


class NotificationsWebProvider(Provider):
    """The web app's: it dispatches both events, so it builds both handlers."""

    scope = Scope.REQUEST

    send_welcome_email = provide(SendWelcomeEmail)
    send_organization_invitation_email = provide(SendOrganizationInvitationEmail)


class NotificationsCliProvider(Provider):
    """The CLI's: it creates users but has no organization commands, so only the welcome email."""

    scope = Scope.REQUEST

    send_welcome_email = provide(SendWelcomeEmail)


class NotificationsWorkerProvider(Provider):
    """
    The worker's: it runs every background handler relayed from the outbox,
    so it builds both. Kept separate from the web app's, like base's
    WorkerProvider, so either entrypoint's list can change on its own.
    """

    scope = Scope.REQUEST

    send_welcome_email = provide(SendWelcomeEmail)
    send_organization_invitation_email = provide(SendOrganizationInvitationEmail)
