"""
Organizations' settings (docs/plans/16-modular-monolith.md, Decision 14): the
values this module reads at run time. Loading them from the environment stays
the composition root's job, in src/app/base/main/config/loader.py with every
other setting's; this file only says what they are.
"""

from pydantic import BaseModel, Field


class OrganizationSettings(BaseModel):
    # How many days a pending organization invitation stays acceptable;
    # InviteOrganizationMember sets expires_at = now + this. ge=1 because a
    # zero-day invitation would already be expired the moment it's sent.
    # Defaults to 7 so no deployment ever gets invitations that never expire.
    INVITATION_TTL_DAYS: int = Field(ge=1, default=7)
