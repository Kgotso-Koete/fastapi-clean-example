# 17. Security: abuse limits, browser and error hardening, account recovery, privacy (POPIA), scoped access, and safe operation

> **Status: draft, 2026-11-18. Research done, nothing built.** Written by the AI agent on autopilot, at the human maintainer's request, from the approved user stories and a day of research (OWASP first, then reference code downloaded into `ai_research/17-security/`). **Not started.** Every decision was taken by the human maintainer on 2026-11-18, one at a time (`agents.md` 4.10); six stories are deferred to later plans. Next: the stories and this plan are committed on their own, before the first RED (`agents.md` 1.4), and later commits update this plan with whatever the code teaches us.
>
> **Order of work** (decided by the human maintainer, 2026-11-18): the domains in the stories file's order, D1 to D7, with "Running it safely" always last.
>
> **Ground rule: tried and tested industry conventions over newer methods** (set by the human maintainer, 2026-11-18). Every security choice in this plan prefers the method the industry has used longest and most widely (what the major frameworks ship by default, and what is easiest to research, test and troubleshoot) over a newer method, even one OWASP endorses. An option that is newer says so plainly, and is chosen only when the human maintainer asks for it. No time is spent exploring frontier options. The human maintainer's words: "I am not a security expert, I am a web developer, not a pen tester. If something goes wrong we should be able to troubleshoot based on knowledge that is easy to research and test. This is why we need to rely on tried and tested methods and industry conventions. New methodology is good but it assumes that I have experience in that specific security methodology."

## Goal

The template is safe to deploy as it is: attackers can't guess their way into accounts or wear the server down, errors reveal nothing useful, users can recover and protect their accounts, personal information is handled as South Africa's Protection of Personal Information Act (POPIA) requires, every key and admin reaches only what it should, and an operator can run it safely.

The minimum baseline is the security setup of a private Node/Express app the human maintainer runs (security headers, HSTS, parameter-pollution guard, CORS allowlist, body size limits, input sanitising, trusted proxy, layered per-IP rate limits, server-side sessions, development-only verbose errors, a generic 404, a "too busy" 503, request logging). Its intent is kept, not its configuration (its CORS allowed every origin, its cookie was readable by scripts and lived 30 days).

## User stories and threat model

> **The stories and the threat model live in [`user-stories/17-security-user-stories.md`](user-stories/17-security-user-stories.md)** (feature code `SEC`): 7 domains, 52 stories, 14 of them protections that existed before this plan (11 fully built, 3 partly), and 2 deferred to a future plan (Decision 17). That file is the source; this plan never copies it.

Each domain there opens with the four questions of the OWASP Threat Modeling Cheat Sheet (https://cheatsheetseries.owasp.org/cheatsheets/Threat_Modeling_Cheat_Sheet.html). This plan answers the third one ("what are we going to do about it?") in code.

### Story changes the research proposes (applied on 2026-11-18)

The research found things the stories get wrong or miss. The human maintainer asked for all of them to go into the stories file (2026-11-18), and for the next conversation to be which stories to grey out and defer, so the work fits in two to four weeks. A criterion that depends on a decision still open says so in the stories file. Each change points to the research note that backs it. New story IDs, as written into the stories file: SEC.D1.AT.J2.A4 (limit per API key), SEC.D1.AT.J3.A1 (parameter pollution), SEC.D2.AT.J1.A6 (absolute session lifetime), SEC.D3.AT.J1.A5 (`/metrics` and docs pages), SEC.D3.AT.J2.A2 and A3 (log, header and command injection), SEC.D4.AT.J1.A2 (admin set-password), SEC.D4.US.J3.A1 (admin resets a second factor), SEC.D4.SY.J1.A1 (security notification emails), SEC.D7.OP.J3.A1 and A2 (hardened production stack, CI).

**D1 Abuse limits** (`ai_research/17-security/notes/d1-abuse-limits.md`)
1. **SEC.D1.T6 (parameter pollution) is closed:** FastAPI reads a single-value parameter with `.get` and Starlette's multidict keeps the last value (https://github.com/fastapi/fastapi/blob/78c4324f0c56bc5282a459978779a9e532d19709/fastapi/dependencies/utils.py#L749-L777, https://github.com/Kludex/starlette/blob/2269e9a08c1edd3dfdea865710f40f84c857b623/starlette/datastructures.py#L281). Mark it handled before plan 17, with one integration test as its story's proof.
2. **The IPv6 prefix becomes a setting, default `/64`,** and an IPv4-mapped IPv6 address is turned back into IPv4 first. No OWASP sheet or ASVS requirement names a prefix; django-ratelimit uses /64 and express-rate-limit /56 (https://github.com/express-rate-limit/express-rate-limit/blob/f2fbded251a5c2186c244b612dabee970f5ad3c1/source/ip-key-generator.ts#L24-L60).
3. **`Retry-After` on login and sign-up is a fixed, coarse value** (the whole window), never a countdown or a "you have N attempts left" (https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html).
4. **Password reset is the escape hatch:** it always works and clears the username's login count, so an attacker can't keep an owner locked out (ASVS 6.1.1, https://github.com/OWASP/ASVS/blob/82fb2f41cdb623e0b11e4d9a6b97c4306c1d119c/5.0/en/0x15-V6-Authentication.md). The stories' "never locked for good" stays; OWASP's Authentication sheet, NIST and django-axes allow permanent lockout, and this plan records that it deliberately doesn't (Decision 3).
5. **The per-day request window is dropped** (Decision 4): on Postgres every window is one more write per request.
6. **New threats:** slow-request attacks (slowloris; only the reverse proxy can stop them, so it goes to D7's TLS story), and one API key flooding the API from many IP addresses (new story **SEC.D1.AT.J2.A4**, a limit per API key).
7. **What happens when the limit store is down:** login answers 503 (fails closed); the general request limit lets requests through (fails open).

**D2 Browser-facing** (`notes/d2-d3-browser-and-errors.md`)
1. **SEC.D2.AT.J1.A1:** production refuses to start with `COOKIE_SECURE=false`, and the cookie gets the `__Host-` prefix (ASVS 3.3.1; OWASP Session Management calls it "Recommended for session IDs"). Log-out must then delete the cookie with `Secure` too, or browsers ignore the deletion. HSTS is `max-age=63072000; includeSubDomains`, production only, never `preload` (https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Strict_Transport_Security_Cheat_Sheet.html).
2. **New story SEC.D2.AT.J1.A6, an absolute session lifetime:** today a session can be refreshed forever (`src/app/base/outbound/auth_ctx/service.py:50-55`). OWASP Session Management says "should"; ASVS 7.3.2 requires it.
3. **SEC.D2.AT.J1.A2 names its defense:** CSRF tokens as a signed double-submit cookie (Decision 6), exempting `/public` (API keys travel in a header browsers never add). `SameSite=Lax` alone isn't enough here: FastAPI parses a body with no `Content-Type` as JSON (https://github.com/fastapi/fastapi/blob/78c4324f0c56bc5282a459978779a9e532d19709/fastapi/routing.py#L438-L485), and accepting or declining an invitation is a `POST` with no body.
4. **SEC.D2.AT.J1.A3's exemption list adds `/public/docs` and `/public/redoc`,** which are live in production today (`src/app/base/main/run_public_api.py`).
5. **SEC.D2.AT.J1.A4:** production also refuses to start with `COOKIE_HTTPONLY=false`.

**D3 What errors and inputs reveal** (`notes/d2-d3-browser-and-errors.md`)
1. **SEC.D3.AT.J1.A4 is only partly built.** Same status and message for an unknown username and a wrong password, yes; but an unknown username returns before any bcrypt work (`src/app/base/outbound/auth_ctx/handlers/log_in.py:73-74`), so response time reveals which usernames exist (OWASP's "quick exit" anti-pattern; ASVS 6.3.8). An inactive account with the right password also gets its own message (line 79-80). Developed becomes *Partly*.
2. **SEC.D3.T3 (CLI enumeration) is confirmed open:** `RawPassword(...)` runs only when the user exists (`src/app/base/main/cli/identity_provider.py:46`), so a rule-breaking password prints the rule for a real username and "Invalid username or password." for an unknown one.
3. **SEC.D3.AT.J1.A1:** delete the debug route (its own docstring says so; a development-only 500 route already exists in `src/app/base/inbound/http/health/router.py`), and production refuses to start with `DEBUG_MODE=true`.
4. **SEC.D3.AT.J1.A2:** the private app's 500 body is already opaque (`{"code":"HTTP_500_INTERNAL_SERVER_ERROR","message":"Internal server error"}`). The public sub-app's own handler answers in plain text first; one test pins the public 500 body.
5. **SEC.D3.T7 (log injection) is closed in practice:** the JSON log formatter escapes newlines, and every user value that reaches a log is a value object that forbids line breaks. One test pins it. **SEC.D3.T8 is closed:** no subprocess or shell calls, and no user value goes into a response header.
6. **SEC.D3.T5 widens:** sign-up and profile edit also reveal taken **email addresses and phone numbers** (409 naming the field), not only usernames. Decision 8.
7. **New threats:** `/metrics` and `/openapi.json` are open in every environment; the public `/docs` too.

**D4 Account recovery and trust** (`notes/d4-account-recovery.md`)
1. **SEC.D4.US.J1.A1 (reset)** adds: the link is built from a public-URL setting, never from the request's `Host`; the token travels in the URL fragment (`#token=`) so it never reaches a server log or a `Referer`; the token is made by the email handler, never stored in an event (an event's payload is kept in `event_outbox`); the request answers in about the same time for a real and an unknown email (the email is sent after the response); a reset also asks for the second factor when one is on (ASVS 6.4.3); the user gets a "your password was changed" email.
2. **SEC.D4.US.J2.A1 (verify email)** adds: changing your email waits as a pending change until the new address confirms, and the old address gets a notice (today it changes at once, `src/app/base/inbound/http/account/update_own_profile.py:73-82`).
3. **SEC.D4.US.J2.A2:** the check is the Have I Been Pwned range API with padding (only 5 hex characters of a SHA-1 leave the server, https://haveibeenpwned.com/API/v3#PwnedPasswords), with a small bundled list as the fallback when the API is unreachable (Decision 7).
4. **SEC.D4.US.J2.A3 (second factor)** names TOTP first, with recovery codes; passkeys after plan 18. TOTP isn't phishing-resistant, so that is an accepted risk in D4's threat model until passkeys exist.
5. **New stories:** an admin resets a user's second factor (ASVS 6.4.4); security notification emails (password changed, email changed, second factor on or off); the CLI login asks for the second factor.
6. **New threats:** an admin setting a user's password doesn't end that user's sessions (`src/app/base/core/commands/set_user_password.py`), and changing a password doesn't revoke API keys. An attacker who signs up with someone else's email can make an API key that survives the owner's later password reset.

**D5 Privacy and POPIA** (`notes/d5-d6-d7-privacy-access-ops.md`)
1. **SEC.D5.T12 now cites the gazetted text:** Regulation 6.4 of the amended Regulations (GN 6126, GG 52523, 17 April 2025) says "opt-out shall not constitute consent" (https://www.gov.za/sites/default/files/gcis_document/202504/52523gon6126.pdf).
2. **New criterion from Regulation 3.6:** the user is told in writing, within 30 days, what was done about a correction or deletion request. A confirmation email covers it.
3. **SEC.D5.US.J1.A1 (export)** adds: the line telling the user they may ask for corrections (s23(2)); "other members of my organizations" as a category of who sees my information.
4. **SEC.D5.US.J1.A3 (delete) is blocked today:** `organizations.created_by_user_id` and `organization_memberships.invited_by_user_id` reference `users` with no `ondelete`, so deleting anyone who created an organization or invited someone fails. Both become `SET NULL`.
5. **SEC.D5.SY.J1.A2's promise is false today:** Loki has no compactor with `retention_enabled` (`observability/loki/loki-config.yml`), so logs are kept forever; Grafana uses admin/admin; and the default console email sender logs every email body, which would put password-reset links in the logs. *Corrected on 2026-11-18: Loki and Grafana run only in development (their Compose profile is off in production), so the production problem is different: production logs are the app's and worker's own output, which Docker stores with no rotation by default, so they grow for ever. Decision 18 answers it.*
6. **SEC.D5.T6 is open:** `phone_number` is required and unique. Decision 9.
7. **SEC.D5.T11 (children) is accepted as the operator's duty:** neither the Act nor the Regulator prescribes age checks.
8. **One sentence on words:** POPIA's "operator" is a processor such as the email provider; this file's Operator actor is POPIA's *responsible party*.

**D6 Who may do what** (`notes/d5-d6-d7-privacy-access-ops.md`)
1. **SEC.D6.OP.J1.A1 (admin record)** adds four actions: admin creates a user, admin edits a profile, an organization is deleted, a member is removed. "Can't be changed through the app" is enforced by a trigger; the database owner can still change it until the app runs as a non-owner role (that role split belongs with the parked row-level-security work, plan 14).

**D7 Running it safely** (`notes/d5-d6-d7-privacy-access-ops.md`)
1. **SEC.D7.OP.J1.A1:** CI never runs `pip-audit` at all, and the hook's `|| echo` also hides network failures. The 29 open findings are fixed before blocking is turned on.
2. **SEC.D7.OP.J1.A3 widens:** the `env.example` placeholders for `JWT_SECRET` and `PASSWORD_PEPPER` pass the length check, so a deployment that never replaces them starts with public secrets. Production refuses known placeholders. (`docs/wiki/content/docker-deployment/production-deployment.md:71` says it already fails; it doesn't.)
3. **SEC.D7.OP.J2.A1:** the API refuses plain HTTP rather than redirecting it (OWASP Transport Layer Security Cheat Sheet: API endpoints shouldn't redirect, so clients that sent credentials over HTTP fail loudly).
4. **New threats, each a story:** production starts uvicorn with `--reload` (`docker-entrypoint.sh:12`); the app connects to Postgres as the superuser; promtail mounts the Docker socket; Grafana, Flower and Redis have default or no credentials; images aren't pinned by digest; CI actions are pinned by tag with no `permissions:` block.

## How this plan was researched

Everything is in `ai_research/17-security/` (git-ignored): `repos/` (cloned, read only, never run), `web/` and `text/` (downloaded pages and plain-text copies), and `notes/` (one file per area, every claim with a pinned link). Re-read the notes, not this summary, when a step starts.

**Primary sources**
- OWASP Cheat Sheet Series, at commit `c12dd22`: https://github.com/OWASP/CheatSheetSeries/tree/c12dd22e17cefa0b8448f3a82b15a60bb3357914/cheatsheets (published at https://cheatsheetseries.owasp.org/)
- OWASP ASVS 5.0, at commit `82fb2f4`: https://github.com/OWASP/ASVS/tree/82fb2f41cdb623e0b11e4d9a6b97c4306c1d119c/5.0/en
- OWASP Top 10 2025: https://top10.owasp.org/2025/
- NIST SP 800-63B (revision 4): https://pages.nist.gov/800-63-4/sp800-63b.html
- POPIA (Act 4 of 2013), as published by the Information Regulator: https://inforegulator.org.za/wp-content/uploads/2025/08/PROTECTION-OF-PERSONAL-INFORMATION-ACT-4-OF-2013.pdf
- Amended POPIA Regulations, 17 April 2025: https://www.gov.za/sites/default/files/gcis_document/202504/52523gon6126.pdf
- Information Regulator, fact sheet on security compromises: https://inforegulator.org.za/2025/08/19/fact-sheet-handling-of-security-compromises/

**Reference repositories** (each pinned to the commit that was read)
- limits (rate-limit strategies and storage): https://github.com/alisaifee/limits/tree/0492c4fbef45c0f66c88c5feb00cb1270af238fa
- slowapi (FastAPI rate limiting; read for what to avoid): https://github.com/laurentS/slowapi/tree/d3442b2e1425a9db535732a0a06248470c7f9fd5
- django-ratelimit: https://github.com/jsocol/django-ratelimit/tree/e1130454337f4fd77c0cee98ff9e2d842388f85b
- django-axes (login lockout): https://github.com/django-commons/django-axes/tree/ba9926171dd93e1006c23bb54cb6bfc274b21fd6
- express-rate-limit (IPv6 handling): https://github.com/express-rate-limit/express-rate-limit/tree/f2fbded251a5c2186c244b612dabee970f5ad3c1
- uvicorn (proxy headers, concurrency limit): https://github.com/Kludex/uvicorn/tree/3eb9a9ab9af69005c687728097461c1fd2a95db9
- Starlette 1.7.0, the version this project pins (body size limit, CORS): https://github.com/Kludex/starlette/tree/2269e9a08c1edd3dfdea865710f40f84c857b623
- FastAPI 0.142.2, the version this project pins: https://github.com/fastapi/fastapi/tree/78c4324f0c56bc5282a459978779a9e532d19709
- Django (security middleware, CSRF, reset tokens, password validators): https://github.com/django/django/tree/9e2e5a31e2ef2e8673d3c2a38d2a391dbf42cf23
- Go's `net/http` cross-origin protection (the Fetch Metadata algorithm): https://github.com/golang/go/blob/1b321e59ce016f65765df3efb4d769ecef148ad7/src/net/http/csrf.go#L132-L175
- asgi-csrf: https://github.com/simonw/asgi-csrf/tree/e23af3215539317707c60266e1b5122a77f026ca
- secure (Python headers package; read and not chosen): https://github.com/TypeError/secure/tree/5878d0d6c2f00945ef5b81a82746eba57bd44cfc
- fastapi-users (reset and verify flows): https://github.com/fastapi-users/fastapi-users/tree/e9c57ff7ff2fd385bb0f6f795b524e9736b64290
- pwned-passwords-django: https://github.com/ubernostrum/pwned-passwords-django/tree/05c4eeff27500e34e3819c2e48eff6eb10495f4e
- pyotp (TOTP): https://github.com/pyauth/pyotp/tree/98c44b5b3294d7a24fe883622ad9d1e76c0687a1
- django-otp (TOTP devices, recovery codes): https://github.com/django-otp/django-otp/tree/1c77c58f6785b49da3250b01dedbbc77ed0429ae
- django-auditlog (audit records): https://github.com/django-commons/django-auditlog/tree/6a2a88f90f908b7d2aa9aa9e62a077a4c330cb18
- django-oauth-toolkit (token scopes): https://github.com/django-oauth/django-oauth-toolkit/tree/285ba9c38306bccf798cc4f9fe64fbbae8659e40
- pip-audit 2.10.1, the version this project pins: https://github.com/pypa/pip-audit/tree/9bd0eff568298f4fbdecfd4477d9463dba8e6393

## Design

Each part starts with the use case it serves (`agents.md` 4.10). Paths for new files are proposals; each is settled at its step's RED.

### Shared groundwork (used by several domains)

**Use case:** several protections need the same three things (the client's real IP address, "refuse to start in production when a setting is unsafe", and one place to declare new settings), so they are built once, first.

- **The client's IP address** (D1, D5, D6). One setting, `APP_TRUSTED_PROXIES` (empty by default). The app factory wraps the app in uvicorn's `ProxyHeadersMiddleware` with that list, and uvicorn starts with `--no-proxy-headers`, so only the app decides. uvicorn walks `X-Forwarded-For` right to left and takes the first address that isn't a trusted proxy (https://github.com/Kludex/uvicorn/blob/3eb9a9ab9af69005c687728097461c1fd2a95db9/uvicorn/middleware/proxy_headers.py#L28-L63); with `*` it would take the leftmost, which the attacker writes. This is the only setup the ASGI integration tests can prove. ASVS 15.3.4.
- **A production safety check at startup** (D2, D3, D7). One function, run by every entrypoint's settings loading, that refuses to start when `ENVIRONMENT=production` and any of these hold: `COOKIE_SECURE=false`, `COOKIE_HTTPONLY=false`, `APP_DEBUG_MODE=true`, `JWT_SECRET` or `PASSWORD_PEPPER` equal to the `env.example` placeholder, the console email sender selected. It follows the existing pattern: the app already refuses a short `JWT_SECRET`. Django only warns (https://github.com/django/django/blob/9e2e5a31e2ef2e8673d3c2a38d2a391dbf42cf23/django/core/checks/security/base.py#L95-L98), which is easy to miss; Decision 2.
- **Every new setting** gets its loader test (`agents.md` 2.3) and an entry in `env.example`.

### D1 Abuse limits

**Use case:** an attacker can't guess passwords, mass-create accounts or flood the server, while the real owner is never locked out for good (SEC.D1.*).

- **One port, two adapters.** A `RateLimiter` port in `src/app/base/core/common/ports/`, like `EmailSender`; the Postgres adapter (the default) and the Redis adapter (optional) in `src/app/shared/outbound/adapters/`, as email's are. A setting `RATE_LIMIT_STORE=postgres|redis` in `.env` chooses; Redis uses the existing `REDIS_*` settings. **The Redis adapter is a priority, never deferred** (the human maintainer, 2026-11-18): "it helps to establish Redis as something we can use outside of Celery workers ... If we ever need caching, boom Redis infrastructure is in place and available." So Redis must start and be reachable whenever `RATE_LIMIT_STORE=redis`, even with `CELERY_ENABLED=false`, and its connection is shared infrastructure that a later cache can reuse, not something owned by Celery.
- **Algorithm: a sliding-window counter on clock-aligned buckets.** OWASP prefers a sliding window or token bucket to fixed windows (https://cheatsheetseries.owasp.org/cheatsheets/Bot_Management_and_Anti-Automation_Cheat_Sheet.html); the `limits` library explains why buckets must be clock-aligned (https://github.com/alisaifee/limits/blob/0492c4fbef45c0f66c88c5feb00cb1270af238fa/doc/source/strategies.rst#L64-L131) and implements it (https://github.com/alisaifee/limits/blob/0492c4fbef45c0f66c88c5feb00cb1270af238fa/limits/strategies.py#L194-L262).
- **Postgres:** an `UNLOGGED` table `rate_limit_buckets (bucket_key, window_start, hits)`, primary key `(bucket_key, window_start)`. One `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` adds a hit atomically and reads the previous bucket. Keys are stored hashed, so the table holds no usernames or IP addresses. Old rows are removed by D5's retention job. The limiter commits on **its own connection**: `LogIn` only commits on success, so a failure counted inside the request's transaction would roll back. Alembic writes the `UNLOGGED` prefix itself (https://github.com/sqlalchemy/alembic/blob/db53474a48914b6b228ca85d4f9cd160c2821cd5/alembic/autogenerate/render.py#L280-L282), so `make migration` works.
- **Redis:** one Lua script with the same buckets, expiry replacing cleanup (https://github.com/alisaifee/limits/blob/0492c4fbef45c0f66c88c5feb00cb1270af238fa/limits/resources/redis/lua_scripts/acquire_sliding_window.lua#L1-L45).
- **Login:** count the attempt **before** looking the user up, keyed on the normalised identifier, so the 429 is the same for real and unknown usernames, and a refused attempt runs no bcrypt. On success, clear the username's bucket (NIST SP 800-63B, throttling). Per-username and per-IP buckets stay separate (OWASP Credential Stuffing Prevention). The CLI uses the per-username limit only.
- **Defaults** (settings; only the sign-up figure has an OWASP example, the rest are judgement within the sources' limits):
  - login per username: 10 failures per 15 minutes
  - login per IP: 30 failures per 15 minutes
  - sign-up per IP: 10 attempts per hour (OWASP's example is 3; 10 allows a shared office network)
  - requests per IP: 300 per minute and 5000 per hour
  - requests per API key: the same as per IP
  - request body: 1 MiB
  - requests in flight: 100 per process
  - IPv6 prefix: 64
- **Body size (413):** Starlette 1.7.0's `RequestBodyLimitMiddleware` refuses on `Content-Length` before reading and counts the real bytes, so chunked or understated bodies are caught too (https://github.com/Kludex/starlette/blob/2269e9a08c1edd3dfdea865710f40f84c857b623/starlette/middleware/body_limit.py#L30-L132). `FastAPI(max_body_size=...)` does nothing in 0.142.2 (https://github.com/fastapi/fastapi/blob/78c4324f0c56bc5282a459978779a9e532d19709/fastapi/applications.py#L1053-L1104).
- **Overload (503):** a small app middleware caps requests in flight and answers 503 in the app's JSON shape with `Retry-After`. uvicorn's `--limit-concurrency` also answers 503 (https://github.com/Kludex/uvicorn/blob/3eb9a9ab9af69005c687728097461c1fd2a95db9/uvicorn/protocols/http/h11_impl.py#L227-L235), but counts idle keep-alive connections, sends no `Retry-After`, and can't be proven by the integration tests (Decision 5).
- **No slow-down before refusing:** a server-side delay costs the server more than the attacker (https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Cheat_Sheet.html).
- **Avoid:** slowapi's `get_ipaddr` trusts `X-Forwarded-For` blindly (https://github.com/laurentS/slowapi/blob/d3442b2e1425a9db535732a0a06248470c7f9fd5/slowapi/util.py#L4-L17).

### D2 Browser-facing

**Use case:** an attacker can't use a logged-in user's browser against them: no stolen cookies, no forged requests, no framing (SEC.D2.*).

- **Cookie:** `__Host-auth_token`, `Secure`, `HttpOnly`, `SameSite=Lax`, path `/`, no `Domain`, no expiry (a browser-session cookie). The 5-minute idle timeout stays (within OWASP's range for high-value apps); an **absolute lifetime** is added (default 8 hours, a setting).
- **CSRF: CSRF tokens, as a signed double-submit cookie** (Decision 6), the token form OWASP marks "RECOMMENDED" when no token is stored on the server (https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html#signed-double-submit-cookie-recommended).
  - The server sets a `__Host-` CSRF cookie holding a random value and an HMAC signature that ties it to the session (or, before login, to a pre-session value), signed with a key derived from an existing secret, as API-key hashing derives its key from the pepper.
  - Every request that changes something must send the same token in a request header; a missing, mismatched or wrongly signed token gets 403 and changes nothing. The comparison is constant-time.
  - Logging in needs a token too, which blocks login CSRF; logging in or out issues a fresh token.
  - `/public` is exempt: API keys travel in a header browsers never add on their own.
  - Clients read the token from its cookie (it isn't `HttpOnly`, so a frontend's JavaScript can read it) or from a small route that returns it; curl human checks fetch it first, and Swagger UI sends it through a documented header (how, settled at its step).
  - `SameSite=Lax` stays as the defense in depth OWASP asks for.
  - Reference implementations: Django's CSRF middleware (https://github.com/django/django/blob/9e2e5a31e2ef2e8673d3c2a38d2a391dbf42cf23/django/middleware/csrf.py#L416-L468) and asgi-csrf, an ASGI double-submit implementation (https://github.com/simonw/asgi-csrf/blob/e23af3215539317707c60266e1b5122a77f026ca/asgi_csrf.py#L142-L226). Whether to use asgi-csrf as a pinned dependency or write the same pattern in this codebase is settled at its step, preferring the existing implementation if it fits (OWASP: "Built-in defenses are generally preferable").
- **Headers,** from one outermost pure-ASGI middleware that sets each header only if the route hasn't (OWASP REST Security, security headers table; https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html):
  - `X-Content-Type-Options: nosniff`
  - `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: no-referrer`
  - `Cache-Control: no-store`
  - `Strict-Transport-Security: max-age=63072000; includeSubDomains` (production only)
  - no `X-XSS-Protection`
  - Swagger and ReDoc pages (`/docs`, `/redoc`, `/public/docs`, `/public/redoc`) get only `frame-ancestors 'none'`, because they load CDN scripts.
  - The `secure` package was read and not chosen: its defaults are looser (`frame-ancestors 'self'`, `SAMEORIGIN`).
- **CORS:** none today, so browsers refuse other origins (SEC.D2.AT.J1.A5). For plan 18: an exact allowlist with credentials, never `*` with credentials, because Starlette then echoes back any `Origin` (https://github.com/Kludex/starlette/blob/271c277da0ff64e2048a4d46ecc812b9d61db5f6/starlette/middleware/cors.py#L163-L175).

### D3 What errors and inputs reveal

**Use case:** an attacker learns nothing from errors, timings or the CLI that helps them aim an attack (SEC.D3.*).

- **Debug route:** deleted, as its own docstring asks (`src/app/base/inbound/http/debug/test_error.py`); the development-only `/http_error/` route in `src/app/base/inbound/http/health/router.py` still lets alerting be tested.
- **Login timing:** an unknown username checks the password against a fixed dummy bcrypt hash, so both paths cost the same (OWASP Authentication, "Authentication Responses"). The inactive-account message is kept only after a correct password (Decision 8 weighs it with sign-up).
- **CLI:** check the password rules before looking the user up, the same order as the HTTP login, and use the same dummy hash.
- **SQL injection, log injection:** already handled; their stories get tests that pin the behaviour (a malicious sort field gets 422; a value such as `' OR 1=1 --` is refused or stored as text; a value with a newline stays one JSON log line).
- **`/metrics`, `/openapi.json`, public `/docs`:** production hides `/docs` and `/redoc` for both apps; `/openapi.json` stays (integrators and ZAP use it); `/metrics` answers only on the internal network or with a bearer token (decided at its step).

### D4 Account recovery and trust

**Use case:** a user who forgets a password gets back in, a stolen password alone isn't enough, and a leaked password is refused (SEC.D4.*).

- **Tokens (reset and email verification):** 256-bit random, stored only as an HMAC hash using the existing API-key hasher with a new label (`src/app/base/outbound/adapters/hmac_sha256_api_key_hasher.py`), single use by one atomic delete, lifetime a setting (reset 30 minutes, capped at 24 hours, the NIST limit for emailed codes; verification 24 hours). Not Django's HMAC tokens or fastapi-users' JWTs: those can't be revoked and several can be live at once (https://github.com/django/django/blob/9e2e5a31e2ef2e8673d3c2a38d2a391dbf42cf23/django/contrib/auth/tokens.py#L84-L122, https://github.com/fastapi-users/fastapi-users/blob/e9c57ff7ff2fd385bb0f6f795b524e9736b64290/fastapi_users/manager.py#L275-L356). Follows https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html.
- **The email handler makes the token,** never the command: an event's payload is stored in `event_outbox` and kept by default.
- **Unverified accounts can't log in** (Decision 10), as Devise does by default: logging in with the right password to an unverified account gets its own message, shown only after the right password, like an inactive account. Asking for a new verification email needs no log-in and answers the same whether or not the address has an account. The retention job deletes accounts never verified, a few days after their link expires. Accounts that exist before plan 17, the seeded accounts and accounts an admin creates count as verified.
- **Breached passwords:** the Have I Been Pwned range API with `Add-Padding: true`; when it's unreachable, a bundled list of about 3,000 passwords of 12 or more characters, cut from SecLists' MIT-licensed top-million file (Django's 20,000-password list has only 190 entries that long). This is what pwned-passwords-django does (https://github.com/ubernostrum/pwned-passwords-django/blob/05c4eeff27500e34e3819c2e48eff6eb10495f4e/src/pwned_passwords_django/api.py#L69-L80). Settings: `BREACHED_PASSWORD_CHECK_ENABLED` (on), the API URL (so an operator can use a mirror).
- **Second factor (TOTP):** 160-bit secret, SHA-1, 6 digits, 30 seconds, accepting the current and previous step; replay blocked by an atomic update of the last accepted step (https://github.com/pyauth/pyotp/blob/98c44b5b3294d7a24fe883622ad9d1e76c0687a1/README.rst#L77-L113); the secret encrypted with AES-256-GCM under a new key in `.secrets`, separate from the pepper (django-otp stores it in plain text: https://github.com/django-otp/django-otp/blob/1c77c58f6785b49da3250b01dedbbc77ed0429ae/src/django_otp/plugins/otp_totp/models.py#L14-L15); 10 recovery codes of 120 bits, hashed, single use; turning it on needs a valid code first. **The password step creates no session,** only a short-lived "second factor pending" row with its own cookie, so a half-logged-in user reaches nothing (django-otp's "verified" flag fails open on any route that forgets to check it: https://github.com/django-otp/django-otp/blob/1c77c58f6785b49da3250b01dedbbc77ed0429ae/src/django_otp/decorators.py#L23). Follows https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html. Whether to pin pyotp 2.11 or compute the time step ourselves is settled at the step.
- **Password storage** already follows OWASP's recipe (HMAC-SHA384 with the pepper, then base64, then bcrypt at work factor 11; OWASP's minimum is 10): nothing is cut at bcrypt's 72 bytes. Rehashing on a work-factor change and Argon2id are out of scope.
- **Sessions and keys on password events:** a reset, a password change and an admin setting a password each end every session; API keys are left alone, as is the convention (Decision 11).

### D5 Privacy and POPIA

**Use case:** a user can see, correct and delete their personal information, it's kept no longer than needed, and an operator can meet POPIA's duties (SEC.D5.*). This is not legal advice; every legal reading in the notes is marked as one.

- **Export:** `GET /api/v1/account/data/` returns everything held about the user as JSON, plus the operator's list of outside services and the s23(2) line about corrections. Logged as `sensitive_read`.
- **Deletion:** hard-delete the user row and let the existing cascades remove sessions, API keys and memberships; `created_by_user_id` and `invited_by_user_id` become `SET NULL`; the last-Owner choice (hand over, or tick "also delete the organizations I'm the last Owner of"); outbox rows naming the user are deleted; a confirmation email meets Regulation 3.6. Backups can't be edited: they are kept a short fixed time, and a restore re-applies deletions (OWASP Multi-Tenant Security: reapply retention rules on restore).
- **Retention:** one CLI command, `retention purge`, run by cron (Celery beat optional). Defaults, each a setting: sessions at expiry, rate-limit buckets after their window, expired invitations after 30 days, relayed outbox rows after 7 days, deactivated accounts after 365 days, the admin record after 1 year, backups after 30 days. Production logs are limited by Docker's own log rotation instead (Decision 18).
- **Logs:** the human maintainer's compromise stands (any personal field may be logged). The protection is around the logs: Docker's own log rotation on the `app` and `worker` services, so production logs can't grow for ever (Decision 18), and the console email sender refused in production. Loki and Grafana run only in development and stay as they are.
- **Privacy notice:** `APP_PRIVACY_NOTICE_URL` setting, returned by a public route, and each account records the notice version it signed up under.
- **Breach runbook:** a CLI command lists accounts touched in a time window, from the admin record and logs; a documented email notice with what s22(5) asks for; the runbook links the Regulator's eServices portal, where the organisation and its Information Officer must already be registered.

### D6 Who may do what

**Use case:** a leaked API key reaches as little as possible, and an operator can trace what admins did (SEC.D6.*).

- **Scoped keys (deferred to a future plan by Decision 17; kept here as its starting point):** two new columns on `api_keys`: `organization_id` (null means "every organization I belong to"; deleted with its organization) and `access` (`read` or `read_write`). Modelled on GitHub fine-grained tokens (one resource owner) and Stripe's None/Read/Write. **Every public route declares its access in code,** and one test walks every route and fails if one declares nothing or declares `read` on a method that changes something (deny by default: https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html; django-oauth-toolkit infers it from the method instead: https://github.com/django-oauth/django-oauth-toolkit/blob/285ba9c38306bccf798cc4f9fe64fbbae8659e40/oauth2_provider/contrib/rest_framework/permissions.py#L69-L86). A key's limits only narrow its owner's current role, never widen it. Whether `organization_id` lives on `api_keys` (a base table pointing into a module) or in a link table owned by Organizations is settled against the import rules at the step.
- **Admin record:** an insert-only `audit_events` table (id, time, actor, actor kind, OWASP Logging Vocabulary event name, target, organization, details, source IP, user agent, request id), written in the same transaction as the change, with no foreign key to `users`, so deleting a user never touches it. Updates, deletes and truncates are refused by triggers whose SQL lives in a readable source module (`agents.md` 4.7); the retention purge goes through one deliberate function. Read by platform admins only. Unlike django-auditlog, it stores ids, not email addresses (https://github.com/django-commons/django-auditlog/blob/6a2a88f90f908b7d2aa9aa9e62a077a4c330cb18/auditlog/models.py#L339-L389), and takes the IP address from the trusted-proxy rule, not the leftmost `X-Forwarded-For` (https://github.com/django-commons/django-auditlog/blob/6a2a88f90f908b7d2aa9aa9e62a077a4c330cb18/auditlog/middleware.py#L20-L37).

### D7 Running it safely (always last)

**Use case:** an operator can deploy without known-vulnerable dependencies, readable secrets, plain-text traffic or untested backups (SEC.D7.*).

- **pip-audit:** fix the 29 findings first; then the hook and a CI step block, with a scheduled weekly CI run; each accepted finding sits in the script as `--ignore-vuln ID  # reason, review by YYYY-MM-DD` (pip-audit has no reason field: https://github.com/pypa/pip-audit/blob/9bd0eff568298f4fbdecfd4477d9463dba8e6393/README.md#L246-L256); a network failure fails the run instead of being hidden.
- **Secrets (deferred to a future update by Decision 12; secrets stay in `.secrets` merged into `.env`; kept here as the starting point):** pydantic-settings' `secrets_dir="/run/secrets"` plus Docker Compose file secrets in production; local development keeps `.secrets`. Compose file secrets are plain mounts, not encryption (OWASP Docker Security, rule 12): they take secrets out of the environment and the project folder, nothing more (Decision 12).
- **Production compose (deferred to a future build by Decision 13, which records what it would gain; the Docker setup stays as it is):** a `docker-compose.prod.yml` override without `--reload`, without the development tools (Flower, Redis Commander, Adminer, Grafana's default login), with `no-new-privileges`, `cap_drop: [ALL]`, resource limits, images pinned by digest, and the app connecting as a non-superuser role (Decision 13).
- **TLS: an optional nginx and certbot service, off by default** (Decision 14). One new service in `docker-compose.yml` behind a Compose profile (`https`), so `make upd` and every existing service are unchanged; a `make` target turns it on. On a host that already provides HTTPS (a cloud platform's load balancer) it stays off. On a plain server it ends HTTPS with a Let's Encrypt certificate that certbot renews automatically. Locally it uses a self-signed certificate (browsers warn unless a local certificate authority such as mkcert is installed). When on, nginx listens on ports 80 and 443 on every network address, because that is its job; everything behind it keeps listening on `127.0.0.1`. The nginx config does what any proxy in front must do, and `docs/wiki/content/docker-deployment/production-deployment.md` lists the same requirements for operators who use their host's proxy instead: end HTTPS with a certificate that renews; refuse plain HTTP to the API rather than redirect it, where the host allows; time out requests sent too slowly; set `X-Forwarded-For`, with its own address in `APP_TRUSTED_PROXIES`. The app sends HSTS itself, so there's one place to change it. The original author planned no proxy (his compose file ran only the app and Postgres, and his `ROOT_PATH` setting exists for running behind someone else's); because this service is optional and off by default, his design still works unchanged, and uvicorn's deployment docs recommend exactly this, nginx in front, when self-hosting.
- **Backups:** `pg_dump -Fc` daily, encrypted to a public key, 30 copies, plus `pg_dumpall --globals-only` for roles; restore with `pg_restore --single-transaction --clean --if-exists`, then re-apply deletions; the restore is a human check into a fresh stack.
- **CI:** actions pinned by commit SHA and a `permissions:` block (https://cheatsheetseries.owasp.org/cheatsheets/CI_CD_Security_Cheat_Sheet.html).

### Deliberately out of scope

- The second factor (TOTP, recovery codes, the admin reset): deferred to a future plan (Decision 17); its design under D4 is the starting point.
- A secret store (Docker Compose secret files): deferred to a future update (Decision 12); secrets stay as they are.
- A production compose file (no `--reload`, no development tools, a non-superuser database role, container hardening, images pinned by digest): deferred to a future build (Decision 13, with what it would gain).
- Scoped API keys (one organization, read-only): deferred to a future plan (Decision 17); their design under D6 is the starting point.
- Passkeys (WebAuthn): after plan 18's frontend.
- Argon2id and rehash-on-login.
- Removing the password composition rule (NIST and ASVS 6.2.5 advise against composition rules; noted, not redesigned).
- The non-owner database role for the whole app beyond what D7 needs, and row-level security: plan 14, parked.
- Tamper-evident hash chaining of the admin record (optional; OWASP Logging suggests it).
- The race on the last-Owner check (no `FOR UPDATE`): an Organizations fix, not a security story.
- Legal advice: the operator remains the responsible party.

## Decisions for the human maintainer

All open. Each is taken one at a time, in this order, before its domain starts. Every option gives its short- and long-term trade-off and a score out of 10 for long-term maintainability, flexibility and readiness for complexity (`agents.md` 4.10).

1. **Commit cadence.** **Decided: (a)**, by the human maintainer, 2026-11-18. (a) One commit per domain, after its human checks: 7 commits, each reviewable, releasable on its own. Score 8. (b) One commit at the end, the default in `agents.md` 1.4: one review of about 100 TDD cycles, nothing protects production until the last one. Score 4. *This amends `agents.md` 1.4's "a commit closes a whole plan" for plan 17 only. Step 0's shared groundwork commits with D1.* **Condition** (the human maintainer, 2026-11-18): "Only if the app can run properly after each commit. Commits should never reduce system functionality." So every domain's commit leaves the app fully working, with every existing route, CLI command and worker task behaving as before except where a story deliberately changes it; a domain that can't be finished that way is split until it can.
2. **Unsafe production settings.** **Decided: (a)**, by the human maintainer, 2026-11-18. (a) Refuse to start, naming the setting: loud, matches the existing short-secret check, may annoy someone testing production mode locally. Score 9. (b) Log a warning and start: easy to miss, as Django's checks show. Score 4. Recommended: (a).
3. **Lockout.** **Decided: (a)**, by the human maintainer, 2026-11-18. (a) Throttle only, never lock (as the stories say), with password reset as the escape hatch: an owner is never shut out by an attacker. Score 8. (b) Permanent lockout after N failures until an admin unlocks (OWASP Authentication, django-axes's default): stronger against slow guessing, but an attacker can lock out anyone whose username they know. Score 5. Recommended: (a).
4. **Request windows.** **Decided: (a)**, by the human maintainer, 2026-11-18. (a) Per minute and per hour: one write per window per request on Postgres. Score 8. (b) Minute, hour and day, as in the Node baseline: a third write on every request for little extra protection. Score 6. Recommended: (a).
5. **Overload guard.** **Decided: (a)**, by the human maintainer, 2026-11-18. (a) An app middleware with a limit on requests in flight: 503 in the app's JSON shape with `Retry-After`, proven by integration tests. Score 8. (b) uvicorn's `--limit-concurrency`: no code, but counts idle connections, plain-text 503, no `Retry-After`, untestable here. Score 5. Recommended: (a).
6. **CSRF defense.** **Decided: (c), CSRF tokens, as a signed double-submit cookie**, by the human maintainer, 2026-11-18, over the recommended (a): "CSRF is the best choice", because tokens are the long-standing industry convention (the default in Django, Rails, Laravel, Spring Security and ASP.NET) and the easiest to research and troubleshoot. This decision set the plan's ground rule on tried and tested conventions. (a) Fetch Metadata with an Origin fallback: no client changes, covers login CSRF; endorsed by OWASP for modern-browser apps, but newer (all major browsers since March 2023; Go's standard library since 2025). Score 8. (b) A required custom header: simple, but every client must send it; a secondary technique in OWASP's sheet. Score 6. (c) Signed double-submit tokens: the most proven; every client fetches and returns a token. Score 7.
7. **Breached-password check when the switch is off.** **Decided: (a)**, by the human maintainer, 2026-11-18. (a) Off means off: no API call and no bundled list, matching "some users might want a password on the breach list". Score 7. (b) The bundled list keeps running when only the API is switched off: still blocks the most common passwords. Score 6. Recommended: (a), because the human maintainer's reason for the switch was convenience for customers.
8. **Enumeration through sign-up and profile edit** (email address and phone number taken). **Decided: (a), accept**, by the human maintainer, 2026-11-18; (b) is not planned. (a) Accept, limited by D1's sign-up limit, and record it in D3's threat model: no change to the original sign-up. Score 6. (b) Once email verification exists, sign-up always answers "check your email" and emails the existing owner instead: closes it, but changes the original author's sign-up and every client. Score 7. Recommended: (a) now, with (b) noted for after D4.
9. **The mandatory phone number** (POPIA s10). **Decided: (b), keep it required**, by the human maintainer, 2026-11-18, over the recommended (a): "this repo will be used for many things in small enterprise. Probably whatsapp interactions too. A phone number is mandatory for business transactions in South Africa." So collecting it is part of the purpose; SEC.D5.T6 is accepted with that reason, and the optional-phone story was removed before it was ever built. (a) A setting that makes it optional (`APP_PHONE_NUMBER_REQUIRED`, default true): additive, the operator decides. Score 7. (b) Keep it required and record why in D5: no change. Score 5.
10. **Unverified accounts.** **Decided: no log-in until verified**, by the human maintainer, 2026-11-18, after the options were re-scored under the ground rule (Devise's default, django-allauth's "mandatory"): the verification link activates the account; an account never verified is deleted by the retention job a few days after its link expires, freeing its username and email; accounts that exist before plan 17 count as verified. It also fully closes the API-key takeover (SEC.D4.T10). The original options, as first scored: (a) Can log in, but reach only an allow-list: a user can fix a mistyped email. Score 8. (b) Can't log in until verified (OWASP's strict view): simpler rule, but a typo in the email locks the user out. Score 6. Recommended: (a).
11. **API keys on password events.** **Decided: password events end sessions, never API keys**, by the human maintainer, 2026-11-18, after re-scoring under the ground rule (GitHub's personal access tokens, Stripe's keys and Django REST framework's tokens all survive a password change or reset). A user revokes their own keys; an admin who deactivates an account stops every key at once. The original options, as first scored: (a) A reset and an admin set-password revoke the user's API keys; an ordinary password change doesn't: closes the pre-signup takeover without breaking integrations on every change. Score 7. (b) Every password event revokes keys: safest, but integrations break whenever a user changes their password. Score 6. Recommended: (a).
12. **Secret store.** **Deferred to a future update**, by the human maintainer, 2026-11-18: "Lets not mess with secrets because it will affect our entire workflow when we have not even shipped version 1 of the template. Lets be pragmatic and defer this secrets management decision to a future update. Keep secrets system as it is now." SEC.D7.OP.J1.A2 is greyed out; its "no secret in a log" criterion moved to SEC.D5.SY.J1.A2, which isn't deferred. The production checks on placeholder and empty secrets (SEC.D7.OP.J1.A3, Decision 2) stay: they validate today's secrets without changing how they're stored. The options, as scored: (a) Docker Compose file secrets read through `secrets_dir`: works on one machine, no new service. Score 7. (b) A cloud secret manager or Vault: stronger, but a mandatory outside service, against `agents.md` 4.1. Score 5. Recommended: (a), with (b) documented for forks.
13. **Production compose file.** **Deferred to a future build**, by the human maintainer, 2026-11-18: "If we tinker with this, we could cause delays in shipping version 1. We are already used to the current docker set up. We should not add another element of uncertainty. If it ain't broke, don't fix it. We can revisit this in future builds but you must make sure to document what the benefit really is." SEC.D7.OP.J3.A1 is greyed out. **What it would really gain, for when it's revisited** (each item is today's setup, then what a production file would change):
    - **Speed under load.** Production starts uvicorn with `--reload`, which uvicorn's docs say is for local development, and which can't be combined with `--workers` (https://github.com/Kludex/uvicorn/blob/3eb9a9ab9af69005c687728097461c1fd2a95db9/docs/deployment/index.md). So the app runs as one process on one CPU core however big the server is, and spends effort watching files. Without `--reload`, several workers use every core.
    - **A deploy that can't change itself.** With `--reload`, any file written into the code folder restarts the server running that file; without it, the running code only changes on a deliberate deploy.
    - **Already true today, so not a gain** (corrected on 2026-11-18; I first listed these as production gains, which was wrong): Flower, Redis Commander, Adminer, Grafana (with its admin/admin login), Loki, promtail (with the Docker socket) and Prometheus run only in development. They sit in the `development` and `celery-development` Compose profiles, which `scripts/makefile/docker_env.sh` switches on only when `ENVIRONMENT=development`, so a production stack never starts them.
    - **A password on Redis.** Redis runs in production whenever Celery is on (the `celery` profile) and has no password; today only its `127.0.0.1` binding protects it.
    - **One bug doesn't become the whole database.** The app connects to Postgres as the superuser. A superuser can read and change every table, drop the database, and run operating-system commands on the database server through `COPY ... FROM PROGRAM` (https://www.postgresql.org/docs/current/sql-copy.html). With its own limited role, one SQL injection or app bug reaches only the app's own tables.
    - **A broken-into container can do less.** Dropping the Linux capabilities the app, worker, database and Redis containers don't need, and `no-new-privileges`, shrink what someone who breaks into one can do next.
    - **The same deploy every time.** An image pinned by digest can't change under the same tag, so a deploy that worked last week runs exactly the same code today.
    - **How much this matters:** little while the template runs on a laptop or a private server, and most of it is already softened by every port listening on `127.0.0.1`. It matters once the app serves real customers on a server other people can reach.

    The options, as scored: (a) A `docker-compose.prod.yml` override: production settings visible in one file, the development file unchanged. Score 8. (b) One file with environment switches: fewer files, more conditionals. Score 5. Recommended: (a).
14. **TLS reverse proxy.** **Decided: ship an optional nginx and certbot service, off by default**, by the human maintainer, 2026-11-18, replacing the same day's "ship no proxy; document what it must do": "Lets implement this rather than expect a 3rd party to guarantee that we wont be caught with our pants down." A Docker Compose profile turns it on: on a host that already provides HTTPS it stays off and nothing changes; on a plain server, nginx ends HTTPS with a free Let's Encrypt certificate that certbot renews; locally, the same nginx uses a self-signed certificate. It adds one service and changes none of the existing ones (Decision 13 still holds). nginx with certbot is the long-standing convention, as the ground rule asks. Two limits, stated plainly: Let's Encrypt is itself a third party (any certificate browsers trust comes from a certificate authority), and the Let's Encrypt half can only be proven on a real server with a real domain name, so that human check waits until one exists. The earlier decision, kept for the record: ship no proxy; document what it must do, after re-scoring under the ground rule and Decision 13. Why: the original author planned no proxy (his last `docker-compose.yml` ran only the app and Postgres, on `127.0.0.1`; his `ROOT_PATH` setting is for running behind someone else's proxy); uvicorn's deployment docs say a managed environment already provides the proxy and recommend nginx when self-hosting (https://github.com/Kludex/uvicorn/blob/3eb9a9ab9af69005c687728097461c1fd2a95db9/docs/deployment/index.md); and templates that do ship one put it in a separate production compose file (FastAPI's full-stack template ships Traefik in `compose.deploy.yml`: https://github.com/fastapi/full-stack-fastapi-template; cookiecutter-django ships Traefik and nginx: https://github.com/cookiecutter/cookiecutter-django), which Decision 13 deferred. The options, re-scored: (a) document the requirements, ship no proxy: no Docker change; nothing tests the operator's proxy. Score 7. (b) ship nginx, the convention, with certbot: a new container and certificate renewal before version 1.0. Score 6. (c) ship Caddy: less conventional, also a new container. Score 5. *First scored, before the ground rule: Caddy 8, nginx 6, Traefik 5.*
15. **Scope for existing API keys.** **Deferred with scoped API keys (Decision 17).** (a) `read_write` and every organization: existing integrations keep working; new keys default to `read`. Score 7. (b) `read` for existing keys: fails closed, silently breaks integrators (pre-1.0, one CHANGELOG line). Score 6. Recommended: (a).
16. **Human checks with pen-testing tools.** **Decided: (a)**, by the human maintainer, 2026-11-18: curl does most checks, and each domain ends with the tools that prove what curl can't (oha for D1, ZAP's passive scan for D2 and D3, sqlmap for D3; testssl.sh once a deployment has HTTPS). ZAP and sqlmap run only against a throwaway stack. (a) Use them (oha, ZAP, sqlmap, testssl.sh; about 1.3 GB, mostly ZAP's image): the checks attack the app as an attacker would. Score 8. (b) curl only: lighter, but proves only what the checks were written to send. Score 6. Recommended: (a).
17. **What to defer so the plan fits two to four weeks for a solo developer.** **Decided** by the human maintainer, 2026-11-18, item by item:
    - **The second factor (SEC.D4.US.J2.A3, SEC.D4.US.J3.A1, and the second-factor emails in SEC.D4.SY.J1.A1): deferred to a future plan.** Greyed out in the stories file. Until then a correct stolen password logs in, made rarer by the breached-password check. Its design above stays as the starting point.
    - **Scoped API keys (SEC.D6.IN.J1.A1, A2): deferred to a future plan.** First chosen for plan 17, then deferred the same day once the fix was spelled out. The human maintainer: "API keys are user scoped and have same authorizations as a user. Organization security is already taken care of by the fact that organizations determine who their members and admins are and public API endpoints for API keys only has READ and no WRITE endpoints. We should not overcomplicate a codebase for a small enterprise." Recorded for accuracy: a key can make one change, revoking its owner's own keys (`DELETE /public/v1/api-keys/{id}/`); that stays an accepted risk until the stories return. Decision 15 is deferred with them.
    - **The optional phone number: not built** (Decision 9).
    - **The privacy-notice route (SEC.D5.US.J2.A1): built in plan 17, backend only.** "We can always frontload any backend work now because the front end will be ready by the time we are done with security plan 17." Showing it comes with plan 18.
    - **The Redis rate-limit adapter: a priority, never deferred** (see D1's design).
18. **Limiting production logs.** **Decided: (a)**, by the human maintainer, 2026-11-18. Production logs are the `app` and `worker` containers' own output, which Docker keeps with no rotation by default, so with personal information in them (SEC.D5.SY.J1.A2) they would be kept for ever, against POPIA s14. (a) Docker's own log rotation: a `logging:` block on `app` and `worker` in `docker-compose.yml` (for example 10 files of 50 MB each); the limit is by size, not by days; no new service, and Loki and Grafana, which run only in development, stay as they are. Score 7. (b) Leave Docker as it is and document that the host must rotate logs. Score 5.

## Proposed changes

### Working method

- **RED/GREEN TDD for every piece of new code** (`agents.md` 2.1); a story that was built before this plan gets tests that pass at once, with no RED possible, said plainly when written.
- **Each step names the stories it serves and their test markers** (`@pytest.mark.story("SEC....")`); the stories file's status columns are updated after each GREEN.
- **Commands:** RED `uv run pytest <file> -v` or `make test-docker-file path=<path>`; GREEN `make check`; the end of each step one full `make test-docker` (`agents.md` 1.3).
- **New tables come from mappings,** then `make migration msg="..."`, never hand-written; trigger SQL lives in a source module (`agents.md` 4.7).

### Steps

Each step: tests first, then production files. Cycle counts are rough (15 minutes each), plus about 3 to 4 hours per domain for its human checks, its `make test-docker` runs and its commit.

**Step 0. Shared groundwork** (about 6 cycles)
- 0a. `APP_TRUSTED_PROXIES` with its loader test; the app factory wraps the app in `ProxyHeadersMiddleware`; `docker-entrypoint.sh` adds `--no-proxy-headers`. Tests: integration, a forged `X-Forwarded-For` from an untrusted peer changes nothing; from a trusted one, the right-most untrusted address wins.
- 0b. The production safety check, starting with the settings that already exist (`COOKIE_SECURE`, `COOKIE_HTTPONLY`, `APP_DEBUG_MODE`, placeholder secrets). Tests: unit, one per refused setting.

**Step 1. D1 Abuse limits** (about 16 cycles)
- 1a. IP bucketing (IPv4, IPv4-mapped IPv6, IPv6 prefix) as a pure function. Unit.
- 1b. `RateLimiter` port and an in-memory fake; the sliding-window arithmetic. Unit.
- 1c. Postgres adapter, mapping, migration. Integration (`with_infra`), including two concurrent hits.
- 1d. Login limits per username and per IP (HTTP), 429 with a fixed `Retry-After`, same for unknown usernames, success clears the username bucket, store failure answers 503. SEC.D1.AT.J1.A1, A2.
- 1e. CLI login per-username limit. SEC.D1.AT.J1.A1.
- 1f. Sign-up limit. SEC.D1.AT.J1.A3.
- 1g. Request limits per IP and per API key (middleware). SEC.D1.AT.J2.A1, SEC.D1.AT.J2.A4.
- 1h. Body size limit (Starlette's middleware, 413 in the app's JSON shape). SEC.D1.AT.J2.A2.
- 1i. Overload guard. SEC.D1.AT.J2.A3.
- 1j. Parameter pollution pinned by one test. SEC.D1.T6.
- 1k. Redis adapter, behind `RATE_LIMIT_STORE`, with Redis running independently of Celery. Integration. A priority: it establishes Redis as shared infrastructure for rate limits now and caching later.

**Step 2. D2 Browser-facing** (about 10 cycles)
- 2a. Cookie `__Host-` prefix and `Secure` deletion on log-out; production check for `COOKIE_SECURE` already in 0b. SEC.D2.AT.J1.A1, A4.
- 2b. Absolute session lifetime. SEC.D2.AT.J1.A6.
- 2c. CSRF tokens (signed double-submit cookie): issuing, checking, login and log-out rotation, `/public` exempt. SEC.D2.AT.J1.A2. About 5 cycles.
- 2d. Security headers middleware, docs pages exempted, HSTS production only. SEC.D2.AT.J1.A3.
- 2e. Tests for what already holds: `HttpOnly`, no CORS headers. SEC.D2.AT.J1.A4, A5.

**Step 3. D3 What errors and inputs reveal** (about 8 cycles)
- 3a. Delete the debug route; `DEBUG_MODE` refused in production (0b). SEC.D3.AT.J1.A1.
- 3b. Pin both apps' 500 bodies. SEC.D3.AT.J1.A2.
- 3c. CLI login: rules first, dummy hash. SEC.D3.AT.J1.A3.
- 3d. HTTP login: dummy hash for unknown usernames. SEC.D3.AT.J1.A4.
- 3e. Pin SQL injection and log injection behaviour. SEC.D3.AT.J2.A1, SEC.D3.T7.
- 3f. Hide `/docs` and `/redoc` of both apps in production; protect `/metrics`.

**Step 4. D4 Account recovery and trust** (about 23 cycles, with the second factor deferred)
- 4a. Token value object and hasher label. Unit.
- 4b. Password reset: request, email (token made by the handler), confirm, sessions and keys ended, notification email, clears the login count. SEC.D4.US.J1.A1.
- 4c. Email verification, the unverified allow-list, pending email change with a notice to the old address. SEC.D4.US.J2.A1.
- 4d. Breached-password port, HIBP adapter, bundled list, the switch. SEC.D4.US.J2.A2, SEC.D4.OP.J1.A1.
- 4e. ~~TOTP: enrolment, the pending-second-factor step, recovery codes, turning it off, admin reset, CLI. SEC.D4.US.J2.A3, SEC.D4.US.J3.A1.~~ Deferred to a future plan (Decision 17).
- 4h. Security notification emails for password and email changes. SEC.D4.SY.J1.A1.
- 4f. Admin set-password ends sessions. New threat.
- 4g. Pin password storage. SEC.D4.AT.J1.A1.

**Step 5. D5 Privacy and POPIA** (about 14 cycles)
- 5a. `SET NULL` on the two foreign keys (migration).
- 5b. Export. SEC.D5.US.J1.A1.
- 5c. Pin correction (profile editing). SEC.D5.US.J1.A2.
- 5d. Deletion, with the last-Owner choice and the confirmation email. SEC.D5.US.J1.A3.
- 5e. Privacy notice route and the recorded version. SEC.D5.US.J2.A1.
- 5f. `retention purge` command. SEC.D5.SY.J1.A1.
- 5g. Log protection: Docker log rotation on `app` and `worker` (Decision 18), console sender refused in production, no secret in any log. SEC.D5.SY.J1.A2.
- 5h. Breach runbook command and docs; outside-services list in the wiki. SEC.D5.OP.J1.A1, A2.

**Step 6. D6 Who may do what** (about 14 cycles)
- 6a to 6c. ~~Key scope columns; organization-limited keys; read-only keys and the walk-every-route test. SEC.D6.IN.J1.A1, A2.~~ Deferred to a future plan (Decision 17).
- 6d. `audit_events` table, triggers, writer port. SEC.D6.OP.J1.A1.
- 6e. Each admin action writes its record (one cycle per action).
- 6f. Pin what already holds. SEC.D6.AT.J1.A1, A2.

**Step 7. D7 Running it safely** (about 8 cycles, plus operations work)
- 7a. Upgrade the 29 findings (exact pins), then blocking `pip-audit` in the hook and CI. SEC.D7.OP.J1.A1.
- 7b. ~~`secrets_dir` with its loader test. SEC.D7.OP.J1.A2.~~ Deferred to a future update (Decision 12).
- 7c. Pin the startup secret checks, and the new database, Redis and SMTP password checks. SEC.D7.OP.J1.A3.
- 7d. The optional nginx and certbot service behind the `https` profile, with its local self-signed certificate and `make` target, and the proxy requirements on the deployment wiki page (Decision 14; about 1 to 2 cycles and 5 to 7 hours of configuration and checks), backups and restore scripts, CI hardening, and pinning the 127.0.0.1 port binding. SEC.D7.OP.J2.A1, A2, SEC.D7.OP.J3.A2, SEC.D7.AT.J1.A1. Mostly human checks. (`docker-compose.prod.yml`, SEC.D7.OP.J3.A1, is deferred by Decision 13.)

**Total, after Decisions 12 to 17:** about 95 cycles (about 24 hours of cycles, including the stories the research added), about 25 hours of per-domain overhead, and about 6 hours for the optional HTTPS service (Decision 14): roughly 54 hours, before subtracting the secret store and the production compose file (Decisions 12, 13), which save about 4 hours, so roughly 50 hours. At about 5 focused hours a day that is about 10 working days, so two weeks is tight and four weeks leaves room. The real limit is the human maintainer's review and human-check time.

## File summary

Settled at each step's RED; the main new places are:
- `src/app/base/core/common/ports/`: `rate_limiter.py`, `breached_password_checker.py`, `audit_recorder.py`, `one_time_token_store.py`
- `src/app/shared/outbound/adapters/`: Postgres and Redis rate limiters, HIBP checker
- `src/app/base/inbound/http/`: middlewares for request limits, overload, CSRF and headers; account routes for reset, verification, second factor, export, deletion
- `src/app/base/main/config/`: new settings classes, the production safety check, `loader.py` prefixes
- `src/app/base/main/cli/`: `retention purge`, the breach listing, the CLI second factor
- mappings for `rate_limit_buckets`, `one_time_tokens`, `totp_devices`, `recovery_codes`, `audit_events`; columns on `api_keys`
- `docker-entrypoint.sh`, `docker-compose.prod.yml`, `Caddyfile`, `scripts/backup/`, `.github/workflows/ci.yaml`, `scripts/makefile/pip_audit.sh`, `env.example`, `observability/loki/loki-config.yml`
- docs: the stories file's status columns, `docs/wiki/` security pages, `docs/wiki/content/docker-deployment/production-deployment.md`, `README.md` and `docs/plans/0-production-readiness-roadmap.md` in step (`agents.md` 6.3), `CHANGELOG.md`

## Verification plan

- Unit tests for every value object, pure function, port fake and use case; integration tests (`with_infra`) for every adapter, middleware and route; each tagged with its `SEC` story.
- Every story with no tests of a kind stays red `0/0` in the stories file until it has them.
- Architecture: `lint-imports` (ports in `base`, adapters in `shared`, no new cross-module imports) and `mypy`, both in `make check`.
- One full `make test-docker` at the end of every step, before its human checks and its commit.
- The human checks below, per domain, once that domain's journeys are built (`agents.md` 1.3).

## Human checks

Human checks start here. They are written in full, with exact commands, once each domain's journeys are built (`agents.md` 1.3: "Human checks wait until a domain's journeys are built"); until then this section holds the tool setup, which is real now, and each domain's planned checks.

### Setup: the testing tools

These are white-hat tools: run them only against your own app on your own computer. Each runs in Docker or from a cloned folder; nothing is installed system-wide. Reports go into the project's `logs/` folder, which git ignores. Research and sources: `ai_research/17-security/notes/pentest-tools.md`.

On Linux, a container reaches the app on `127.0.0.1:8000` only with `--network host` (https://docs.docker.com/engine/network/drivers/host/), so every container command below uses it.

**oha**, a load generator, to see 429 and 503 (MIT licence, https://github.com/hatoo/oha). Download its official image, about 65 MB:

```
docker pull ghcr.io/hatoo/oha:1.17.0
```

- `docker pull` downloads an image without running it.
- `ghcr.io/hatoo/oha:1.17.0` is the image on GitHub's registry, pinned to version 1.17.0.

**ZAP**, OWASP's web scanner, to check headers, cookies, errors and injection (Apache-2.0, https://www.zaproxy.org/). About 1.2 GB:

```
docker pull ghcr.io/zaproxy/zaproxy:2.17.0
```

- The full image is needed: the small "bare" one doesn't include the scan scripts.
- **Warning, before any ZAP run:** even its passive mode (`-S`) calls every route once while reading the OpenAPI file, including log-out and the routes that delete things. Its active mode creates, changes and deletes rows. Run ZAP only against a throwaway stack, never one whose data you want.

**sqlmap**, to try SQL injection (GPL-2.0, https://sqlmap.org). It has no official image; it runs with the computer's Python 3:

```
git clone --depth 1 --branch 1.10.11 https://github.com/sqlmapproject/sqlmap.git ~/tools/sqlmap
```

- `--depth 1` downloads only the latest commit, not the whole history.
- `--branch 1.10.11` picks that release.
- `~/tools/sqlmap` is where it lands, outside this project.

**testssl.sh**, to check TLS once a deployment has HTTPS in front (its host's or its own proxy) (GPL-2.0, https://testssl.sh). About 13 MB:

```
docker pull ghcr.io/testssl/testssl.sh:3.2
```

### Planned checks, by domain

Each will follow its journey, prove its starting state, log in each user at its own start, and end by reading the result back (`agents.md` 1.3).

- **D1:** a burst of wrong passwords for one seeded username gets 429 with the same body as an unknown username, and a correct login after the window works (curl). A forged `X-Forwarded-For` doesn't escape the per-IP limit (curl). A flood of requests shows 429 in oha's status-code table. A 2 MiB body gets 413 (curl). An overload run shows 503 (oha, with the limits raised in a throwaway stack). The CLI login is throttled too. Raw SQL shows `rate_limit_buckets` holds no usernames or IP addresses.
- **D2:** the login response's `Set-Cookie` shows `__Host-`, `Secure`, `HttpOnly` and `SameSite=Lax` (curl). A `POST` without the CSRF token gets 403 and changes nothing; the same request with the token works (curl, side by side). Every response carries the headers (ZAP passive scan, rules 10020, 10021, 10038, 10055). A session past its absolute lifetime gets 401.
- **D3:** `/debug/test-error/` gets 404. A production-mode 500 body shows no exception text (ZAP rule 90022). The CLI login gives the same message for an unknown and a real username with a rule-breaking password. sqlmap reports "all tested parameters do not appear to be injectable" for the login body and the admin `sorting_field`.
- **D4:** a password reset journey end to end (request, the email in the console sender in development, the link, the new password, old sessions gone). Email verification and the allow-list. A known breached password refused; the switch off lets it through. Turning on the second factor with an authenticator app, logging in with it, a reused code refused, a recovery code used once.
- **D5:** download my data and compare it with raw SQL. Delete an account that is the last Owner of an organization, with and without the box. `retention purge` removes an expired invitation (raw SQL before and after). `docker inspect` shows the log rotation on the `app` and `worker` containers.
- **D6:** an organization-limited key gets 404 for another organization; a read-only key gets 403 on a write. An admin action shows up in `audit_events`, and a raw `UPDATE` on it is refused.
- **D7:** a blocking `pip-audit` fails on a deliberately pinned vulnerable version in a scratch branch; with the `https` profile on locally, curl and testssl.sh against `https://localhost` show the self-signed certificate, no TLS 1.0 or 1.1, HSTS present and plain HTTP refused; with the profile off, the stack starts exactly as before; on a real server with a domain (when one exists), testssl.sh shows a valid Let's Encrypt certificate and a renewal dry run succeeds; a backup restored into a fresh stack shows the seeded rows.

Human checks end here.

## After this plan

- Apply the accepted story changes to `docs/plans/user-stories/17-security-user-stories.md`, and list `SEC` in `docs/plans/user-stories/README.md`.
- Add a line to `agents.md` 6.1 describing the threat-model rows and the Threat column, if they become part of the template.
- Add plan 17's items to `docs/plans/0-production-readiness-roadmap.md` and the README checklist (`agents.md` 6.3).
