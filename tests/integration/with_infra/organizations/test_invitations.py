from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.events.handlers.send_organization_invitation_email import SendOrganizationInvitationEmail
from app.core.common.events.organization_invitation_created import OrganizationInvitationCreatedEvent
from app.core.common.services.user import UserService
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.main.config.loader import load_organization_settings
from app.outbound.adapters.event_serialization import dotted_path
from app.outbound.adapters.outbox_message import OutboxMessage
from app.outbound.persistence_sqla.mappings.outbox_message import event_outbox_table
from tests.integration.with_infra.organizations.helpers import (
    Account,
    add_membership,
    create_organization_as,
    find_membership,
    log_in,
    members_url,
    new_account,
)

# Invitations end to end (docs/plans/9-organizations.md, Step 6): the invite,
# accept and decline routes, through the real HTTP stack, DI container
# (CoreProvider's organization bindings, the ORGANIZATION_INVITATION_TTL_DAYS
# setting) and Postgres. The use cases' own rules are unit-tested in
# tests/unit/core/commands/organizations/; these tests prove the wiring and
# the HTTP status codes.


# --- Helpers ------------------------------------------------------------------
# The shared ones (accounts, logging in, creating an organization, reading a
# membership back) live in helpers.py; these three are invitation-specific.


def _accept_url(organization_id: UUID, membership_id: UUID) -> str:
    return f"{members_url(organization_id)}{membership_id}/accept/"


def _decline_url(organization_id: UUID, membership_id: UUID) -> str:
    return f"{members_url(organization_id)}{membership_id}/decline/"


async def _invite(
    it_client: httpx2.AsyncClient,
    organization_id: UUID,
    invitee: Account,
    role: OrganizationRole | None = None,
) -> httpx2.Response:
    body: dict[str, str] = {"username": invitee.username}
    if role is not None:
        body["role"] = role.value
    return await it_client.post(members_url(organization_id), json=body)


# --- Invite -------------------------------------------------------------------


async def test_invite_returns_201_and_stores_a_pending_invitation_with_the_configured_expiry(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    ttl = timedelta(days=load_organization_settings().INVITATION_TTL_DAYS)
    before = datetime.now(UTC)

    r = await _invite(it_client, organization_id, invitee)

    after = datetime.now(UTC)
    assert r.status_code == 201
    body = r.json()
    membership = await find_membership(it_session, UUID(body["membership_id"]))
    assert membership is not None
    assert membership.user_id == invitee.user_id
    assert membership.role == OrganizationRole.MEMBER
    assert membership.invited_by_user_id == owner.user_id
    assert membership.is_accepted is False
    # The real setting reached the use case: now + TTL, as stored and as returned.
    assert membership.expires_at is not None
    assert before + ttl <= membership.expires_at.value <= after + ttl
    assert datetime.fromisoformat(body["expires_at"]) == membership.expires_at.value


async def test_invite_stages_the_invitation_email_in_the_outbox(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # SendOrganizationInvitationEmail is "background"-mode, so, like the
    # welcome email in test_create_user.py, HybridEventDispatcher.stage()
    # writes its outbox row in the same transaction as the invitation. The
    # worker's drain loop relays it later; nothing has drained it here.
    owner = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)

    r = await _invite(it_client, organization_id, invitee)

    assert r.status_code == 201
    stmt = select(OutboxMessage).where(
        event_outbox_table.c.event_type == dotted_path(OrganizationInvitationCreatedEvent),
        event_outbox_table.c.handler_type == dotted_path(SendOrganizationInvitationEmail),
    )
    outbox_message = await it_session.scalar(stmt)
    assert isinstance(outbox_message, OutboxMessage)
    assert outbox_message.processed_at is None
    # Addressed to the invitee, about this invitation.
    assert outbox_message.payload["invitee_email"] == invitee.email
    assert outbox_message.payload["membership_id"] == r.json()["membership_id"]
    assert outbox_message.payload["inviter_username"] == owner.username


async def test_reinvite_over_an_expired_invitation_renews_the_row_loaded_from_the_database(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # A regression test, found by the human checks (plan 9, Step 6 check 13):
    # re-inviting over an EXPIRED invitation returned 500. The renewal records
    # its OrganizationInvitationCreatedEvent on the membership row that
    # InviteOrganizationMember LOADED from Postgres -- and SQLAlchemy never
    # calls Entity.__init__ when it loads a row, so a loaded entity had no
    # _events list for record_event() to append to. Every earlier event was
    # recorded on a freshly constructed entity, which is why nothing else hit it.
    owner = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    membership_id = UUID((await _invite(it_client, organization_id, invitee)).json()["membership_id"])
    # Expire it directly in the database, like the 410 test below does.
    membership = await find_membership(it_session, membership_id)
    assert membership is not None
    membership.expires_at = UtcDatetime(datetime.now(UTC) - timedelta(minutes=1))
    await it_session.commit()
    before = datetime.now(UTC)

    # Still logged in as the owner (create_organization_as leaves them so).
    # The route runs in its own session, so it loads the expired row fresh.
    r = await _invite(it_client, organization_id, invitee)

    assert r.status_code == 201
    body = r.json()
    # Renewed in place: the same row, not a second one, with a fresh expiry.
    assert UUID(body["membership_id"]) == membership_id
    assert datetime.fromisoformat(body["expires_at"]) > before
    # Two invitation emails staged for this membership: the original
    # invite's, and the renewal's -- the renewal's event really was recorded.
    stmt = select(OutboxMessage).where(
        event_outbox_table.c.event_type == dotted_path(OrganizationInvitationCreatedEvent),
    )
    outbox_messages = (await it_session.scalars(stmt)).all()
    for_this_membership = [m for m in outbox_messages if m.payload["membership_id"] == str(membership_id)]
    assert len(for_this_membership) == 2


async def test_invite_returns_401_when_not_authenticated(it_client: httpx2.AsyncClient) -> None:
    r = await it_client.post(members_url(UUID(int=1)), json={"username": "anyone"})

    assert r.status_code == 401


async def test_invite_returns_403_for_a_member_below_admin(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)
    await log_in(it_client, member)

    r = await _invite(it_client, organization_id, invitee)

    assert r.status_code == 403


async def test_invite_returns_404_for_an_outsider(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # An outsider can't even confirm the organization exists.
    owner = await new_account(it_session, it_user_service)
    outsider = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await log_in(it_client, outsider)

    r = await _invite(it_client, organization_id, invitee)

    assert r.status_code == 404
    # The use case's own message -- a missing route's generic 404 can't
    # produce it, so this can't pass by accident.
    assert "Organization not found." in r.text


async def test_invite_returns_404_for_an_unknown_username(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)

    r = await it_client.post(members_url(organization_id), json={"username": "nobody_by_this_name"})

    assert r.status_code == 404
    # UnknownInviteeError's message, not a missing route's generic 404.
    assert "No active user with that username." in r.text


async def test_invite_returns_403_when_an_admin_tries_to_grant_owner(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    admin = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, admin, OrganizationRole.ADMIN)
    await log_in(it_client, admin)

    r = await _invite(it_client, organization_id, invitee, role=OrganizationRole.OWNER)

    assert r.status_code == 403


async def test_invite_returns_409_when_the_user_is_already_invited(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    first = await _invite(it_client, organization_id, invitee)
    assert first.status_code == 201

    second = await _invite(it_client, organization_id, invitee)

    assert second.status_code == 409


async def test_invite_returns_422_for_a_malformed_organization_id(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # FastAPI rejects the path parameter before the use case ever runs.
    caller = await new_account(it_session, it_user_service)
    await log_in(it_client, caller)

    r = await it_client.post(members_url("not-a-uuid"), json={"username": "anyone"})

    assert r.status_code == 422


# --- Accept -------------------------------------------------------------------


async def test_accept_returns_204_and_the_invitee_becomes_a_member(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    membership_id = UUID((await _invite(it_client, organization_id, invitee)).json()["membership_id"])
    await log_in(it_client, invitee)

    r = await it_client.post(_accept_url(organization_id, membership_id))

    assert r.status_code == 204
    membership = await find_membership(it_session, membership_id)
    assert membership is not None
    assert membership.is_accepted is True
    assert membership.expires_at is None


async def test_accept_returns_404_for_someone_elses_invitation(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    someone_else = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    membership_id = UUID((await _invite(it_client, organization_id, invitee)).json()["membership_id"])
    await log_in(it_client, someone_else)

    r = await it_client.post(_accept_url(organization_id, membership_id))

    assert r.status_code == 404
    membership = await find_membership(it_session, membership_id)
    assert membership is not None
    assert membership.is_accepted is False


async def test_accept_returns_410_for_an_expired_invitation(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    membership_id = UUID((await _invite(it_client, organization_id, invitee)).json()["membership_id"])
    # Push the expiry into the past directly in the database, rather than
    # waiting a week.
    membership = await find_membership(it_session, membership_id)
    assert membership is not None
    membership.expires_at = UtcDatetime(datetime.now(UTC) - timedelta(minutes=1))
    await it_session.commit()
    await log_in(it_client, invitee)

    r = await it_client.post(_accept_url(organization_id, membership_id))

    assert r.status_code == 410


# --- Decline ------------------------------------------------------------------


async def test_decline_returns_204_and_deletes_the_invitation(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    membership_id = UUID((await _invite(it_client, organization_id, invitee)).json()["membership_id"])
    await log_in(it_client, invitee)

    r = await it_client.post(_decline_url(organization_id, membership_id))

    assert r.status_code == 204
    assert await find_membership(it_session, membership_id) is None


async def test_decline_returns_404_for_someone_elses_invitation(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    someone_else = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    membership_id = UUID((await _invite(it_client, organization_id, invitee)).json()["membership_id"])
    await log_in(it_client, someone_else)

    r = await it_client.post(_decline_url(organization_id, membership_id))

    assert r.status_code == 404
    assert await find_membership(it_session, membership_id) is not None


async def test_decline_returns_404_for_an_accepted_membership_and_keeps_it(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # Leaving is RemoveOrganizationMember's job (it guards the last owner);
    # decline only ever removes a pending invitation.
    owner = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    membership_id = UUID((await _invite(it_client, organization_id, invitee)).json()["membership_id"])
    await log_in(it_client, invitee)
    accepted = await it_client.post(_accept_url(organization_id, membership_id))
    assert accepted.status_code == 204

    r = await it_client.post(_decline_url(organization_id, membership_id))

    assert r.status_code == 404
    membership = await find_membership(it_session, membership_id)
    assert membership is not None
    assert membership.is_accepted is True


# --- The whole flow -------------------------------------------------------------


async def test_after_accepting_the_invitee_is_recognised_as_a_member(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # Before accepting, the invitee is an outsider (404 on invite). After
    # accepting, the real MembershipChecker sees them as a MEMBER, so the
    # same request is refused for being below ADMIN (403) instead.
    owner = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    third_party = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    membership_id = UUID((await _invite(it_client, organization_id, invitee)).json()["membership_id"])
    await log_in(it_client, invitee)

    before_accepting = await _invite(it_client, organization_id, third_party)
    accepted = await it_client.post(_accept_url(organization_id, membership_id))
    after_accepting = await _invite(it_client, organization_id, third_party)

    assert before_accepting.status_code == 404
    assert accepted.status_code == 204
    assert after_accepting.status_code == 403
