# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
