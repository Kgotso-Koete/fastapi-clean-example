"""
shared's settings (docs/plans/16-modular-monolith.md, Step 5 and "What goes where"):
the values its email adapters read. Loading them from the environment stays the
composition root's job, in src/app/base/main/config/loader.py with every other
setting's; this file only says what they are.
"""

from pydantic import BaseModel


class EmailSettings(BaseModel):
    USE_CONSOLE: bool = True
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    FROM_EMAIL: str = "noreply@example.com"
    FROM_NAME: str = "Clean Example"
