"""
byceps.services.netsession_tourney.ffa_stage_builder_stage_preview
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Preview of a single stage planned by the FFA stage builder.
"""

from __future__ import annotations

from typing import Any

from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .engines.base import MatchSpec
from .engines.registry import (
    find_stage_engine,
)
from .ffa_stage_builder_validation import (
    validate_ffa_stage_builder_settings as validate_ffa_stage_builder_settings,
)
from .flatout2_builder import (
    summarize_flatout2_builder_rounds,
)
from .models import (
    ParticipantID,
    Stage,
    StageID,
    StageStatus,
    StageType,
    TournamentID,
)


def preview_ffa_stage_builder_stage(
    *,
    tournament_id: TournamentID,
    stage_type: StageType,
    participant_count: int,
    max_players_per_match: int,
    stop_when_participants_at_most: int | None = None,
) -> Result[dict[str, Any], str]:
    if stage_type == StageType.ffa_flatout2_single_elimination:
        return Ok(
            _preview_flatout2_builder_stage(
                participant_count=participant_count,
                max_players_per_match=max_players_per_match,
                stop_when_participants_at_most=stop_when_participants_at_most,
            )
        )

    engine = find_stage_engine(stage_type)
    if engine is None:
        return Err('Für diesen FFA-Phasentyp gibt es keine Match-Erzeugung.')

    preview_stage = Stage(
        id=StageID(generate_uuid7()),
        tournament_id=tournament_id,
        order_no=1,
        type=stage_type,
        name='Preview',
        settings={'max_players_per_match': max_players_per_match},
        status=StageStatus.draft,
    )
    preview_participant_ids = [
        ParticipantID(generate_uuid7()) for _ in range(participant_count)
    ]
    generated_specs_result = engine.generate(
        preview_stage, preview_participant_ids
    )
    if generated_specs_result.is_err():
        return Err(generated_specs_result.unwrap_err())

    specs = generated_specs_result.unwrap()
    round_summaries = _summarize_ffa_builder_match_specs(specs)

    return Ok(
        {
            'round_summaries': round_summaries,
            'match_count': len(specs),
            'expected_final_heat_size': _get_expected_final_heat_size(
                round_summaries
            ),
        }
    )


def _preview_flatout2_builder_stage(
    *,
    participant_count: int,
    max_players_per_match: int,
    stop_when_participants_at_most: int | None,
) -> dict[str, Any]:
    round_summaries = summarize_flatout2_builder_rounds(
        participant_count=participant_count,
        max_players_per_match=max_players_per_match,
        stop_when_participants_at_most=stop_when_participants_at_most,
    )
    return {
        'round_summaries': round_summaries,
        'match_count': sum(
            round_summary['match_count'] for round_summary in round_summaries
        ),
        'expected_final_heat_size': _get_expected_final_heat_size(
            round_summaries
        ),
    }


def _get_expected_final_heat_size(round_summaries: list[dict[str, Any]]) -> int:
    return round_summaries[-1]['max_heat_size'] if round_summaries else 0


def _summarize_ffa_builder_match_specs(
    specs: list[MatchSpec],
) -> list[dict[str, int]]:
    round_summaries = []
    for round_no in sorted({spec.round_no for spec in specs}):
        round_specs = [spec for spec in specs if spec.round_no == round_no]
        heat_sizes = [_count_ffa_spec_heat_size(spec) for spec in round_specs]
        round_summaries.append(
            {
                'round_no': round_no,
                'match_count': len(round_specs),
                'max_heat_size': max(heat_sizes) if heat_sizes else 0,
            }
        )

    return round_summaries


def _count_ffa_spec_heat_size(spec: MatchSpec) -> int:
    return len(
        [
            slot
            for slot in spec.slots
            if slot.participant_id is not None
            or slot.source_match_no is not None
        ]
    )
