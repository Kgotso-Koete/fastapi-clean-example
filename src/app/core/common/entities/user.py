from app.core.common.entities.base import Entity
from app.core.common.entities.types_ import UserId, UserPasswordHash, UserRole
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.email import Email
from app.core.common.value_objects.phone_number import PhoneNumber
from app.core.common.value_objects.username import Username
from app.core.common.value_objects.utc_datetime import UtcDatetime


class User(Entity[UserId]):
    def __init__(
        self,
        *,
        id_: UserId,
        username: Username,
        email: Email,
        phone_number: PhoneNumber,
        password_hash: UserPasswordHash,
        role: UserRole,
        is_active: bool,
        created_at: UtcDatetime,
        updated_at: UtcDatetime,
        description: Description | None = None,
    ) -> None:
        super().__init__(id_=id_)
        self.username = username
        self.email = email
        self.phone_number = phone_number
        self.password_hash = password_hash
        self.role = role
        self.is_active = is_active
        self._created_at = created_at
        self.updated_at = updated_at
        # Optional, so None by default (docs/plans/10-profile-editing.md,
        # decision 1); None means "no description". A plain attribute, like
        # Organization.description: the users mapping handles NULL with a
        # nullable composite (mappings/composite/description.py), so the
        # entity needs no getter or setter.
        self.description = description

    @property
    def created_at(self) -> UtcDatetime:
        return self._created_at
