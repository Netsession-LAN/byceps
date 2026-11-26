"""
byceps.services.netsession_tourney.blueprints.site.routes_index_notifications
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Notification state (Discord DMs, browser push) of the tournament
overview.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g

from byceps.services.external_accounts import external_accounts_service
from byceps.services.netsession_tourney.browser_push_service import (
    get_browser_push_public_key_for_party,
    has_active_browser_push_subscription_for_user,
)
from byceps.services.netsession_tourney.discord_dm_service import (
    has_active_discord_dm_subscription_for_user,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_user_active_participation_tournament_ids,
)


def _build_discord_dm_state() -> dict:
    discord_account_connected = (
        external_accounts_service.find_connected_external_account_for_user_and_service(
            g.user.id, 'discord'
        )
        is not None
    )
    discord_dm_has_subscription = has_active_discord_dm_subscription_for_user(
        g.party.id, g.user.id
    )
    return {
        'discord_account_connected': discord_account_connected,
        'discord_dm_has_subscription': discord_dm_has_subscription,
    }


def _build_browser_push_state() -> dict:
    browser_push_vapid_public_key = get_browser_push_public_key_for_party(
        g.party.id
    )
    browser_push_has_subscription = (
        has_active_browser_push_subscription_for_user(g.party.id, g.user.id)
    )
    return {
        'browser_push_vapid_public_key': browser_push_vapid_public_key,
        'browser_push_has_subscription': browser_push_has_subscription,
    }


def _is_discord_dm_prompt_enabled(
    discord_dm_enabled, has_involved_tournaments, discord_dm_has_subscription
):
    return discord_dm_enabled and (
        has_involved_tournaments or discord_dm_has_subscription
    )


def _build_user_notification_state(
    state: dict, tournament_ids, browser_push_enabled, discord_dm_enabled
) -> None:
    involved_tournament_ids = get_user_active_participation_tournament_ids(
        g.party.id,
        tournament_ids,
        g.user.id,
    )
    has_involved_tournaments = bool(involved_tournament_ids)
    state['browser_push_prompt_enabled'] = (
        browser_push_enabled and has_involved_tournaments
    )
    if discord_dm_enabled:
        state.update(_build_discord_dm_state())
    state['discord_dm_prompt_enabled'] = _is_discord_dm_prompt_enabled(
        discord_dm_enabled,
        has_involved_tournaments,
        state['discord_dm_has_subscription'],
    )
    if state['browser_push_prompt_enabled']:
        state.update(_build_browser_push_state())


def build_index_notification_state(
    tournament_ids, browser_push_enabled, discord_dm_enabled
) -> dict:
    state = {
        'browser_push_prompt_enabled': False,
        'browser_push_vapid_public_key': None,
        'browser_push_has_subscription': False,
        'discord_dm_prompt_enabled': False,
        'discord_dm_has_subscription': False,
        'discord_account_connected': False,
    }
    if g.user.authenticated:
        _build_user_notification_state(
            state, tournament_ids, browser_push_enabled, discord_dm_enabled
        )
    return state


def parse_browser_push_subscription_payload(payload) -> tuple[str, str, str]:
    endpoint = str(payload.get('endpoint') or '').strip()
    keys = payload.get('keys') or {}
    endpoint_p256dh = str(keys.get('p256dh') or '').strip()
    endpoint_auth = str(keys.get('auth') or '').strip()
    return endpoint, endpoint_p256dh, endpoint_auth


def has_connected_discord_account(user_id) -> bool:
    connected_account = external_accounts_service.find_connected_external_account_for_user_and_service(
        user_id, 'discord'
    )
    return connected_account is not None and bool(connected_account.external_id)
