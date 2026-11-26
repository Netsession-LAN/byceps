"""
byceps.services.netsession_tourney.generation_participants_builder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Participant selection for stage builder main stages: the main stage
size decision and the fixed participants.
"""

from __future__ import annotations

from uuid import UUID

from byceps.util.result import Err, Ok, Result

from . import domain_service
from .models import (
    Participant,
    ParticipantID,
    Stage,
)
from .stage_builder_settings import (
    get_stage_builder_main_stage_size,
    is_stage_builder_v1_main_stage,
)


def _decide_by_builder_main_stage_size(
    stage: Stage, eligible_participants: list[Participant]
) -> Result[list[Participant], str] | None:
    """A builder main stage takes everybody if they fit, and refuses if
    they do not fit and there is no preliminary."""
    builder_main_stage_size = get_stage_builder_main_stage_size(stage)
    if (
        not is_stage_builder_v1_main_stage(stage)
        or builder_main_stage_size is None
    ):
        return None

    has_preliminary = bool(stage.settings.get('builder_preliminary_stage_id'))
    if (
        has_preliminary
        and len(eligible_participants) <= builder_main_stage_size
    ):
        return Ok(eligible_participants)
    if (
        not has_preliminary
        and len(eligible_participants) > builder_main_stage_size
    ):
        return Err(
            'Die aktuelle Anzahl bereiter Teilnehmer überschreitet die konfigurierte Größe des Hauptturniers. '
            'Aktiviere eine Vorrunde oder reduziere die Teilnehmerbasis.'
        )
    return None


def _select_builder_fixed_participants(
    stage: Stage, all_tournament_participants: list[Participant]
) -> Result[list[Participant], str]:
    """The participants the stage builder assigned to a group."""
    fixed_participant_ids = _parse_builder_fixed_participant_ids(stage)

    if not fixed_participant_ids:
        return Err('Teilnehmerliste der Gruppe ist leer.')

    ready_participants_by_id = {
        participant.id: participant
        for participant in domain_service.select_ready_participants(
            all_tournament_participants
        )
    }
    selected_participants = [
        ready_participants_by_id[participant_id]
        for participant_id in fixed_participant_ids
        if participant_id in ready_participants_by_id
    ]
    if len(selected_participants) < 2:
        return Err('Zu wenige bereite Teilnehmer für diese Gruppe.')
    return Ok(selected_participants)


def _parse_builder_fixed_participant_ids(stage: Stage) -> list[ParticipantID]:
    fixed_participant_ids: list[ParticipantID] = []
    for raw_participant_id in (stage.settings or {}).get(
        'builder_fixed_participant_ids', []
    ):
        try:
            fixed_participant_ids.append(
                ParticipantID(UUID(str(raw_participant_id)))
            )
        except ValueError:
            continue
    return fixed_participant_ids
