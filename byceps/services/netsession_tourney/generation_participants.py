"""
byceps.services.netsession_tourney.generation_participants
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Participants of a stage to generate: from the whole field or qualified from source stages, in seed order.
"""

from __future__ import annotations

from dataclasses import dataclass
import random

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from . import domain_service
from .checkin_service import select_checked_in_participants
from .dbmodels import (
    DbNetsessionTourneyStage,
    DbNetsessionTourneyTournament,
)
from .generation_participants_builder import (
    _decide_by_builder_main_stage_size,
    _select_builder_fixed_participants,
)
from .models import (
    Participant,
    ParticipantID,
    Stage,
    StageID,
    TournamentID,
)
from .qualifier_selection import (
    select_match_qualifiers,
    select_stage_qualifiers,
)
from .service_helpers import (
    db_stage_to_model,
    db_tournament_to_model,
)
from .stage_builder_settings import (
    get_stage_builder_main_stage_size,
    is_stage_builder_v1_main_stage,
    is_stage_builder_v1_preliminary_stage,
)
from .tournament_queries import (
    find_db_tournament_for_party,
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
    if find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unbekannte Phase.')

    stage = db_stage_to_model(db_stage)
    return select_generation_participants_for_stage(
        party_id, tournament_id, stage
    )


def order_participants_for_stage_generation(
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

    for participant in sorted(participants, key=_get_generation_order_sort_key):
        seed = participant.seed
        if not _is_next_contiguous_seed(
            seed, participant_count, seen_seeds, expected_seed
        ):
            deferred_unseeded.append(participant)
            continue

        contiguous_seeded.append(participant)
        seen_seeds.add(seed)
        expected_seed += 1

    if shuffle_unseeded:
        random.shuffle(deferred_unseeded)
    return contiguous_seeded + deferred_unseeded


def _get_generation_order_sort_key(
    item: Participant,
) -> tuple[int, str, str]:
    return (
        item.seed if item.seed is not None else 999_999,
        item.name.lower(),
        str(item.id),
    )


def _is_next_contiguous_seed(
    seed: int | None,
    participant_count: int,
    seen_seeds: set[int],
    expected_seed: int,
) -> bool:
    return not (
        seed is None
        or seed < 1
        or seed > participant_count
        or seed in seen_seeds
        or seed != expected_seed
    )


def is_builder_preliminary_skipped(stage: Stage) -> bool:
    """A builder main stage skips its preliminary when all eligible
    participants fit into it."""
    size = get_stage_builder_main_stage_size(stage)
    if (
        not is_stage_builder_v1_main_stage(stage)
        or size is None
        or not stage.settings.get('builder_preliminary_stage_id')
    ):
        return False
    db_tournament = db.session.get(
        DbNetsessionTourneyTournament, stage.tournament_id
    )
    if db_tournament is None:
        return False
    _, eligible = _select_eligible_participants(
        db_tournament.party_id, stage.tournament_id, stage
    )
    return len(eligible) <= size


def _select_eligible_participants(
    party_id: PartyID, tournament_id: TournamentID, stage: Stage
) -> tuple[list[Participant], list[Participant]]:
    """Return all (checked-in) participants and those eligible to play."""
    all_tournament_participants = get_participants_for_tournament(
        party_id, tournament_id
    )
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is not None:  # with a check-in, only checked-in ones
        all_tournament_participants = select_checked_in_participants(
            db_tournament_to_model(db_tournament), all_tournament_participants
        )
    eligible_participants = (
        domain_service.select_ready_participants(all_tournament_participants)
        if _is_builder_stage(stage)
        else domain_service.select_bracket_ready_participants(
            all_tournament_participants
        )
    )
    return all_tournament_participants, eligible_participants


def _is_builder_stage(stage: Stage) -> bool:
    return is_stage_builder_v1_main_stage(
        stage
    ) or is_stage_builder_v1_preliminary_stage(stage)


def select_generation_participants_for_stage(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage: Stage,
) -> Result[list[Participant], str]:
    all_tournament_participants, eligible_participants = (
        _select_eligible_participants(party_id, tournament_id, stage)
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
            is_stage_builder_v1_stage=_is_builder_stage(stage),
        )
    return Ok(eligible_participants)
