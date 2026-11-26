"""
byceps.services.netsession_tourney.blueprints.site.routes_team_member_actions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Team joining, invite codes, members and ready state actions of
players and captains.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import (
    g,
    request,
)
from flask_babel import gettext

from byceps.services.netsession_tourney.forms import (
    TeamJoinForm,
    TeamMemberAddForm,
)
from byceps.services.netsession_tourney.team_captain_service import (
    set_managed_team_ready_state,
)
from byceps.services.netsession_tourney.team_invite_service import (
    join_team_by_invite_code,
    regenerate_team_invite_code_for_manager,
)
from byceps.services.netsession_tourney.team_member_service import (
    add_team_member_by_captain,
    assign_team_captain_by_captain,
    remove_team_member_by_captain,
)
from byceps.services.user import user_service
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.views import login_required, redirect_to

from .blueprint import blueprint
from .common import _get_tournament_or_404


@blueprint.post('/<slug>/teams/join')
@login_required
def join_team(slug):
    tournament = _get_tournament_or_404(slug)
    form = TeamJoinForm(request.form)
    if not form.validate():
        flash_error(gettext('Ungültiger Invite-Code.'))
        return redirect_to('.create_team_form', slug=slug)

    user = user_service.get_user(g.user.id)
    result = join_team_by_invite_code(
        g.party.id, tournament.id, form.invite_code.data, user
    )
    if result.is_ok():
        flash_success(gettext('Du bist dem Team beigetreten.'))
        team = result.unwrap()
        return redirect_to('.view_team', slug=slug, participant_id=team.id)
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.create_team_form', slug=slug)


@blueprint.post('/<slug>/teams/<uuid:participant_id>/invite-code/regenerate')
@login_required
def regenerate_team_invite_code(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    user = user_service.get_user(g.user.id)

    result = regenerate_team_invite_code_for_manager(
        g.party.id,
        tournament.id,
        participant_id,
        user,
    )
    if result.is_ok():
        flash_success(gettext('Invite-Code wurde erneuert.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_team', slug=slug, participant_id=participant_id)


@blueprint.post(
    '/<slug>/teams/<uuid:participant_id>/members/<uuid:member_user_id>/remove'
)
@login_required
def remove_team_member(slug, participant_id, member_user_id):
    tournament = _get_tournament_or_404(slug)
    user = user_service.get_user(g.user.id)

    result = remove_team_member_by_captain(
        g.party.id,
        tournament.id,
        participant_id,
        member_user_id,
        user,
    )
    if result.is_ok():
        flash_success(gettext('Teammitglied wurde entfernt.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_team', slug=slug, participant_id=participant_id)


@blueprint.post(
    '/<slug>/teams/<uuid:participant_id>/members/<uuid:member_user_id>/captain'
)
@login_required
def assign_team_captain(slug, participant_id, member_user_id):
    tournament = _get_tournament_or_404(slug)
    user = user_service.get_user(g.user.id)

    result = assign_team_captain_by_captain(
        g.party.id,
        tournament.id,
        participant_id,
        member_user_id,
        user,
    )
    if result.is_ok():
        flash_success(gettext('Der Teamkapitän wurde geändert.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_team', slug=slug, participant_id=participant_id)


@blueprint.post('/<slug>/teams/<uuid:participant_id>/members/add')
@login_required
def add_team_member(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    form = TeamMemberAddForm(request.form)
    if not form.validate():
        flash_error(gettext('Ungültige Teammitglied-Daten.'))
        return redirect_to(
            '.view_team', slug=slug, participant_id=participant_id
        )

    screen_name = form.screen_name.data.strip()
    member_user = user_service.find_user_by_screen_name(screen_name)
    if member_user is None:
        flash_error(gettext('Unbekannter Benutzer.'))
        return redirect_to(
            '.view_team', slug=slug, participant_id=participant_id
        )

    user = user_service.get_user(g.user.id)
    result = add_team_member_by_captain(
        g.party.id,
        tournament.id,
        participant_id,
        member_user,
        user,
    )
    if result.is_ok():
        flash_success(gettext('Teammitglied wurde hinzugefügt.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_team', slug=slug, participant_id=participant_id)


@blueprint.post('/<slug>/teams/<uuid:participant_id>/ready')
@login_required
def set_team_ready_state(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    user = user_service.get_user(g.user.id)
    should_be_ready = request.form.get('ready') == 'true'

    result = set_managed_team_ready_state(
        g.party.id,
        tournament.id,
        participant_id,
        user,
        ready=should_be_ready,
    )
    if result.is_ok():
        flash_success(gettext('Der Teamstatus wurde aktualisiert.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_team', slug=slug, participant_id=participant_id)
