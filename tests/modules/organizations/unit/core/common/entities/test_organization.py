from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.base.core.common.entities.types_ import UserId
from app.base.core.common.value_objects.description import Description
from app.base.core.common.value_objects.utc_datetime import UtcDatetime
from app.modules.organizations.core.common.entities.organization import Organization, OrganizationId
from app.modules.organizations.core.common.value_objects.organization_name import OrganizationName

# The user story these tests prove (docs/plans/user-stories/9-organizations-user-stories.md),
# counted per story by tests/conftest.py.
pytestmark = pytest.mark.story("ORG.D1.US.J1.A1")

_DEFAULT_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _create_organization(
    *,
    name: str = "Test Org",  # raw string in, wrapped in OrganizationName below
    description: str = "A test organization.",  # wrapped in Description below
    created_by_user_id: UserId | None = None,
    created_at: datetime = _DEFAULT_CREATED_AT,
) -> Organization:
    # A small, self-contained factory (not a shared tests/.../factories.py)
    # since only this file needs it -- mirrors test_api_key.py's own
    # _create_api_key helper.
    return Organization(
        id_=OrganizationId(uuid4()),
        name=OrganizationName(name),
        description=Description(description),
        created_by_user_id=created_by_user_id or UserId(uuid4()),
        created_at=UtcDatetime(created_at),
    )


def test_organization_retains_the_fields_it_was_constructed_with() -> None:
    # Organization has no behavior of its own beyond what Entity already
    # provides (identity, equality-by-id) -- this is the one test needed to
    # confirm it's a faithful, unremarkable data holder for its fields.
    creator_id = UserId(uuid4())
    created_at = UtcDatetime(_DEFAULT_CREATED_AT)

    sut = _create_organization(
        name="Avengers",
        description="Earth's mightiest heroes.",
        created_by_user_id=creator_id,
        created_at=_DEFAULT_CREATED_AT,
    )

    # The entity holds the validated value objects, not raw strs -- the same
    # way User holds a Username rather than a plain string.
    assert sut.name == OrganizationName("Avengers")
    # Mandatory: every organization explains itself, so it's a Description,
    # never None.
    assert sut.description == Description("Earth's mightiest heroes.")
    assert sut.created_by_user_id == creator_id
    assert sut.created_at == created_at
