from uuid_utils import compat as uuid_utils

from app.core.common.entities.api_key import ApiKeyId


def create_api_key_id() -> ApiKeyId:
    return ApiKeyId(uuid_utils.uuid7())
