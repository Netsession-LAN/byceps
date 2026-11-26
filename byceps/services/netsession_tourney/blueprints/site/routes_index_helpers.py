"""
byceps.services.netsession_tourney.blueprints.site.routes_index_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Helpers for the views in `routes_index`.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from flask import g, url_for
from flask_babel import format_datetime, gettext

from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
    get_user_active_participation_tournament_ids,
)
from byceps.services.netsession_tourney.tournament_service import (
    get_tournaments_for_party,
)

from .common import build_public_tournament_status
from .match_helpers import build_match_labels
from .match_state_labels import open_class_name, open_label
from .routes_index_notifications import (
    build_index_notification_state as build_index_notification_state,
    has_connected_discord_account as has_connected_discord_account,
    parse_browser_push_subscription_payload as parse_browser_push_subscription_payload,
)
from .user_state_helpers import (
    build_registration_state,
    format_open_match_participant_name,
    is_match_involving_user,
)


# -------------------------------------------------------------------- #
# index


def build_registration_states_by_tournament_id(
    tournaments, active_participant_counts, user_registered_tournament_ids
) -> dict:
    return {
        tournament.id: build_registration_state(
            tournament,
            active_participant_counts.get(tournament.id, 0),
            tournament.id in user_registered_tournament_ids,
        )
        for tournament in tournaments
    }


def build_public_statuses_by_tournament_id(tournaments) -> dict:
    return {
        tournament.id: build_public_tournament_status(tournament)
        for tournament in tournaments
    }


def build_index_filter_values(status_param, mode_param, game) -> dict:
    return {
        'status_filter': status_param or '',
        'mode_filter': mode_param or '',
        'game_filter': game or '',
    }


# -------------------------------------------------------------------- #
# subscriptions


def get_involved_party_tournament_ids(party_id, user_id):
    tournament_ids = [
        tournament.id for tournament in get_tournaments_for_party(party_id)
    ]
    return get_user_active_participation_tournament_ids(
        party_id,
        tournament_ids,
        user_id,
    )


# -------------------------------------------------------------------- #
# open matches


def collect_slot_participant_ids(slots_by_match_id) -> set:
    return {
        slot.participant_id
        for slots in slots_by_match_id.values()
        for slot in slots
        if slot.participant_id
    }


def build_tournaments_by_id(party_id, tournament_ids) -> dict:
    return {
        tournament.id: tournament
        for tournament in get_tournaments_for_party(party_id)
        if tournament.id in tournament_ids
    }


def build_stages_by_tournament_id(party_id, tournament_ids) -> dict:
    return {
        tournament_id: {
            stage.id: stage
            for stage in get_stages_for_tournament(party_id, tournament_id)
        }
        for tournament_id in tournament_ids
    }


def build_open_match_labels(
    matches, slots_by_match_id, stages_by_tournament_id
) -> dict:
    match_labels_by_id = {}
    matches_by_tournament_id: dict[UUID, list] = defaultdict(list)
    for match in matches:
        matches_by_tournament_id[match.tournament_id].append(match)

    for tournament_id, tournament_matches in matches_by_tournament_id.items():
        match_labels_by_id.update(
            build_match_labels(
                tournament_matches,
                {
                    match.id: slots_by_match_id.get(match.id, [])
                    for match in tournament_matches
                },
                stages_by_tournament_id.get(tournament_id, {}),
            )
        )

    return match_labels_by_id


def get_authenticated_current_user_id():
    current_user = getattr(g, 'user', None)
    return (
        current_user.id
        if current_user is not None and current_user.authenticated
        else None
    )


def _build_open_match_row(
    match,
    tournament,
    stage,
    slots,
    participants,
    members_by_participant_id,
    current_user_id,
    match_labels_by_id,
) -> dict:
    participant_names = [
        format_open_match_participant_name(
            slot, participants_by_id=participants
        )
        for slot in slots
    ]
    is_my_match = current_user_id is not None and is_match_involving_user(
        current_user_id,
        slots,
        participants_by_id=participants,
        members_by_participant_id=members_by_participant_id,
    )

    return {
        'match': match,
        'url': url_for(
            'netsession_tourney.view_match',
            slug=tournament.slug,
            match_id=match.id,
        ),
        'match_label': match_labels_by_id.get(
            match.id, f'{gettext("Match")} #{match.match_no}'
        ),
        'participants_label': ' vs '.join(participant_names),
        'tournament_title': tournament.title,
        'stage_name': stage.name if stage is not None else gettext('Phase'),
        'state_label': open_label(match.state),
        'state_class_name': open_class_name(match.state),
        'scheduled_label': (
            format_datetime(match.scheduled_at, 'short')
            if match.scheduled_at is not None
            else gettext('Nicht geplant')
        ),
        'is_my_match': is_my_match,
        'is_scheduled': match.scheduled_at is not None,
    }


def _open_match_row_sort_key(row) -> tuple:
    return (
        not row['is_my_match'],
        row['match'].scheduled_at or datetime.max,
        row['tournament_title'].lower(),
        row['stage_name'].lower(),
        row['match'].round_no,
        row['match'].match_no,
    )


def build_open_match_rows(
    matches,
    slots_by_match_id,
    tournaments_by_id,
    stages_by_tournament_id,
    participants,
    members_by_participant_id,
    match_labels_by_id,
) -> list[dict]:
    current_user_id = get_authenticated_current_user_id()

    rows = []
    for match in matches:
        tournament = tournaments_by_id.get(match.tournament_id)
        if tournament is None:
            continue

        stage = stages_by_tournament_id.get(match.tournament_id, {}).get(
            match.stage_id
        )
        slots = sorted(
            slots_by_match_id.get(match.id, []), key=lambda slot: slot.slot_no
        )
        rows.append(
            _build_open_match_row(
                match,
                tournament,
                stage,
                slots,
                participants,
                members_by_participant_id,
                current_user_id,
                match_labels_by_id,
            )
        )

    rows.sort(key=_open_match_row_sort_key)
    return rows
