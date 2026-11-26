"""
byceps.services.netsession_tourney.blueprints.admin.stage_generation_submit
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Submitting the generation form of a stage other than FlatOut 2 (see
`routes_stage_generation`): seeds, round start times, generating the
matches.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import g, request
from flask_babel import gettext, to_utc

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_generation_seeds import (
    parse_stage_generation_auto_seed_participant_ids,
    parse_stage_generation_manual_seed_values_by_participant_id,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_generation_common import (
    find_redirect_stage_id,
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
from byceps.services.netsession_tourney.seed_service import (
    set_stage_generation_seeds,
)
from byceps.util.framework.flash import flash_error
from byceps.util.result import Err, Ok, Result


_ROUND_START_KEY_PREFIX = 'round_starts_at_round_'


def generate_stage_matches_from_form(
    generation: StageGenerationRequest, is_locked_auto_seeding: bool
) -> Any:
    party = generation.party
    tournament = generation.tournament

    participants_result = get_stage_generation_participants(
        party.id, tournament.id, generation.stage.id
    )
    if participants_result.is_err():
        flash_error(participants_result.unwrap_err())
        return redirect_to_stage_view(party, tournament, generation.stage.id)

    participants = participants_result.unwrap()
    allowed_participant_ids = {participant.id for participant in participants}
    seeds_result = _parse_seeds(
        generation, allowed_participant_ids, is_locked_auto_seeding
    )
    if seeds_result.is_err():
        return seeds_result.unwrap_err()

    auto_seed_participant_ids, manual_seed_values_by_participant_id = (
        seeds_result.unwrap()
    )
    return _assign_seeds_and_generate(
        generation,
        auto_seed_participant_ids,
        manual_seed_values_by_participant_id,
    )


def _parse_seeds(
    generation: StageGenerationRequest,
    allowed_participant_ids: set,
    is_locked_auto_seeding: bool,
) -> Result[tuple[list, dict], Any]:
    """Return automatic and manual seeds; on an error, the re-rendered
    form."""
    auto_seed_participant_ids_result = (
        parse_stage_generation_auto_seed_participant_ids(
            request.form, allowed_participant_ids
        )
    )
    if auto_seed_participant_ids_result.is_err():
        flash_error(auto_seed_participant_ids_result.unwrap_err())
        return Err(
            generation.render_form(
                generation.party.id,
                generation.tournament.id,
                generation.stage.id,
                erroneous_auto_seed_participant_ids=request.form.getlist(
                    'auto_seed_participant_ids'
                ),
                erroneous_manual_seed_values_by_participant_id=request.form,
                erroneous_flatout2_generation_form=generation.erroneous_flatout2_generation_form,
            )
        )
    auto_seed_participant_ids = auto_seed_participant_ids_result.unwrap()

    if is_locked_auto_seeding:
        return Ok((auto_seed_participant_ids, {}))

    manual_seed_values_result = (
        parse_stage_generation_manual_seed_values_by_participant_id(
            request.form, allowed_participant_ids
        )
    )
    if manual_seed_values_result.is_err():
        flash_error(manual_seed_values_result.unwrap_err())
        return Err(
            _render_seed_error(
                generation, generation.stage.id, auto_seed_participant_ids
            )
        )

    return Ok((auto_seed_participant_ids, manual_seed_values_result.unwrap()))


def _assign_seeds_and_generate(
    generation: StageGenerationRequest,
    auto_seed_participant_ids: list,
    manual_seed_values_by_participant_id: dict,
) -> Any:
    party = generation.party
    tournament = generation.tournament

    round_starts_result = _parse_round_starts(
        generation, auto_seed_participant_ids
    )
    if round_starts_result.is_err():
        return round_starts_result.unwrap_err()
    round_starts_at_by_round_no, round_start_values_by_round_no = (
        round_starts_result.unwrap()
    )

    seed_assignment_result = set_stage_generation_seeds(
        party.id,
        tournament.id,
        generation.stage.id,
        auto_seed_participant_ids,
        manual_seed_values_by_participant_id,
        g.user.as_user(),
    )
    if seed_assignment_result.is_err():
        flash_error(seed_assignment_result.unwrap_err())
        return _render_seed_error(
            generation,
            generation.stage.id,
            auto_seed_participant_ids,
            erroneous_round_start_values_by_round_no=round_start_values_by_round_no,
        )

    correlation_id = request.headers.get('X-Correlation-ID')
    flash_generation_result(
        generate_stage_matches(
            party.id,
            tournament.id,
            generation.stage_id,
            g.user.as_user(),
            correlation_id=correlation_id,
            round_starts_at_by_round_no=round_starts_at_by_round_no or None,
        )
    )

    redirect_stage_id = find_redirect_stage_id(
        party, tournament, generation.stage_id
    )
    return redirect_to_stage_view(party, tournament, redirect_stage_id)


def _parse_round_starts(
    generation: StageGenerationRequest, auto_seed_participant_ids: list
) -> Result[tuple[dict[int, datetime], dict[int, str]], Any]:
    """Return the start times per round and the posted values; on an
    invalid value, the re-rendered form."""
    round_starts_at_by_round_no: dict[int, datetime] = {}
    round_start_values_by_round_no: dict[int, str] = {}
    for key, raw_value in request.form.items():
        round_no = _round_no_from_key(key)
        if round_no is None:
            continue

        normalized_raw_value = (raw_value or '').strip()
        round_start_values_by_round_no[round_no] = normalized_raw_value
        if not normalized_raw_value:
            continue

        starts_at_local = deserialize_datetime_local(normalized_raw_value)
        if starts_at_local is None:
            flash_error(
                gettext(
                    'Ungültiger Startzeitpunkt für Runde %(round_no)s.',
                    round_no=round_no,
                )
            )
            return Err(
                _render_seed_error(
                    generation,
                    generation.stage_id,
                    auto_seed_participant_ids,
                    erroneous_round_start_values_by_round_no=round_start_values_by_round_no,
                )
            )

        round_starts_at_by_round_no[round_no] = to_utc(starts_at_local)

    return Ok((round_starts_at_by_round_no, round_start_values_by_round_no))


def _round_no_from_key(key: str) -> int | None:
    if not key.startswith(_ROUND_START_KEY_PREFIX):
        return None
    try:
        round_no = int(key.removeprefix(_ROUND_START_KEY_PREFIX))
    except ValueError:
        return None
    if round_no < 1:
        return None
    return round_no


def _render_seed_error(
    generation: StageGenerationRequest,
    stage_id: Any,
    auto_seed_participant_ids: list,
    **extra_kwargs: Any,
) -> Any:
    return generation.render_form(
        generation.party.id,
        generation.tournament.id,
        stage_id,
        erroneous_auto_seed_participant_ids=[
            str(participant_id) for participant_id in auto_seed_participant_ids
        ],
        erroneous_manual_seed_values_by_participant_id=request.form,
        erroneous_flatout2_generation_form=generation.erroneous_flatout2_generation_form,
        **extra_kwargs,
    )
