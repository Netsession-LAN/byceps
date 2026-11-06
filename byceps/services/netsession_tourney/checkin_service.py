"""
byceps.services.netsession_tourney.checkin_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional check-in before a tournament starts. It is active only when the
tournament has a check-in window (`checkin_open_at` and `checkin_close_at`).
Within the window, a solo player checks in themselves, a team is checked in
by its captain. Only checked-in participants get into the bracket; the
matches cannot be generated while the window is still open.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result

from .dbmodels import DbNetsessionTourneyParticipant
from .models import (
    CheckinState,
    Participant,
    ParticipantStatus,
    ParticipantType,
    Tournament,
    TournamentID,
)
from .service_helpers import (
    append_audit_log,
    db_participant_to_model,
    db_tournament_to_model,
)
from .tournament_queries import find_db_tournament_for_party


_CHECKIN_ALLOWED_STATUSES = {
    ParticipantStatus.ready.value,
    ParticipantStatus.checked_in.value,
    ParticipantStatus.locked.value,
}


class CheckinPhase(Enum):
    before = 'before'
    open = 'open'
    closed = 'closed'


def has_checkin(tournament: Tournament) -> bool:
    return (
        tournament.checkin_open_at is not None
        and tournament.checkin_close_at is not None
    )


def get_checkin_phase(
    tournament: Tournament, now: datetime | None = None
) -> CheckinPhase | None:
    """Return the phase of the check-in window, or None without one."""
    if not has_checkin(tournament):
        return None
    now = now or datetime.utcnow()
    if now < tournament.checkin_open_at:
        return CheckinPhase.before
    if now <= tournament.checkin_close_at:
        return CheckinPhase.open
    return CheckinPhase.closed


def select_checked_in_participants(
    tournament: Tournament, participants: list[Participant]
) -> list[Participant]:
    """Without a check-in window everybody counts, otherwise only the
    checked-in participants."""
    if not has_checkin(tournament):
        return participants
    return [p for p in participants if p.checkin_state == CheckinState.checked_in]


def check_generation_allowed(tournament: Tournament) -> str | None:
    """Return why the bracket cannot be generated yet, or None."""
    if get_checkin_phase(tournament) in {CheckinPhase.before, CheckinPhase.open}:
        return (
            'Der Check-in läuft noch. Die Matches können erst nach dem Ende '
            'des Check-ins erzeugt werden.'
        )
    return None


def check_in(
    party_id: PartyID, tournament_id: TournamentID, user: User
) -> Result[Participant, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')
    tournament = db_tournament_to_model(db_tournament)

    phase = get_checkin_phase(tournament)
    if phase is None:
        return Err('Dieses Turnier hat keinen Check-in.')
    if phase != CheckinPhase.open:
        return Err('Der Check-in ist gerade nicht geöffnet.')

    db_participant = _find_db_participant_to_check_in(tournament_id, user)
    if db_participant is None:
        return Err(
            'Du bist nicht angemeldet, oder nur der Team-Captain kann das '
            'Team einchecken.'
        )
    if db_participant.status not in _CHECKIN_ALLOWED_STATUSES:
        return Err('Das Team ist noch nicht bereit und kann nicht einchecken.')

    if db_participant.checkin_state != CheckinState.checked_in.value:
        db_participant.checkin_state = CheckinState.checked_in.value
        append_audit_log(
            actor_user_id=user.id,
            object_type='participant',
            object_id=db_participant.id,
            action='participant_checked_in',
            payload={},
            created_at=datetime.utcnow(),
        )
        db.session.commit()

    return Ok(db_participant_to_model(db_participant))


def _find_db_participant_to_check_in(
    tournament_id: TournamentID, user: User
) -> DbNetsessionTourneyParticipant | None:
    """The user's solo entry, or the team they are captain of."""
    return db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .filter(
            (
                (DbNetsessionTourneyParticipant.type == ParticipantType.user.value)
                & (DbNetsessionTourneyParticipant.user_id == user.id)
            )
            | (
                (DbNetsessionTourneyParticipant.type == ParticipantType.team.value)
                & (DbNetsessionTourneyParticipant.manager_user_id == user.id)
            )
        )
    ).first()


def set_checkin_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id,
    checked_in: bool,
    initiator: User,
) -> Result[Participant, str]:
    """Check a participant in (or take it back) on their behalf, e.g. when
    a player has trouble at their seat. Works outside the window, too."""
    if find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    db_participant = db.session.get(DbNetsessionTourneyParticipant, participant_id)
    if db_participant is None or db_participant.tournament_id != tournament_id:
        return Err('Unbekannter Teilnehmer.')

    new_state = CheckinState.checked_in if checked_in else CheckinState.pending
    if db_participant.checkin_state != new_state.value:
        db_participant.checkin_state = new_state.value
        append_audit_log(
            actor_user_id=initiator.id,
            object_type='participant',
            object_id=db_participant.id,
            action=(
                'participant_checked_in_by_admin'
                if checked_in
                else 'participant_checkin_revoked_by_admin'
            ),
            payload={},
            created_at=datetime.utcnow(),
        )
        db.session.commit()

    return Ok(db_participant_to_model(db_participant))
