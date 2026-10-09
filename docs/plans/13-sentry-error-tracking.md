# Sentry Error Tracking

## Context

`docs/plans/2-observability.md` already ships Prometheus (metrics), Loki (logs), and Grafana (dashboards over both), plus a hand-rolled, rate-limited email alert for unhandled 5xx errors (`AlertCooldown` + `EmailSender`, in `src/app/inbound/http/errors/alerting.py` / `src/app/inbound/http/errors/exception_middleware.py`). That plan's own closing section ("Free/local vs. paid/cloud") already anticipated this exact gap:

> If per-error-type grouping ever matters more than dashboards, GlitchTip (https://glitchtip.com/) is worth a look -- a self-hosted, open-source, Sentry-API-compatible tool that groups errors by type/stack trace natively, using the same `sentry-sdk` Python client. It'd sit alongside this stack rather than replace it.

This plan fills that gap with Sentry itself, via the official `sentry-sdk` Python client (https://github.com/getsentry/sentry-python). What Sentry adds that Prometheus/Loki/Grafana don't, specifically:

- **Automatic error grouping/fingerprinting + a triage workflow.** Loki lets you search log lines; `app_unhandled_exceptions_total` (Prometheus) counts by type. Neither groups "these 40 log lines across 3 days are the same underlying bug" into one trackable issue with first-seen/last-seen and resolved/regressed state.
- **Full stack trace with local variable values per frame** -- much faster root-causing than a text traceback in a log line, without needing to reproduce locally.
- **Release/deploy correlation** ("this issue first appeared in `release=0.14.2`", "regression since yesterday's deploy") using `AppSettings.VERSION`, which this codebase already threads through as a setting.
- **Dedup-aware alert routing** -- the existing `AlertCooldown` in `alerting.py` is a small, hand-rolled version of exactly this problem; Sentry is the general, mature version of it (this plan does not replace `AlertCooldown`/email alerting -- see "Not in scope" below).

Because the adapter this plan adds talks to the `sentry-sdk` client (not directly to Sentry-the-company's API), swapping the target to a self-hosted GlitchTip instance later is a one-line DSN change, not a rewrite -- GlitchTip is deliberately Sentry-API-compatible.

## User stories

| Story | As a | I want | So that | Acceptance criteria |
|---|---|---|---|---|
| 1. Grouped error reports | maintainer on call | every unhandled server error reported to Sentry (or GlitchTip) with its stack trace | repeats of one bug show up as one trackable issue I can triage | A genuine unhandled error produces exactly one event<br>The event carries `environment` and `release` tags<br>The existing 500 response, log line, metric and alert email still happen |
| 2. No noise from business errors | maintainer on call | ordinary 4xx business errors kept out of Sentry | the issue list only holds real bugs | A mapped 4xx (e.g. a wrong login password) produces zero events |
| 3. Off by default, free tier only | deployment operator | Sentry disabled unless I switch it on, and never sampling traces | the stack runs with no Sentry account and never spends paid quota | With `SENTRY_ENABLED` unset or `false`, nothing is sent<br>The stack starts with no `SENTRY_*` variables set<br>`SENTRY_TRACES_SAMPLE_RATE` defaults to `0.0` |
| 4. Minimal personal data | account holder | only non-identifying context sent to a third-party service | my email, phone number and username don't leave this deployment's own systems | Events carry `user_status` and `user_id` tags only<br>No `email`, `phone_number` or `username` in any event |

## Design

### Where this sits in Clean Architecture -- and why it's deliberately NOT a `core/common/ports/` port

`2-observability.md` §7 already made this call once, for the Prometheus counter: *"No equivalent port exists for the Prometheus counter, deliberately: nothing in `core/` ever needs to record a metric, only the outermost exception handler does, so wrapping it in a port would add indirection with nobody on the other end needing the decoupling."* The same reasoning applies here, and more strongly:

- `EmailSender` earns a real `core/common/ports/` Protocol because (a) genuine `core/` business logic depends on it (`SendWelcomeEmail`, an event handler), and (b) it has two real, environment-selected production implementations (`ConsoleEmailSender`/`SmtpEmailSender`).
- Error reporting to Sentry has neither property. Nothing in `core/` ever needs to report an error to Sentry -- only `GlobalExceptionMiddleware` (an `inbound/http/errors/` concern) does. There is also, in practice, only **one** real implementation (the `sentry-sdk` call itself); "disabled" isn't a second implementation to swap in, it's a config value (`SentrySettings.ENABLED`) gating whether the one implementation's `sentry_sdk.init()` ever ran.

Promoting this to a `core/common/ports/error_reporter.py` Protocol + an `outbound/adapters/sentry_error_reporter.py`/`NoOpErrorReporter` pair would mechanically copy `EmailSender`'s shape onto a case that doesn't share its motivating structure -- exactly the kind of precedent-without-reasoning this codebase's own naming/wiring decisions have repeatedly rejected elsewhere (see `docs/plans/8-public-api-key-auth.md`'s `ApiKeyIdentityProvider` naming discussion). Instead, this plan follows the **`AlertCooldown.clock: Callable[[], float]`** precedent already in `alerting.py`: a plain, injectable callable is the right amount of abstraction when there's exactly one real implementation and the only reason for a seam at all is test substitution, not genuine multi-implementation dependency inversion.

Concretely:
- `src/app/inbound/http/errors/sentry_reporting.py` (new) -- a plain function, `report_to_sentry(exc: Exception, *, context: Mapping[str, str]) -> None`, calling `sentry_sdk.capture_exception(exc)` with `context` attached as Sentry tags. Lives alongside `alerting.py` in the same package, for the same reason `RequestUserContext`/`AlertCooldown` do: this is HTTP-error-handling-adapter logic, not a `core/` or `outbound/adapters/` concern -- there is no repository, external API client, or business port to adapt here, just a call to an already-initialized SDK.
- `GlobalExceptionMiddleware.__init__` gains one more constructor parameter, `report_to_sentry: Callable[[Exception, Mapping[str, str]], None]`, defaulting to the real function above -- exactly how `clock: Callable[[], float] = field(default=time.monotonic)` already works for `AlertCooldown`. Tests inject a spy callable instead of monkeypatching the `sentry_sdk` module.

### Settings: `SentrySettings`, a new, separate class

Mirroring `AlertSettings` being deliberately separate from `EmailSettings` (`2-observability.md` §7's DDD-precision example): `SentrySettings` is its own class, not folded into `AlertSettings`, because "should this exception email an on-call human" and "should this exception be reported to an error-tracking service" are different questions with different toggles, even though both currently gate on "did `GlobalExceptionMiddleware` catch something."

```python
class SentrySettings(BaseModel):
    """Controls whether/how unhandled (5xx-class) server errors are reported
    to Sentry (or a Sentry-API-compatible self-hosted alternative such as
    GlitchTip, via the same DSN-pointed sentry-sdk client).

    Deliberately separate from AlertSettings: whether an on-call human gets
    emailed and whether an error-tracking service records the event are
    independent decisions with independent toggles.
    """

    ENABLED: bool = False
    DSN: str = ""
    # Reuses AppSettings.ENVIRONMENT/VERSION for Sentry's environment/release
    # tags rather than duplicating them here -- there is exactly one
    # environment and one version per running process, not a
    # Sentry-specific one.
    TRACES_SAMPLE_RATE: float = 0.0  # APM/tracing is explicitly out of scope -- see below; 0.0 keeps it off.
```

`main/config/loader.py` reads it the same way every other settings group is read:

```python
class SentryEnvConfig(BaseSettings, SentrySettings):
    model_config = _DEFAULT_CONFIG_DICT | SettingsConfigDict(env_prefix="SENTRY_")


def load_sentry_settings() -> SentrySettings:
    return _load_settings(SentryEnvConfig)
```

### Deliberately disabling Sentry's own automatic Starlette/FastAPI integrations

`sentry_sdk.init()` auto-enables its Starlette/FastAPI integrations by default when those packages are importable, which would let Sentry capture unhandled exceptions on its own, via its own hook, in addition to the explicit `report_to_sentry()` call this plan adds to `GlobalExceptionMiddleware`. That would create a second, implicit "what counts as reportable" path alongside the existing, deliberate one (recall: `GlobalExceptionMiddleware` was built as pure ASGI middleware specifically to avoid a second, implicit exception-handling path duplicating the first -- see `2-observability.md` §6's write-up of the double-logging/traceback bug). `sentry_sdk.init()` is therefore called with `default_integrations=False` and an explicit, minimal `integrations=[]` list, so `GlobalExceptionMiddleware`'s own, already-tested "what's worth alerting on" logic (never business-rule 4xx exceptions, only genuine unhandled errors) stays the single source of truth for what reaches Sentry too.

### Where `sentry_sdk.init()` actually runs

Once, at process startup, in `main/setup.py`, alongside the existing `setup_metrics()`/`setup_global_exception_handlers()` calls -- not per-request, and not inside the DI container (nothing about Sentry initialization needs per-request scoping or swapping):

```python
def setup_sentry(settings: SentrySettings, *, environment: str, release: str) -> None:
    if not settings.ENABLED:
        return
    sentry_sdk.init(
        dsn=settings.DSN,
        environment=environment,
        release=release,
        traces_sample_rate=settings.TRACES_SAMPLE_RATE,
        default_integrations=False,
        integrations=[],
    )
```

### Privacy: a smaller context than the full alert email gets

`_describe_user()` in `alerting.py` already flags that email/phone in logs/alert emails is a deliberate POPIA-relevant choice, redactable in one place if needed. Sentry is a third-party cloud service (unless pointed at a self-hosted GlitchTip), so `report_to_sentry()`'s `context` is deliberately a smaller projection of `RequestUserContext` than the alert email gets -- `user_status` and `user_id` only, never raw `email`/`phone_number`/`username`. The fuller record stays in Loki, which is already self-hosted and already governed by this deployment's own retention/access controls.

### Constraint: free-tier Sentry only, no paid features

Everything in this design stays within Sentry's free "Developer" plan (as of this writing: 5K errors/month, 1 user, error monitoring + basic issue grouping/triage, 30-day retention) -- nothing here requires upgrading:

- **Error capture, tagging, `environment`/`release` correlation** -- all core, free-tier error-monitoring features. This plan uses exactly these and nothing else.
- **Performance monitoring/tracing (APM)** -- has its own separate, smaller free quota and is a distinct product surface from error tracking. `TRACES_SAMPLE_RATE` stays `0.0` (see "Not in scope" below) specifically so this feature never samples a transaction and never touches that quota at all -- not "use it sparingly," but "never use it."
- **Session replay, profiling, and Sentry's own alert-routing/integrations (Slack/PagerDuty/etc.)** -- none of these are used. This plan only ever calls `sentry_sdk.capture_exception()`; it never configures Sentry-side alert rules, since the existing `AlertCooldown`/email mechanism already owns "notify a human," and Sentry's own paid alerting integrations aren't needed to get the grouping/triage value this plan is actually after.
- **Team size/SSO** -- an account-level, not code-level, concern; not something this plan's design can violate either way, but worth naming since a real deployment would still need to keep the Sentry organization itself on the free plan's single-user limit (or accept that cost separately) if this constraint matters beyond the code.

If a future need (e.g. tracing) would require the paid plan, that should be a new, explicit decision -- not something this plan's defaults drift into by accident. `TRACES_SAMPLE_RATE=0.0` and no Sentry-side alert-rule configuration are the two concrete guardrails that keep it that way.

### Not in scope

- **The public API (`PublicApiProvider`), CLI, and Celery worker.** This plan wires Sentry into the private app's `GlobalExceptionMiddleware` only, mirroring the existing alert-email feature's own scope. Extending it to the other entrypoints is a separate, later addition -- each would need its own `sentry_sdk.init()` call at its own composition root (`main/run_public_api.py`, `main/cli/...`, the Celery worker's own startup), not a shared one, since they're independent processes.
- **Performance/tracing (APM).** `TRACES_SAMPLE_RATE` defaults to `0.0` and stays there in this plan. Prometheus/Grafana already cover latency percentiles (`2-observability.md`'s shipped dashboard); Sentry's tracing product would be overlap, not new capability, for this codebase's current needs.
- **Replacing `AlertCooldown`/email alerting.** Both mechanisms run side by side, same as the design section above explains -- a human still gets emailed; Sentry additionally gets a structured, grouped, triageable record of the same event.

## Proposed Changes

Test file(s) before production file(s) per step (RED -> GREEN -> refactor). No production code -- including settings classes, the reporting function, or middleware wiring -- gets written before its test exists and has been run to a confirmed failure.

**Step 1 -- `SentrySettings` + its env-var loader.**
- Test: `tests/unit/main/config/test_loader.py` (extend the existing file) -- `load_sentry_settings()` with no `SENTRY_*` env vars set returns `ENABLED=False`, `DSN=""`, `TRACES_SAMPLE_RATE=0.0`; with `SENTRY_ENABLED=true`/`SENTRY_DSN=...`/`SENTRY_TRACES_SAMPLE_RATE=0.1` set, returns those values.
- Production: `main/config/settings.py` (+`SentrySettings`), `main/config/loader.py` (+`SentryEnvConfig`, `load_sentry_settings()`).

**Step 2 -- `report_to_sentry()`.**
- Test: `tests/unit/inbound/http/errors/test_sentry_reporting.py` -- initializes `sentry_sdk` with a fake in-memory `transport` (the SDK's own supported test seam -- no network, no real DSN) and asserts: calling `report_to_sentry(ValueError("boom"), context={"user_status": "authenticated", "user_id": "123"})` results in exactly one captured event; that event's exception type is `ValueError`; its tags include `user_status`/`user_id` from `context`; `context` never includes (and the captured event never contains) `email`/`phone_number`/`username` keys, since the function's own signature only accepts the smaller projection described above.
- Production: `inbound/http/errors/sentry_reporting.py` (new) -- `report_to_sentry()`.

**Step 3 -- Wire into `GlobalExceptionMiddleware`, gated by `SentrySettings.ENABLED`, with auto-integrations disabled.**
- Test: extend `tests/unit/inbound/http/errors/test_alerting.py` (or a new sibling unit-test file for the middleware itself, matching however `GlobalExceptionMiddleware` is currently unit-tested) with a spy callable in place of `report_to_sentry` -- an unhandled exception calls the spy exactly once, with the original exception and a context dict containing `user_status`; a spy that raises does not prevent the 500 JSON response, the log line, the Prometheus increment, or the alert email (best-effort, matching `_try_send_alert_email`'s existing wrapping).
- Test: extend `tests/integration/with_infra/observability/test_metrics_and_alerting.py` with a fake Sentry transport wired through the real app -- a genuine unhandled exception (hit via the existing `GET /debug/test-error/` debug endpoint) results in exactly one captured Sentry event; a mapped 4xx business exception (e.g. wrong login password) results in zero captured Sentry events, mirroring the existing "4xx never triggers an alert" test in the same file.
- Production: `inbound/http/errors/exception_middleware.py` (+`_try_report_to_sentry`, +constructor parameter), `main/setup.py` (+`setup_sentry()`, call site alongside `setup_metrics()`/`setup_global_exception_handlers()`), `main/run.py` (load `SentrySettings`, pass through).

**Step 4 -- Dependency, Docker/env, and docs/roadmap sync.**
- `pyproject.toml` -- add `sentry-sdk`, exact-pinned (`==`, never `>=`, per this project's standing dependency-pinning convention).
- `.env.example`/`docker-compose.yml` -- `SENTRY_ENABLED` (default `false`), `SENTRY_DSN` (default empty), `SENTRY_TRACES_SAMPLE_RATE` (default `0.0`), each with a safe fallback so the stack still starts with none of them set.
- `docs/plans/0-production-readiness-roadmap.md` / `README.md` -- checklist sync.
- `docs/plans/2-observability.md` -- update its own "Free/local vs. paid/cloud" closing note, which currently just mentions GlitchTip as a hypothetical, to instead point at this plan file now that it's real, planned work.
- Manual verification: with `SENTRY_ENABLED=true` and a real DSN, `make upd`, hit `GET /debug/test-error/`, confirm the event appears in the Sentry (or GlitchTip) dashboard with `environment`/`release` tags set and `user_status`/`user_id` present.

## File Summary

| File | Purpose |
|---|---|
| `src/app/main/config/settings.py` (+`SentrySettings`) | New settings class, deliberately separate from `AlertSettings` |
| `src/app/main/config/loader.py` (+`SentryEnvConfig`/`load_sentry_settings()`) | `SENTRY_`-prefixed env var loading |
| `src/app/inbound/http/errors/sentry_reporting.py` | `report_to_sentry()` -- the one real implementation, no port/adapter pair |
| `src/app/inbound/http/errors/exception_middleware.py` | `GlobalExceptionMiddleware` gains a `report_to_sentry` callable parameter |
| `src/app/main/setup.py` (+`setup_sentry()`) | One-time `sentry_sdk.init()` at startup, auto-integrations disabled |
| `src/app/main/run.py` | Loads `SentrySettings`, passes it through to `setup_sentry()` |
| `pyproject.toml` | `sentry-sdk`, exact-pinned |
| `.env.example`, `docker-compose.yml` | `SENTRY_ENABLED`/`SENTRY_DSN`/`SENTRY_TRACES_SAMPLE_RATE`, safe fallbacks |
| `docs/plans/0-production-readiness-roadmap.md`, `README.md` | Checklist sync |
| `docs/plans/2-observability.md` | Update the closing GlitchTip mention to point at this plan |

## Verification Plan

- **`make check`** -- lint (`ruff`/`mypy --strict`/`slotscheck`) + fast unit tests (Steps 1-3's unit tests, including the fake-transport Sentry tests -- no real network call, no real DSN needed).
- **`make test-docker`** -- full integration suite, including the extended `test_metrics_and_alerting.py`, and every pre-existing suite (proving nothing regressed).
- **Manual verification**, using real entrypoints: `make upd` with `SENTRY_ENABLED=true` and a real Sentry (or GlitchTip) DSN set in `.secrets`, hit `GET /debug/test-error/`, confirm the event appears in the dashboard within a few seconds, tagged with the right `environment`/`release`/`user_status`/`user_id`, and that a routine 4xx (e.g. a bad login attempt) produces no event at all.

## Human checks

**(planned -- to run once Sentry is implemented)** These checks are based only on what this plan specifies; adjust them to the shipped code if the implementation differs.

They trigger errors through the existing debug route `GET http://localhost:8000/debug/test-error/` (`src/app/inbound/http/debug/test_error.py`, mounted under `/debug` in `src/app/inbound/http/root_router.py`), which always raises `ValueError("Test error for alerting - this triggers a 500 and email alert")`. That file is marked "remove after testing"; these checks need it to still exist.

### Setup

1. Create a free-tier Sentry project (or a self-hosted GlitchTip one). Copy its DSN from the project's **Settings > Client Keys (DSN)** page. It's a secret of your own, so it goes only in `.secrets`.
2. In `.secrets`, add these lines, pasting your DSN straight after `SENTRY_DSN=`:
   ```shell
   SEED_DB_WITH_TEST_DATA=true
   SENTRY_ENABLED=true
   SENTRY_DSN=
   ALERT_ENABLED=true
   ALERT_TO_EMAILS=oncall@example.com
   ALERT_COOLDOWN_S=0
   ```
   - `SEED_DB_WITH_TEST_DATA=true` creates `peter-parker` (`SpideySense2024!`), whom checks 2, 3 and 5 log in as. It's `false` in `env.example`.
   - The three `ALERT_*` lines let check 6 see the existing alert email. `EMAIL_USE_CONSOLE=true` (the `env.example` default) writes it to the app's logs instead of sending it. `ALERT_COOLDOWN_S=0` turns off the 300-second per-exception-type cooldown, so every check's error emails, not just the first.
   - Leave `SENTRY_TRACES_SAMPLE_RATE` out, so it stays at its `0.0` default.
3. Restart with the real entrypoint. `make upd` regenerates `.env` from `env.example` plus `.secrets`, and settings are read only at startup:
   ```shell
   make down
   make upd
   ```
4. A login session lasts only **5 minutes** without use (`SessionSettings.TTL_MIN`), so each check that acts as a user logs in at its own start, with its own cookie file in `/tmp`. Run everything in one terminal, top to bottom, with the Sentry project's **Issues** page open in a browser.
5. Set the Compose project name, from the repo root:
   ```shell
   PROJECT=$(grep -h '^APP_SERVICE_NAME=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2)
   PROJECT=${PROJECT:-$(basename "$PWD")}
   echo "$PROJECT"
   ```
   This reads the Compose project name the same way the Makefile does (`APP_SERVICE_NAME`, last value wins, else the folder name), so the direct `docker compose -p "$PROJECT"` commands below look at the same containers `make upd` started.

### Checks

1. **A genuine unhandled error reaches Sentry: `500`, one event.**

   **Why:** an unhandled exception is a real bug, so it must become a Sentry issue with its stack trace. It's `500` because `GlobalExceptionMiddleware` answers every unhandled exception with a 500 JSON body.

   **Acts on:** no seeded data; the request is anonymous (no cookie).

   **Prove** Sentry is switched on and pointed at your project:
   ```shell
   grep -E '^(SENTRY_ENABLED|SENTRY_DSN)=' .env
   ```
   Expect the last `SENTRY_ENABLED` line to be `true`, and a `SENTRY_DSN` line holding your DSN. In the Sentry Issues page, note whether a `ValueError` issue already exists, and its event count. Then trigger the error:
   ```shell
   curl -s -w '\n%{http_code}\n' http://localhost:8000/debug/test-error/
   ```
   Expect `500`. Within a few seconds, expect one new `ValueError` event with the message above and a stack trace through `test_error.py`: a new issue, or the existing one's count up by exactly 1. Because this request was anonymous, its tags show `user_status` `anonymous` and no `user_id`.

2. **A logged-in user's event is tagged with environment, release, user status and user id.**

   **Why:** `environment` and `release` let you see which deployment and version a bug first appeared in. `user_status` and `user_id` let you find who was affected in this deployment's own systems, without sending who they are to a third party. `release` comes from `AppSettings.VERSION` (env var `APP_VERSION`), which defaults to `development`.

   **Acts on:** `peter-parker`, whose user id is saved in `$PETER_ID`.

   **Prove** the values the tags should carry:
   ```shell
   grep -E '^(ENVIRONMENT|APP_VERSION)=' .env
   ```
   Expect `ENVIRONMENT=development` and no `APP_VERSION` line, so `release` should be `development`. If an `APP_VERSION` line shows, expect its last value instead. Log in as `peter-parker`, saving the response so his id can be read from it:
   ```shell
   curl -s -o /tmp/peter-parker-login.json -w '%{http_code}\n' -c /tmp/peter-parker.cookies \
     -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   PETER_ID=$(python3 -c 'import json; print(json.load(open("/tmp/peter-parker-login.json"))["id"])')
   echo "$PETER_ID"
   ```
   Expect `200`, then a UUID. Then, as `peter-parker`, trigger the error:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies http://localhost:8000/debug/test-error/
   ```
   Expect `500`. Open the newest event of the `ValueError` issue. Expect the tags `environment: development`, `release: development` (or your `APP_VERSION`), `user_status: authenticated` and `user_id` equal to the UUID printed above.

3. **No personal data in the event.**

   **Why:** Sentry is a third-party service, so it gets only `user_status` and `user_id`. Email, phone number and username stay in Loki, which this deployment controls. Searching for peter's real values, not just the field names, catches them under any key.

   **Acts on:** `peter-parker`'s seeded email `peter.parker@dailybugle.com`, phone number `27821000011` and username `peter-parker`.

   Log in as `peter-parker`, and trigger an error as him:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies http://localhost:8000/debug/test-error/
   ```
   Expect `200`, then `500`. **Prove** this event is peter's: open the newest `ValueError` event and expect `user_status: authenticated` with a `user_id`. Then use the browser's find-in-page (Ctrl+F) on that event page, including its tags, context and the event's JSON view. Expect no match for `peter.parker@dailybugle.com`, `27821000011` or `peter-parker`, and no `email`, `phone_number` or `username` tag in the tag list.

4. **Repeats group into one issue.**

   **Why:** grouping is the reason to use Sentry at all: the same bug, hit many times, is one issue to triage, with an event count, not many separate issues.

   **Acts on:** no seeded data; anonymous requests.

   **Prove** the starting state: in the Issues page, note how many `ValueError` issues there are (expect one) and its event count. Then trigger the same error three times:
   ```shell
   for i in 1 2 3; do curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/debug/test-error/; done
   ```
   Expect `500` three times. Expect still exactly one `ValueError` issue, with its event count up by 3.

5. **A business 4xx is not reported: `401`, no event.**

   **Why:** a wrong password is an ordinary mistake, mapped to `401` (`AuthenticationError`, in `src/app/inbound/http/account/log_in.py`), not a bug. Reporting it would bury real bugs under noise. It's `401` and not `400` because the password is well-formed (12+ characters, a letter, a digit, a special character), just wrong.

   **Acts on:** `peter-parker`.

   **Prove** the account exists, so the `401` below is about the password and not a missing user:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200` with his profile. In the Issues page, note the number of issues and the `ValueError` event count. Then log in with a wrong password:
   ```shell
   curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "WrongPassword123!"}'
   ```
   Expect `401` with `Not authenticated.`, and after a few seconds no new issue and no new event.

6. **Existing error handling still runs alongside Sentry.**

   **Why:** Sentry is added next to the existing log line, Prometheus counter and alert email, and replaces none of them. A failure in one must not silence the others.

   **Acts on:** no seeded data; an anonymous request.

   **Prove** alerting is on, with no cooldown:
   ```shell
   grep -E '^(ALERT_ENABLED|ALERT_TO_EMAILS|ALERT_COOLDOWN_S|EMAIL_USE_CONSOLE)=' .env
   ```
   Expect the last value of each to be `true`, `oncall@example.com`, `0` and `true`. Then trigger the error, and read the counter:
   ```shell
   curl -s -w '\n%{http_code}\n' http://localhost:8000/debug/test-error/
   curl -s http://localhost:8000/metrics | grep 'app_unhandled_exceptions_total{'
   ```
   Expect `500`, and an `exception_type="ValueError"` counter line with a value above 0. Then show the app's logs (the command prints them and exits):
   ```shell
   docker compose -p "$PROJECT" logs --no-log-prefix app | grep -E 'Unhandled exception|\[ALERT\]'
   ```
   Expect an `Unhandled exception` line with `ValueError` and path `/debug/test-error/`, and an `EMAIL [to=['oncall@example.com']]` line with subject `[ALERT] ValueError on GET /debug/test-error/`. In Sentry, expect the `ValueError` event count up by 1 as well.

7. **No performance data is collected.**

   **Why:** tracing has its own quota on Sentry's free plan, and Prometheus and Grafana already cover latency. `SENTRY_TRACES_SAMPLE_RATE=0.0` means no transaction is ever sampled, so the quota is never touched.

   **Acts on:** no seeded data.

   **Prove** the sample rate is `0.0`:
   ```shell
   grep '^SENTRY_TRACES_SAMPLE_RATE=' .env
   ```
   Expect `SENTRY_TRACES_SAMPLE_RATE=0.0` (from `env.example`) and no other value. Then, in the Sentry project's **Performance** (or **Traces**) page, expect no transactions at all, even after the requests above.

8. **Disabled means silent.**

   **Why:** Sentry is off by default, so the stack must run with no Sentry account and send nothing when switched off. The error itself is still handled: still `500`.

   **Acts on:** no seeded data; an anonymous request.

   In `.secrets`, change `SENTRY_ENABLED=true` to `SENTRY_ENABLED=false`, then restart:
   ```shell
   make down
   make upd
   ```
   **Prove** Sentry is now off and the stack started normally:
   ```shell
   grep '^SENTRY_ENABLED=' .env | tail -1
   curl -s -w '\n%{http_code}\n' http://localhost:8000/healthz/
   ```
   Expect `SENTRY_ENABLED=false`, then `"OK"` and `200`. In the Issues page, note the `ValueError` event count. Then trigger the error:
   ```shell
   curl -s -w '\n%{http_code}\n' http://localhost:8000/debug/test-error/
   ```
   Expect `500`, and after a few seconds no new event. To check the stack also starts with no `SENTRY_*` lines at all, delete both `SENTRY_*` lines from `.secrets` and run the same `make down`, `make upd`, `/healthz/` and `/debug/test-error/` commands: expect the same results. Afterwards, remove the `ALERT_*` lines from `.secrets` too if you don't want them, and run `make down` then `make upd`.
