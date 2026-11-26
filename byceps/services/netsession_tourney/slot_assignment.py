"""
byceps.services.netsession_tourney.slot_assignment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Admins put participants into match slots by hand.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyStage,
)
from .engines.registry import (
    find_stage_engine,
)
from .match_advancement import (
    auto_advance_byes,
)
from .models import (
    MatchID,
    MatchState,
    ParticipantID,
    TournamentID,
    TournamentStatus,
)
from .notification_service import (
    enqueue_match_ready_notifications,
)
from .participant_state import (
    calculate_match_state_for_slots,
)
from .service_helpers import (
    append_audit_log,
    db_stage_to_model,
    db_tournament_to_model,
)
from .tournament_queries import (
    ACTIVE_PARTICIPANT_STATUS_VALUES,
    find_db_tournament_for_party,
)


def set_match_slot_participant_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    slot_no: int,
    participant_id: ParticipantID | None,
    initiator: User,
    *,
    comment: str | None = None,
) -> Result[None, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err('Matches lassen sich nur im Entwurf zuweisen.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch)
        .filter_by(id=match_id, tournament_id=tournament_id)
        .with_for_update()
    )
    if db_match is None:
        return Err('Unbekanntes Match.')

    match_error = _check_match_accepts_slot_assignment(db_match, match_id)
    if match_error is not None:
        return Err(match_error)

    db_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=match_id, slot_no=slot_no)
        .with_for_update()
    )
    if db_slot is None:
        return Err('Unbekannter Platz im Match.')

    # Slots that are fed by previous matches are maintained by bracket logic.
    if db_slot.source_match_slot_id is not None:
        return Err(
            'Dieser Platz hängt an einem vorherigen Match und lässt sich nicht von Hand ändern.'
        )

    if participant_id is not None:
        participant_error = _check_participant_assignable(
            tournament_id, db_match, match_id, slot_no, participant_id
        )
        if participant_error is not None:
            return Err(participant_error)

    db_slot.participant_id = participant_id

    previous_state = MatchState(db_match.state)
    next_state = _recalculate_match_state(
        db_tournament.status, db_match, match_id
    )

    _auto_advance_byes_of_match_stage(tournament_id, db_match)

    if previous_state != MatchState.ready and next_state == MatchState.ready:
        enqueue_match_ready_notifications(db_match)

    _append_slot_assignment_audit_log(
        initiator, match_id, slot_no, participant_id, comment
    )

    db.session.commit()
    return Ok(None)


def _append_slot_assignment_audit_log(
    initiator: User,
    match_id: MatchID,
    slot_no: int,
    participant_id: ParticipantID | None,
    comment: str | None,
) -> None:
    append_audit_log(
        actor_user_id=initiator.id,
        object_type='match',
        object_id=match_id,
        action='match_slot_assignment_updated_by_admin',
        payload={
            'slot_no': slot_no,
            'participant_id': (
                str(participant_id) if participant_id is not None else None
            ),
            'comment': comment.strip() if comment else None,
        },
        created_at=datetime.utcnow(),
    )


def _check_match_accepts_slot_assignment(
    db_match: DbNetsessionTourneyMatch, match_id: MatchID
) -> str | None:
    """Return an error message if the match's slots must not be changed."""
    if db_match.state in {
        MatchState.completed.value,
        MatchState.in_progress.value,
        MatchState.pending_confirmation.value,
        MatchState.needs_admin_review.value,
        MatchState.disputed.value,
    }:
        return 'Plätze lassen sich nur bei wartenden oder spielbereiten Matches zuweisen.'

    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=match_id)
    )
    if db_result is not None:
        return 'Sobald ein Ergebnis existiert, lassen sich keine Plätze mehr zuweisen.'

    return None


def _check_participant_assignable(
    tournament_id: TournamentID,
    db_match: DbNetsessionTourneyMatch,
    match_id: MatchID,
    slot_no: int,
    participant_id: ParticipantID,
) -> str | None:
    """Return an error message if the participant must not be put into
    that slot of the match."""
    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(id=participant_id, tournament_id=tournament_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    if db_participant is None:
        return 'Unbekannter Teilnehmer.'

    duplicate_in_match = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot.id)
        .filter_by(match_id=match_id, participant_id=participant_id)
        .filter(DbNetsessionTourneyMatchSlot.slot_no != slot_no)
    )
    if duplicate_in_match is not None:
        return 'Der Teilnehmer ist diesem Match bereits zugewiesen.'

    duplicate_in_round = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot.id)
        .join(
            DbNetsessionTourneyMatch,
            DbNetsessionTourneyMatch.id
            == DbNetsessionTourneyMatchSlot.match_id,
        )
        .filter(DbNetsessionTourneyMatch.stage_id == db_match.stage_id)
        .filter(DbNetsessionTourneyMatch.round_no == db_match.round_no)
        .filter(DbNetsessionTourneyMatchSlot.participant_id == participant_id)
        .filter(DbNetsessionTourneyMatchSlot.match_id != match_id)
    )
    if duplicate_in_round is not None:
        return 'Der Teilnehmer ist in dieser Runde bereits zugewiesen.'

    return None


def _recalculate_match_state(
    tournament_status: str,
    db_match: DbNetsessionTourneyMatch,
    match_id: MatchID,
) -> MatchState:
    """Recalculate and store the match's state from its slots."""
    db_match_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    next_state = calculate_match_state_for_slots(
        tournament_status=tournament_status,
        db_match_slots=db_match_slots,
    )
    db_match.state = next_state.value
    db_match.updated_at = datetime.utcnow()
    return next_state


def _auto_advance_byes_of_match_stage(
    tournament_id: TournamentID, db_match: DbNetsessionTourneyMatch
) -> None:
    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if db_stage is not None:
        stage = db_stage_to_model(db_stage)
        auto_advance_byes(
            tournament_id,
            stage,
            engine=find_stage_engine(stage.type),
        )
