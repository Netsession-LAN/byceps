"""
byceps.services.netsession_tourney.blueprints.admin.routes_stage_actions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes to start the stage builder, show its review step, change
the participant source of a stage and delete a stage (see
`routes_stage_management`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney.stage_service import (
    delete_stage,
    update_stage,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required, redirect_to

from .result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
    get_stage_or_404,
)
from .result_redirects import (
    redirect_to_related_tournament_view,
)
from .stage_builder_participant_source import (
    participant_source_settings_from_form,
)
from .stage_builder_wizard_state import (
    assert_tournament_has_no_stages_for_builder_or_redirect,
    build_stage_builder_review_preview,
    is_stage_builder_main_complete,
    is_stage_builder_preliminary_complete,
    is_stage_builder_timing_complete,
    stage_builder_steps,
)
from .wizard_helpers import (
    get_stage_builder_wizard_state,
)


def register_stage_builder_start_routes(blueprint):
    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder'
    )
    @permission_required('netsession_tourney.manage')
    def stage_builder_form(party_id, tournament_id):
        return redirect_to(
            '.stage_builder_wizard_main',
            party_id=party_id,
            tournament_id=tournament_id,
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder'
    )
    @permission_required('netsession_tourney.manage')
    def stage_builder_create(party_id, tournament_id):
        return redirect_to(
            '.stage_builder_wizard_main',
            party_id=party_id,
            tournament_id=tournament_id,
        )


def register_stage_builder_review_routes(blueprint):
    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/review'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage_builder/review')
    def stage_builder_wizard_review(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not is_stage_builder_main_complete(state):
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )
        if not is_stage_builder_preliminary_complete(state):
            return redirect_to(
                '.stage_builder_wizard_preliminary',
                party_id=party.id,
                tournament_id=tournament.id,
            )
        if not is_stage_builder_timing_complete(state):
            return redirect_to(
                '.stage_builder_wizard_timing',
                party_id=party.id,
                tournament_id=tournament.id,
            )

        return {
            'party': party,
            'tournament': tournament,
            'state': state,
            'wizard_step': 'review',
            'wizard_steps': stage_builder_steps(),
            'stage_builder_preview_summary': build_stage_builder_review_preview(
                party,
                tournament,
                state=state,
            ),
        }


def _get_eligible_source_stages(stages: list[Any], stage: Any) -> dict:
    return {
        stage_item.id: stage_item
        for stage_item in stages
        if stage_item.id != stage.id and stage_item.order_no < stage.order_no
    }


def _merge_participant_source_settings(
    stage_settings: dict, participant_source_settings: dict
) -> dict:
    settings = dict(stage_settings)
    for key in (
        'participant_source_mode',
        'qualifier_source_stage_ids',
        'qualifier_top_n',
    ):
        settings.pop(key, None)
    settings.update(participant_source_settings)
    return settings


def _update_stage_settings(
    party_id: Any, tournament_id: Any, stage: Any, settings: dict
) -> None:
    match update_stage(
        party_id,
        tournament_id,
        stage.id,
        stage.type,
        stage.name,
        settings,
        g.user.as_user(),
    ):
        case Ok(_):
            flash_success(
                gettext('Teilnehmerquelle der Phase wurde aktualisiert.')
            )
        case Err(message):
            flash_error(message)


def register_stage_participant_source_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/<uuid:stage_id>/participant-source'
    )
    @permission_required('netsession_tourney.manage')
    def stage_participant_source_update(party_id, tournament_id, stage_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        stage = get_stage_or_404(party.id, tournament.id, stage_id)
        stages = get_stages_for_tournament(party.id, tournament.id)

        eligible_source_stages = _get_eligible_source_stages(stages, stage)
        match participant_source_settings_from_form(
            request.form, eligible_source_stages=eligible_source_stages
        ):
            case Err(message):
                flash_error(message)
                return redirect_to(
                    '.view',
                    party_id=party.id,
                    tournament_id=tournament.id,
                    tab='stages',
                    stage_id=stage.id,
                )
            case Ok(participant_source_settings):
                pass

        settings = _merge_participant_source_settings(
            stage.settings, participant_source_settings
        )
        _update_stage_settings(party.id, tournament.id, stage, settings)

        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='stages',
            stage_id=stage.id,
        )


def register_stage_delete_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/<uuid:stage_id>/delete'
    )
    @permission_required('netsession_tourney.manage')
    def stage_delete(party_id, tournament_id, stage_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match delete_stage(
            party.id,
            tournament.id,
            stage_id,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Phase wurde gelöscht.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)
