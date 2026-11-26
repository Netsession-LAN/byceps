"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament_actions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes to send tournament notifications, show a participant and
change the tournament status (see `routes_tournament`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney import (
    notification_service,
    participant_state,
    registration_validation,
    tournament_lifecycle_service,
)
from byceps.services.netsession_tourney.forms import (
    AdminTeamMemberAddForm,
    ParticipantDisqualifyForm,
    ParticipantStatusForm,
    TournamentNotificationSendForm,
)
from byceps.services.netsession_tourney.screen_name_suggestions import (
    get_suggested_screen_names_for_party,
)
from byceps.services.user import user_service
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required, redirect_to

from .result_helpers import (
    _get_tournament_or_404,
    get_participant_or_404,
    get_party_or_404,
)
from .result_redirects import (
    redirect_to_related_tournament_view,
)


def register_tournament_notification_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/notifications/send'
    )
    @permission_required('netsession_tourney.manage')
    def tournament_notification_send(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        form = TournamentNotificationSendForm(request.form)
        if not form.validate():
            flash_error(
                gettext('Benachrichtigung konnte nicht gesendet werden.')
            )
            return redirect_to(
                '.view',
                party_id=party.id,
                tournament_id=tournament.id,
                tab='notifications',
            )

        match notification_service.send_manual_tournament_notification(
            party.id,
            tournament.id,
            g.user.as_user(),
            title=form.title.data or '',
            body=form.body.data or '',
            target_url=form.target_url.data or None,
        ):
            case Err(message):
                flash_error(gettext(message))
            case Ok(dispatch_result):
                flash_success(
                    gettext(
                        'Benachrichtigung wurde an %(user_count)s Teilnehmer mit %(subscription_count)s aktiven Browser-Subscriptions gesendet.',
                        user_count=dispatch_result.recipient_user_count,
                        subscription_count=dispatch_result.subscription_count,
                    )
                )

        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='notifications',
        )


def register_participant_view_routes(blueprint):
    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/participants/<uuid:participant_id>'
    )
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/participant/view')
    def participant_view(party_id, tournament_id, participant_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        participant = get_participant_or_404(
            party.id, tournament.id, participant_id
        )

        members_by_participant_id = (
            registration_validation.get_team_members_for_participants(
                {participant.id}
            )
        )
        members = members_by_participant_id.get(participant.id, [])
        member_user_ids = {member.user_id for member in members}
        user_ids = set(member_user_ids)
        if participant.manager_user_id is not None:
            user_ids.add(participant.manager_user_id)
        users_by_id = user_service.get_users_indexed_by_id(user_ids)

        return {
            'party': party,
            'tournament': tournament,
            'participant': participant,
            'members': members,
            'users_by_id': users_by_id,
            'suggested_screen_names': get_suggested_screen_names_for_party(
                party.id
            ),
            'participant_disqualify_form': ParticipantDisqualifyForm(
                data={'reason_code': 'admin_disqualification'}
            ),
            'status_form': ParticipantStatusForm(),
            'team_member_add_form': AdminTeamMemberAddForm(),
            'active_participant_count': participant_state.count_active_participants_for_tournament(
                party.id, tournament.id
            ),
        }


def register_tournament_status_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/publish'
    )
    @permission_required('netsession_tourney.manage')
    def publish(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match tournament_lifecycle_service.publish_tournament(
            party.id, tournament.id, g.user.as_user()
        ):
            case Ok(_):
                flash_success(gettext('Turnier wurde veröffentlicht.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/unpublish'
    )
    @permission_required('netsession_tourney.manage')
    def unpublish(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match tournament_lifecycle_service.unpublish_tournament(
            party.id, tournament.id, g.user.as_user()
        ):
            case Ok(_):
                flash_success(gettext('Turnier ist wieder ein Entwurf.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/close'
    )
    @permission_required('netsession_tourney.manage')
    def close(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match tournament_lifecycle_service.close_tournament(
            party.id, tournament.id, g.user.as_user()
        ):
            case Ok(_):
                flash_success(gettext('Turnier wurde abgeschlossen.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/cancel'
    )
    @permission_required('netsession_tourney.manage')
    def cancel(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match tournament_lifecycle_service.cancel_tournament(
            party.id, tournament.id, g.user.as_user()
        ):
            case Ok(_):
                flash_success(gettext('Turnier wurde abgesagt.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)


def register_tournament_delete_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/delete'
    )
    @permission_required('netsession_tourney.manage')
    def delete(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match tournament_lifecycle_service.delete_tournament(
            party.id, tournament.id, g.user.as_user()
        ):
            case Ok(_):
                flash_success(gettext('Turnier wurde gelöscht.'))
                return redirect_to('.index', party_id=party.id)
            case Err(message):
                flash_error(message)
                return redirect_to_related_tournament_view(
                    party.id, tournament.id
                )
