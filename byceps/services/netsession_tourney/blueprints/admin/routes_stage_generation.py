"""
byceps.services.netsession_tourney.blueprints.admin.routes_stage_generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes to generate the matches of a stage: the generation form and its
submit (see `routes_stage_management`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flask import request

from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
    get_stage_or_404,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_generation import (
    is_flatout2_stage_type,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_display import (
    is_builder_main_stage_with_preliminary_source,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_generation_common import (
    count_existing_stage_matches,
    get_generation_block_redirect,
    redirect_to_stage_view,
    StageGenerationRequest,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_generation_flatout2_submit import (
    generate_flatout2_stage_matches,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_generation_form_context import (
    build_flatout2_generation_form_context,
    build_generation_form_context,
    GenerationFormInput,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_generation_submit import (
    generate_stage_matches_from_form,
)
from byceps.services.netsession_tourney.generation_participants import (
    get_stage_generation_participants,
)
from byceps.services.party.models import Party
from byceps.util.framework.flash import flash_error
from byceps.util.framework.templating import templated
from byceps.util.views import permission_required


def register_stage_generation_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/<uuid:stage_id>/generate'
    )
    @permission_required('netsession_tourney.manage')
    def stage_generate(party_id, tournament_id, stage_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        stage = get_stage_or_404(party.id, tournament.id, stage_id)
        return _generate_stage(
            party, tournament, stage, stage_id, stage_generate_form
        )

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/<uuid:stage_id>/generate'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage/generate_form')
    def stage_generate_form(
        party_id,
        tournament_id,
        stage_id,
        *,
        erroneous_auto_seed_participant_ids: list[str] | None = None,
        erroneous_manual_seed_values_by_participant_id=None,
        erroneous_round_start_values_by_round_no: dict[int, str] | None = None,
        erroneous_flatout2_generation_form=None,
    ):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        stage = get_stage_or_404(party.id, tournament.id, stage_id)
        return _build_generation_form(
            GenerationFormInput(
                party=party,
                tournament=tournament,
                stage=stage,
                erroneous_auto_seed_participant_ids=erroneous_auto_seed_participant_ids,
                erroneous_manual_seed_values_by_participant_id=erroneous_manual_seed_values_by_participant_id,
                erroneous_round_start_values_by_round_no=erroneous_round_start_values_by_round_no,
                erroneous_flatout2_generation_form=erroneous_flatout2_generation_form,
            )
        )


def _generate_stage(
    party: Party,
    tournament: Any,
    stage: Any,
    stage_id: Any,
    render_form: Callable[..., Any],
) -> Any:
    erroneous_flatout2_generation_form = (
        request.form if is_flatout2_stage_type(stage.type) else None
    )
    redirect_response = get_generation_block_redirect(party, tournament, stage)
    if redirect_response is not None:
        return redirect_response

    is_locked_auto_seeding = is_builder_main_stage_with_preliminary_source(
        stage
    )
    existing_stage_match_count = count_existing_stage_matches(
        party, tournament, stage
    )
    is_incremental_swiss_generation = False

    generation = StageGenerationRequest(
        party=party,
        tournament=tournament,
        stage=stage,
        stage_id=stage_id,
        erroneous_flatout2_generation_form=erroneous_flatout2_generation_form,
        render_form=render_form,
    )
    if is_flatout2_stage_type(stage.type):
        return generate_flatout2_stage_matches(generation)

    return generate_stage_matches_from_form(generation, is_locked_auto_seeding)


def _build_generation_form(form_input: GenerationFormInput) -> Any:
    party = form_input.party
    tournament = form_input.tournament
    stage = form_input.stage

    redirect_response = get_generation_block_redirect(party, tournament, stage)
    if redirect_response is not None:
        return redirect_response

    is_locked_auto_seeding = is_builder_main_stage_with_preliminary_source(
        stage
    )
    existing_stage_match_count = count_existing_stage_matches(
        party, tournament, stage
    )
    is_incremental_swiss_generation = False
    is_incremental_flatout2_generation = False

    participants_result = get_stage_generation_participants(
        party.id, tournament.id, stage.id
    )
    if participants_result.is_err():
        flash_error(participants_result.unwrap_err())
        return redirect_to_stage_view(party, tournament, stage.id)
    participants = participants_result.unwrap()

    if is_flatout2_stage_type(stage.type):
        return build_flatout2_generation_form_context(
            form_input,
            participants,
            existing_stage_match_count=existing_stage_match_count,
            is_incremental_flatout2_generation=is_incremental_flatout2_generation,
        )

    return build_generation_form_context(
        form_input,
        participants,
        is_locked_auto_seeding=is_locked_auto_seeding,
        existing_stage_match_count=existing_stage_match_count,
        is_incremental_swiss_generation=is_incremental_swiss_generation,
        is_incremental_flatout2_generation=is_incremental_flatout2_generation,
    )
