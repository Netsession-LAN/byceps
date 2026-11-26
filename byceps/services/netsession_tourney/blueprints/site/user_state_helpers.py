"""
byceps.services.netsession_tourney.blueprints.site.user_state_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g

from byceps.services.netsession_tourney.coin_service import (
    get_coin_settings,
    get_user_coin_balance,
    is_tournament_coin_refund_available,
)
from byceps.services.netsession_tourney.models import (
    TournamentStatus,
)
from byceps.services.netsession_tourney.participant_admin_service import (
    get_active_participant_counts_for_tournaments,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_user_active_participation_tournament_ids,
)
from byceps.services.party.models import PartyID

from .user_state_memberships import (
    format_team_member_role_label as format_team_member_role_label,
    get_captain_team_for_current_user as get_captain_team_for_current_user,
    get_current_user_tournament_membership as get_current_user_tournament_membership,
    get_seat_data_by_user_id as get_seat_data_by_user_id,
)


def get_registration_state_for_tournament(tournament) -> dict:
    active_participant_count = get_active_participant_counts_for_tournaments(
        g.party.id, {tournament.id}
    ).get(tournament.id, 0)
    is_user_registered = tournament.id in get_user_registered_tournament_ids(
        g.party.id, {tournament.id}
    )
    return build_registration_state(
        tournament, active_participant_count, is_user_registered
    )


def get_party_coin_settings():
    cache_key = '_ns_tourney_coin_settings'
    if not hasattr(g, cache_key):
        setattr(g, cache_key, get_coin_settings(g.party.id))

    return getattr(g, cache_key)


def get_current_user_coin_balance():
    user = getattr(g, 'user', None)
    if user is None or not user.authenticated:
        return None

    cache_key = '_ns_tourney_current_user_coin_balance'
    if not hasattr(g, cache_key):
        setattr(g, cache_key, get_user_coin_balance(g.party.id, user.id))

    return getattr(g, cache_key)


def get_user_registered_tournament_ids(
    party_id: PartyID, tournament_ids: set
) -> set:
    if not tournament_ids:
        return set()
    user = getattr(g, 'user', None)
    if user is None or not user.authenticated:
        return set()

    return get_user_active_participation_tournament_ids(
        party_id,
        tournament_ids,
        user.id,
    )


def _is_registration_full(tournament, active_participant_count: int):
    return (
        tournament.participant_limit is not None
        and active_participant_count >= tournament.participant_limit
    )


def _get_available_coins(user_coin_balance):
    return (
        user_coin_balance.available_coins
        if user_coin_balance is not None
        else None
    )


def _has_enough_coins(
    coins_enabled, tournament, can_participate, available_coins
):
    return (
        not coins_enabled
        or tournament.coin_cost <= 0
        or not can_participate
        or (
            available_coins is not None
            and available_coins >= tournament.coin_cost
        )
    )


def _can_register(
    tournament,
    can_participate,
    user_is_registered: bool,
    is_full,
    has_enough_coins,
):
    return (
        can_participate
        and tournament.registration_open
        and tournament.status == TournamentStatus.draft
        and not user_is_registered
        and not is_full
        and has_enough_coins
    )


def _can_unregister(tournament, can_participate, user_is_registered: bool):
    return (
        can_participate
        and user_is_registered
        and tournament.status == TournamentStatus.draft
    )


def _is_coin_refund_available(tournament, coins_enabled):
    return (
        coins_enabled
        and tournament.coin_cost > 0
        and is_tournament_coin_refund_available(tournament)
    )


def build_registration_state(
    tournament,
    active_participant_count: int,
    user_is_registered: bool,
) -> dict:
    is_full = _is_registration_full(tournament, active_participant_count)
    user = getattr(g, 'user', None)
    can_participate = user is not None and user.authenticated
    coin_settings = get_party_coin_settings()
    user_coin_balance = get_current_user_coin_balance()
    available_coins = _get_available_coins(user_coin_balance)
    coins_enabled = coin_settings.enabled
    has_enough_coins = _has_enough_coins(
        coins_enabled, tournament, can_participate, available_coins
    )
    insufficient_coins = can_participate and not has_enough_coins
    can_register = _can_register(
        tournament,
        can_participate,
        user_is_registered,
        is_full,
        has_enough_coins,
    )
    can_unregister = _can_unregister(
        tournament, can_participate, user_is_registered
    )
    refund_available = _is_coin_refund_available(tournament, coins_enabled)

    return {
        'active_participant_count': active_participant_count,
        'is_full': is_full,
        'user_is_registered': user_is_registered,
        'can_register': can_register,
        'can_unregister': can_unregister,
        'coins_enabled': coins_enabled,
        'available_coins': available_coins,
        'has_enough_coins': has_enough_coins,
        'insufficient_coins': insufficient_coins,
        'refund_available': refund_available,
    }
