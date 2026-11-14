from typing import cast
from unittest.mock import create_autospec

import pytest

from app.base.core.common.ports.password_hasher import PasswordHasher
from tests.base.unit.core.common.services.mock_types import PasswordHasherMock


@pytest.fixture
def password_hasher() -> PasswordHasherMock:
    return cast(PasswordHasherMock, create_autospec(PasswordHasher, instance=True))
