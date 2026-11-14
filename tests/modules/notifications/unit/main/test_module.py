import re

import pytest

from app.base.main.modules import MissingUnitError, check_needs
from app.modules.notifications.main import module as notifications
from app.modules.organizations.main import module as organizations


def test_notifications_refuses_to_start_without_organizations() -> None:
    # Notifications handles Organizations' invitation event (its WEB_SUBSCRIPTIONS),
    # so it needs Organizations registered. Registering Notifications alone must
    # stop the app at start-up and name what's missing (plan 16, "The registry"
    # and user story 4). The import rules can't catch this: a deregistered
    # Organizations is still importable, so this declaration is the only guard.
    with pytest.raises(
        MissingUnitError,
        match=re.escape("Unit 'notifications' needs unit 'organizations', which is not registered."),
    ):
        check_needs([notifications])


def test_notifications_refuses_to_start_without_shared() -> None:
    # Notifications' handlers send email through base's EmailSender port, which
    # shared binds (plan 16, Step 5). Notifications imports nothing from shared,
    # so the import rules can't see this need; this declaration is the only
    # guard. Registering Notifications with Organizations but without shared must
    # stop the app at start-up and name Notifications' own need.
    with pytest.raises(
        MissingUnitError,
        match=re.escape("Unit 'notifications' needs unit 'shared', which is not registered."),
    ):
        check_needs([organizations, notifications])
