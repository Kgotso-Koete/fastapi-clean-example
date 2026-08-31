# Email (SMTP)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/core/common/ports/email_sender.py`](../../../../src/app/core/common/ports/email_sender.py) — the `EmailSender` **port** (a `Protocol` — an abstract interface `core` declares without knowing which concrete adapter satisfies it; see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md)), the only thing `core` knows about
    - [`src/app/outbound/adapters/console_email_sender.py`](../../../../src/app/outbound/adapters/console_email_sender.py) — `ConsoleEmailSender`, the dev/test adapter
    - [`src/app/outbound/adapters/smtp_email_sender.py`](../../../../src/app/outbound/adapters/smtp_email_sender.py) — `SmtpEmailSender`, the real adapter (any SMTP (Simple Mail Transfer Protocol) provider)
    - [`src/app/core/common/events/handlers/send_welcome_email.py`](../../../../src/app/core/common/events/handlers/send_welcome_email.py) — `SendWelcomeEmail`, the one domain-event handler that uses this port today
    - [`src/app/main/ioc/core.py`](../../../../src/app/main/ioc/core.py) — `CoreProvider.provide_email_sender()`, the web process's port-to-adapter wiring
    - [`src/app/main/worker/provider.py`](../../../../src/app/main/worker/provider.py) — `WorkerProvider.provide_email_sender()`, the worker process's own (deliberately duplicated) wiring
    - [`env.example`](../../../../env.example) — every `EMAIL_*` variable

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## The port, and the swap

`core` depends only on `EmailSender` — a `Protocol` with one method, `send(*, to_emails, subject, html_body, cc_emails=(), bcc_emails=())` — and never knows or cares whether an email actually goes anywhere. Two adapters fulfill it: `ConsoleEmailSender`, which just logs the email at `INFO` instead of sending it, and `SmtpEmailSender`, which sends a real message via `aiosmtplib` against any SMTP provider (Brevo, Mailgun, SES, ...). Which one gets wired in is decided purely by `EmailSettings.USE_CONSOLE` — no code change, ever, to switch providers or to go from local dev to a real mailbox.

!!! figure "Port/adapter swap: which EmailSender gets built"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        core["core: depends only on\nthe EmailSender port"] --> usecheck{"EMAIL_USE_CONSOLE?"}
        usecheck -->|true, default| console["ConsoleEmailSender\n(logs the email, sends nothing)"]
        usecheck -->|false| smtp["SmtpEmailSender\n(aiosmtplib, any SMTP host)"]
        smtp --> provider[("your SMTP provider\nBrevo / Mailgun / SES / ...")]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

This wiring is deliberately duplicated, not shared, between the two processes that need it: `CoreProvider.provide_email_sender()` (web process, `main/ioc/core.py`) and `WorkerProvider.provide_email_sender()` (worker process, `main/worker/provider.py`) are separate `@provide` methods with identical bodies. That's a conscious trade-off documented directly in `WorkerProvider`'s own docstring: the worker's whole provider set is built to stay independent of `CoreProvider`/`AuthProvider` so that deleting `app.main.worker` entirely would need zero changes to the web process's wiring — a small amount of duplicated plumbing accepted in exchange for that isolation.

## Where `SendWelcomeEmail` plugs into domain events

`SendWelcomeEmail` is a concrete `EventHandler[UserRegisteredEvent]` — a subscriber to a **domain event** (see [Core Patterns → Domain Events & Outbox](../core-patterns/domain-events-outbox.md) for what a domain event is and how it's staged/dispatched) — it depends on `EmailSender` (the port, never a concrete adapter) and does nothing Celery-specific at all. It declares `DISPATCH_MODE: ClassVar[Literal["sync", "background"]] = "background"`, since a new user doesn't need to wait for their welcome email before their signup response returns.

!!! figure "From UserRegisteredEvent to a sent (or logged) email"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        signup["SignUp.execute()"] --> event["User.register()\nrecords UserRegisteredEvent"]
        event --> registry["CoreProvider's handler registry:\nUserRegisteredEvent -> [SendWelcomeEmail]"]
        registry --> dispatcher["HybridEventDispatcher\nsees DISPATCH_MODE='background'"]
        dispatcher --> outbox[("staged in event_outbox,\nrelayed by the worker")]
        outbox --> handler["SendWelcomeEmail.handle(event)\n(running in the worker process)"]
        handler --> sender["EmailSender.send(...)"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > Because `SendWelcomeEmail` is registered in `CoreProvider.provide_handler_registry()` (a plain `dict[type[DomainEvent], Sequence[EventHandler[Any]]]`, mapping `UserRegisteredEvent` to `[send_welcome_email]`), adding a *second* subscriber to the same event — say, an analytics handler — is a one-line addition to that dict, with zero changes to `SendWelcomeEmail` itself. Since its `DISPATCH_MODE` is `"background"`, the actual `.handle(event)` call happens inside the worker process (see [Background Jobs](background-jobs.md) for the full staging/relay mechanism and the `CELERY_ENABLED=false` inline fallback) — which is exactly why `WorkerProvider` needs its own `EmailSender` wiring: the handler that calls it runs there, not in the web process.

## `env.example`'s `EMAIL_*` variables

| Variable | Default | Notes |
|---|---|---|
| `EMAIL_USE_CONSOLE` | `true` | the switch in the diagram above; `true` means nothing ever really leaves the machine |
| `EMAIL_SMTP_HOST` | `smtp-relay.brevo.com` | any SMTP provider's host works here |
| `EMAIL_SMTP_PORT` | `587` | `465` selects implicit TLS (Transport Layer Security) instead of STARTTLS — `SmtpEmailSender` picks `use_tls`/`start_tls` based on this port |
| `EMAIL_SMTP_USERNAME` / `EMAIL_SMTP_PASSWORD` | *(empty)* | provider credentials |
| `EMAIL_SMTP_USE_TLS` | `true` | |
| `EMAIL_FROM_EMAIL` / `EMAIL_FROM_NAME` | `noreply@yourdomain.com` / `Your Company Name` | the `From:` header on every outgoing email |

`bcc_emails` (used by the [alerting path](observability.md), not by `SendWelcomeEmail`) are only ever passed via the SMTP envelope's `recipients` list, never as a `Bcc:` message header — a header would defeat the point by revealing every bcc'd address to every other recipient.

## Where to go next

- [Background Jobs (Celery / Redis)](background-jobs.md) — how a `"background"`-mode handler like `SendWelcomeEmail` actually gets from an HTTP (Hypertext Transfer Protocol) request to a running worker process.
- [Observability (Prometheus, Grafana, Loki)](observability.md) — the other consumer of this same `EmailSender` port, for 5xx alert emails.
- [Core Patterns → Domain Events & Outbox](../core-patterns/domain-events-outbox.md) — the domain-events mechanism `SendWelcomeEmail` is a subscriber of.
