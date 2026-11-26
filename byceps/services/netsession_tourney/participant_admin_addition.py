"""
byceps.services.netsession_tourney.participant_admin_addition
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adding a user as participant by an admin.
"""

from __future__ import annotations

from datetime import datetime

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .coin_service import (
    charge_coins_for_tournament_registration,
)
from .dbmodels import (
    DbNetsessionTourneyParticipant,
)
from .eligibility import (
    validate_user_uses_ticket_for_party as _validate_user_uses_ticket_for_party,
)
from .models import (
    Participant,
    ParticipantID,
    ParticipantStatus,
    ParticipantType,
    RegistrationMode,
    Tournament,
    TournamentID,
    TournamentStatus,
)
from .participant_state import (
    count_active_participants_for_tournament,
    is_user_already_active_participant,
)
from .registration_service import (
    ensure_registration_is_registered,
)
from .service_helpers import (
    append_audit_log,
    db_participant_to_model,
    db_tournament_to_model,
)
from .tournament_queries import (
    find_db_tournament_for_party,
)


def add_user_participant_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_user: User,
    initiator: User,
) -> Result[Participant, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = db_tournament_to_model(db_tournament)
    eligibility_check = _check_user_participant_addable_by_admin(
        party_id, tournament_id, tournament, participant_user
    )
    if eligibility_check.is_err():
        return eligibility_check

    charge_result = charge_coins_for_tournament_registration(
        party_id,
        tournament,
        participant_user.id,
        created_by_user_id=initiator.id,
    )
    if charge_result.is_err():
        return Err(charge_result.unwrap_err())

    now = datetime.utcnow()
    db_participant = DbNetsessionTourneyParticipant(
        ParticipantID(generate_uuid7()),
        tournament_id,
        ParticipantType.user,
        participant_user.screen_name or str(participant_user.id),
        now,
        user_id=participant_user.id,
        manager_user_id=participant_user.id,
        status=ParticipantStatus.ready,
    )
    db.session.add(db_participant)
    ensure_registration_is_registered(tournament_id, participant_user.id)

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=db_participant.id,
        action='participant_added_by_admin',
        payload={'user_id': str(participant_user.id)},
        created_at=now,
    )
    db.session.commit()

    return Ok(db_participant_to_model(db_participant))


def _check_user_participant_addable_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    tournament: Tournament,
    participant_user: User,
) -> Result[None, str]:
    if tournament.status != TournamentStatus.draft:
        return Err('Teilnehmer lassen sich nur im Entwurf verwalten.')
    if tournament.registration_mode not in {
        RegistrationMode.solo,
        RegistrationMode.mixed,
    }:
        return Err(
            'Spieler direkt hinzufügen geht nur bei Einzel- oder gemischter Anmeldung.'
        )
    if (
        ticket_check := _validate_user_uses_ticket_for_party(
            participant_user.id, party_id
        )
    ).is_err():
        return ticket_check
    if is_user_already_active_participant(tournament_id, participant_user.id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')

    if _is_tournament_full_for_admin_addition(
        party_id, tournament_id, tournament
    ):
        return Err('Das Turnier ist voll.')

    return Ok(None)


def _is_tournament_full_for_admin_addition(
    party_id: PartyID, tournament_id: TournamentID, tournament: Tournament
) -> bool:
    if tournament.participant_limit is None:
        return False

    active_count = count_active_participants_for_tournament(
        party_id, tournament_id
    )
    return active_count >= tournament.participant_limit
