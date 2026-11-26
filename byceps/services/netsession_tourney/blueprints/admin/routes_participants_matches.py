"""
byceps.services.netsession_tourney.blueprints.admin.routes_participants_matches
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

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
from byceps.services.netsession_tourney.blueprints.admin.routes_participants_match_result import (
    find_match,
    get_match_stage,
    is_ffa_result_stage,
    set_ffa_result,
    set_two_slot_result,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_participants_teams import (
    register_team_captain_routes,
    register_team_create_routes,
    register_team_member_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_form_checks import (
    is_invalid_discord_forum_image_url,
)
from byceps.services.netsession_tourney.discord_service import configure_discord
from byceps.services.netsession_tourney.forms import DiscordConfigForm
from byceps.services.netsession_tourney.logo_service import (
    get_discord_forum_image_choices,
)
from byceps.services.party.models import PartyID
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required

from .result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
    parse_csv,
)
from .result_redirects import (
    redirect_to_match_or_tournament_view,
    redirect_to_related_tournament_view,
)
from .route_config import DISCORD_DM_EVENT_CHOICES, DISCORD_FORUM_EVENT_CHOICES


def _build_discord_config_form(party_id: PartyID) -> DiscordConfigForm:
    form = DiscordConfigForm(request.form)
    form.discord_forum_image_url.choices = [
        ('', gettext('Kein Discord-Forum-Bild ausgewählt'))
    ] + get_discord_forum_image_choices(party_id)
    form.event_mask.choices = DISCORD_FORUM_EVENT_CHOICES
    form.discord_dm_event_mask.choices = DISCORD_DM_EVENT_CHOICES
    return form


def _parse_discord_update_values(form: DiscordConfigForm) -> dict[str, Any]:
    return {
        'tag_ids': parse_csv(form.applied_tag_ids.data),
        'event_mask': list(form.event_mask.data or []),
        'discord_dm_event_mask': list(form.discord_dm_event_mask.data or []),
        'discord_forum_image_url': form.discord_forum_image_url.data or None,
    }


def _apply_discord_update(
    party_id: PartyID,
    tournament_id: Any,
    form: DiscordConfigForm,
    values: dict[str, Any],
) -> None:
    match configure_discord(
        party_id,
        tournament_id,
        g.user.as_user(),
        enabled=bool(form.discord_enabled.data),
        forum_channel_id=form.forum_channel_id.data,
        discord_forum_image_url=values['discord_forum_image_url'],
        applied_tag_ids=values['tag_ids'],
        event_mask=values['event_mask'],
        discord_dm_enabled=bool(form.discord_dm_enabled.data),
        discord_dm_event_mask=values['discord_dm_event_mask'],
    ):
        case Ok(_):
            flash_success(gettext('Discord-Konfiguration wurde aktualisiert.'))
        case Err(message):
            flash_error(message)


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

        match = find_match(party.id, tournament.id, match_id)
        if match is None:
            flash_error(gettext('Unbekanntes Match.'))
            return redirect_to_match_or_tournament_view(
                party.id, tournament.id, match_id
            )

        stage = get_match_stage(party.id, tournament.id, match)
        if is_ffa_result_stage(stage):
            return set_ffa_result(
                party.id, tournament.id, match_id, match, stage
            )

        return set_two_slot_result(party.id, tournament.id, match_id)

    register_match_walkover_routes(blueprint)
    register_match_schedule_dispute_routes(blueprint)

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/discord'
    )
    @permission_required('netsession_tourney.manage')
    def discord_update(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = _build_discord_config_form(party.id)
        if not form.validate():
            flash_error(gettext('Discord-Konfiguration ist ungültig.'))
            return redirect_to_related_tournament_view(party.id, tournament.id)

        values = _parse_discord_update_values(form)
        if is_invalid_discord_forum_image_url(
            party.id, values['discord_forum_image_url']
        ):
            flash_error(
                gettext('Das ausgewählte Discord-Forum-Bild ist ungültig.')
            )
            return redirect_to_related_tournament_view(party.id, tournament.id)

        _apply_discord_update(party.id, tournament.id, form, values)

        return redirect_to_related_tournament_view(party.id, tournament.id)
