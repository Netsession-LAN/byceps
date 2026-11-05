"""
byceps.services.netsession_tourney.generation_participants
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Participants of a stage to generate: from the whole field or qualified from source stages, in seed order.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from uuid import UUID

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from . import domain_service
from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .models import (
    Participant,
    ParticipantID,
    Stage,
    StageID,
    TournamentID,
)
from .qualifier_selection import select_match_qualifiers, select_stage_qualifiers
from .service_helpers import (
    _db_stage_to_model,
)
from .stage_builder_settings import (
    _get_stage_builder_main_stage_size,
    _is_stage_builder_v1_main_stage,
    _is_stage_builder_v1_preliminary_stage,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
    get_participants_for_tournament,
)


@dataclass(frozen=True, kw_only=True)
class StageMatchGenerationPreviewParticipant:
    participant_id: ParticipantID
    name: str


def get_stage_generation_participants(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
) -> Result[list[Participant], str]:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unbekannte Stage.')

    stage = _db_stage_to_model(db_stage)
    return _select_generation_participants_for_stage(
        party_id, tournament_id, stage
    )


def _order_participants_for_stage_generation(
    participants: list[Participant],
    *,
    shuffle_unseeded: bool,
) -> list[Participant]:
    participant_count = len(participants)
    if participant_count <= 1:
        return participants

    contiguous_seeded: list[Participant] = []
    deferred_unseeded: list[Participant] = []
    seen_seeds: set[int] = set()
    expected_seed = 1

    for participant in sorted(
        participants,
        key=lambda item: (
            item.seed if item.seed is not None else 999_999,
            item.name.lower(),
            str(item.id),
        ),
    ):
        seed = participant.seed
        if (
            seed is None
            or seed < 1
            or seed > participant_count
            or seed in seen_seeds
            or seed != expected_seed
        ):
            deferred_unseeded.append(participant)
            continue

        contiguous_seeded.append(participant)
        seen_seeds.add(seed)
        expected_seed += 1

    if shuffle_unseeded:
        random.shuffle(deferred_unseeded)
    return contiguous_seeded + deferred_unseeded


def _select_generation_participants_for_stage(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage: Stage,
) -> Result[list[Participant], str]:
    all_tournament_participants = get_participants_for_tournament(
        party_id, tournament_id
    )
    is_stage_builder_v1_stage = _is_stage_builder_v1_main_stage(
        stage
    ) or _is_stage_builder_v1_preliminary_stage(stage)
    eligible_participants = (
        domain_service.select_ready_participants(all_tournament_participants)
        if is_stage_builder_v1_stage
        else domain_service.select_bracket_ready_participants(
            all_tournament_participants
        )
    )
    main_stage_decision = _decide_by_builder_main_stage_size(
        stage, eligible_participants
    )
    if main_stage_decision is not None:
        return main_stage_decision

    source_mode = (stage.settings or {}).get('participant_source_mode')
    if source_mode == 'builder_fixed_participants':
        return _select_builder_fixed_participants(
            stage, all_tournament_participants
        )
    if source_mode == 'stage_match_qualifiers':
        return select_match_qualifiers(party_id, tournament_id, stage)
    if source_mode == 'stage_qualifiers':
        return select_stage_qualifiers(
            party_id,
            tournament_id,
            stage,
            is_stage_builder_v1_stage=is_stage_builder_v1_stage,
        )
    return Ok(eligible_participants)


def _decide_by_builder_main_stage_size(
    stage: Stage, eligible_participants: list[Participant]
) -> Result[list[Participant], str] | None:
    """A builder main stage takes everybody if they fit, and refuses if
    they do not fit and there is no preliminary."""
    builder_main_stage_size = _get_stage_builder_main_stage_size(stage)
    if (
        not _is_stage_builder_v1_main_stage(stage)
        or builder_main_stage_size is None
    ):
        return None

    has_preliminary = bool(stage.settings.get('builder_preliminary_stage_id'))
    if has_preliminary and len(eligible_participants) <= builder_main_stage_size:
        return Ok(eligible_participants)
    if not has_preliminary and len(eligible_participants) > builder_main_stage_size:
        return Err(
            'Die aktuelle Anzahl ready Teilnehmer überschreitet die konfigurierte Main Stage Größe. '
            'Aktiviere eine Vorrunde oder reduziere die Teilnehmerbasis.'
        )
    return None


def _select_builder_fixed_participants(
    stage: Stage, all_tournament_participants: list[Participant]
) -> Result[list[Participant], str]:
    """The participants the stage builder assigned to a group."""
    fixed_participant_ids: list[ParticipantID] = []
    for raw_participant_id in (stage.settings or {}).get(
        'builder_fixed_participant_ids', []
    ):
        try:
            fixed_participant_ids.append(ParticipantID(UUID(str(raw_participant_id))))
        except ValueError:
            continue

    if not fixed_participant_ids:
        return Err('Builder-Gruppen-Teilnehmerliste ist leer.')

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
