"""
byceps.services.netsession_tourney.seed_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Seeds of participants for match generation.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyStage,
)
from .generation_participants import (
    get_stage_generation_participants,
)
from .models import (
    Participant,
    ParticipantID,
    Stage,
    StageID,
    TournamentID,
)
from .service_helpers import (
    append_audit_log,
    db_participant_to_model,
    db_stage_to_model,
)
from .stage_builder_settings import (
    is_stage_builder_v1_main_stage_with_locked_qualifier_seeding,
)
from .tournament_queries import (
    ACTIVE_PARTICIPANT_STATUS_VALUES,
    find_db_tournament_for_party,
)


def set_participant_seed(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    seed: int,
    initiator: User,
) -> Result[Participant, str]:
    if seed < 1:
        return Err('Der Setzplatz muss mindestens 1 sein.')

    if find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
        .order_by(DbNetsessionTourneyParticipant.created_at.asc())
    ).all()
    db_participants_by_id = {item.id: item for item in db_participants}
    db_participant = db_participants_by_id.get(participant_id)
    if db_participant is None:
        return Err('Unbekannter Teilnehmer.')

    active_participant_count = len(db_participants)
    if seed > active_participant_count:
        return Err(
            'Der Setzplatz darf nicht größer sein als die Zahl der aktiven Teilnehmer.'
        )

    seeded_participants = sorted(
        (
            item
            for item in db_participants
            if item.id != participant_id and item.seed is not None
        ),
        key=lambda item: (item.seed, item.created_at),
    )

    max_assignable_seed = len(seeded_participants) + 1
    if seed > max_assignable_seed:
        return Err(
            'Setzplätze müssen lückenlos vergeben werden. '
            f'Der nächste freie manuelle Setzplatz ist {max_assignable_seed}.'
        )

    insertion_index = seed - 1
    seeded_participants.insert(insertion_index, db_participant)

    for index, item in enumerate(seeded_participants, start=1):
        item.seed = index

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='participant_seed_set',
        payload={'seed': seed},
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    return Ok(db_participant_to_model(db_participant))


def set_stage_generation_seeds(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    auto_seed_participant_ids: list[ParticipantID],
    manual_seed_by_participant_id: dict[ParticipantID, int],
    initiator: User,
) -> Result[list[Participant], str]:
    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unbekannte Phase.')

    stage = db_stage_to_model(db_stage)
    selected_participants_result = get_stage_generation_participants(
        party_id, tournament_id, stage_id
    )
    if selected_participants_result.is_err():
        return Err(selected_participants_result.unwrap_err())

    selected_participants = selected_participants_result.unwrap()
    if len(selected_participants) < 2:
        return Err('Zu wenige Teilnehmer für die Vergabe der Setzplätze.')

    selected_participants_by_id = {
        participant.id: participant for participant in selected_participants
    }
    selected_participant_ids = set(selected_participants_by_id.keys())
    final_participant_ids_result = _resolve_final_seed_participant_ids(
        stage,
        selected_participants,
        selected_participant_ids,
        auto_seed_participant_ids,
        manual_seed_by_participant_id,
    )
    if final_participant_ids_result.is_err():
        return Err(final_participant_ids_result.unwrap_err())
    final_participant_ids = final_participant_ids_result.unwrap()

    normalized_manual_seed_by_participant_id = _normalize_manual_seeds(
        manual_seed_by_participant_id, selected_participant_ids
    )

    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyParticipant.id.in_(final_participant_ids))
    ).all()
    db_participants_by_id = {
        participant.id: participant for participant in db_participants
    }

    now = datetime.utcnow()
    for seed, participant_id in enumerate(final_participant_ids, start=1):
        db_participant = db_participants_by_id.get(participant_id)
        if db_participant is None:
            return Err(
                'Ein Teilnehmer für die Vergabe der Setzplätze wurde nicht gefunden.'
            )
        db_participant.seed = seed

    _append_stage_generation_seeds_audit_log(
        initiator,
        stage_id,
        participant_count=len(final_participant_ids),
        manual_seed_count=len(normalized_manual_seed_by_participant_id),
        now=now,
    )

    db.session.commit()

    return Ok(
        [
            selected_participants_by_id[participant_id]
            for participant_id in final_participant_ids
        ]
    )


def _append_stage_generation_seeds_audit_log(
    initiator: User,
    stage_id: StageID,
    *,
    participant_count: int,
    manual_seed_count: int,
    now: datetime,
) -> None:
    append_audit_log(
        actor_user_id=initiator.id,
        object_type='stage',
        object_id=stage_id,
        action='stage_generation_seeds_set',
        payload={
            'participant_count': participant_count,
            'manual_seed_count': manual_seed_count,
        },
        created_at=now,
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
        if manual_seed_by_participant_id:
            return Err(
                'Die Setzliste für dieses Hauptturnier wird automatisch aus den abgeschlossenen Vorrunden übernommen und kann nicht manuell angepasst werden.'
            )

        return Ok([participant.id for participant in selected_participants])

    normalized_manual_seed_by_participant_id = _normalize_manual_seeds(
        manual_seed_by_participant_id, selected_participant_ids
    )
    manual_seed_values = sorted(
        normalized_manual_seed_by_participant_id.values()
    )
    expected_manual_seed_values = list(
        range(1, len(normalized_manual_seed_by_participant_id) + 1)
    )
    if manual_seed_values != expected_manual_seed_values:
        return Err(
            'Manuelle Setzplätze müssen lückenlos bei 1 beginnen und dürfen keine Duplikate enthalten.'
        )

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
    return Ok(
        manual_prefix_participant_ids + remaining_auto_seed_participant_ids
    )
