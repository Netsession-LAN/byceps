"""
byceps.services.netsession_tourney.blueprints.admin.stage_generation_flatout2_submit
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Submitting the generation form of a FlatOut 2 stage (see
`routes_stage_generation`): round configuration, round start times,
generating the matches.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import g, request
from flask_babel import gettext, to_utc

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_generation import (
    parse_flatout2_generation_configuration,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_generation_common import (
    flash_generation_result,
    redirect_to_stage_view,
    StageGenerationRequest,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    deserialize_datetime_local,
)
from byceps.services.netsession_tourney.generation_participants import (
    get_stage_generation_participants,
)
from byceps.services.netsession_tourney.match_generation import (
    generate_stage_matches,
)
from byceps.util.framework.flash import flash_error
from byceps.util.result import Err, Ok, Result


def generate_flatout2_stage_matches(generation: StageGenerationRequest) -> Any:
    party = generation.party
    tournament = generation.tournament
    stage = generation.stage

    participants_result = get_stage_generation_participants(
        party.id, tournament.id, stage.id
    )
    if participants_result.is_err():
        return _render_error(generation, participants_result.unwrap_err())

    flatout2_config_result = parse_flatout2_generation_configuration(
        stage,
        participants_result.unwrap(),
        request.form,
    )
    if flatout2_config_result.is_err():
        return _render_error(generation, flatout2_config_result.unwrap_err())

    (
        stage_settings_patch,
        match_settings_by_round_and_match_no,
    ) = flatout2_config_result.unwrap()

    round_starts_result = _parse_round_starts(generation, stage_settings_patch)
    if round_starts_result.is_err():
        return round_starts_result.unwrap_err()
    round_starts_at_by_round_no = round_starts_result.unwrap()

    correlation_id = request.headers.get('X-Correlation-ID')
    flash_generation_result(
        generate_stage_matches(
            party.id,
            tournament.id,
            generation.stage_id,
            g.user.as_user(),
            correlation_id=correlation_id,
            round_starts_at_by_round_no=round_starts_at_by_round_no or None,
            stage_settings_patch=stage_settings_patch,
            match_settings_by_round_and_match_no=match_settings_by_round_and_match_no,
        )
    )

    return redirect_to_stage_view(party, tournament, stage.id)


def _render_error(
    generation: StageGenerationRequest, message: str, **extra_kwargs: Any
) -> Any:
    flash_error(message)
    return generation.render_form(
        generation.party.id,
        generation.tournament.id,
        generation.stage.id,
        erroneous_flatout2_generation_form=request.form,
        **extra_kwargs,
    )


def _parse_round_starts(
    generation: StageGenerationRequest, stage_settings_patch: dict
) -> Result[dict[int, datetime], Any]:
    """Return the start times per round; on an invalid value, the
    re-rendered form."""
    round_starts_at_by_round_no: dict[int, datetime] = {}
    for round_config in stage_settings_patch.get('flatout2_rounds', []):
        round_no = int(round_config.get('round_no') or 0)
        if round_no < 1:
            continue
        raw_value = (
            request.form.get(f'round_starts_at_round_{round_no}') or ''
        ).strip()
        if not raw_value:
            continue
        starts_at_local = deserialize_datetime_local(raw_value)
        if starts_at_local is None:
            return Err(
                _render_error(
                    generation,
                    gettext(
                        'Ungültiger Startzeitpunkt für Runde %(round_no)s.',
                        round_no=round_no,
                    ),
                    erroneous_round_start_values_by_round_no={
                        round_no: raw_value
                    },
                )
            )
        round_starts_at_by_round_no[round_no] = to_utc(starts_at_local)

    return Ok(round_starts_at_by_round_no)
