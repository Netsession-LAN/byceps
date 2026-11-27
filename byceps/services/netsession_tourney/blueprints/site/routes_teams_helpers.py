"""
byceps.services.netsession_tourney.blueprints.site.routes_teams_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Helpers for the team and player pages in `routes_teams`.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import abort, g

from byceps.services.netsession_tourney.double_grand_final import (
    get_match_results,
)
from byceps.services.netsession_tourney.match_queries import (
    get_match_slots,
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.models import ParticipantType
from byceps.services.netsession_tourney.participant_admin_service import (
    get_participants_by_ids,
)
from byceps.services.netsession_tourney.team_invite_service import (
    get_team_invite_code_for_manager,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)

from .builder_helpers import get_materialized_builder_container_stages
from .match_helpers import build_match_labels
from .stage_filters import (
    uses_only_ffa_scoring_stages,
    uses_only_ffa_simple_stages,
    uses_only_flatout2_stages,
)
from .stage_render_helpers import build_team_history_rows


TEAM_MEMBER_ROLE_SORT_ORDER = {'captain': 0, 'player': 1, 'substitute': 2}


def get_tournament_participant_or_404(
    tournament, participant_id, participant_type: ParticipantType
):
    participants_by_id = get_participants_by_ids(g.party.id, {participant_id})
    participant = participants_by_id.get(participant_id)
    if participant is None or participant.tournament_id != tournament.id:
        abort(404)
    if participant.type != participant_type:
        abort(404)
    return participant


def _team_member_sort_key(member, users_by_id) -> tuple:
    return (
        TEAM_MEMBER_ROLE_SORT_ORDER.get(member.role.value, 9),
        (
            users_by_id.get(member.user_id).screen_name.lower()
            if users_by_id.get(member.user_id)
            else str(member.user_id)
        ),
    )


def sort_team_members(members, users_by_id) -> list:
    return sorted(
        members,
        key=lambda member: _team_member_sort_key(member, users_by_id),
    )


def can_current_user_manage_team(team):
    current_user = getattr(g, 'user', None)
    return (
        current_user is not None
        and current_user.authenticated
        and team.manager_user_id == current_user.id
    )


def find_team_invite_code(tournament, team, can_manage_team) -> str | None:
    if not can_manage_team:
        return None

    current_user = getattr(g, 'user', None)
    invite_code_result = get_team_invite_code_for_manager(
        g.party.id,
        tournament.id,
        team.id,
        current_user.id,
    )
    if invite_code_result.is_ok():
        return invite_code_result.unwrap()

    return None


def _collect_slot_participant_ids(slots_by_match_id) -> set:
    return {
        slot.participant_id
        for slots in slots_by_match_id.values()
        for slot in slots
        if slot.participant_id
    }


def build_participant_history(tournament, participant) -> tuple:
    """Return matches, (freshly loaded) stages and the history rows."""
    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id = get_match_slots({match.id for match in matches})
    results_by_match_id = get_match_results({match.id for match in matches})
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    stages_by_id = {stage.id: stage for stage in stages}
    match_labels_by_id = build_match_labels(
        matches,
        slots_by_match_id,
        stages_by_id,
    )
    participant_ids = _collect_slot_participant_ids(slots_by_match_id)
    participants_lookup = get_participants_by_ids(g.party.id, participant_ids)
    history = build_team_history_rows(
        participant,
        matches,
        slots_by_match_id,
        results_by_match_id,
        participants_lookup,
        match_labels_by_id,
        stages_by_id,
    )
    return matches, stages, history


def build_participant_page_tab_flags(stages, matches) -> dict:
    is_flatout2_tournament = uses_only_flatout2_stages(stages, matches)
    return {
        'is_ffa_scoring_tournament': uses_only_ffa_scoring_stages(
            stages, matches
        ),
        'is_flatout2_tournament': is_flatout2_tournament,
        'hide_bracket_tab': uses_only_ffa_simple_stages(stages, []),
        'show_preliminaries_tab': bool(
            get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        )
        and not is_flatout2_tournament,
    }
