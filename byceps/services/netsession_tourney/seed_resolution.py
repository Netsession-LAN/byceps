"""
byceps.services.netsession_tourney.seed_resolution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Resolving the final seed order for stage generation.
"""

from __future__ import annotations

from byceps.util.result import Err, Ok, Result

from .models import (
    Participant,
    ParticipantID,
    Stage,
)
from .stage_builder_settings import (
    is_stage_builder_v1_main_stage_with_locked_qualifier_seeding,
)


def _normalize_manual_seeds(
    manual_seed_by_participant_id: dict[ParticipantID, int],
    selected_participant_ids: set[ParticipantID],
) -> dict[ParticipantID, int]:
    return {
        participant_id: seed
        for participant_id, seed in manual_seed_by_participant_id.items()
        if participant_id in selected_participant_ids
    }


def _resolve_final_seed_participant_ids(
    stage: Stage,
    selected_participants: list[Participant],
    selected_participant_ids: set[ParticipantID],
    auto_seed_participant_ids: list[ParticipantID],
    manual_seed_by_participant_id: dict[ParticipantID, int],
) -> Result[list[ParticipantID], str]:
    if set(auto_seed_participant_ids) != selected_participant_ids:
        return Err(
            'Die Teilnehmerliste hat sich geändert. Bitte die Setzlisten-Seite neu laden.'
        )

    if is_stage_builder_v1_main_stage_with_locked_qualifier_seeding(stage):
        return _resolve_locked_qualifier_seed_participant_ids(
            selected_participants, manual_seed_by_participant_id
        )

    normalized_manual_seed_by_participant_id = _normalize_manual_seeds(
        manual_seed_by_participant_id, selected_participant_ids
    )
    if not _are_manual_seeds_contiguous(
        normalized_manual_seed_by_participant_id
    ):
        return Err(
            'Manuelle Setzplätze müssen lückenlos bei 1 beginnen und dürfen keine Duplikate enthalten.'
        )

    return Ok(
        _order_participant_ids_by_manual_seeds(
            normalized_manual_seed_by_participant_id, auto_seed_participant_ids
        )
    )


def _resolve_locked_qualifier_seed_participant_ids(
    selected_participants: list[Participant],
    manual_seed_by_participant_id: dict[ParticipantID, int],
) -> Result[list[ParticipantID], str]:
    if manual_seed_by_participant_id:
        return Err(
            'Die Setzliste für dieses Hauptturnier wird automatisch aus den abgeschlossenen Vorrunden übernommen und kann nicht manuell angepasst werden.'
        )

    return Ok([participant.id for participant in selected_participants])


def _are_manual_seeds_contiguous(
    normalized_manual_seed_by_participant_id: dict[ParticipantID, int],
) -> bool:
    manual_seed_values = sorted(
        normalized_manual_seed_by_participant_id.values()
    )
    expected_manual_seed_values = list(
        range(1, len(normalized_manual_seed_by_participant_id) + 1)
    )
    return manual_seed_values == expected_manual_seed_values


def _order_participant_ids_by_manual_seeds(
    normalized_manual_seed_by_participant_id: dict[ParticipantID, int],
    auto_seed_participant_ids: list[ParticipantID],
) -> list[ParticipantID]:
    manual_prefix_participant_ids = [
        participant_id
        for participant_id, _seed in sorted(
            normalized_manual_seed_by_participant_id.items(),
            key=lambda item: item[1],
        )
    ]
    remaining_auto_seed_participant_ids = [
        participant_id
        for participant_id in auto_seed_participant_ids
        if participant_id not in normalized_manual_seed_by_participant_id
    ]
    return manual_prefix_participant_ids + remaining_auto_seed_participant_ids
