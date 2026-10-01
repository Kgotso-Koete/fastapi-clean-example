from uuid_utils import compat as uuid_utils

from app.core.common.entities.organization_membership import OrganizationMembershipId


def create_organization_membership_id() -> OrganizationMembershipId:
    return OrganizationMembershipId(uuid_utils.uuid7())
