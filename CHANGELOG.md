# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-08-05: Domain events and background email dispatching

### Added
- **Domain:** Introduced the `DomainEvent` base class and `UserRegisteredEvent`. Upgraded the base `Entity` class to safely record and flush transient domain events.
- **Architecture:** Implemented the Publish-Subscribe pattern to strictly decouple secondary side-effects (like emails) from core business logic transactions.
- **Ports:** Added `EventHandler`, `EventDispatcher`, and `EmailSender` interfaces to the application core.
- **Adapters (Background Processing):** Created `BackgroundEventDispatcher`, which utilizes `asyncio.create_task` to fire off event handlers concurrently without blocking the main HTTP response. Added `SyncEventDispatcher` for sequential execution (ideal for testing).
- **Adapters (Email):** Created `SmtpEmailSender` (powered by `aiosmtplib` with smart TLS/STARTTLS port negotiation) for production, and `ConsoleEmailSender` for local development.
- **Use Cases:** The `SignUp` and `CreateUser` commands now dispatch a `UserRegisteredEvent` immediately after the primary database transaction successfully commits.
- **Event Handlers:** Added a `SendWelcomeEmail` subscriber that listens for `UserRegisteredEvent` and dispatches an onboarding email in the background.
- **Configuration:** Added comprehensive `EMAIL_*` environment variables. Documented and enforced the `.secrets` file orchestration for overriding local variables without committing them to version control.

## [0.3.0] - 2026-07-30: User contact information fields

### Added
- **Domain:** Added `email` and `phone_number` fields to the `User` domain entity as mandatory parameters.
- **Value Objects:** Added `Email` value object with regex validation and `PhoneNumber` value object for South African numbers with normalization logic.
- **Database:** Added `email` and `phone_number` columns to the `users` table with unique constraints (`uq_users_email`, `uq_users_phone_number`).
- **API:** Updated `CreateUserRequest` DTO to include mandatory `email` and `phone_number` fields.
- **API:** Updated sign-up endpoint to require `email` and `phone_number` in the request payload.
- **Query Model:** Updated `UserQm` to include `email` and `phone_number` fields for read operations.
- **Exceptions:** Added `EmailAlreadyExistsError` and `PhoneNumberAlreadyExistsError` for uniqueness constraint violations.
- **Adapters:** Updated `SqlaFlusher` to map new constraint violations to application exceptions.
- **Adapters:** Updated `SqlaUserReader` to select and map `email` and `phone_number` columns.
- **Handlers:** Updated `LogIn` handler to return `email` and `phone_number` in the response.
- **Tests:** Updated all unit and integration tests to include `email` and `phone_number` in test payloads and assertions.

### Changed
- **Factories:** Updated test factories to generate unique phone numbers using random digit generation instead of UUID hex to ensure valid South African number format.

## [0.2.0] - 2026-07-27: Authentication API enhancements and session security patch

### Added
- **API (Auth):** The `/api/v1/account/signup/` and `/api/v1/account/login/` endpoints now return a sanitized `UserQm` profile (DTO) in the JSON response body instead of an empty payload. This provides frontends (like Angular/React) with immediate access to the authenticated user's ID, username, and role.
- **Tests:** Added explicit integration test assertions in `test_log_in.py` and `test_sign_up.py` to verify the schema of the new DTO response and guarantee that sensitive fields (like `password_hash`) are never leaked.

### Changed
- **API (Auth):** Changed HTTP status code for successful signup and login from `204 No Content` to `200 OK`.
- **Integration Tests:** Updated `tests/integration/with_infra/authentication.py` and test suites to expect `200 OK` rather than `204 No Content`.

### Fixed
- **Security:** Patched a severe session invalidation flaw. The `ChangePassword` handler now forcefully revokes all active database sessions and terminates the local cookie whenever a user changes their password, preventing compromised sessions from remaining active.
- **Data Serialization:** Fixed a bug where Domain Value Objects (`Username` and `UtcDatetime`) were improperly serialized in the API response as string representations (e.g., `Username('name')`) and nested dictionaries. The DTO mapping now correctly extracts the underlying `.value`.

## [0.1.0] - 2025-01-01: Initial project scaffold and core authentication module

### Added
- Initial project scaffolding using Domain-Driven Design, Clean Architecture, and Test-Driven Development principles.
- User management module with basic RBAC (`admin`, `user`).
- Authentication via `HttpOnly` cookies and JWT sessions.
- Dependency Injection architecture using `Dishka`.
- Database integration using `SQLAlchemy` and `Alembic`.
