"""
byceps.services.netsession_tourney.blueprints.admin.routes_participants_matches
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.routes_matches_edit import (
    register_match_schedule_dispute_routes,
    register_match_slot_host_routes,
    register_match_walkover_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_participants_entries import (
    register_participant_add_routes,
    register_participant_removal_routes,
    register_participant_seed_status_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_participants_teams import (
    register_team_captain_routes,
    register_team_create_routes,
    register_team_member_routes,
)
from byceps.services.netsession_tourney.discord_service import configure_discord
from byceps.services.netsession_tourney.forms import (
    DiscordConfigForm,
    MatchResultForm,
)
from byceps.services.netsession_tourney.logo_service import (
    get_discord_forum_image_choices,
    is_known_discord_forum_image_url,
)
from byceps.services.netsession_tourney.match_queries import (
    get_match_slots,
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.result_service import (
    report_result,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
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
    redirect_to_related_tournament_view,
)
from .route_config import DISCORD_DM_EVENT_CHOICES, DISCORD_FORUM_EVENT_CHOICES
from .stage_builder_flatout2_generation import (
    is_flatout2_stage_type,
)
from .stage_builder_stage_form_data import (
    is_ffa_result_stage_type,
)


def register(blueprint):
    register_participant_add_routes(blueprint)
    register_team_create_routes(blueprint)
    register_team_member_routes(blueprint)
    register_team_captain_routes(blueprint)
    register_participant_seed_status_routes(blueprint)
    register_participant_removal_routes(blueprint)
    register_match_slot_host_routes(blueprint)

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

    register_match_walkover_routes(blueprint)
    register_match_schedule_dispute_routes(blueprint)

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
