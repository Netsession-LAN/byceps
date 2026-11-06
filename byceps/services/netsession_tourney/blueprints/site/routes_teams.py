"""
byceps.services.netsession_tourney.blueprints.site.routes_teams
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Team and player pages.
"""

from __future__ import annotations


from flask import (
    abort,
    g,
)
from flask_babel import gettext

from byceps.services.user import user_service
from byceps.util.framework.flash import flash_error
from byceps.util.framework.templating import templated
from byceps.util.views import login_required, redirect_to

from ...double_grand_final import get_match_results
from ...forms import (
    TeamCreationForm,
    TeamMemberAddForm,
)
from ...match_queries import (
    get_match_slots,
    get_matches_for_tournament,
)
from ...models import (
    ParticipantType,
    TournamentStatus,
)
from ...participant_admin_service import (
    get_participants_by_ids,
)
from ...registration_validation import get_team_members_for_participants
from ...team_invite_service import (
    get_team_invite_code_for_manager,
)
from ...tournament_queries import (
    get_stages_for_tournament,
)
from .builder_helpers import get_materialized_builder_container_stages
from .match_helpers import (
    build_match_labels,
)
from .stage_filters import (
    uses_only_ffa_scoring_stages,
    uses_only_ffa_simple_stages,
    uses_only_flatout2_stages,
)
from .stage_render_helpers import (
    build_team_history_rows,
)
from .user_state_helpers import (
    get_seat_data_by_user_id,
)

from .blueprint import blueprint
from .common import (
    get_main_nav_current_page_id,
    _get_tournament_or_404,
)
from ...screen_name_suggestions import get_suggested_screen_names_for_party


def _build_team_view_context(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    participants_by_id = get_participants_by_ids(g.party.id, {participant_id})
    team = participants_by_id.get(participant_id)
    if team is None or team.tournament_id != tournament.id:
        abort(404)
    if team.type != ParticipantType.team:
        abort(404)

    members_by_participant_id = get_team_members_for_participants({participant_id})
    members = members_by_participant_id.get(participant_id, [])
    users_by_id = user_service.get_users_indexed_by_id(
        {member.user_id for member in members},
        include_avatars=True,
    )
    role_sort_order = {'captain': 0, 'player': 1, 'substitute': 2}
    members = sorted(
        members,
        key=lambda member: (
            role_sort_order.get(member.role.value, 9),
            (
                users_by_id.get(member.user_id).screen_name.lower()
                if users_by_id.get(member.user_id)
                else str(member.user_id)
            ),
        ),
    )
    seat_data_by_user_id = get_seat_data_by_user_id(
        g.party.id, {member.user_id for member in members}
    )
    current_user = getattr(g, 'user', None)
    can_manage_team = (
        current_user is not None
        and current_user.authenticated
        and team.manager_user_id == current_user.id
    )
    team_invite_code = None
    if can_manage_team:
        invite_code_result = get_team_invite_code_for_manager(
            g.party.id,
            tournament.id,
            team.id,
            current_user.id,
        )
        if invite_code_result.is_ok():
            team_invite_code = invite_code_result.unwrap()

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
    participant_ids = {
        slot.participant_id
        for slots in slots_by_match_id.values()
        for slot in slots
        if slot.participant_id
    }
    participants_lookup = get_participants_by_ids(g.party.id, participant_ids)
    team_history = build_team_history_rows(
        team,
        matches,
        slots_by_match_id,
        results_by_match_id,
        participants_lookup,
        match_labels_by_id,
        stages_by_id,
    )
    is_flatout2_tournament = uses_only_flatout2_stages(stages, matches)

    current_page_id = get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'team': team,
        'members': members,
        'users_by_id': users_by_id,
        'seat_data_by_user_id': seat_data_by_user_id,
        'can_manage_team': can_manage_team,
        'team_invite_code': team_invite_code,
        'team_creation_form': TeamCreationForm(data={'name': team.name}),
        'team_member_add_form': TeamMemberAddForm(),
        'suggested_screen_names': get_suggested_screen_names_for_party(
            g.party.id
        ),
        'team_history': team_history,
        'is_ffa_scoring_tournament': uses_only_ffa_scoring_stages(
            stages, matches
        ),
        'is_flatout2_tournament': uses_only_flatout2_stages(stages, matches),
        'hide_bracket_tab': uses_only_ffa_simple_stages(stages, []),
        'show_preliminaries_tab': bool(
            get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'overview',
    }


def _build_player_view_context(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    participants_by_id = get_participants_by_ids(g.party.id, {participant_id})
    player = participants_by_id.get(participant_id)
    if player is None or player.tournament_id != tournament.id:
        abort(404)
    if player.type != ParticipantType.user:
        abort(404)
    if player.user_id is None:
        abort(404)

    player_user = user_service.get_user(player.user_id, include_avatar=True)
    seat_data_by_user_id = get_seat_data_by_user_id(
        g.party.id, {player.user_id}
    )
    seat_data = seat_data_by_user_id.get(player.user_id)

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
    participant_ids = {
        slot.participant_id
        for slots in slots_by_match_id.values()
        for slot in slots
        if slot.participant_id
    }
    participants_lookup = get_participants_by_ids(g.party.id, participant_ids)
    player_history = build_team_history_rows(
        player,
        matches,
        slots_by_match_id,
        results_by_match_id,
        participants_lookup,
        match_labels_by_id,
        stages_by_id,
    )
    is_flatout2_tournament = uses_only_flatout2_stages(stages, matches)

    current_page_id = get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'player': player,
        'player_user': player_user,
        'seat_data': seat_data,
        'player_history': player_history,
        'is_ffa_scoring_tournament': uses_only_ffa_scoring_stages(
            stages, matches
        ),
        'is_flatout2_tournament': uses_only_flatout2_stages(stages, matches),
        'hide_bracket_tab': uses_only_ffa_simple_stages(stages, []),
        'show_preliminaries_tab': bool(
            get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'overview',
    }


@blueprint.get('/<slug>/teams/<uuid:participant_id>')
@templated
def view_team(slug, participant_id):
    context = _build_team_view_context(slug, participant_id)
    context['manage_page'] = False
    return context


@blueprint.get('/<slug>/teams/<uuid:participant_id>/edit')
@login_required
@templated('site/netsession_tourney/view_team')
def edit_team(slug, participant_id):
    context = _build_team_view_context(slug, participant_id)
    is_manageable = (
        context['can_manage_team']
        and context['tournament'].status
        in {TournamentStatus.draft, TournamentStatus.live}
    )
    if not is_manageable:
        flash_error(gettext('Team kann aktuell nicht bearbeitet werden.'))
        return redirect_to(
            '.view_team', slug=slug, participant_id=participant_id
        )

    context['manage_page'] = True
    return context


@blueprint.get('/<slug>/players/<uuid:participant_id>')
@templated('site/netsession_tourney/view_player')
def view_player(slug, participant_id):
    return _build_player_view_context(slug, participant_id)
