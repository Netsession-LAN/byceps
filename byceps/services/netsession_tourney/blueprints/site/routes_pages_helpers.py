"""
byceps.services.netsession_tourney.blueprints.site.routes_pages_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Helpers for the views in `routes_pages`.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, url_for
from flask_babel import format_datetime, gettext

from byceps.services.netsession_tourney.double_grand_final import (
    get_match_results,
)
from byceps.services.netsession_tourney.match_queries import (
    get_match_slots,
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.models import TeamMemberRole
from byceps.services.netsession_tourney.tournament_prize_service import (
    get_tournament_prizes_for_tournament,
)

from .body_rendering import (
    render_formatted_body_html as _render_formatted_body_html,
)
from .builder_display_helpers import (
    get_materialized_builder_round_robin_group_stages,
)
from .match_helpers import build_match_labels
from .user_state_helpers import format_team_member_role_label
from .user_state_overview_rows import build_current_user_overview_match_rows


# -------------------------------------------------------------------- #
# overview


def collect_overview_user_ids(
    participants, members_by_participant_id, admin_user_ids
) -> set:
    participant_user_ids = {
        participant.user_id
        for participant in participants
        if participant.user_id
    }
    member_user_ids = {
        member.user_id
        for members in members_by_participant_id.values()
        for member in members
    }
    return participant_user_ids | member_user_ids | admin_user_ids


def sort_admin_users(users_by_id, admin_user_ids) -> list:
    return sorted(
        (
            users_by_id[user_id]
            for user_id in admin_user_ids
            if user_id in users_by_id
        ),
        key=lambda user: user.screen_name.lower(),
    )


def build_current_user_team_role(
    current_user_tournament_membership,
) -> tuple[str | None, str | None]:
    if current_user_tournament_membership is None:
        return None, None

    current_user_member = current_user_tournament_membership['member']
    if current_user_member is None:
        return None, None

    current_user_team_role_label = format_team_member_role_label(
        current_user_member.role
    )
    current_user_team_role_icon_id = (
        'crown'
        if current_user_member.role == TeamMemberRole.captain
        else 'controller'
    )
    return current_user_team_role_label, current_user_team_role_icon_id


def build_current_user_overview_matches(
    tournament,
    participants,
    stages_by_id,
    current_user_tournament_membership,
) -> list:
    if current_user_tournament_membership is None:
        return []

    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id = get_match_slots({match.id for match in matches})
    results_by_match_id = get_match_results({match.id for match in matches})
    match_labels_by_id = build_match_labels(
        matches,
        slots_by_match_id,
        stages_by_id,
    )
    participants_by_id = {
        participant.id: participant for participant in participants
    }
    return build_current_user_overview_match_rows(
        tournament,
        matches,
        slots_by_match_id,
        results_by_match_id,
        participants_by_id,
        stages_by_id,
        match_labels_by_id,
        current_user_tournament_membership['participant'].id,
    )


def build_starts_at_label(starts_at) -> str:
    if not starts_at:
        return '-'

    return (
        f'{format_datetime(starts_at, "EEEE")}, '
        f'{format_datetime(starts_at, "d. MMMM y")}, '
        f'{format_datetime(starts_at, "HH:mm")} Uhr'
    )


def build_starts_at_mobile_lines(starts_at) -> tuple[str, ...]:
    if not starts_at:
        return ('-',)

    return (
        (
            f'{format_datetime(starts_at, "EEEE")}, '
            f'{format_datetime(starts_at, "d.")}'
        ),
        format_datetime(starts_at, 'MMMM y'),
        f'{format_datetime(starts_at, "HH:mm")} Uhr',
    )


def build_prizes_with_html(tournament_id) -> list[dict]:
    prizes = get_tournament_prizes_for_tournament(tournament_id)
    return [
        {
            'position': prize.position,
            'body_html': _render_formatted_body_html(
                prize.body, prize.body_format
            ),
        }
        for prize in prizes
    ]


def build_preliminary_link_rows(tournament, stages) -> list[dict]:
    return [
        {
            'title': stage.name,
            'url': url_for(
                'netsession_tourney.view_preliminaries',
                slug=tournament.slug,
                stage=str(stage.id),
            ),
        }
        for stage in get_materialized_builder_round_robin_group_stages(stages)
    ]


# -------------------------------------------------------------------- #
# ranking


def _are_all_team_participants(participants) -> bool:
    return all(participant.type.value == 'team' for participant in participants)


def _are_all_user_participants(participants) -> bool:
    return all(participant.user_id is not None for participant in participants)


def build_ranking_subject_label(participants) -> str:
    if participants and _are_all_team_participants(participants):
        return gettext('Team')

    if participants and _are_all_user_participants(participants):
        return gettext('Spieler')

    return gettext('Teilnehmer')
