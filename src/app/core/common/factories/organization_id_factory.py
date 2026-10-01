from uuid_utils import compat as uuid_utils

from app.core.common.entities.organization import OrganizationId


def create_organization_id() -> OrganizationId:
    return OrganizationId(uuid_utils.uuid7())
