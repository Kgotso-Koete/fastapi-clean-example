from app.core.common.events.handlers.send_organization_invitation_email import SendOrganizationInvitationEmail
from app.main.worker.container import build_worker_container, close_worker_container

# The invitation email runs in the Celery worker when Celery is enabled
# (docs/plans/9-organizations.md, Step 6b). The worker resolves each handler
# by class from its OWN container (WorkerProvider, not CoreProvider -- see
# app.main.worker.tasks._dispatch), so the handler must be bound there too,
# or every relayed invitation email would fail inside the worker.


async def test_the_worker_container_can_build_the_invitation_email_handler() -> None:
    # The same function a real worker process calls at startup
    # (worker_process_init), with the same settings it would load.
    container = build_worker_container()
    try:
        # One REQUEST scope per task, exactly like tasks._dispatch opens.
        async with container() as request_container:
            handler = await request_container.get(SendOrganizationInvitationEmail)

        assert isinstance(handler, SendOrganizationInvitationEmail)
    finally:
        await close_worker_container()
