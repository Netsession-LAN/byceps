"""
byceps.services.netsession_tourney.blueprints.admin.routes_participants_matches
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from uuid import UUID

from flask import g, request
from flask_babel import gettext, to_utc

from byceps.services.netsession_tourney.discord_service import configure_discord
from byceps.services.netsession_tourney.flatout2_rounds import (
    set_flatout2_match_host_by_admin,
)
from byceps.services.netsession_tourney.forms import (
    AdminParticipantAddForm,
    AdminTeamCreateForm,
    AdminTeamMemberAddForm,
    DiscordConfigForm,
    MatchDisputeForm,
    MatchResultForm,
    MatchScheduleForm,
    MatchWalkoverForm,
    ParticipantDisqualifyForm,
    ParticipantSeedForm,
    ParticipantStatusForm,
)
from byceps.services.netsession_tourney.logo_service import (
    get_discord_forum_image_choices,
    is_known_discord_forum_image_url,
    upload_logo_image,
)
from byceps.services.netsession_tourney.match_queries import (
    get_match_slots,
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.match_schedule import reschedule_match
from byceps.services.netsession_tourney.models import ParticipantStatus
from byceps.services.netsession_tourney.participant_admin_service import (
    add_user_participant_by_admin,
    disqualify_participant,
    remove_participant_by_admin,
    set_participant_status,
)
from byceps.services.netsession_tourney.result_deletion import (
    delete_match_result_by_admin,
    open_match_dispute,
)
from byceps.services.netsession_tourney.result_service import (
    apply_walkover_result,
    report_result,
)
from byceps.services.netsession_tourney.seed_service import set_participant_seed
from byceps.services.netsession_tourney.slot_assignment import (
    set_match_slot_participant_by_admin,
)
from byceps.services.netsession_tourney.team_admin_service import (
    add_team_member_by_admin,
    assign_team_captain_by_admin,
    create_team_by_admin,
    remove_team_member_by_admin,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.services.user import user_service
from byceps.services.user.models import UserID
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required

from .result_helpers import (
    _get_tournament_or_404,
    build_score_payload,
    get_or_create_idempotency_key,
    get_party_or_404,
    parse_admin_ffa_result_form,
    parse_admin_flatout2_result_form,
    parse_csv,
)
from .result_redirects import (
    redirect_to_match_or_tournament_view,
    redirect_to_participant_or_tournament_view,
    redirect_to_related_tournament_view,
)
from .route_config import DISCORD_DM_EVENT_CHOICES, DISCORD_FORUM_EVENT_CHOICES
from .stage_builder_helpers import (
    is_ffa_result_stage_type,
    is_flatout2_stage_type,
)


def register(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/participants/add'
    )
    @permission_required('netsession_tourney.manage')
    def participant_add(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = AdminParticipantAddForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültige Teilnehmerdaten.'))
            return redirect_to_related_tournament_view(party.id, tournament.id)

        screen_name = form.screen_name.data.strip()
        participant_user = user_service.find_user_by_screen_name(screen_name)
        if participant_user is None:
            flash_error(gettext('Unbekannter Benutzer.'))
            return redirect_to_related_tournament_view(party.id, tournament.id)

        match add_user_participant_by_admin(
            party.id,
            tournament.id,
            participant_user,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Teilnehmer wurde hinzugefügt.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/teams/create'
    )
    @permission_required('netsession_tourney.manage')
    def team_create(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form_fields = request.form.copy()
        if request.files:
            form_fields.update(request.files)

        form = AdminTeamCreateForm(form_fields)
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

        team_logo_url = None
        logo_file = request.files.get('logo_file')
        if logo_file is not None and logo_file.filename:
            upload_result = upload_logo_image(
                party.id,
                g.user.as_user(),
                logo_file.stream,
                label=form.name.data,
                original_filename=logo_file.filename,
            )
            if upload_result.is_err():
                flash_error(upload_result.unwrap_err())
                return redirect_to_related_tournament_view(
                    party.id, tournament.id
                )
            team_logo_url = upload_result.unwrap()

        match create_team_by_admin(
            party.id,
            tournament.id,
            form.name.data,
            captain_user,
            g.user.as_user(),
            team_logo_url=team_logo_url,
        ):
            case Ok(_):
                flash_success(gettext('Team wurde angelegt.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)

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

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/participants/<uuid:participant_id>/seed'
    )
    @permission_required('netsession_tourney.manage')
    def participant_set_seed(party_id, tournament_id, participant_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = ParticipantSeedForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültiger Setzplatz.'))
            return redirect_to_participant_or_tournament_view(
                party.id, tournament.id, participant_id
            )

        match set_participant_seed(
            party.id,
            tournament.id,
            participant_id,
            form.seed.data,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Setzplatz wurde gespeichert.'))
            case Err(message):
                flash_error(message)

        return redirect_to_participant_or_tournament_view(
            party.id, tournament.id, participant_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/participants/<uuid:participant_id>/status'
    )
    @permission_required('netsession_tourney.manage')
    def participant_set_status(party_id, tournament_id, participant_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = ParticipantStatusForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültiger Status.'))
            return redirect_to_participant_or_tournament_view(
                party.id, tournament.id, participant_id
            )

        status = ParticipantStatus(form.status.data)
        match set_participant_status(
            party.id,
            tournament.id,
            participant_id,
            status,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(
                    gettext('Status des Teilnehmers wurde gespeichert.')
                )
            case Err(message):
                flash_error(message)

        return redirect_to_participant_or_tournament_view(
            party.id, tournament.id, participant_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/participants/<uuid:participant_id>/disqualify'
    )
    @permission_required('netsession_tourney.manage')
    def participant_disqualify(party_id, tournament_id, participant_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = ParticipantDisqualifyForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültige Angaben zur Disqualifikation.'))
            return redirect_to_participant_or_tournament_view(
                party.id, tournament.id, participant_id
            )

        match disqualify_participant(
            party.id,
            tournament.id,
            participant_id,
            g.user.as_user(),
            reason_code=form.reason_code.data,
            comment=form.comment.data,
            correlation_id=request.headers.get('X-Correlation-ID'),
        ):
            case Ok(_):
                flash_success(gettext('Teilnehmer wurde disqualifiziert.'))
            case Err(message):
                flash_error(message)

        return redirect_to_participant_or_tournament_view(
            party.id, tournament.id, participant_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/participants/<uuid:participant_id>/remove'
    )
    @permission_required('netsession_tourney.manage')
    def participant_remove(party_id, tournament_id, participant_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        comment = (request.form.get('comment') or '').strip()
        match remove_participant_by_admin(
            party.id,
            tournament.id,
            participant_id,
            g.user.as_user(),
            comment=comment,
        ):
            case Ok(_):
                flash_success(gettext('Teilnehmer wurde entfernt.'))
            case Err(message):
                flash_error(message)

        return redirect_to_participant_or_tournament_view(
            party.id, tournament.id, participant_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/slots/<int:slot_no>'
    )
    @permission_required('netsession_tourney.manage')
    def match_slot_set(party_id, tournament_id, match_id, slot_no):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        raw_participant_id = (request.form.get('participant_id') or '').strip()
        participant_id = None
        if raw_participant_id:
            try:
                participant_id = UUID(raw_participant_id)
            except ValueError:
                flash_error(gettext('Ungültiger Teilnehmer.'))
                return redirect_to_match_or_tournament_view(
                    party.id, tournament.id, match_id
                )

        comment = (request.form.get('comment') or '').strip() or None
        match set_match_slot_participant_by_admin(
            party.id,
            tournament.id,
            match_id,
            slot_no,
            participant_id,
            g.user.as_user(),
            comment=comment,
        ):
            case Ok(_):
                flash_success(gettext('Match-Slot wurde aktualisiert.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/host'
    )
    @permission_required('netsession_tourney.manage')
    def match_host_set(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        raw_host_participant_id = (
            request.form.get('host_participant_id') or ''
        ).strip()
        host_participant_id = None
        if raw_host_participant_id:
            try:
                host_participant_id = UUID(raw_host_participant_id)
            except ValueError:
                flash_error(gettext('Ungültiger Host.'))
                return redirect_to_match_or_tournament_view(
                    party.id, tournament.id, match_id
                )

        match set_flatout2_match_host_by_admin(
            party.id,
            tournament.id,
            match_id,
            host_participant_id,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('FlatOut-2-Host wurde aktualisiert.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/result'
    )
    @permission_required('netsession_tourney.manage')
    def match_set_result(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        matches = get_matches_for_tournament(party.id, tournament.id)
        match = next((item for item in matches if item.id == match_id), None)
        if match is None:
            flash_error(gettext('Unbekanntes Match.'))
            return redirect_to_match_or_tournament_view(
                party.id, tournament.id, match_id
            )

        stages_by_id = {
            stage.id: stage
            for stage in get_stages_for_tournament(party.id, tournament.id)
        }
        stage = stages_by_id.get(match.stage_id)
        if stage is not None and is_ffa_result_stage_type(stage.type):
            slots = sorted(
                get_match_slots({match.id}).get(match.id, []),
                key=lambda slot: slot.slot_no,
            )
            parsed_ffa_result = (
                parse_admin_flatout2_result_form(request.form, slots)
                if is_flatout2_stage_type(stage.type)
                else parse_admin_ffa_result_form(
                    request.form,
                    slots,
                    placement_points_rules=stage.settings.get(
                        'placement_points_rules', []
                    ),
                )
            )
            if parsed_ffa_result.is_err():
                flash_error(parsed_ffa_result.unwrap_err())
                return redirect_to_match_or_tournament_view(
                    party.id, tournament.id, match_id
                )

            winner_slot, score, ranking, comment = parsed_ffa_result.unwrap()
            idempotency_key = get_or_create_idempotency_key(
                request.form.get('idempotency_key')
            )

            match report_result(
                party.id,
                tournament.id,
                match_id,
                g.user.id,
                idempotency_key=idempotency_key,
                winner_slot=winner_slot,
                score=score,
                ranking=ranking,
                actor_is_admin_or_referee=True,
                admin_comment=comment,
                reason_code='admin_override',
                correlation_id=request.headers.get('X-Correlation-ID'),
            ):
                case Ok(_):
                    flash_success(gettext('Ergebnis wurde gespeichert.'))
                case Err(message):
                    flash_error(message)

            return redirect_to_match_or_tournament_view(
                party.id, tournament.id, match_id
            )

        form = MatchResultForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültige Ergebnisdaten.'))
            return redirect_to_match_or_tournament_view(
                party.id, tournament.id, match_id
            )

        if form.slot_1_points.data == form.slot_2_points.data:
            flash_error(
                gettext(
                    'Gleichstände sind bei der manuellen Ergebniserfassung nicht erlaubt.'
                )
            )
            return redirect_to_match_or_tournament_view(
                party.id, tournament.id, match_id
            )

        winner_slot = (
            1 if form.slot_1_points.data > form.slot_2_points.data else 2
        )
        score = build_score_payload(
            f'{form.slot_1_points.data}:{form.slot_2_points.data}'
        )
        ranking = {}
        idempotency_key = get_or_create_idempotency_key(
            form.idempotency_key.data
        )
        comment = form.comment.data.strip() if form.comment.data else None

        match report_result(
            party.id,
            tournament.id,
            match_id,
            g.user.id,
            idempotency_key=idempotency_key,
            winner_slot=winner_slot,
            score=score,
            ranking=ranking,
            actor_is_admin_or_referee=True,
            admin_comment=comment,
            reason_code='admin_override',
            correlation_id=request.headers.get('X-Correlation-ID'),
        ):
            case Ok(_):
                flash_success(gettext('Ergebnis wurde gespeichert.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/walkover'
    )
    @permission_required('netsession_tourney.manage')
    def match_set_walkover(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = MatchWalkoverForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültige Daten für den kampflosen Sieg.'))
            return redirect_to_match_or_tournament_view(
                party.id, tournament.id, match_id
            )

        idempotency_key = get_or_create_idempotency_key(
            form.idempotency_key.data
        )

        match apply_walkover_result(
            party.id,
            tournament.id,
            match_id,
            g.user.as_user(),
            winner_slot=form.winner_slot.data,
            idempotency_key=idempotency_key,
            comment=form.comment.data,
            correlation_id=request.headers.get('X-Correlation-ID'),
        ):
            case Ok(_):
                flash_success(gettext('Kampfloser Sieg wurde gespeichert.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/result/delete'
    )
    @permission_required('netsession_tourney.manage')
    def match_delete_result(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match delete_match_result_by_admin(
            party.id,
            tournament.id,
            match_id,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Ergebnis wurde gelöscht.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/reschedule'
    )
    @permission_required('netsession_tourney.manage')
    def match_reschedule(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = MatchScheduleForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültige Planungsdaten.'))
            return redirect_to_match_or_tournament_view(
                party.id, tournament.id, match_id
            )

        match reschedule_match(
            party.id,
            tournament.id,
            match_id,
            to_utc(form.scheduled_at.data),
            g.user.as_user(),
            comment=form.comment.data,
            correlation_id=request.headers.get('X-Correlation-ID'),
        ):
            case Ok(_):
                flash_success(gettext('Match wurde neu angesetzt.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/dispute'
    )
    @permission_required('netsession_tourney.manage')
    def match_dispute(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = MatchDisputeForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültige Streitfall-Daten.'))
            return redirect_to_match_or_tournament_view(
                party.id, tournament.id, match_id
            )

        match open_match_dispute(
            party.id,
            tournament.id,
            match_id,
            g.user.as_user(),
            reason_code=form.reason_code.data,
            comment=form.comment.data,
            correlation_id=request.headers.get('X-Correlation-ID'),
        ):
            case Ok(_):
                flash_success(gettext('Streitfall wurde eröffnet.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/discord'
    )
    @permission_required('netsession_tourney.manage')
    def discord_update(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = DiscordConfigForm(request.form)
        form.discord_forum_image_url.choices = [
            ('', gettext('Kein Discord-Forum-Bild ausgewählt'))
        ] + get_discord_forum_image_choices(party.id)
        form.event_mask.choices = DISCORD_FORUM_EVENT_CHOICES
        form.discord_dm_event_mask.choices = DISCORD_DM_EVENT_CHOICES
        if not form.validate():
            flash_error(gettext('Discord-Konfiguration ist ungültig.'))
            return redirect_to_related_tournament_view(party.id, tournament.id)

        tag_ids = parse_csv(form.applied_tag_ids.data)
        event_mask = list(form.event_mask.data or [])
        discord_dm_event_mask = list(form.discord_dm_event_mask.data or [])
        discord_forum_image_url = form.discord_forum_image_url.data or None
        if discord_forum_image_url and not is_known_discord_forum_image_url(
            party.id, discord_forum_image_url
        ):
            flash_error(
                gettext('Das ausgewählte Discord-Forum-Bild ist ungültig.')
            )
            return redirect_to_related_tournament_view(party.id, tournament.id)

        match configure_discord(
            party.id,
            tournament.id,
            g.user.as_user(),
            enabled=bool(form.discord_enabled.data),
            forum_channel_id=form.forum_channel_id.data,
            discord_forum_image_url=discord_forum_image_url,
            applied_tag_ids=tag_ids,
            event_mask=event_mask,
            discord_dm_enabled=bool(form.discord_dm_enabled.data),
            discord_dm_event_mask=discord_dm_event_mask,
        ):
            case Ok(_):
                flash_success(
                    gettext('Discord-Konfiguration wurde aktualisiert.')
                )
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)
