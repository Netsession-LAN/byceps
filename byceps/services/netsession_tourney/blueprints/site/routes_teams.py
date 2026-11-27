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

from byceps.services.netsession_tourney.forms import (
    TeamCreationForm,
    TeamMemberAddForm,
)
from byceps.services.netsession_tourney.models import (
    ParticipantType,
    TournamentStatus,
)
from byceps.services.netsession_tourney.registration_validation import (
    get_team_members_for_participants,
)
from byceps.services.netsession_tourney.screen_name_suggestions import (
    get_suggested_screen_names_for_party,
)
from byceps.services.user import user_service
from byceps.util.framework.flash import flash_error
from byceps.util.framework.templating import templated
from byceps.util.views import login_required, redirect_to

from .blueprint import blueprint
from .common import (
    _get_tournament_or_404,
    get_main_nav_current_page_id,
)
from .routes_teams_helpers import (
    build_participant_history,
    build_participant_page_tab_flags,
    can_current_user_manage_team,
    find_team_invite_code,
    get_tournament_participant_or_404,
    sort_team_members,
)
from .user_state_helpers import (
    get_seat_data_by_user_id,
)


def _build_team_view_context(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    team = get_tournament_participant_or_404(
        tournament, participant_id, ParticipantType.team
    )

    members_by_participant_id = get_team_members_for_participants(
        {participant_id}
    )
    members = members_by_participant_id.get(participant_id, [])
    users_by_id = user_service.get_users_indexed_by_id(
        {member.user_id for member in members},
        include_avatars=True,
    )
    members = sort_team_members(members, users_by_id)
    seat_data_by_user_id = get_seat_data_by_user_id(
        g.party.id, {member.user_id for member in members}
    )
    can_manage_team = can_current_user_manage_team(team)
    team_invite_code = find_team_invite_code(tournament, team, can_manage_team)

    matches, stages, team_history = build_participant_history(tournament, team)
    tab_flags = build_participant_page_tab_flags(stages, matches)

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
        **tab_flags,
        'current_page': current_page_id,
        'current_tournament_page': 'overview',
    }


def _build_player_view_context(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    player = get_tournament_participant_or_404(
        tournament, participant_id, ParticipantType.user
    )
    if player.user_id is None:
        abort(404)

    player_user = user_service.get_user(player.user_id, include_avatar=True)
    seat_data_by_user_id = get_seat_data_by_user_id(
        g.party.id, {player.user_id}
    )
    seat_data = seat_data_by_user_id.get(player.user_id)

    matches, stages, player_history = build_participant_history(
        tournament, player
    )
    tab_flags = build_participant_page_tab_flags(stages, matches)

    current_page_id = get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'player': player,
        'player_user': player_user,
        'seat_data': seat_data,
        'player_history': player_history,
        **tab_flags,
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
    is_manageable = context['can_manage_team'] and context[
        'tournament'
    ].status in {TournamentStatus.draft, TournamentStatus.live}
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
