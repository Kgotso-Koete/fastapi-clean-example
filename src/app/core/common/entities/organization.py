from typing import NewType
from uuid import UUID

from app.core.common.entities.base import Entity
from app.core.common.entities.types_ import UserId
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.organization_name import OrganizationName
from app.core.common.value_objects.utc_datetime import UtcDatetime

# NewType lives alongside its entity, exactly like ApiKeyId lives alongside
# ApiKey in api_key.py.
OrganizationId = NewType("OrganizationId", UUID)


class Organization(Entity[OrganizationId]):
    """
    A tenant boundary. Deliberately minimal -- no billing/plan/slug fields,
    since this is template scaffolding, not a real product; a fork adds
    whatever SaaS-specific fields it actually needs.

    Who belongs to an organization, and with what role, is NOT modelled
    here -- that lives on OrganizationMembership (a separate join entity),
    so neither Organization nor User ever has to know about the other's
    membership rows.
    """

    def __init__(
        self,
        *,
        id_: OrganizationId,
        name: OrganizationName,
        description: Description,
        created_by_user_id: UserId,
        created_at: UtcDatetime,
    ) -> None:
        super().__init__(id_=id_)
        self.name = name
        # Mandatory: every organization explains itself to the people it
        # invites, so there is no "no description" state to model.
        self.description = description
        # A plain foreign reference to Identity's User, the same kind of
        # reference ApiKey.user_id is -- Organizations depends on Identity,
        # never the other way round.
        self.created_by_user_id = created_by_user_id
        self._created_at = created_at

    @property
    def created_at(self) -> UtcDatetime:
        return self._created_at
