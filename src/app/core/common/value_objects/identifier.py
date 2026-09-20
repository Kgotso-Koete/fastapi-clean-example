from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.email import Email
from app.core.common.value_objects.username import Username


def resolve_username_or_email(raw: str) -> Email | Username:
    try:
        return Email(raw)
    except BusinessTypeError:
        return Username(raw)
