"""
byceps.services.netsession_tourney.gen_flatout2_round_hosts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Host participants of the current FlatOut 2 round as configured by the admin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from byceps.util.result import Err, Ok, Result

from .models import (
    Participant,
    ParticipantID,
    Stage,
)


@dataclass(frozen=True, kw_only=True)
class Flatout2CurrentRoundGenerationContext:
    current_round_no: int
    total_round_count: int
    match_nos: list[int]
    participants: list[Participant]
    replace_existing_matches: bool


def get_flatout2_round_host_participant_ids(
    stage: Stage,
    context: Flatout2CurrentRoundGenerationContext,
) -> Result[list[ParticipantID], str]:
    raw_host_ids = _get_raw_flatout2_round_host_ids(
        stage, context.current_round_no
    )

    host_participant_ids_result = _parse_flatout2_host_participant_ids(
        raw_host_ids
    )
    if host_participant_ids_result.is_err():
        return Err(host_participant_ids_result.unwrap_err())
    host_participant_ids = host_participant_ids_result.unwrap()

    error = _validate_flatout2_round_host_participant_ids(
        host_participant_ids, context
    )
    if error is not None:
        return Err(error)

    return Ok(host_participant_ids)


def _get_raw_flatout2_round_host_ids(stage: Stage, round_no: int) -> list[Any]:
    raw_hosts_by_round = (stage.settings or {}).get('flatout2_round_hosts', {})
    if not isinstance(raw_hosts_by_round, dict):
        raw_hosts_by_round = {}

    raw_host_ids = raw_hosts_by_round.get(str(round_no)) or []
    if not isinstance(raw_host_ids, list):
        raw_host_ids = []

    return raw_host_ids


def _parse_flatout2_host_participant_ids(
    raw_host_ids: list[Any],
) -> Result[list[ParticipantID], str]:
    host_participant_ids: list[ParticipantID] = []
    for raw_host_id in raw_host_ids:
        try:
            host_participant_ids.append(ParticipantID(UUID(str(raw_host_id))))
        except TypeError, ValueError:
            return Err(
                'Die Host-Auswahl für die aktuelle FlatOut-2-Runde ist ungültig.'
            )

    return Ok(host_participant_ids)


def _validate_flatout2_round_host_participant_ids(
    host_participant_ids: list[ParticipantID],
    context: Flatout2CurrentRoundGenerationContext,
) -> str | None:
    """Return an error message, or `None` if there is exactly one host per
    match, each from the round's participants."""
    if len(host_participant_ids) != len(context.match_nos):
        return 'Bitte für jedes Match der aktuellen FlatOut-2-Runde genau einen Host auswählen.'

    if len(set(host_participant_ids)) != len(host_participant_ids):
        return 'Jeder FlatOut-2-Host darf in einer Runde nur einmal ausgewählt werden.'

    allowed_participant_ids = {
        participant.id for participant in context.participants
    }
    if any(
        host_participant_id not in allowed_participant_ids
        for host_participant_id in host_participant_ids
    ):
        return 'Mindestens ein ausgewählter FlatOut-2-Host gehört nicht zum Teilnehmerfeld dieser Runde.'

    return None
