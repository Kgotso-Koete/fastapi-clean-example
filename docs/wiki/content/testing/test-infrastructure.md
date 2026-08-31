# Test Infrastructure & Fixtures

!!! sourcefiles "Relevant Source Files/Folders"
    - [`tests/integration/conftest.py`](../../../../tests/integration/conftest.py) — the `allow_destructive` safety-guard fixture shared by everything under `tests/integration/`
    - [`tests/integration/with_infra/conftest.py`](../../../../tests/integration/with_infra/conftest.py) — the real-Postgres, eager-Celery fixture chain
    - [`tests/smoke/conftest.py`](../../../../tests/smoke/conftest.py) — the plain `make_app()` fixture smoke tests run against
    - [`tests/integration/no_infra/`](../../../../tests/integration/no_infra/) — currently an empty tier (just an `__init__.py`), reserved for FastAPI-level tests that don't need Docker
    - [`docker-compose.test.yml`](../../../../docker-compose.test.yml) — the compose overlay that actually provisions Postgres/Redis/worker for the `with_infra`/`smoke` tiers

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## The test-tier pyramid

This project's tests aren't one undifferentiated `tests/` folder — they're split into tiers by how much real infrastructure they need, verified directly against the directory layout under [`tests/`](../../../../tests/):

!!! figure "Test tiers, bottom to top, mapped to the infrastructure each one needs"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph unit["tests/unit + tests/sanity"]
            u1["fast, in-process<br/>fakes/stubs only<br/>(e.g. StubPasswordHasher)"]
        end
        subgraph noinfra["tests/integration/no_infra"]
            n1["reserved tier --<br/>currently empty<br/>(just __init__.py)"]
        end
        subgraph withinfra["tests/integration/with_infra"]
            w1["real Postgres via db_pg<br/>eager (in-process) Celery --<br/>no real Redis round-trip"]
        end
        subgraph smoke["tests/smoke"]
            s1["real worker + redis<br/>containers, a real<br/>broker round-trip"]
        end

        noinfra_infra[("no Docker")]
        withinfra_infra[("db_pg only")]
        smoke_infra[("db_pg + redis + worker")]

        unit -.->|needs| noinfra_infra
        noinfra -.->|needs| noinfra_infra
        withinfra -.->|needs| withinfra_infra
        smoke -.->|needs| smoke_infra

        unit --> noinfra --> withinfra --> smoke

        linkStyle default stroke-width:3px,stroke:#333333
        style unit stroke-width:1px,stroke:#333333
        style noinfra stroke-width:1px,stroke:#333333
        style withinfra stroke-width:1px,stroke:#333333
        style smoke stroke-width:1px,stroke:#333333
    ```

    > Left to right is increasing infrastructure weight, not increasing importance. `tests/unit` (29 test modules at the time of writing) and `tests/sanity` need nothing but the Python process itself — value objects, entities, and services (the Domain-Driven Design building blocks; see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) for what each means) are exercised directly, with fakes standing in for ports — abstract interfaces `core` declares without implementing, also explained on that same page — like `PasswordHasher`. `tests/integration/no_infra` is a reserved tier for FastAPI-level tests (real ASGI (Asynchronous Server Gateway Interface) app, real routing/DI (Dependency Injection) wiring) that still don't touch a database — it exists in the directory tree and in the `Makefile`'s [`PYTEST_PATHS_LIGHT`](running-tests.md) grouping, but has no test modules in it yet, only its `__init__.py`. `tests/integration/with_infra` (12 test modules) runs against a real Postgres container but keeps Celery in *eager* mode — no real Redis, no real broker round-trip, no separate worker process — see below. `tests/smoke` (2 test modules) is the only tier that talks to a real, separately-running `worker` container over a real `redis` broker; [`docker-compose.test.yml`](../../../../docker-compose.test.yml) is what actually brings `db_pg`/`redis`/`worker` up for the `with_infra` and `smoke` tiers together, via `make test-docker` (see [Running Tests](running-tests.md)).

## `tests/integration/conftest.py` — the shared destructive-cleanup guard

Every fixture under `tests/integration/` (both `no_infra` and `with_infra`) can reach this fixture, defined in [`tests/integration/conftest.py`](../../../../tests/integration/conftest.py), since conftest fixtures apply to everything at or below their own directory:

```python
@pytest.fixture(scope="session")
def allow_destructive() -> None:
    """Use on fixtures that require potentially dangerous cleanup."""
    if os.getenv(ALLOW_DESTRUCTIVE_TEST_CLEANUP) != ALLOW_DESTRUCTIVE_TEST_CLEANUP_EXPECTED_VALUE:
        raise pytest.UsageError(...)
```

It's a trip-wire, not a resource: any fixture that's about to do something destructive (in practice, truncating every table between tests) depends on `allow_destructive`, which immediately raises unless `ALLOW_DESTRUCTIVE_TEST_CLEANUP=1` is set in the environment. [`docker-compose.test.yml`](../../../../docker-compose.test.yml) sets that variable on the `app` service specifically for test runs, and CI (Continuous Integration) sets it explicitly for `make test-docker` — so a developer who accidentally points these tests at a real, non-test database without that variable gets a clear `UsageError` instead of a silently truncated table.

## `tests/integration/with_infra/conftest.py` — real Postgres, eager Celery

This is the tier that talks to real infrastructure. Its fixtures form a dependency chain, each layer built on the one before it:

!!! figure "The with_infra fixture chain"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        app["it_fastapi_app<br/>make_app() + _EagerCeleryProvider"]
        runtime["it_worker_runtime<br/>(autouse) primes the worker's<br/>loop_runtime + container"]
        client["it_client<br/>real ASGI lifespan +<br/>httpx2.AsyncClient"]
        maker["it_sessionmaker<br/>async_sessionmaker pulled<br/>out of the DI container"]
        clean["it_db_clean<br/>TRUNCATE every mapped<br/>table, RESTART IDENTITY"]
        session["it_session<br/>one AsyncSession,<br/>post-cleanup"]
        userservice["it_user_service<br/>UserService pulled<br/>out of the DI container"]

        app --> runtime
        app --> client
        client --> maker --> clean --> session
        client --> userservice

        linkStyle default stroke-width:3px,stroke:#333333
    ```

What each fixture actually provides:

- **`it_fastapi_app`** builds the real app via `make_app()`, with one deliberate override: `_EagerCeleryProvider` swaps in the *worker's own* `Celery` object (not a fresh one) with `task_always_eager=True, task_eager_propagates=True`. This matters specifically because a Celery task is only registered on the exact object that decorated it — `app.main.worker.tasks` registers `dispatch_event_handler_task` against the worker's `celery_app`, so running the *real* task body (not just proving a message was published) means dispatching through that same object, synchronously, in-process. No Redis round-trip happens in this tier at all.
- **`it_worker_runtime`** is `autouse=True`: it calls `loop_runtime.start_loop()` and points `get_worker_container()` at this test's own app container — the same priming a real worker process does once at startup via `worker_process_init` — so a "background"-dispatch event handler resolves through this test's DI overrides (e.g. a spy email sender) instead of a real worker's container.
- **`it_client`** wraps the app in `asgi_lifespan.LifespanManager` (so startup/shutdown hooks actually run) and returns an `httpx2.AsyncClient` talking to it over ASGI transport — no real TCP (Transmission Control Protocol) socket.
- **`it_sessionmaker`** and **`it_user_service`** both pull real objects straight out of the app's own Dishka container (`async_sessionmaker[AsyncSession]` and `UserService` respectively) rather than constructing parallel ones, so tests exercise the exact same objects the app's own request handling uses.
- **`it_db_clean`** truncates every table the ORM (Object-Relational Mapping) mapper registry knows about (except `alembic_version`) before each test, gated behind `allow_destructive`.
- **`it_session`** depends on `it_db_clean`, guaranteeing a clean table set before the session it hands back is ever used.

## `tests/smoke/conftest.py` — the plainest possible app, against real containers

[`tests/smoke/conftest.py`](../../../../tests/smoke/conftest.py) defines the plainest possible fixtures:

```python
@pytest.fixture
def smoke_app() -> FastAPI:
    return make_app()

@pytest.fixture
async def smoke_client(smoke_app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    async with (
        LifespanManager(smoke_app, startup_timeout=60) as manager,
        httpx2.AsyncClient(transport=..., base_url="http://test") as client,
    ):
        yield client
```

No DI overrides at all — `make_app()` is called exactly as production would call it, reading real settings from the environment `docker-compose.test.yml` sets up. `tests/smoke/inbound/http/test_health_router.py` uses this to hit `/livez/`/`/healthz/`/a 404 case for real. `tests/smoke/test_celery_broker.py` goes further and builds its *own*, wholly separate `Celery` producer (`_build_standalone_celery_app()`, no eager mode) pointed at the real `redis` + `worker` containers `make test-docker` brings up, publishes one real message, and blocks on `AsyncResult.get()` until the real, separately-running `worker` container picks it up — the one place in this whole test suite that proves the actual broker/queue/serializer wiring, rather than an in-process stand-in for it.

## Where to go next

- [Running Tests](running-tests.md) — the `make` targets and `PYTEST_PATHS_*` groupings that decide which of these tiers actually runs, and what brings up `db_pg`/`redis`/`worker` for the ones that need them.
- [Test Factories](test-factories.md) — the builder functions used inside these fixtures (and the tests built on top of them) to construct `User` entities without repeating setup boilerplate.
- [Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md) — the background-dispatch mechanism `_EagerCeleryProvider` and `it_worker_runtime` exist to test without a real broker.
