"""
byceps.services.netsession_tourney.blueprints.admin.routes_stage_form
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes to create and update a single stage with the stage form (see
`routes_stage_management`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
    get_stage_or_404,
)
from byceps.services.netsession_tourney.blueprints.admin.result_redirects import (
    redirect_to_related_tournament_view,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_stage_form_helpers import (
    build_default_stage_create_form,
    build_default_stage_update_form,
    build_posted_stage_form,
    build_update_generation_summary,
    create_stage_from_form,
    earlier_source_stages,
    stage_type_or_none,
    update_stage_from_form,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_stage_participant_source_form import (
    apply_posted_participant_source,
    default_participant_source,
    participant_source_context,
    participant_source_from_settings,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_form_data import (
    get_ffa_placement_points_row_count,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_meta import (
    build_stage_builder_meta,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.util.framework.flash import flash_error
from byceps.util.framework.templating import templated
from byceps.util.result import Err
from byceps.util.views import permission_required


def register_stage_create_routes(blueprint):
    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/create'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage/create_form')
    def stage_create_form(party_id, tournament_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = (
            erroneous_form
            if erroneous_form is not None
            else build_default_stage_create_form(tournament)
        )
        stages = get_stages_for_tournament(party.id, tournament.id)
        source = default_participant_source()
        if erroneous_form is not None:
            source = apply_posted_participant_source(source)

        return {
            'party': party,
            'tournament': tournament,
            'form': form,
            'placement_points_row_count': get_ffa_placement_points_row_count(
                tournament,
                form.placement_points.data,
                stage_type=stage_type_or_none(form.type.data),
                max_players_per_match=form.max_players_per_match.data,
            ),
            'show_participant_source_settings': True,
            **participant_source_context(source),
            'available_source_stages': stages,
        }

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages'
    )
    @permission_required('netsession_tourney.manage')
    def stage_create(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = build_posted_stage_form(tournament)
        if not form.validate():
            flash_error(gettext('Ungültige Phasendaten.'))
            return stage_create_form(party.id, tournament.id, form)

        match create_stage_from_form(party, tournament, form):
            case Err(message):
                flash_error(message)
                return stage_create_form(party.id, tournament.id, form)

        return redirect_to_related_tournament_view(party.id, tournament.id)


def register_stage_update_routes(blueprint):
    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/<uuid:stage_id>/update'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage/update_form')
    def stage_update_form(
        party_id, tournament_id, stage_id, erroneous_form=None
    ):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        stage = get_stage_or_404(party.id, tournament.id, stage_id)
        stage_builder_meta = build_stage_builder_meta(stage)
        stage_builder_generation_summary = build_update_generation_summary(
            party, tournament, stage, stage_builder_meta
        )

        form = (
            erroneous_form
            if erroneous_form is not None
            else build_default_stage_update_form(tournament, stage)
        )

        stages = get_stages_for_tournament(party.id, tournament.id)
        available_source_stages = earlier_source_stages(stages, stage)

        source = participant_source_from_settings(stage.settings)
        if erroneous_form is not None:
            source = apply_posted_participant_source(source)

        return {
            'party': party,
            'tournament': tournament,
            'stage': stage,
            'form': form,
            'placement_points_row_count': get_ffa_placement_points_row_count(
                tournament,
                form.placement_points.data,
                stage_type=stage.type,
                max_players_per_match=form.max_players_per_match.data,
                existing_settings=stage.settings,
            ),
            'show_participant_source_settings': True,
            **participant_source_context(source),
            'available_source_stages': available_source_stages,
            'stage_builder_meta': stage_builder_meta,
            'stage_builder_generation_summary': stage_builder_generation_summary,
        }

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/<uuid:stage_id>/update'
    )
    @permission_required('netsession_tourney.manage')
    def stage_update(party_id, tournament_id, stage_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        stage = get_stage_or_404(party.id, tournament.id, stage_id)

        form = build_posted_stage_form(tournament)
        if not form.validate():
            flash_error(gettext('Ungültige Phasendaten.'))
            return stage_update_form(party.id, tournament.id, stage_id, form)

        match update_stage_from_form(party, tournament, stage, stage_id, form):
            case Err(message):
                flash_error(message)
                return stage_update_form(
                    party.id, tournament.id, stage_id, form
                )

        return redirect_to_related_tournament_view(party.id, tournament.id)
