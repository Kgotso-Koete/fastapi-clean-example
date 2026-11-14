from app.base.core.common.authorization.base import Permission, PermissionContext
from app.base.core.common.authorization.exceptions import AuthorizationError


def authorize[PC: PermissionContext](
    permission: Permission[PC],
    *,
    context: PC,
) -> None:
    if not permission.is_satisfied_by(context):
        raise AuthorizationError
