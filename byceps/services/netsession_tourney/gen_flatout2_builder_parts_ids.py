"""
byceps.services.netsession_tourney.gen_flatout2_builder_parts_ids
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Parsing of the participant IDs of a manually planned FlatOut 2 match.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from byceps.util.result import Err, Ok, Result

from .models import (
    ParticipantID,
)


def _parse_manual_flatout2_match_participant_ids(
    blueprint: dict[str, Any],
    max_players_per_match: int,
) -> Result[list[ParticipantID | None], str]:
    raw_participant_ids = blueprint.get('participant_ids')
    if not isinstance(raw_participant_ids, list):
        raw_participant_ids = []

    participant_ids_result = _parse_manual_flatout2_participant_id_list(
        raw_participant_ids[:max_players_per_match]
    )
    if participant_ids_result.is_err():
        return Err(participant_ids_result.unwrap_err())
    participant_ids = participant_ids_result.unwrap()

    while len(participant_ids) < max_players_per_match:
        participant_ids.append(None)

    if _contains_duplicate_participant_ids(participant_ids):
        return Err(
            'Ein FlatOut-2-Match darf denselben Teilnehmer nicht mehrfach enthalten.'
        )

    return Ok(participant_ids)


def _parse_manual_flatout2_participant_id_list(
    raw_participant_ids: list[Any],
) -> Result[list[ParticipantID | None], str]:
    """Parse participant IDs; empty values become `None` (free slot)."""
    participant_ids: list[ParticipantID | None] = []
    for raw_participant_id in raw_participant_ids:
        if not raw_participant_id:
            participant_ids.append(None)
            continue
        try:
            participant_ids.append(ParticipantID(UUID(str(raw_participant_id))))
        except TypeError, ValueError:
            return Err(
                'Die Teilnehmerzuordnung in der FlatOut-2-Phase ist ungültig.'
            )

    return Ok(participant_ids)


def _contains_duplicate_participant_ids(
    participant_ids: list[ParticipantID | None],
) -> bool:
    real_participant_ids = [
        participant_id
        for participant_id in participant_ids
        if participant_id is not None
    ]
    return len(set(real_participant_ids)) != len(real_participant_ids)
