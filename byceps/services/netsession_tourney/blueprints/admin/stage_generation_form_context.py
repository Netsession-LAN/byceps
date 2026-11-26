"""
byceps.services.netsession_tourney.blueprints.admin.stage_generation_form_context
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Template context of the stage generation form (see
`routes_stage_generation`): preview, seeds and round start times, or
the round configuration of a FlatOut 2 stage.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any
from uuid import UUID

from byceps.services.netsession_tourney.blueprints.admin.datetime_fields import (
    serialize_utc_as_local,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_generation import (
    build_flatout2_generation_state,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_generation_seeds import (
    build_stage_generation_seed_rows,
    parse_stage_generation_manual_seed_values_by_participant_id,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_helpers import (
    build_current_manual_seed_values_by_participant_id,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_display import (
    is_builder_round_robin_summary_stage,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_meta import (
    build_round_robin_generation_intro,
    build_stage_builder_generation_summary,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_generation_common import (
    redirect_to_stage_view,
)
from byceps.services.netsession_tourney.models import ParticipantID
from byceps.services.netsession_tourney.stage_generation import (
    preview_stage_match_generation,
)
from byceps.services.party.models import Party
from byceps.util.framework.flash import flash_error


@dataclass(frozen=True, kw_only=True)
class GenerationFormInput:
    """The arguments of the generation form view."""

    party: Party
    tournament: Any
    stage: Any
    erroneous_auto_seed_participant_ids: list[str] | None
    erroneous_manual_seed_values_by_participant_id: Any
    erroneous_round_start_values_by_round_no: dict[int, str] | None
    erroneous_flatout2_generation_form: Any


def build_flatout2_generation_form_context(
    form_input: GenerationFormInput,
    participants: list,
    *,
    existing_stage_match_count: int,
    is_incremental_flatout2_generation: bool,
) -> dict[str, Any]:
    flatout2_generation_state = build_flatout2_generation_state(
        form_input.stage,
        participants=participants,
        posted_form=form_input.erroneous_flatout2_generation_form,
    )
    round_start_values_by_round_no = {
        round_state['round_no']: (
            form_input.erroneous_round_start_values_by_round_no or {}
        ).get(round_state['round_no'], '')
        for round_state in flatout2_generation_state['rounds']
        if round_state['is_active']
    }
    return {
        'party': form_input.party,
        'tournament': form_input.tournament,
        'stage': form_input.stage,
        'preview': None,
        'is_builder_round_robin_summary_stage': False,
        'round_robin_generation_intro': None,
        'stage_builder_preview_summary': None,
        'seed_rows': [],
        'auto_seed_participant_ids': [],
        'is_locked_auto_seeding': False,
        'round_start_values_by_round_no': round_start_values_by_round_no,
        'existing_stage_match_count': existing_stage_match_count,
        'is_incremental_swiss_generation': False,
        'is_incremental_flatout2_generation': is_incremental_flatout2_generation,
        'flatout2_generation_state': flatout2_generation_state,
        'is_flatout2_manual_stage': True,
    }


def build_generation_form_context(
    form_input: GenerationFormInput,
    participants: list,
    *,
    is_locked_auto_seeding: bool,
    existing_stage_match_count: int,
    is_incremental_swiss_generation: bool,
    is_incremental_flatout2_generation: bool,
) -> Any:
    party = form_input.party
    tournament = form_input.tournament
    stage = form_input.stage

    preview_result = preview_stage_match_generation(
        party.id, tournament.id, stage.id
    )
    if preview_result.is_err():
        flash_error(preview_result.unwrap_err())
        return redirect_to_stage_view(party, tournament, stage.id)

    preview = preview_result.unwrap()
    participants_by_id = {
        participant.id: participant for participant in participants
    }
    auto_seed_participant_ids = _get_auto_seed_participant_ids(
        form_input, participants, participants_by_id, is_locked_auto_seeding
    )
    manual_seed_values_by_participant_id = _get_manual_seed_values(
        form_input, participants, participants_by_id, is_locked_auto_seeding
    )
    seed_rows = build_stage_generation_seed_rows(
        participants,
        auto_seed_participant_ids,
        manual_seed_values_by_participant_id,
    )
    round_start_values_by_round_no = _get_round_start_values(
        form_input, preview
    )

    return {
        'party': party,
        'tournament': tournament,
        'stage': stage,
        'preview': preview,
        'is_builder_round_robin_summary_stage': (
            is_builder_round_robin_summary_stage(stage)
        ),
        'round_robin_generation_intro': build_round_robin_generation_intro(
            stage,
            preview.stage,
            preview.participant_count,
        ),
        'stage_builder_preview_summary': build_stage_builder_generation_summary(
            stage,
            preview.stage,
            preview.participant_count,
            match_count=preview.match_count,
        ),
        'seed_rows': seed_rows,
        'auto_seed_participant_ids': auto_seed_participant_ids,
        'is_locked_auto_seeding': is_locked_auto_seeding,
        'round_start_values_by_round_no': round_start_values_by_round_no,
        'existing_stage_match_count': existing_stage_match_count,
        'is_incremental_swiss_generation': is_incremental_swiss_generation,
        'is_incremental_flatout2_generation': is_incremental_flatout2_generation,
        'flatout2_generation_state': None,
        'is_flatout2_manual_stage': False,
    }


def _get_auto_seed_participant_ids(
    form_input: GenerationFormInput,
    participants: list,
    participants_by_id: dict,
    is_locked_auto_seeding: bool,
) -> list:
    if is_locked_auto_seeding:
        return [participant.id for participant in participants]

    if form_input.erroneous_auto_seed_participant_ids:
        return _parse_erroneous_auto_seed_participant_ids(
            form_input.erroneous_auto_seed_participant_ids,
            participants_by_id,
        )

    return _shuffled_participant_ids(participants_by_id)


def _parse_erroneous_auto_seed_participant_ids(
    raw_participant_ids: list[str], participants_by_id: dict
) -> list:
    auto_seed_participant_ids = []
    for raw_participant_id in raw_participant_ids:
        try:
            participant_id = ParticipantID(UUID(str(raw_participant_id)))
        except ValueError:
            continue
        if participant_id in participants_by_id:
            auto_seed_participant_ids.append(participant_id)

    if set(auto_seed_participant_ids) != set(participants_by_id.keys()):
        return _shuffled_participant_ids(participants_by_id)

    return auto_seed_participant_ids


def _shuffled_participant_ids(participants_by_id: dict) -> list:
    participant_ids = list(participants_by_id.keys())
    random.shuffle(participant_ids)
    return participant_ids


def _get_manual_seed_values(
    form_input: GenerationFormInput,
    participants: list,
    participants_by_id: dict,
    is_locked_auto_seeding: bool,
) -> dict:
    if is_locked_auto_seeding:
        return {}

    erroneous_values = form_input.erroneous_manual_seed_values_by_participant_id
    if erroneous_values is None:
        return build_current_manual_seed_values_by_participant_id(participants)

    manual_seed_values_result = (
        parse_stage_generation_manual_seed_values_by_participant_id(
            erroneous_values,
            set(participants_by_id.keys()),
        )
    )
    return (
        manual_seed_values_result.unwrap()
        if manual_seed_values_result.is_ok()
        else build_current_manual_seed_values_by_participant_id(participants)
    )


def _get_round_start_values(
    form_input: GenerationFormInput, preview: Any
) -> dict[int, str]:
    round_start_values_by_round_no: dict[int, str] = {}
    for round_preview in preview.rounds:
        round_start_values_by_round_no[round_preview.round_no] = (
            form_input.erroneous_round_start_values_by_round_no or {}
        ).get(
            round_preview.round_no,
            serialize_utc_as_local(round_preview.suggested_starts_at) or '',
        )
    return round_start_values_by_round_no
