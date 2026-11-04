"""
byceps.services.netsession_tourney.blueprints.site.user_state_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from datetime import datetime

from flask import g, url_for
from flask_babel import format_datetime, gettext

from byceps.services.party.models import PartyID
from byceps.services.ticketing import ticket_service

from ...models import (
    MatchState,
    ParticipantType,
    TeamMemberRole,
    TournamentMode,
    TournamentStatus,
)
from ...service import (
    find_managed_team_for_user,
    get_active_participant_counts_for_tournaments,
    get_coin_settings,
    get_user_active_participation_tournament_ids,
    get_user_coin_balance,
    is_tournament_coin_refund_available,
)
from .flatout2_public_rendering import get_flatout2_host_participant_id
from .stage_filters import _is_flatout2_stage


def _get_registration_state_for_tournament(tournament) -> dict:
    active_participant_count = get_active_participant_counts_for_tournaments(
        g.party.id, {tournament.id}
    ).get(tournament.id, 0)
    is_user_registered = (
        tournament.id in _get_user_registered_tournament_ids(g.party.id, {tournament.id})
    )
    return _build_registration_state(
        tournament, active_participant_count, is_user_registered
    )


def _get_party_coin_settings():
    cache_key = '_ns_tourney_coin_settings'
    if not hasattr(g, cache_key):
        setattr(g, cache_key, get_coin_settings(g.party.id))

    return getattr(g, cache_key)


def _get_current_user_coin_balance():
    user = getattr(g, 'user', None)
    if user is None or not user.authenticated:
        return None

    cache_key = '_ns_tourney_current_user_coin_balance'
    if not hasattr(g, cache_key):
        setattr(g, cache_key, get_user_coin_balance(g.party.id, user.id))

    return getattr(g, cache_key)


def _get_user_registered_tournament_ids(
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


def _build_registration_state(
    tournament,
    active_participant_count: int,
    user_is_registered: bool,
) -> dict:
    is_full = (
        tournament.participant_limit is not None
        and active_participant_count >= tournament.participant_limit
    )
    user = getattr(g, 'user', None)
    can_participate = user is not None and user.authenticated
    coin_settings = _get_party_coin_settings()
    user_coin_balance = _get_current_user_coin_balance()
    available_coins = (
        user_coin_balance.available_coins
        if user_coin_balance is not None
        else None
    )
    coins_enabled = coin_settings.enabled
    has_enough_coins = (
        not coins_enabled
        or tournament.coin_cost <= 0
        or not can_participate
        or (
            available_coins is not None
            and available_coins >= tournament.coin_cost
        )
    )
    insufficient_coins = can_participate and not has_enough_coins
    can_register = (
        can_participate
        and tournament.registration_open
        and tournament.status == TournamentStatus.draft
        and not user_is_registered
        and not is_full
        and has_enough_coins
    )
    can_unregister = (
        can_participate
        and user_is_registered
        and tournament.status == TournamentStatus.draft
    )
    refund_available = (
        coins_enabled
        and tournament.coin_cost > 0
        and is_tournament_coin_refund_available(tournament)
    )

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


def _can_user_report_match_result(
    user_id,
    tournament,
    match,
    slots,
    participants_by_id,
    *,
    is_admin_or_referee: bool,
) -> bool:
    if tournament.status != TournamentStatus.live:
        return False

    if match.state not in {
        MatchState.ready,
        MatchState.in_progress,
        MatchState.pending_confirmation,
    }:
        return False

    if is_admin_or_referee:
        return True

    if tournament.mode == TournamentMode.ffa:
        return False

    return any(
        participant is not None and participant.manager_user_id == user_id
        for slot in slots
        for participant in [participants_by_id.get(slot.participant_id)]
    )


def _get_captain_team_for_current_user(tournament_id):
    user = getattr(g, 'user', None)
    if user is None or not user.authenticated:
        return None

    return find_managed_team_for_user(g.party.id, tournament_id, user.id)


def _get_current_user_tournament_membership(
    participants, members_by_participant_id
):
    user = getattr(g, 'user', None)
    if user is None or not user.authenticated:
        return None

    for participant in participants:
        if participant.type == ParticipantType.team:
            for member in members_by_participant_id.get(participant.id, []):
                if member.user_id != user.id:
                    continue

                return {
                    'participant': participant,
                    'member': member,
                }

        if participant.user_id == user.id:
            return {
                'participant': participant,
                'member': None,
            }

    return None


def _format_open_match_participant_name(slot, *, participants_by_id) -> str:
    if slot.participant_id is None:
        return gettext('TBD')

    participant = participants_by_id.get(slot.participant_id)
    if participant is None:
        return gettext('TBD')

    return participant.name


def _is_match_involving_user(
    user_id,
    slots,
    *,
    participants_by_id,
    members_by_participant_id,
) -> bool:
    for slot in slots:
        if slot.participant_id is None:
            continue

        participant = participants_by_id.get(slot.participant_id)
        if participant is None:
            continue

        if participant.user_id == user_id or participant.manager_user_id == user_id:
            return True

        if any(
            member.user_id == user_id
            for member in members_by_participant_id.get(participant.id, [])
        ):
            return True

    return False


def _get_open_match_state_label(state: MatchState) -> str:
    if state == MatchState.ready:
        return gettext('Spielbereit')
    if state == MatchState.in_progress:
        return gettext('Live')
    if state == MatchState.pending_confirmation:
        return gettext('Wartet auf Bestätigung')
    if state == MatchState.needs_admin_review:
        return gettext('Admin-Review')

    return state.value.replace('_', ' ').title()


def _get_open_match_state_class_name(state: MatchState) -> str:
    if state == MatchState.ready:
        return 'is-ready'
    if state == MatchState.in_progress:
        return 'is-live'
    if state == MatchState.pending_confirmation:
        return 'is-pending-confirmation'
    if state == MatchState.needs_admin_review:
        return 'is-needs-review'

    return ''


def _format_team_member_role_label(role: TeamMemberRole) -> str:
    if role == TeamMemberRole.captain:
        return gettext('Teamkapitän')
    if role == TeamMemberRole.substitute:
        return gettext('Ersatzspieler')

    return gettext('Mitspieler')


def _build_current_user_overview_match_rows(
    tournament,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    stages_by_id,
    match_labels_by_id,
    current_participant_id,
):
    if current_participant_id is None:
        return []

    rows = []

    for match in matches:
        slots = slots_by_match_id.get(match.id, [])
        if not any(slot.participant_id == current_participant_id for slot in slots):
            continue

        is_flatout2_match = _is_flatout2_stage(stages_by_id.get(match.stage_id))
        participant_count = len(
            [slot for slot in slots if slot.participant_id is not None]
        )

        opponent_names = []
        for slot in slots:
            if slot.participant_id == current_participant_id:
                continue

            participant = participants_by_id.get(slot.participant_id)
            if participant is not None:
                opponent_names.append(participant.name)
            elif slot.participant_id is None:
                opponent_names.append(gettext('Freilos'))

        result = results_by_match_id.get(match.id)
        score_display = None
        if result is not None and isinstance(result.score, dict):
            score_display = result.score.get('display')

        rows.append(
            {
                'match': match,
                'url': url_for(
                    'netsession_tourney.view_match',
                    slug=tournament.slug,
                    match_id=match.id,
                ),
                'match_label': match_labels_by_id.get(
                    match.id, f'{gettext("Match")} #{match.match_no}'
                ),
                'stage_name': (
                    stages_by_id[match.stage_id].name
                    if match.stage_id in stages_by_id
                    else '-'
                ),
                'opponent_label': (
                    gettext(
                        'Heat mit %(count)s Teilnehmern',
                        count=participant_count,
                    )
                    if is_flatout2_match
                    else (
                        ', '.join(opponent_names)
                        if opponent_names
                        else gettext('Freilos')
                    )
                ),
                'scheduled_at_label': (
                    format_datetime(match.scheduled_at, 'short')
                    if match.scheduled_at is not None
                    else '-'
                ),
                'state_label': match.state.value.replace('_', ' ').title(),
                'score_display': score_display,
                'is_flatout2_match': is_flatout2_match,
                'is_host': (
                    get_flatout2_host_participant_id(match)
                    == str(current_participant_id)
                ),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row['match'].state == MatchState.completed,
            row['match'].scheduled_at or datetime.max,
            row['match'].round_no,
            row['match'].match_no,
        ),
    )


def _get_seat_data_by_user_id(
    party_id: PartyID, user_ids: set
) -> dict:
    seat_data_by_user_id = {}

    for user_id in user_ids:
        tickets = ticket_service.get_tickets_used_by_user(user_id, party_id)
        for ticket in tickets:
            seat = ticket.occupied_seat
            if seat is None:
                continue

            seat_label = seat.label or '-'
            seat_url = None
            area = getattr(seat, 'area', None)
            if area is not None and area.slug:
                seat_url = url_for(
                    'seating.view_area',
                    slug=area.slug,
                    _anchor=f'seat-{seat.id}',
                )

            seat_data_by_user_id[user_id] = {
                'label': seat_label,
                'url': seat_url,
            }
            break

    return seat_data_by_user_id

