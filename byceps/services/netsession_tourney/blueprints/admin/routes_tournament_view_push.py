"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament_view_push
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Notification, push recipient and tournament admin data of the
tournament detail page (see `routes_tournament_view`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from byceps.services.netsession_tourney import (
    browser_push_service,
    discord_dm_service,
    participant_state,
    tournament_admin_service,
)
from byceps.services.party.models import PartyID
from byceps.services.user import user_service


def _collect_push_status(
    party_id: PartyID, tournament_id: Any
) -> dict[str, Any]:
    browser_push_config = browser_push_service.get_browser_push_config(party_id)
    discord_dm_config = discord_dm_service.get_discord_dm_config(party_id)
    browser_push_subscribed_participant_count = browser_push_service.count_browser_push_subscribed_participants_for_tournament(
        party_id, tournament_id
    )
    browser_push_subscribed_user_ids = browser_push_service.get_browser_push_subscribed_user_ids_for_tournament(
        party_id, tournament_id
    )
    browser_push_outbox_entries = browser_push_service.get_recent_browser_push_outbox_entries_for_tournament(
        tournament_id
    )
    return {
        'browser_push_config': browser_push_config,
        'discord_dm_config': discord_dm_config,
        'browser_push_subscribed_participant_count': browser_push_subscribed_participant_count,
        'browser_push_subscribed_user_ids': browser_push_subscribed_user_ids,
        'browser_push_outbox_entries': browser_push_outbox_entries,
    }


def _get_outbox_user_ids(outbox_entries: list[dict[str, Any]]) -> set[Any]:
    return {
        entry['user_id']
        for entry in outbox_entries
        if entry.get('user_id') is not None
    }


def _get_tournament_admin_users(tournament_id: Any) -> list[Any]:
    admin_users_by_id = user_service.get_users_indexed_by_id(
        tournament_admin_service.get_tournament_admin_user_ids(tournament_id)
    )
    return sorted(
        admin_users_by_id.values(),
        key=lambda user: user.screen_name.lower(),
    )


def _iter_manager_user_ids(participants: list[Any]) -> Iterator[Any]:
    return (
        participant.manager_user_id
        for participant in participants
        if participant.manager_user_id is not None
    )


def _iter_member_user_ids(
    members_by_participant_id: dict[Any, Any],
) -> Iterator[Any]:
    return (
        member.user_id
        for members in members_by_participant_id.values()
        for member in members
    )


def _get_push_recipient_user_ids(
    participants: list[Any], members_by_participant_id: dict[Any, Any]
) -> set[Any]:
    browser_push_recipient_user_ids = {
        participant.user_id
        for participant in participants
        if participant.user_id is not None
    }
    browser_push_recipient_user_ids.update(_iter_manager_user_ids(participants))
    browser_push_recipient_user_ids.update(
        _iter_member_user_ids(members_by_participant_id)
    )
    return browser_push_recipient_user_ids


def _build_push_recipient_rows(
    party_id: PartyID, users_by_id: dict[Any, Any]
) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                'user_id': user_id,
                'screen_name': user.screen_name,
                'subscription_count': browser_push_service.count_active_browser_push_subscriptions_for_user(
                    party_id, user_id
                ),
            }
            for user_id, user in users_by_id.items()
        ],
        key=lambda item: item['screen_name'].lower(),
    )


def collect_push_and_admin_data(
    party_id: PartyID, tournament_id: Any, context: dict[str, Any]
) -> dict[str, Any]:
    """Return push and Discord DM status, admins and push recipients."""
    data = _collect_push_status(party_id, tournament_id)
    browser_push_outbox_user_ids = _get_outbox_user_ids(
        data['browser_push_outbox_entries']
    )
    data['active_participant_count'] = (
        participant_state.count_active_participants_for_tournament(
            party_id, tournament_id
        )
    )
    data['tournament_admin_users'] = _get_tournament_admin_users(tournament_id)
    browser_push_recipient_users_by_id = user_service.get_users_indexed_by_id(
        _get_push_recipient_user_ids(
            context['participants'], context['members_by_participant_id']
        )
    )
    data['browser_push_recipient_rows'] = _build_push_recipient_rows(
        party_id, browser_push_recipient_users_by_id
    )
    data['browser_push_outbox_users_by_id'] = (
        user_service.get_users_indexed_by_id(browser_push_outbox_user_ids)
    )
    return data
