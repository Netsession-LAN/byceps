"""
byceps.services.netsession_tourney.blueprints.admin.routes_participants_teams
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes to create teams and manage their members (see
`routes_participants_matches`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney.forms import (
    AdminTeamCreateForm,
    AdminTeamMemberAddForm,
)
from byceps.services.netsession_tourney.logo_service import (
    upload_logo_image,
)
from byceps.services.netsession_tourney.team_admin_service import (
    add_team_member_by_admin,
    assign_team_captain_by_admin,
    create_team_by_admin,
    remove_team_member_by_admin,
)
from byceps.services.user import user_service
from byceps.services.user.models import UserID
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok, Result
from byceps.util.views import permission_required

from .result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
)
from .result_redirects import (
    redirect_to_participant_or_tournament_view,
    redirect_to_related_tournament_view,
)


def _get_team_form_fields() -> Any:
    form_fields = request.form.copy()
    if request.files:
        form_fields.update(request.files)
    return form_fields


def _upload_team_logo(
    party_id: Any, form: AdminTeamCreateForm
) -> Result[str | None, str]:
    """Upload the submitted team logo, if any."""
    logo_file = request.files.get('logo_file')
    if logo_file is None or not logo_file.filename:
        return Ok(None)

    return upload_logo_image(
        party_id,
        g.user.as_user(),
        logo_file.stream,
        label=form.name.data,
        original_filename=logo_file.filename,
    )


def _create_team(
    party_id: Any,
    tournament_id: Any,
    name: str,
    captain_user: Any,
    team_logo_url: str | None,
) -> None:
    match create_team_by_admin(
        party_id,
        tournament_id,
        name,
        captain_user,
        g.user.as_user(),
        team_logo_url=team_logo_url,
    ):
        case Ok(_):
            flash_success(gettext('Team wurde angelegt.'))
        case Err(message):
            flash_error(message)


def register_team_create_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/teams/create'
    )
    @permission_required('netsession_tourney.manage')
    def team_create(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = AdminTeamCreateForm(_get_team_form_fields())
        if not form.validate():
            flash_error(gettext('Ungültige Teamdaten.'))
            return redirect_to_related_tournament_view(party.id, tournament.id)

        captain_screen_name = form.captain_screen_name.data.strip()
        captain_user = user_service.find_user_by_screen_name(
            captain_screen_name
        )
        if captain_user is None:
            flash_error(gettext('Unbekannter Benutzer.'))
            return redirect_to_related_tournament_view(party.id, tournament.id)

        logo_result = _upload_team_logo(party.id, form)
        if logo_result.is_err():
            flash_error(logo_result.unwrap_err())
            return redirect_to_related_tournament_view(party.id, tournament.id)
        team_logo_url = logo_result.unwrap()

        _create_team(
            party.id, tournament.id, form.name.data, captain_user, team_logo_url
        )

        return redirect_to_related_tournament_view(party.id, tournament.id)


def register_team_member_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/teams/<uuid:participant_id>/members/add'
    )
    @permission_required('netsession_tourney.manage')
    def team_member_add(party_id, tournament_id, participant_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = AdminTeamMemberAddForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültige Daten zum Teammitglied.'))
            return redirect_to_participant_or_tournament_view(
                party.id, tournament.id, participant_id
            )

        screen_name = form.screen_name.data.strip()
        member_user = user_service.find_user_by_screen_name(screen_name)
        if member_user is None:
            flash_error(gettext('Unbekannter Benutzer.'))
            return redirect_to_participant_or_tournament_view(
                party.id, tournament.id, participant_id
            )

        match add_team_member_by_admin(
            party.id,
            tournament.id,
            participant_id,
            member_user,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Teammitglied wurde hinzugefügt.'))
            case Err(message):
                flash_error(message)

        return redirect_to_participant_or_tournament_view(
            party.id, tournament.id, participant_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/teams/<uuid:participant_id>/members/<uuid:member_user_id>/remove'
    )
    @permission_required('netsession_tourney.manage')
    def team_member_remove(
        party_id, tournament_id, participant_id, member_user_id
    ):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match remove_team_member_by_admin(
            party.id,
            tournament.id,
            participant_id,
            member_user_id,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Teammitglied wurde entfernt.'))
            case Err(message):
                flash_error(message)

        return redirect_to_participant_or_tournament_view(
            party.id, tournament.id, participant_id
        )


def register_team_captain_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/teams/<uuid:participant_id>/captain'
    )
    @permission_required('netsession_tourney.manage')
    def team_captain_set(party_id, tournament_id, participant_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        raw_member_user_id = (request.form.get('member_user_id') or '').strip()
        try:
            member_user_id = UserID(UUID(raw_member_user_id))
        except ValueError:
            flash_error(gettext('Ungültiges Team-Mitglied.'))
            return redirect_to_participant_or_tournament_view(
                party.id, tournament.id, participant_id
            )

        match assign_team_captain_by_admin(
            party.id,
            tournament.id,
            participant_id,
            member_user_id,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Teamkapitän wurde geändert.'))
            case Err(message):
                flash_error(message)

        return redirect_to_participant_or_tournament_view(
            party.id, tournament.id, participant_id
        )
