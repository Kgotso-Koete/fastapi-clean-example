# TDD (Red-Green-Refactor)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`docs/plans/4-transactional-outbox.md`](../../../../docs/plans/4-transactional-outbox.md) — Step 4's "TDD order" line is this page's worked example
    - [`docs/plans/3-celery-redis-events.md`](../../../../docs/plans/3-celery-redis-events.md) — a second, shorter worked example
    - [`tests/unit/main/worker/test_drain_outbox.py`](../../../../tests/unit/main/worker/test_drain_outbox.py) — the RED test written before `_drain_outbox()` existed
    - [`src/app/main/worker/outbox_drain_loop.py`](../../../../src/app/main/worker/outbox_drain_loop.py) — the GREEN implementation that test now exercises
    - [`tests/unit/core/common/events/handlers/test_send_welcome_email.py`](../../../../tests/unit/core/common/events/handlers/test_send_welcome_email.py) — the smaller, one-assertion worked example below

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## The convention

Every implementation plan under [`docs/plans/`](https://github.com/ivan-borovets/fastapi-clean-example/tree/master/docs/plans) breaks a feature into numbered steps, and almost every step opens with a line literally labeled **"TDD order:"** — a short sentence naming the test file(s) to write first, then `→ RED →`, then the production file(s) to create or modify, then `→ GREEN`. This isn't a stylistic flourish: it's a real, followed-in-practice constraint on the order code gets written in, going all the way back through this project's own git history. Refactor is the implicit third beat — once a step is GREEN, the plan's own prose (architectural decisions, naming, the "why" behind a structure) is what a following cleanup pass is checked against, rather than a separately-labeled step.

!!! figure "The red-green-refactor cycle"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        red["RED<br/>write a failing test<br/>for behavior that<br/>doesn't exist yet"]
        green["GREEN<br/>write the smallest<br/>production code that<br/>makes it pass"]
        refactor["REFACTOR<br/>clean up naming/structure<br/>with the test suite<br/>still green"]

        red --> green --> refactor --> red

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > This shows one lap of the cycle: a test is written against code that doesn't exist (or doesn't yet do the new thing), it fails for exactly that reason (RED), the minimum code to satisfy it is added (GREEN), and only then is the result cleaned up — still under the same passing tests — before the next lap starts on the next piece of behavior. Each step of a `docs/plans/*.md` file is one or a few laps of this cycle, not the whole feature at once.

## A real example: draining the transactional outbox

[`docs/plans/4-transactional-outbox.md`](../../../../docs/plans/4-transactional-outbox.md)'s Step 4 states its TDD (Test-Driven Development) order like this (lightly reformatted, not paraphrased):

> write `tests/unit/main/worker/test_drain_outbox.py` (fakes for the repository and `celery_app`; a case with retention on asserting `mark_processed()` is called, `delete()` is not, and `commit()` is called exactly once for the batch; a case with retention off asserting `mark_processed()`/`delete()`/one `commit()`) and `tests/unit/main/worker/test_outbox_drain_loop.py` (the perpetual-loop wrapper: a failed tick is logged and swallowed, the loop keeps ticking afterward, and it sleeps the configured interval between ticks) → RED → create the files below → GREEN.

That is exactly what the repository contains today:

!!! figure "One step of the outbox-drain feature, RED to GREEN"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph before["RED"]
            test["test_drain_outbox.py<br/>imports _drain_outbox<br/>from a module that<br/>doesn't exist yet"]
            fail(["ImportError /<br/>collection failure"])
            test --> fail
        end

        subgraph after["GREEN"]
            impl["outbox_drain_loop.py<br/>_drain_outbox() written<br/>to satisfy every case"]
            pass(["all 5 test cases pass"])
            impl --> pass
        end

        before -->|"implementation added"| after

        linkStyle default stroke-width:3px,stroke:#333333
        style before stroke-width:1px,stroke:#333333
        style after stroke-width:1px,stroke:#333333
    ```

Concretely, [`tests/unit/main/worker/test_drain_outbox.py`](../../../../tests/unit/main/worker/test_drain_outbox.py) hands `_drain_outbox()` a fake `OutboxRepository` (an `AsyncMock`) and a fake Celery client (a plain `Mock`) — no database, no broker — and asserts on how `_drain_outbox` calls them:

```python
async def test_marks_processed_but_does_not_delete_when_retention_is_on(self) -> None:
    message = _make_message()
    outbox = AsyncMock()
    outbox.get_pending.return_value = [message]
    celery = Mock()

    await _drain_outbox(outbox, celery, retain_after_relay=True)

    outbox.mark_processed.assert_called_once_with(message)
    outbox.delete.assert_not_called()
    outbox.commit.assert_called_once()
```

Before [`src/app/main/worker/outbox_drain_loop.py`](../../../../src/app/main/worker/outbox_drain_loop.py) existed, this test failed at collection — `_drain_outbox` had nothing to import. That failure *is* RED: proof the test can actually detect the missing behavior, not a tautology that would pass regardless of whether the feature exists. Only once that failure was in hand did the plan call for writing the real `_drain_outbox()` body (relay each pending row via `send_task(..., task_id=str(message.id_))`, then `mark_processed()`/`delete()` depending on the retention setting, then a single `commit()` for the whole batch) — turning the same test GREEN, along with `test_outbox_drain_loop.py`'s cases for the perpetual-loop wrapper around it.

## A smaller example: a one-line behavior change

Not every step is this involved. [`docs/plans/3-celery-redis-events.md`](../../../../docs/plans/3-celery-redis-events.md) Step 2 is a single-assertion example of the same discipline at a much smaller scale:

> extend `tests/unit/core/common/events/handlers/test_send_welcome_email.py` to assert `SendWelcomeEmail.DISPATCH_MODE == "background"` → RED → modify `src/app/core/common/ports/event_handler.py` (add `DISPATCH_MODE: ClassVar[Literal["sync", "background"]]`) and `send_welcome_email.py` (`DISPATCH_MODE: ClassVar[...] = "background"`) → GREEN.

Here RED is a plain `AttributeError` — `SendWelcomeEmail.DISPATCH_MODE` doesn't exist until the port's `Protocol` declares it and the concrete handler sets it — and GREEN is exactly the two-line addition the plan names, nothing more. The size of the step varies; the RED-before-GREEN order does not.

## Why this order, not "write the code, then test it"

Writing the test first forces it to fail for the *right* reason — a missing class, a missing attribute, a specific assertion — rather than passing by accident because it was written to match whatever the code already does. A test that has never failed hasn't proven it can fail, which is exactly the gap TDD closes. Every step in [`docs/plans/*.md`](https://github.com/ivan-borovets/fastapi-clean-example/tree/master/docs/plans) that carries a "TDD order" line is following this same discipline, one lap of the cycle per described chunk of behavior.

## Where to go next

- [Test Infrastructure & Fixtures](test-infrastructure.md) — what actually backs the tests these TDD steps write (unit fakes vs. real Postgres/Redis vs. a real worker).
- [Running Tests](running-tests.md) — the `make` targets that run these tests, light and full-infra alike.
- [Test Factories](test-factories.md) — the builder functions these tests use to construct entities like `User` without repeating setup boilerplate.
