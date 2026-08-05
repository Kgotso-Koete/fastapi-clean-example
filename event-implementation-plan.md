# Domain Events Infrastructure + Welcome Email on User Registration

> **Implementation Plan v0.4.0**
>
> Add a reusable domain events system to the codebase, with a welcome email on user registration as the first concrete use case. This establishes the event-driven pattern so future events (e.g. `PasswordChangedEvent`, `OrderDispatchedEvent`) become trivial to add.

---

## TDD Methodology: Red-Green-Refactor

We follow **strict Red-Green TDD** throughout this implementation. For every step:

1. **RED** — Write the test first. The test describes the desired behavior. Run it. It **must fail** because the production code doesn't exist yet. This proves the test is actually testing something.
2. **GREEN** — Write the **minimum** production code needed to make the failing test pass. No more, no less.
3. **REFACTOR** — Clean up the code (both test and production) while keeping all tests green. Improve naming, remove duplication, extract constants.

**Execution order for each step below:**
1. Create/update the **test file(s)** listed in Step 6 that correspond to the current step
2. Run `make test` → confirm tests **fail** (RED)
3. Create/update the **production code** file(s) described in the current step
4. Run `make test` → confirm tests **pass** (GREEN)
5. Refactor if needed → run `make test` → confirm tests still pass

This means we always touch test files **before** source files.

---

## Reference Implementations Studied

This plan is informed by studying how two mature DDD/Clean Architecture repos implement domain events:

### python-ddd (pgorecki)

- [AggregateRoot](file:///home/kgotso-koete/Documents/Projects/Work/Training/python-ddd/src/seedwork/domain/entities.py) stores events in a plain `list` field, with `register_event()` and `collect_events()` methods
- [DomainEvent](file:///home/kgotso-koete/Documents/Projects/Work/Training/python-ddd/src/seedwork/domain/events.py) extends a base `Event` → `Message` class (Pydantic models with UUID)
- [Concrete events](file:///home/kgotso-koete/Documents/Projects/Work/Training/python-ddd/src/modules/bidding/domain/events.py) like `BidWasPlaced` are minimal data-only Pydantic models
- Events are recorded inside domain methods: `self.register_event(BidWasPlaced(...))`
- No event bus/dispatcher exists in this repo — events are collected but not dispatched

### clean-architecture (Enforcer/Buczyński)

- [EventMixin](file:///home/kgotso-koete/Documents/Projects/Work/Training/clean-architecture/auctioning_platform/foundation/foundation/events.py) is a mixin class with `_record_event()`, `domain_events` property, and `clear_events()`
- [Auction entity](file:///home/kgotso-koete/Documents/Projects/Work/Training/clean-architecture/auctioning_platform/auctions/auctions/domain/entities/auction.py) inherits `EventMixin` and calls `self._record_event(...)` inside business methods
- [Events](file:///home/kgotso-koete/Documents/Projects/Work/Training/clean-architecture/auctioning_platform/auctions/auctions/domain/events.py) are frozen dataclasses with domain-specific fields
- **Has an actual EventBus**: `InjectorEventBus` dispatches to `Handler[EventType]` and `AsyncHandler[EventType]` via DI
- Supports both sync and async handlers through separate `Handler` and `AsyncHandler` generic types

### What we take from both

| Pattern | Source | Our approach |
|---------|--------|-------------|
| Event list on entity | Both repos | Add `_events` list + `record_event()` + `collect_events()` to base `Entity` |
| Events are frozen dataclasses | Enforcer | Use `@dataclass(frozen=True, slots=True)` matching our existing VO pattern |
| EventBus with handler registry | Enforcer | `EventDispatcher` port in core, concrete dispatchers in outbound |
| Events recorded in domain logic | Both repos | Record `UserRegisteredEvent` inside `UserService.create_user()` |
| Collect → dispatch after commit | Both repos | Use case calls `entity.collect_events()` → `dispatcher.dispatch()` after `commit()` |

---

## Architectural Decisions

### No vendor SDK — SMTP for email (truly vendor-independent)

We do NOT install any email vendor SDK (Brevo, Mailgun, SendGrid, etc.) and we do NOT use vendor-specific REST APIs (which have different payload formats per provider). Instead, we use **SMTP** — the universal email protocol that every provider supports with the same interface.

The adapter uses `aiosmtplib` (async SMTP client) + Python's built-in `email.mime` (message builder):

- **Truly vendor-independent** — SMTP is a universal standard. Switch from Brevo to Mailgun to Amazon SES by changing 4 env vars (`host`, `port`, `username`, `password`). Zero code changes.
- **Full debuggability** — You can see the SMTP conversation, enable debug logging, inspect the raw MIME message
- **Minimal dependencies** — `aiosmtplib` is a single focused package (~600 stars, actively maintained). The `email.mime` message builder is Python standard library (zero extra dependency)
- **No vendor-specific payload builders** — Unlike raw HTTP where each vendor has a different JSON format (Brevo uses `htmlContent`, Mailgun uses `html`, etc.), SMTP uses the same MIME format for everyone

### Framework-independent background dispatch

We do NOT use FastAPI's `BackgroundTasks` (which couples to Starlette). Instead, we use **`asyncio.create_task()`** — pure Python standard library, zero framework dependency. This means:

- The event dispatch system works with any async Python framework (FastAPI, Starlette, aiohttp, etc.)
- If you ever outgrow in-process tasks, you can swap in Celery or a message queue by changing only the adapter — the `EventDispatcher` port in the core layer doesn't care what the adapter uses
- No need for Redis/RabbitMQ infrastructure at this scale

### Publisher-Subscriber model via handler registry

The event system IS a publisher-subscriber (pub/sub) model:

```
Publisher:  user.record_event(UserRegisteredEvent(...))  →  dispatcher.dispatch(events)
                                                                    ↓
Subscribers:  handler_registry = {                                  ↓
    UserRegisteredEvent: [SendWelcomeEmail, AuditLogger],  ← matched by event type
    PasswordChangedEvent: [NotifySecurityTeam],
}
```

**To subscribe new code to an event:**
1. Write a handler class with `async def handle(self, event: T) -> None`
2. Register it in the handler registry (one line in IoC config)

Multiple handlers per event are supported. Handlers are decoupled from each other — `SendWelcomeEmail` doesn't know `AuditLogger` exists. Adding a new subscriber to an existing event requires zero changes to existing code.

---

## Sync vs Background Dispatch — Tradeoffs

### Sync Dispatch (events fire in the same HTTP request)

```
Client → POST /signup → Create User → Commit → Send Email → Return 200
                                                  ↑ blocks response
```

**Pros:**
- Simple to reason about — if the email fails, you know immediately
- Easier to test — no race conditions
- Errors propagate naturally to the caller
- Good for events that MUST complete before the response (e.g. audit logging)

**Cons:**
- The HTTP response is slower (email API call adds ~200-500ms)
- If the email provider is down, the entire signup fails even though the user was created successfully
- Doesn't scale well if you add multiple handlers per event

### Background Dispatch (events fire after the HTTP response)

```
Client → POST /signup → Create User → Commit → Return 200
                                                  ↓ (asyncio.create_task)
                                            Send Email (background)
```

**Pros:**
- Fast HTTP responses — user gets their 200 immediately
- Email failure doesn't break signup
- Scales well with multiple handlers

**Cons:**
- Harder to debug — errors happen after the response is sent
- Need to handle failures separately (logging, retry logic)
- Slightly more complex testing

### Our choice

**Background dispatch for email-type events** using `asyncio.create_task()`. Non-critical side effects like welcome emails should never block the HTTP response or cause signup failures. Critical events (audit logs) can use the sync dispatcher — both are available and swappable via IoC config.

---

## Open Questions

- **Email provider:** Is Brevo confirmed, or do you want to start with Mailgun? (The raw HTTP adapter makes switching trivial, but we need to pick one for the initial implementation so we can set up the API endpoint URL and payload format.)

- **Sender identity:** What email address and name should the welcome email come from? (e.g. `noreply@yourdomain.com` / `Your Company Name`). This must be verified in your email provider account.

- **Email provider account:** Is an account already set up, or do we need to create one?

---

## Proposed Changes

The changes are organized into 6 steps. Each step follows Red-Green TDD: write tests first (RED), then write the production code to make them pass (GREEN).

---

### Step 1: Domain Events Base Infrastructure (Core Layer)

**TDD order:**
1. Write `tests/unit/core/common/events/test_domain_event.py` → RED
2. Write `tests/unit/core/common/entities/test_base_events.py` → RED
3. Create `src/app/core/common/events/domain_event.py` → GREEN
4. Modify `src/app/core/common/entities/base.py` → GREEN

#### [NEW] `src/app/core/common/events/__init__.py`

Empty init file for the new events package.

#### [NEW] `src/app/core/common/events/domain_event.py`

Base `DomainEvent` frozen dataclass — following the Enforcer pattern of frozen dataclasses, adapted to our existing `ValueObject` style:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """
    Base class for domain events.
    Events are immutable records of something that happened in the domain.
    They carry enough data for handlers to act without querying the database.

    Inspired by:
    - Enforcer/clean-architecture: frozen dataclasses with domain fields
    - pgorecki/python-ddd: events recorded on aggregates and collected after commit
    """
    occurred_at: datetime

    def __new__(cls, *_args: Any, **_kwargs: Any) -> Self:
        if cls is DomainEvent:
            raise TypeError("Base DomainEvent cannot be instantiated directly.")
        return object.__new__(cls)
```

#### [NEW] `src/app/core/common/events/user_registered.py`

First concrete event:

```python
from dataclasses import dataclass

from app.core.common.entities.types_ import UserId
from app.core.common.events.domain_event import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class UserRegisteredEvent(DomainEvent):
    """Raised when a new user account is created (via signup or admin creation)."""
    user_id: UserId
    username: str
    email: str
```

#### [MODIFY] `src/app/core/common/entities/base.py`

Add event recording capability to the base `Entity`, inspired by both reference repos:

```diff
+from app.core.common.events.domain_event import DomainEvent

 class Entity[T: Hashable]:
     def __init__(self, *, id_: T) -> None:
         self.id_ = id_
+        object.__setattr__(self, "_events", [])

+    def record_event(self, event: DomainEvent) -> None:
+        """Record a domain event. Events are collected after the use case commits."""
+        self._events.append(event)
+
+    def collect_events(self) -> list[DomainEvent]:
+        """Return and clear all recorded events. Call after transaction commit."""
+        events = self._events.copy()
+        self._events.clear()
+        return events
```

We use `object.__setattr__` for `_events` to work with the existing `__setattr__` override that protects `id_`. The `_events` list is transient in-memory state — never persisted to the database.

---

### Step 2: Event Dispatcher & Handler Ports (Core Layer)

**TDD order:**
1. Write `tests/unit/core/common/events/test_user_registered.py` → RED
2. Create `src/app/core/common/events/user_registered.py` (if not already from step 1) → GREEN
3. Create `src/app/core/common/ports/event_handler.py` → GREEN
4. Create `src/app/core/common/ports/event_dispatcher.py` → GREEN

#### [NEW] `src/app/core/common/ports/event_handler.py`

```python
from abc import abstractmethod
from typing import Protocol

from app.core.common.events.domain_event import DomainEvent


class EventHandler[T: DomainEvent](Protocol):
    """Handles a specific type of domain event."""
    @abstractmethod
    async def handle(self, event: T) -> None: ...
```

#### [NEW] `src/app/core/common/ports/event_dispatcher.py`

```python
from abc import abstractmethod
from typing import Protocol

from app.core.common.events.domain_event import DomainEvent


class EventDispatcher(Protocol):
    """Dispatches domain events to their registered handlers."""
    @abstractmethod
    async def dispatch(self, events: list[DomainEvent]) -> None: ...
```

---

### Step 3: Email Sender Port + Welcome Email Handler (Core Layer)

**TDD order:**
1. Write `tests/unit/core/common/events/handlers/test_send_welcome_email.py` → RED
2. Create `src/app/core/common/ports/email_sender.py` → partial GREEN (port only)
3. Create `src/app/core/common/events/handlers/send_welcome_email.py` → GREEN

#### [NEW] `src/app/core/common/ports/email_sender.py`

```python
from abc import abstractmethod
from typing import Protocol


class EmailSender(Protocol):
    """Port for sending emails. Implementations may use SMTP, console logging, etc."""
    @abstractmethod
    async def send(
        self,
        *,
        to_email: str,
        to_name: str,
        subject: str,
        html_body: str,
    ) -> None: ...
```

#### [NEW] `src/app/core/common/events/handlers/__init__.py`

Empty init file.

#### [NEW] `src/app/core/common/events/handlers/send_welcome_email.py`

```python
import logging

from app.core.common.events.user_registered import UserRegisteredEvent
from app.core.common.ports.email_sender import EmailSender

logger = logging.getLogger(__name__)

WELCOME_EMAIL_SUBJECT = "Welcome to the platform!"

WELCOME_EMAIL_HTML = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <h1 style="color: #2c3e50;">Welcome, {username}!</h1>
  <p>Your account has been successfully created.</p>
  <p>You can now log in and start using the platform.</p>
  <hr style="border: 1px solid #ecf0f1;">
  <p style="color: #95a5a6; font-size: 12px;">
    This is an automated message. Please do not reply.
  </p>
</body>
</html>
"""


class SendWelcomeEmail:
    def __init__(self, email_sender: EmailSender) -> None:
        self._email_sender = email_sender

    async def handle(self, event: UserRegisteredEvent) -> None:
        logger.info("Sending welcome email to %s", event.email)
        await self._email_sender.send(
            to_email=event.email,
            to_name=event.username,
            subject=WELCOME_EMAIL_SUBJECT,
            html_body=WELCOME_EMAIL_HTML.format(username=event.username),
        )
        logger.info("Welcome email sent to %s", event.email)
```

---

### Step 4: Outbound Adapters (Outbound Layer)

**TDD order:**
1. Write `tests/unit/outbound/adapters/test_sync_event_dispatcher.py` → RED
2. Write `tests/unit/outbound/adapters/test_background_event_dispatcher.py` → RED
3. Create all adapter files → GREEN

#### [NEW] `src/app/outbound/adapters/console_email_sender.py`

Development adapter that logs emails to stdout (used in dev/testing):

```python
import logging

logger = logging.getLogger(__name__)


class ConsoleEmailSender:
    """Logs emails to console instead of sending them. For development and testing."""
    async def send(self, *, to_email: str, to_name: str, subject: str, html_body: str) -> None:
        logger.info(
            "EMAIL [to=%s (%s)] [subject=%s]\n%s",
            to_email, to_name, subject, html_body,
        )
```

#### [NEW] `src/app/outbound/adapters/smtp_email_sender.py`

Production email adapter using SMTP via `aiosmtplib` + Python's built-in `email.mime`. Truly vendor-independent — works with any SMTP provider (Brevo, Mailgun, SES, self-hosted) by changing env vars only:

```python
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

logger = logging.getLogger(__name__)


class SmtpEmailSender:
    """
    Sends emails via SMTP. Truly vendor-independent — works with any SMTP provider.
    Switch providers by changing host/port/credentials in env vars. Zero code changes.
    Uses Python's built-in email.mime for message building (no extra dependencies).
    """
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str,
        use_tls: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email
        self._from_name = from_name
        self._use_tls = use_tls

    async def send(self, *, to_email: str, to_name: str, subject: str, html_body: str) -> None:
        message = MIMEMultipart("alternative")
        message["From"] = f"{self._from_name} <{self._from_email}>"
        message["To"] = f"{to_name} <{to_email}>"
        message["Subject"] = subject
        message.attach(MIMEText(html_body, "html"))

        logger.info("Sending email via SMTP to=%s subject=%s host=%s", to_email, subject, self._host)

        await aiosmtplib.send(
            message,
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            use_tls=self._use_tls,
        )

        logger.info("Email sent via SMTP to=%s", to_email)
```

#### [NEW] `src/app/outbound/adapters/sync_event_dispatcher.py`

Dispatches events sequentially within the current request (use for critical events like audit logging):

```python
import logging
from collections.abc import Sequence

from app.core.common.events.domain_event import DomainEvent
from app.core.common.ports.event_handler import EventHandler

logger = logging.getLogger(__name__)


class SyncEventDispatcher:
    """Dispatches events synchronously. The HTTP response waits for all handlers to complete."""
    def __init__(
        self,
        handler_registry: dict[type[DomainEvent], Sequence[EventHandler]],
    ) -> None:
        self._handlers = handler_registry

    async def dispatch(self, events: list[DomainEvent]) -> None:
        for event in events:
            handlers = self._handlers.get(type(event), ())
            for handler in handlers:
                logger.info("Dispatching %s to %s", type(event).__name__, type(handler).__name__)
                await handler.handle(event)
```

#### [NEW] `src/app/outbound/adapters/background_event_dispatcher.py`

Dispatches events as background async tasks using `asyncio.create_task()` — pure Python, no framework dependency:

```python
import asyncio
import logging
from collections.abc import Sequence

from app.core.common.events.domain_event import DomainEvent
from app.core.common.ports.event_handler import EventHandler

logger = logging.getLogger(__name__)


class BackgroundEventDispatcher:
    """
    Dispatches events as background async tasks via asyncio.create_task().
    Framework-independent — works with any async Python framework.
    The HTTP response returns immediately without waiting for handlers.
    """
    def __init__(
        self,
        handler_registry: dict[type[DomainEvent], Sequence[EventHandler]],
    ) -> None:
        self._handlers = handler_registry

    async def dispatch(self, events: list[DomainEvent]) -> None:
        for event in events:
            handlers = self._handlers.get(type(event), ())
            for handler in handlers:
                logger.info(
                    "Scheduling background dispatch: %s -> %s",
                    type(event).__name__, type(handler).__name__,
                )
                asyncio.create_task(
                    self._safe_handle(handler, event),
                    name=f"{type(event).__name__}->{type(handler).__name__}",
                )

    @staticmethod
    async def _safe_handle(handler: EventHandler, event: DomainEvent) -> None:
        """Wraps handler execution with error logging so background failures don't crash."""
        try:
            await handler.handle(event)
        except Exception:
            logger.exception(
                "Background event handler failed: %s handling %s",
                type(handler).__name__, type(event).__name__,
            )
```

---

### Step 5: Wire Events into Use Cases + IoC (Core + Main + Outbound Layers)

**TDD order:**
1. Update `tests/unit/core/common/services/test_user.py` to assert `UserRegisteredEvent` is recorded → RED
2. Modify `src/app/core/common/services/user.py` to record the event → GREEN
3. Update integration tests to verify email dispatch → RED
4. Modify use cases and IoC wiring → GREEN

#### [MODIFY] `src/app/core/common/services/user.py`

After creating the user entity, record the `UserRegisteredEvent` — following both reference repos where events are recorded inside domain logic:

```diff
+from app.core.common.events.user_registered import UserRegisteredEvent

 def create_user(self, ...) -> User:
     if role.is_system:
         raise RoleAssignmentNotPermittedError
     user = User(...)
+    user.record_event(UserRegisteredEvent(
+        occurred_at=now.value,
+        user_id=user_id,
+        username=username.value,
+        email=email.value,
+    ))
     return user
```

#### [MODIFY] `src/app/outbound/auth_ctx/handlers/sign_up.py`

After `transaction_manager.commit()`, collect events from the user entity and dispatch:

```diff
+from app.core.common.ports.event_dispatcher import EventDispatcher

 class SignUp:
     def __init__(self, ..., event_dispatcher: EventDispatcher) -> None:
         ...
+        self._event_dispatcher = event_dispatcher

     async def execute(self, request: SignUpRequest) -> UserQm:
         ...
         await self._transaction_manager.commit()
+
+        await self._event_dispatcher.dispatch(user.collect_events())
+
         logger.info("Sign up: done.")
```

#### [MODIFY] `src/app/core/commands/create_user.py`

Same pattern — dispatch events after commit in the admin `CreateUser` command:

```diff
+from app.core.common.ports.event_dispatcher import EventDispatcher

 class CreateUser:
     def __init__(self, ..., event_dispatcher: EventDispatcher) -> None:
         ...
+        self._event_dispatcher = event_dispatcher

     async def execute(self, request: CreateUserRequest) -> CreateUserResponse:
         ...
         await self._transaction_manager.commit()
+
+        await self._event_dispatcher.dispatch(user.collect_events())
+
         logger.info("Create user: done.")
```

#### [MODIFY] `src/app/main/ioc/core.py`

Register the new ports, handlers, and the handler registry:

```python
from app.core.common.events.handlers.send_welcome_email import SendWelcomeEmail
from app.core.common.events.user_registered import UserRegisteredEvent
from app.core.common.ports.email_sender import EmailSender
from app.core.common.ports.event_dispatcher import EventDispatcher
from app.outbound.adapters.background_event_dispatcher import BackgroundEventDispatcher
from app.outbound.adapters.console_email_sender import ConsoleEmailSender

class CoreProvider(Provider):
    # ... existing providers ...

    # Event Handlers (subscribers)
    send_welcome_email = provide(SendWelcomeEmail)

    # Event Ports
    email_sender = provide(ConsoleEmailSender, provides=EmailSender)
    event_dispatcher = provide(BackgroundEventDispatcher, provides=EventDispatcher)

    @provide(scope=Scope.REQUEST)
    def provide_handler_registry(
        self,
        send_welcome_email: SendWelcomeEmail,
    ) -> dict[type, list]:
        """
        Pub/Sub registry: maps event types to their subscriber handlers.
        To subscribe new code to an event, add the handler here.
        """
        return {
            UserRegisteredEvent: [send_welcome_email],
        }
```

To switch to production SMTP email, change `ConsoleEmailSender` → `SmtpEmailSender` and add the SMTP settings. To switch to sync dispatch, change `BackgroundEventDispatcher` → `SyncEventDispatcher`. That's it — **one line change** in the IoC config.

#### [NEW] `src/app/main/config/email.py`

Email settings (SMTP — vendor-independent):

```python
from pydantic import BaseModel


class EmailSettings(BaseModel):
    USE_CONSOLE: bool = True  # Set to False in production to use SMTP
    SMTP_HOST: str = ""  # e.g. "smtp-relay.brevo.com" or "smtp.mailgun.org"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    FROM_EMAIL: str = "noreply@example.com"
    FROM_NAME: str = "Clean Example"
```

#### [MODIFY] `.env` and `env.example`

Add email config:

```
# Email (SMTP — works with any provider: Brevo, Mailgun, SES, etc.)
EMAIL_USE_CONSOLE=true
EMAIL_SMTP_HOST=smtp-relay.brevo.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USERNAME=
EMAIL_SMTP_PASSWORD=
EMAIL_SMTP_USE_TLS=true
EMAIL_FROM_EMAIL=noreply@yourdomain.com
EMAIL_FROM_NAME=Your Company Name
```

#### [MODIFY] `pyproject.toml`

Add `aiosmtplib` as a production dependency:

```diff
 dependencies = [
     ...
+    "aiosmtplib>=3.0.0",
 ]
```

---

### Step 6: Tests

All tests follow **Red-Green TDD** — each test is written **before** the code it tests.

#### Unit Tests

| File | What it tests | Written before |
|------|---------------|----------------|
| `tests/unit/core/common/events/test_domain_event.py` | Base event cannot be instantiated directly; subclasses work correctly | Step 1 code |
| `tests/unit/core/common/events/test_user_registered.py` | `UserRegisteredEvent` construction with correct fields and immutability | Step 2 code |
| `tests/unit/core/common/entities/test_base_events.py` | `record_event()`, `collect_events()`, clearing after collect, multiple events | Step 1 code |
| `tests/unit/core/common/events/handlers/test_send_welcome_email.py` | Handler calls `EmailSender.send()` with correct args (using mock `EmailSender`) | Step 3 code |
| `tests/unit/core/common/services/test_user.py` (MODIFY) | Assert `UserRegisteredEvent` is recorded when user is created via `create_user()` | Step 5 code |
| `tests/unit/outbound/adapters/test_sync_event_dispatcher.py` | Dispatcher routes events to correct handlers, ignores unregistered events | Step 4 code |
| `tests/unit/outbound/adapters/test_background_event_dispatcher.py` | Background dispatcher schedules tasks correctly | Step 4 code |

#### Integration Tests

| File | What it tests | Written before |
|------|---------------|----------------|
| `tests/integration/with_infra/account/test_sign_up.py` (MODIFY) | After signup, verify email sender was invoked (via DI override with spy) | Step 5 wiring |
| `tests/integration/with_infra/users/test_create_user.py` (MODIFY) | After admin creates user, verify email sender was invoked | Step 5 wiring |

#### Testing strategy for email

For unit tests: Use a mock `EmailSender` that records calls.
For integration tests: Override `EmailSender` in the DI container with a `SpyEmailSender` that captures sent emails in a list, then assert on that list after the API call completes.

```python
class SpyEmailSender:
    """Test double that captures sent emails for assertion."""
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, *, to_email: str, to_name: str, subject: str, html_body: str) -> None:
        self.sent.append({"to_email": to_email, "to_name": to_name, "subject": subject})
```

---

## File Summary

| Action | Count | Layer |
|--------|-------|-------|
| New files | ~14 | core (7), outbound (4), main (1), tests (2+) |
| Modified files | ~8 | core (2), outbound (1), main (2), config (2), tests (1) |

## Verification Plan

### Automated Tests

```bash
# Unit tests (no infra required) — run after every RED/GREEN cycle
make test

# Full integration tests (requires Docker + Postgres)
make test-docker
```

### Architecture Verification

```bash
# Verify Clean Architecture layer boundaries are not violated
uv run lint-imports

# Type checking
uv run mypy
```

### Manual Verification

1. Start the app locally (`make upd-local && uvicorn app.main.run:make_app --reload`)
2. Sign up a new user via Postman → `POST /api/v1/account/signup/`
3. Check the console output for the logged welcome email (from `ConsoleEmailSender`)
4. Configure email provider settings in `.env` to test production email delivery
5. Run `make check` to verify linting, type checking, import-linter, and unit tests all pass

---

# Configuration: Toggling Event Dispatcher via Env Var

> **Implementation Plan v0.5.0**
>
> This phase adds a configuration setting that allows the application to toggle between synchronous (`SyncEventDispatcher`) and background (`BackgroundEventDispatcher`) asyncio event dispatchers at runtime without changing the core business logic.

## Proposed Changes

### Configuration Layer

#### [MODIFY] `src/app/main/config/settings.py`
Add the `EventSettings` model:
- Define `EventSettings(BaseModel)` with a single field: `DISPATCH_MODE: Literal["sync", "background"] = "background"`.

#### [MODIFY] `src/app/main/config/loader.py`
Add the logic to parse environment variables (e.g., `EVENT_DISPATCH_MODE`):
- Add `EventEnvConfig(BaseSettings, EventSettings)` with `env_prefix="EVENT_"`.
- Add a `load_event_settings()` function.

### Application Bootstrapping

#### [MODIFY] `src/app/main/run.py`
Inject the new settings into the dependency injection container context:
- Update `make_app` signature to accept `event_settings: EventSettings | None = None`.
- Call `load_event_settings()` if not provided.
- Add `EventSettings: event_settings` to the context dictionary when creating the Dishka container.

### Dependency Injection (IoC)

#### [MODIFY] `src/app/main/ioc/core.py`
Make the `EventDispatcher` provider dynamic based on the injected settings:
- Replace the static `event_dispatcher = provide(...)` line.
- Add a new `@provide(scope=Scope.REQUEST)` method `provide_event_dispatcher` that accepts `EventSettings` and the `handler_registry`.
- Return `SyncEventDispatcher` if `settings.DISPATCH_MODE == "sync"`, otherwise return `BackgroundEventDispatcher`.

### Documentation

#### [MODIFY] `README.md`
- Check the box for: "Add event dispatcher with support for synchronous and background task execution (via FastAPI `BackgroundTasks`)".

## Verification Plan

### Automated Tests
- Run `make test-docker` to ensure no DI resolution errors break the test suite. All tests should pass.

### Manual Verification
- We can manually set `EVENT_DISPATCH_MODE=sync` in the `.env` file (or export it) and start the server to verify the `SyncEventDispatcher` is used during a sign-up request.
