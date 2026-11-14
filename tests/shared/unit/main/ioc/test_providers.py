import pytest
from dishka import Provider, Scope, make_async_container, provide

from app.base.core.common.ports.email_sender import EmailSender
from app.shared.main.config.settings import EmailSettings
from app.shared.main.ioc.providers import SharedEmailProvider
from app.shared.outbound.adapters.console_email_sender import ConsoleEmailSender
from app.shared.outbound.adapters.smtp_email_sender import SmtpEmailSender

# shared's dishka provider (docs/plans/16-modular-monolith.md, Step 5 and "What goes
# where"): one class, listed for the web app, the CLI and the worker, that binds
# base's EmailSender port to an email adapter. Each test builds a tiny real dishka
# container from it, so what is checked is what dishka actually builds.


class _EmailSettingsProvider(Provider):
    """Stands in for the entrypoint, which passes EmailSettings into its container."""

    scope = Scope.APP

    def __init__(self, settings: EmailSettings) -> None:
        super().__init__()
        self._settings = settings

    @provide
    def provide_email_settings(self) -> EmailSettings:
        return self._settings


@pytest.mark.parametrize(
    ("use_console", "adapter_type"),
    [
        pytest.param(True, ConsoleEmailSender, id="use_console_True"),
        pytest.param(False, SmtpEmailSender, id="use_console_False"),
    ],
)
async def test_the_email_sender_follows_use_console(use_console: bool, adapter_type: type[EmailSender]) -> None:
    # The same choice the characterisation test pins at each entrypoint
    # (tests/base/characterisation/main/test_container_bindings.py,
    # test_the_email_sender_follows_use_console): the console adapter writes emails
    # to the log for development, and SMTP sends them for real.
    container = make_async_container(
        SharedEmailProvider(), _EmailSettingsProvider(EmailSettings(USE_CONSOLE=use_console))
    )
    try:
        email_sender = await container.get(EmailSender)
    finally:
        await container.close()

    assert isinstance(email_sender, adapter_type)
