from datetime import UTC, datetime
from uuid import uuid4

from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.types_ import UserId
from app.core.common.value_objects.organization_name import OrganizationName
from app.core.common.value_objects.utc_datetime import UtcDatetime

_DEFAULT_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _create_organization(
    *,
    name: str = "Test Org",  # raw string in, wrapped in OrganizationName below
    created_by_user_id: UserId | None = None,
    created_at: datetime = _DEFAULT_CREATED_AT,
) -> Organization:
    # A small, self-contained factory (not a shared tests/.../factories.py)
    # since only this file needs it -- mirrors test_api_key.py's own
    # _create_api_key helper.
    return Organization(
        id_=OrganizationId(uuid4()),
        name=OrganizationName(name),
        created_by_user_id=created_by_user_id or UserId(uuid4()),
        created_at=UtcDatetime(created_at),
    )


def test_organization_retains_the_fields_it_was_constructed_with() -> None:
    # Organization has no behavior of its own beyond what Entity already
    # provides (identity, equality-by-id) -- this is the one test needed to
    # confirm it's a faithful, unremarkable data holder for its fields.
    creator_id = UserId(uuid4())
    created_at = UtcDatetime(_DEFAULT_CREATED_AT)

    sut = _create_organization(name="Avengers", created_by_user_id=creator_id, created_at=_DEFAULT_CREATED_AT)

    # The entity holds the validated value object, not a raw str -- the same
    # way User holds a Username rather than a plain string.
    assert sut.name == OrganizationName("Avengers")
    assert sut.created_by_user_id == creator_id
    assert sut.created_at == created_at
