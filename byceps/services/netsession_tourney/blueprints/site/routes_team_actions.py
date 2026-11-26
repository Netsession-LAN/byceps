"""
byceps.services.netsession_tourney.blueprints.site.routes_team_actions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Registration and team management actions of players and captains.
"""

from __future__ import annotations

from flask import (
    g,
    redirect,
    request,
    url_for,
)
from flask_babel import gettext

from byceps.services.netsession_tourney.forms import (
    TeamCreationForm,
    TeamJoinForm,
    TeamMemberAddForm,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    TournamentStatus,
)
from byceps.services.netsession_tourney.registration_service import (
    deregister_user,
    register_user,
)
from byceps.services.netsession_tourney.team_captain_service import (
    create_team_for_captain,
    set_managed_team_ready_state,
    update_managed_team_for_captain,
)
from byceps.services.netsession_tourney.team_invite_service import (
    join_team_by_invite_code,
    regenerate_team_invite_code_for_manager,
)
from byceps.services.netsession_tourney.team_logo_uploads import (
    upload_logo_for_managed_team,
    upload_logo_for_new_team,
)
from byceps.services.netsession_tourney.team_member_service import (
    add_team_member_by_captain,
    assign_team_captain_by_captain,
    remove_team_member_by_captain,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.services.user import user_service
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.views import login_required, redirect_to

from .blueprint import blueprint
from .builder_helpers import get_materialized_builder_container_stages
from .common import (
    _get_tournament_or_404,
    get_main_nav_current_page_id,
)
from .stage_filters import (
    uses_only_ffa_simple_stages,
    uses_only_flatout2_stages,
)
from .user_state_helpers import (
    get_captain_team_for_current_user,
    get_registration_state_for_tournament,
)


@blueprint.post('/<slug>/register')
@login_required
def register(slug):
    tournament = _get_tournament_or_404(slug)

    user = user_service.get_user(g.user.id)
    result = register_user(g.party.id, tournament.id, user)

    if result.is_ok():
        flash_success(gettext('Du wurdest angemeldet.'))
    else:
        flash_error(result.unwrap_err())

    return redirect(url_for('netsession_tourney.view_overview', slug=slug))


@blueprint.post('/<slug>/unregister')
@login_required
def unregister(slug):
    tournament = _get_tournament_or_404(slug)

    user = user_service.get_user(g.user.id)
    result = deregister_user(g.party.id, tournament.id, user)

    if result.is_ok():
        flash_success(gettext('Du wurdest abgemeldet.'))
    else:
        flash_error(result.unwrap_err())

    return redirect(url_for('netsession_tourney.view_overview', slug=slug))


@blueprint.get('/<slug>/teams/create')
@login_required
@templated
def create_team_form(slug):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    is_flatout2_tournament = uses_only_flatout2_stages(stages, [])
    registration_state = get_registration_state_for_tournament(tournament)

    if tournament.registration_mode == RegistrationMode.solo:
        flash_error(gettext('Dieses Turnier erlaubt nur Solo-Anmeldungen.'))
        return redirect_to('.view_participants', slug=slug)

    if not registration_state['can_register']:
        captain_team = get_captain_team_for_current_user(tournament.id)
        if captain_team is not None:
            return redirect_to(
                '.view_team',
                slug=slug,
                participant_id=captain_team.id,
            )
        if registration_state['insufficient_coins']:
            flash_error(
                gettext(
                    'Du hast aktuell nicht genügend Coins für dieses Turnier.'
                )
            )
        else:
            flash_error(
                gettext('Team-Anmeldungen sind aktuell nicht verfügbar.')
            )
        return redirect_to('.view_participants', slug=slug)

    current_page_id = get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'form': TeamCreationForm(),
        'join_form': TeamJoinForm(),
        'hide_bracket_tab': uses_only_ffa_simple_stages(stages, []),
        'show_preliminaries_tab': bool(
            get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        )
        and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'overview',
    }


@blueprint.post('/<slug>/teams/create')
@login_required
def create_team(slug):
    tournament = _get_tournament_or_404(slug)
    form_fields = request.form.copy()
    if request.files:
        form_fields.update(request.files)

    form = TeamCreationForm(form_fields)
    if not form.validate():
        flash_error(gettext('Ungültige Teamdaten.'))
        return redirect_to('.create_team_form', slug=slug)

    user = user_service.get_user(g.user.id)
    team_logo_url = None
    logo_file = request.files.get('logo_file')
    if logo_file is not None and logo_file.filename:
        upload_result = upload_logo_for_new_team(
            g.party.id,
            tournament,
            user,
            logo_file.stream,
            label=form.name.data,
            original_filename=logo_file.filename,
        )
        if upload_result.is_err():
            flash_error(upload_result.unwrap_err())
            return redirect_to('.create_team_form', slug=slug)
        team_logo_url = upload_result.unwrap()

    result = create_team_for_captain(
        g.party.id,
        tournament.id,
        user,
        form.name.data,
        team_logo_url=team_logo_url,
    )
    if result.is_ok():
        flash_success(gettext('Das Team wurde erstellt.'))
        team = result.unwrap()
        return redirect_to('.view_team', slug=slug, participant_id=team.id)
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.create_team_form', slug=slug)


@blueprint.post('/<slug>/teams/<uuid:participant_id>/update')
@login_required
def update_team(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    if tournament.status not in {TournamentStatus.draft, TournamentStatus.live}:
        flash_error(gettext('Team kann aktuell nicht bearbeitet werden.'))
        return redirect_to(
            '.view_team', slug=slug, participant_id=participant_id
        )

    form_fields = request.form.copy()
    if request.files:
        form_fields.update(request.files)

    form = TeamCreationForm(form_fields)
    if tournament.status == TournamentStatus.draft and not form.validate():
        flash_error(gettext('Ungültige Teamdaten.'))
        return redirect_to(
            '.view_team', slug=slug, participant_id=participant_id
        )

    user = user_service.get_user(g.user.id)
    logo_file = request.files.get('logo_file')
    replace_logo = _is_logo_replacement(logo_file)
    team_logo_url = None
    if replace_logo:
        upload_result = upload_logo_for_managed_team(
            g.party.id,
            tournament.id,
            participant_id,
            user,
            logo_file.stream,
            label=form.name.data,
            original_filename=logo_file.filename,
        )
        if upload_result.is_err():
            flash_error(upload_result.unwrap_err())
            return redirect_to(
                '.view_team', slug=slug, participant_id=participant_id
            )
        team_logo_url = upload_result.unwrap()

    result = update_managed_team_for_captain(
        g.party.id,
        tournament.id,
        participant_id,
        user,
        _get_team_update_name(tournament, form),
        team_logo_url=team_logo_url,
        replace_logo=replace_logo,
    )
    _flash_team_update_result(result)

    return redirect_to('.view_team', slug=slug, participant_id=participant_id)


def _is_logo_replacement(logo_file) -> bool:
    return bool(logo_file is not None and logo_file.filename)


def _get_team_update_name(tournament, form) -> str:
    return (
        form.name.data
        if tournament.status == TournamentStatus.draft
        else request.form.get('name', '')
    )


def _flash_team_update_result(result) -> None:
    if result.is_ok():
        flash_success(gettext('Das Team wurde aktualisiert.'))
    else:
        flash_error(result.unwrap_err())


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
