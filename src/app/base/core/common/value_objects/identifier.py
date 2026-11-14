from app.base.core.common.exceptions import BusinessTypeError
from app.base.core.common.value_objects.email import Email
from app.base.core.common.value_objects.username import Username


def resolve_username_or_email(raw: str) -> Email | Username:
    try:
        return Email(raw)
    except BusinessTypeError:
        return Username(raw)
