from sqlalchemy import UUID, Column, DateTime, Enum, ForeignKey, Table, UniqueConstraint
from sqlalchemy.orm import composite

from app.core.common.entities.organization_membership import OrganizationMembership, OrganizationRole
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.outbound.persistence_sqla.mappings.user import get_strenum_values
from app.outbound.persistence_sqla.registry import mapper_registry

organization_memberships_table = Table(
    "organization_memberships",
    mapper_registry.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "organization_id",
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # CASCADE like api_keys.user_id: a deleted user's memberships go with them.
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    # Stored the same way as users.role: a non-native enum holding the
    # StrEnum's VALUES ("owner"/"admin"/"member"), not its member names.
    Column(
        "role",
        Enum(
            OrganizationRole,
            name="organization_role",
            native_enum=False,
            validate_strings=True,
            values_callable=get_strenum_values,
        ),
        nullable=False,
    ),
    # No ondelete: the inviter's own deletion must not wipe out memberships
    # they happened to send.
    Column("invited_by_user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # NULL = a still-pending invitation; set = an active membership.
    Column("accepted_at", DateTime(timezone=True), nullable=True),
    # Set on a pending invitation (now + ORGANIZATION_INVITATION_TTL_DAYS);
    # NULL on an accepted membership, which never expires. The entity
    # enforces that exactly one of accepted_at/expires_at is set.
    Column("expires_at", DateTime(timezone=True), nullable=True),
    # One row per (organization, user), pending or accepted -- inviting the
    # same user twice must fail, or MembershipChecker would have two roles
    # to choose between. Mirrors apptension/saas-boilerplate's
    # unique_non_null_user_and_tenant constraint.
    UniqueConstraint("organization_id", "user_id", name="uq_organization_memberships_organization_id_user_id"),
)


def map_organization_memberships_table() -> None:
    mapper_registry.map_imperatively(
        OrganizationMembership,
        organization_memberships_table,
        properties={
            "id_": organization_memberships_table.c.id,
            "organization_id": organization_memberships_table.c.organization_id,
            "user_id": organization_memberships_table.c.user_id,
            "role": organization_memberships_table.c.role,
            "invited_by_user_id": organization_memberships_table.c.invited_by_user_id,
            "_created_at": composite(UtcDatetime, organization_memberships_table.c.created_at),
            # A plain column, NOT composite(UtcDatetime, ...) -- accepted_at is
            # nullable, and OrganizationMembership's own accepted_at property
            # already does the UtcDatetime wrap/unwrap and the None-check.
            # Same fix as ApiKey's revoked_at/last_used_at; see
            # docs/plans/8-public-api-key-auth.md's Step 3 notes.
            "_accepted_at": organization_memberships_table.c.accepted_at,
            # Nullable too, so the same plain-column approach as _accepted_at;
            # the entity's expires_at property does the UtcDatetime wrapping.
            "_expires_at": organization_memberships_table.c.expires_at,
        },
        column_prefix="__",
    )
