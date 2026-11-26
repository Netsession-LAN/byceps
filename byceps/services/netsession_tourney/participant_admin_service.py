"""
byceps.services.netsession_tourney.participant_admin_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Participants managed by admins: add, status, disqualify, remove.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result

from . import domain_service
from .coin_service import (
    refund_coins_for_tournament_registration_if_available,
)
from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTournament,
)
from .models import (
    MatchState,
    Participant,
    ParticipantID,
    ParticipantStatus,
    RegistrationState,
    TournamentID,
)
from .notification_service import (
    append_notification,
)
from .participant_admin_addition import (
    add_user_participant_by_admin as add_user_participant_by_admin,
)
from .registration_service import (
    get_team_member_user_ids_for_participant,
    set_registration_state_for_user,
)
from .service_helpers import (
    append_audit_log,
    db_participant_to_model,
)
from .tournament_queries import (
    ACTIVE_PARTICIPANT_STATUS_VALUES,
    find_db_tournament_for_party,
)
from .tournament_service import (
    find_tournament_for_party,
)


log = structlog.get_logger()


def remove_participant_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    initiator: User,
    *,
    comment: str,
) -> Result[Participant, str]:
    comment = comment.strip()
    if not comment:
        return Err('Bitte einen Kommentar angeben.')

    dq_result = disqualify_participant(
        party_id,
        tournament_id,
        participant_id,
        initiator,
        reason_code='admin_removed',
        comment=comment,
    )
    if dq_result.is_err():
        return Err(dq_result.unwrap_err())

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant).filter_by(
            id=participant_id,
            tournament_id=tournament_id,
        )
    )
    if db_participant is None:
        return Err('Unbekannter Teilnehmer.')

    affected_user_ids = set(
        get_team_member_user_ids_for_participant(participant_id)
    )
    if db_participant.user_id is not None:
        affected_user_ids.add(db_participant.user_id)
    if db_participant.manager_user_id is not None:
        affected_user_ids.add(db_participant.manager_user_id)

    tournament = find_tournament_for_party(party_id, tournament_id)
    for user_id in affected_user_ids:
        set_registration_state_for_user(
            tournament_id, user_id, RegistrationState.canceled
        )
        refund_coins_for_tournament_registration_if_available(
            party_id, tournament, user_id, created_by_user_id=initiator.id
        )

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='participant_removed_by_admin',
        payload={'comment': comment},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(dq_result.unwrap())


def get_active_participant_counts_for_tournaments(
    party_id: PartyID, tournament_ids: set[TournamentID]
) -> dict[TournamentID, int]:
    if not tournament_ids:
        return {}

    rows = db.session.execute(
        select(
            DbNetsessionTourneyParticipant.tournament_id,
            db.func.count(DbNetsessionTourneyParticipant.id),
        )
        .join(
            DbNetsessionTourneyTournament,
            DbNetsessionTourneyParticipant.tournament_id
            == DbNetsessionTourneyTournament.id,
        )
        .filter(DbNetsessionTourneyTournament.party_id == party_id)
        .filter(
            DbNetsessionTourneyParticipant.tournament_id.in_(tournament_ids)
        )
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
        .group_by(DbNetsessionTourneyParticipant.tournament_id)
    ).all()
    return {tournament_id: int(count) for tournament_id, count in rows}


def get_participants_by_ids(
    party_id: PartyID, participant_ids: set[ParticipantID]
) -> dict[ParticipantID, Participant]:
    if not participant_ids:
        return {}

    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .join(
            DbNetsessionTourneyTournament,
            DbNetsessionTourneyParticipant.tournament_id
            == DbNetsessionTourneyTournament.id,
        )
        .filter(DbNetsessionTourneyTournament.party_id == party_id)
        .filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
    ).all()
    return {item.id: db_participant_to_model(item) for item in db_participants}


def set_participant_status(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    status: ParticipantStatus,
    initiator: User,
) -> Result[Participant, str]:
    if find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant).filter_by(
            id=participant_id,
            tournament_id=tournament_id,
        )
    )
    if db_participant is None:
        return Err('Unbekannter Teilnehmer.')

    if status not in domain_service.ADMIN_SETTABLE_PARTICIPANT_STATUSES:
        return Err(
            'Dieser Status lässt sich nicht direkt setzen. Zum Abmelden '
            '„Teilnehmer entfernen“ (mit Coin-Erstattung) oder '
            '„Disqualifizieren“ verwenden, zum Einchecken den Check-in.'
        )

    db_participant.status = status.value

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='participant_status_set',
        payload={'status': status.value},
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    return Ok(db_participant_to_model(db_participant))


def disqualify_participant(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    initiator: User,
    *,
    reason_code: str,
    comment: str,
    correlation_id: str | None = None,
) -> Result[Participant, str]:
    if find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    reason_code = reason_code.strip()
    comment = comment.strip()
    if not reason_code:
        return Err('Bitte einen Grund angeben.')
    if not comment:
        return Err('Bitte einen Kommentar angeben.')

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant).filter_by(
            id=participant_id,
            tournament_id=tournament_id,
        )
    )
    if db_participant is None:
        return Err('Unbekannter Teilnehmer.')

    db_participant.status = ParticipantStatus.dropped.value

    affected_matches = _find_open_matches_for_participant(
        tournament_id, participant_id
    )

    now = datetime.utcnow()
    _flag_matches_for_admin_review(
        affected_matches,
        initiator,
        participant_id,
        comment,
        correlation_id,
        now,
    )

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='participant_disqualified',
        payload={
            'reason_code': reason_code,
            'comment': comment,
            'affected_match_count': len(affected_matches),
            'correlation_id': correlation_id,
        },
        created_at=now,
    )

    if db_participant.manager_user_id is not None:
        _notify_manager_of_disqualification(
            tournament_id, db_participant, participant_id, reason_code, now
        )

    db.session.commit()

    log.info(
        'netsession_tourney.participant_disqualified',
        tournament_id=str(tournament_id),
        participant_id=str(participant_id),
        actor_user_id=str(initiator.id),
        reason_code=reason_code,
        correlation_id=correlation_id,
    )

    return Ok(db_participant_to_model(db_participant))


def _find_open_matches_for_participant(
    tournament_id: TournamentID, participant_id: ParticipantID
) -> Sequence[DbNetsessionTourneyMatch]:
    """Return the participant's matches that are not finished yet."""
    return db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .join(
            DbNetsessionTourneyMatchSlot,
            DbNetsessionTourneyMatch.id
            == DbNetsessionTourneyMatchSlot.match_id,
        )
        .filter(DbNetsessionTourneyMatch.tournament_id == tournament_id)
        .filter(DbNetsessionTourneyMatchSlot.participant_id == participant_id)
        .filter(
            DbNetsessionTourneyMatch.state.in_(
                [
                    MatchState.pending.value,
                    MatchState.ready.value,
                    MatchState.in_progress.value,
                    MatchState.pending_confirmation.value,
                ]
            )
        )
    ).all()


def _flag_matches_for_admin_review(
    db_matches: Sequence[DbNetsessionTourneyMatch],
    initiator: User,
    participant_id: ParticipantID,
    comment: str,
    correlation_id: str | None,
    now: datetime,
) -> None:
    for db_match in db_matches:
        db_match.state = MatchState.needs_admin_review.value
        db_match.dispute_reason_code = 'participant_disqualified'
        db_match.dispute_comment = comment
        db_match.updated_at = now

        append_audit_log(
            actor_user_id=initiator.id,
            object_type='match',
            object_id=db_match.id,
            action='match_needs_admin_review',
            payload={
                'reason_code': 'participant_disqualified',
                'participant_id': str(participant_id),
                'comment': comment,
                'correlation_id': correlation_id,
            },
            created_at=now,
        )


def _notify_manager_of_disqualification(
    tournament_id: TournamentID,
    db_participant: DbNetsessionTourneyParticipant,
    participant_id: ParticipantID,
    reason_code: str,
    now: datetime,
) -> None:
    append_notification(
        tournament_id=tournament_id,
        user_id=db_participant.manager_user_id,
        kind='participant_disqualified',
        payload={
            'participant_id': str(participant_id),
            'reason_code': reason_code,
        },
        created_at=now,
    )
